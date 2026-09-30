"""Preserve a frozen research candidate after exact-ZIP GCC12 and runtime checks.

This entry point never promotes a candidate or uploads it. Match wins are recorded
but are deliberately separate from the runtime and packaging validity checks.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import traceback

sys.dont_write_bytecode = True
import package_deadline_candidate as evidence
import package_frozen_candidate as package
from verify_gcc12_tmp import gcc12_toolchain

BASELINE = 'v8'
V8_SOURCE_SHA256 = '61a4f25113d9bf2c387a59ddc770a3143de6311e3fd2e004827a66eb78edfbc9'
require, read, sha, write = package.require, package.read, package.sha, package.write


def normalized(args):
    args = argparse.Namespace(**vars(args))
    for name in ('arena', 'output_zip', 'records'):
        path = Path(getattr(args, name))
        require(not path.is_symlink(), 'Refusing symlink path: ' + str(path))
        setattr(args, name, path.resolve())
    require(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', args.candidate) is not None and
            args.candidate != BASELINE, 'Expected a distinct research candidate ID')
    package.cpu_seeds(args.cpu_seed_start)
    require(type(args.toolchain_budget_seconds) is int and args.toolchain_budget_seconds > 0,
            'Toolchain budget must be a positive integer')
    outputs = [args.output_zip, args.records]
    for index, path in enumerate(outputs):
        require(not path.exists(), 'Refusing to overwrite output: ' + str(path))
        for other in [args.arena, *outputs[index + 1:]]:
            require(not path.is_relative_to(other) and not other.is_relative_to(path),
                    'Output overlaps another output or frozen input')
    return args


def verify_inputs(arena, candidate):
    manifest, sdk = evidence.verify_manifest(arena)
    require(isinstance(manifest.get('source_commit'), str) and manifest['source_commit'],
            'Missing frozen source commit')
    require(candidate in manifest['bots'] and BASELINE in manifest['bots'], 'Missing candidate or v8 baseline')
    require(manifest['bots'][BASELINE]['source_sha256'] == V8_SOURCE_SHA256,
            'v8 baseline differs from the preserved guard3 submission')
    bundles = {}
    for name in (candidate, BASELINE):
        folder = Path(manifest['bots'][name]['source']).parent
        bundles[name] = {}
        for member in package.FILES:
            relative = str(folder / member)
            original = package.frozen_file(arena, manifest, relative)
            bundles[name][member] = {'relative': relative, 'sha256': sha(original)}
        require(bundles[name]['main.cpp']['sha256'] == manifest['bots'][name]['source_sha256'],
                'Frozen bundle source differs from bot identity: ' + name)
        metadata = read(arena / bundles[name]['submission.json']['relative'])
        require(metadata == {'schemaVersion': 1, 'language': 'cpp'}, 'Unexpected C++ submission metadata')
    tools = [Path(__file__), Path(package.__file__), Path(evidence.__file__),
             Path(__file__).with_name('verify_gcc12_tmp.py'),
             Path(__file__).with_name('audit_deadline_actions.py'),
             *[package.KIT / name for name in ('submission.py', 'run_tests.py', 'output_usage.py',
                                              '_support.py', 'limits.json')]]
    seal = {'manifest_sha256': sha(arena / 'manifest.json'), 'source_commit': manifest['source_commit'],
            'bundles': bundles, 'sdk_input_sha256': sdk,
            'validation_tools_sha256': {str(path.relative_to(package.ROOT)): sha(path) for path in tools}}
    return manifest, seal


def validate_cpu_rows(rows, candidate, seed_start):
    expected = {(seed, team) for seed in package.cpu_seeds(seed_start) for team in 'YK'}
    require(len(rows) == 4 and {(r['map_seed'], r['team']) for r in rows} == expected,
            'Expected exactly four paired CPU validation games')
    for row in rows:
        require(row['candidate'] == candidate and row['opponent'] == BASELINE, 'Runtime bot identity differs')
        result = row['result']
        require(result['reason'] != 'forfeit' and result['winner'] in ('Y', 'K', 'DRAW'),
                'Runtime error or forfeit')
        require(1 <= result['turns'] <= 160 and row['elapsed_seconds'] <= 180,
                'Runtime match length exceeded limits')
        for side in ('candidate', 'opponent'):
            require(not row[side + '_issues'] and not row[side + '_output_usage']['warnings'],
                    'Runtime command or output warning')
            responses = row[side + '_response_ms']
            require(len(responses) == result['turns'] and responses and
                    all(0 <= value <= (3000 if index == 0 else 300)
                        for index, value in enumerate(responses)), 'Missing or late response evidence')


def audit_actions(rows, records):
    folder = records / 'action-input'
    folder.mkdir()
    inputs = []
    for row in rows:
        replay = evidence.safe_file(records, row['replay'])
        require(sha(replay) == row['replay_sha256'], 'Runtime replay digest differs')
        inputs.append({'job_id': f"cpu-{row['map_seed']}-{row['team']}",
                       'map_seed': row['map_seed'], 'team': row['team'],
                       'candidate': row['candidate'], 'opponent': row['opponent'],
                       'replay': '../' + row['replay']})
    (folder / 'results.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in inputs))
    output = records / 'action-audit.json'
    command = [sys.executable, '-B', str(Path(__file__).with_name('audit_deadline_actions.py')),
               '--run-dir', str(folder), '--output', str(output), '--sdk-dir', str(package.SDK)]
    result = subprocess.run(command, text=True, capture_output=True, timeout=120)
    write(records / 'action-audit-process.json', {'command': command, 'returncode': result.returncode,
                                                 'stdout': result.stdout, 'stderr': result.stderr})
    require(result.returncode == 0 and output.is_file(), 'Runtime action auditor failed')
    audit = read(output)
    require(audit['replays'] == 4 and audit['frames'] > 0 and audit['counts'], 'Incomplete runtime action audit')
    issues = {label: {key: value for key, value in counts.items()
                      if key not in ('turns', 'commands') and value}
              for label, counts in audit['counts'].items()}
    require(not any(issues.values()) and not audit['examples'], 'Runtime commands were rejected or clipped')
    return {'sha256': sha(output), 'replays': audit['replays'], 'frames': audit['frames'], 'issues': 0}


def validate_archive(args, manifest, seal, record, compiler):
    temporary = None
    try:
        with tempfile.TemporaryDirectory(prefix='yk-mission-package-', dir='/tmp') as folder:
            temporary = Path(folder)
            source = temporary / 'source'
            source.mkdir()
            for member, detail in seal['bundles'][args.candidate].items():
                original = package.frozen_file(args.arena, manifest, detail['relative'])
                shutil.copyfile(original, source / member)
            packer, checker = package.load_sdk()
            packer.build_zip(source, temporary / 'sdk.zip')
            archive = temporary / 'submission.zip'
            package.canonical_zip(temporary / 'sdk.zip', archive)
            record['zip'] = package.validate_zip(archive, source)
            inspection = packer.inspect_zip(archive)
            write(args.records / 'zip-inspection.json', inspection)
            require(inspection.get('ok') is True and not inspection.get('issues') and
                    not inspection.get('warnings'), 'SDK ZIP inspection failed')
            extracted = temporary / 'extracted'
            require(packer.extract_zip(archive, extracted) == 'cpp', 'ZIP is not C++')
            for member in package.FILES:
                require(sha(extracted / member) == record['zip']['members'][member]['sha256'],
                        'Extracted ZIP member differs: ' + member)
            package.compile_bot(compiler, extracted / 'main.cpp', temporary / 'candidate',
                                args.records, 'candidate-from-zip')
            baseline = package.frozen_file(args.arena, manifest, manifest['bots'][BASELINE]['source'])
            package.compile_bot(compiler, baseline, temporary / 'baseline', args.records, 'frozen-v8')
            rows = package.validate_runtime(checker, temporary / 'candidate', temporary / 'baseline',
                                            args.candidate, args.records, baseline=BASELINE,
                                            cpu_seed_start=args.cpu_seed_start)
            validate_cpu_rows(rows, args.candidate, args.cpu_seed_start)
            record['action_audit'] = audit_actions(rows, args.records)
            shutil.copytree(source, args.records / 'source')
            shutil.copyfile(archive, args.records / 'archive.pending')
            record.update(cpu_matches=4, sdk_smoke_matches=1, errors=0, forfeits=0,
                          maximum_candidate_response_ms=max(r['candidate_max_turn_ms'] for r in rows),
                          runtime_results={'wins': sum(r['result']['winner'] == r['team'] for r in rows),
                                           'draws': sum(r['result']['winner'] == 'DRAW' for r in rows),
                                           'losses': sum(r['result']['winner'] not in (r['team'], 'DRAW') for r in rows)})
    finally:
        record['packaging_temporary_directory'] = str(temporary) if temporary else None
        record['packaging_temporary_directory_removed'] = temporary is None or not temporary.exists()
    require(record['packaging_temporary_directory_removed'], 'Packaging temporary cleanup failed')


def run(args):
    args = normalized(args)
    args.records.parent.mkdir(parents=True, exist_ok=True)
    args.records.mkdir()
    record = {'schema_version': 1, 'status': 'running', 'purpose': 'research_candidate_only',
              'candidate': args.candidate, 'baseline': BASELINE, 'started_utc': package.stamp(),
              'promotion_evaluated': False, 'promotion_approved': False, 'server_upload_performed': False,
              'cpu_map_seeds': list(package.cpu_seeds(args.cpu_seed_start)), 'toolchain': {},
              'runtime_limits': {'memory_address_space_mib': 384, 'turn_ms': 300, 'first_turn_ms': 3000,
                                 'process_wall_seconds': 180, 'compiler': 'GCC12.2/C++20'},
              'limitations': ['Runtime validity does not establish win-rate superiority or promote this candidate.',
                              'Host CPU, kernel, binutils and isolation can differ from the official server.',
                              'Toolchain setup budget does not bound the complete packaging run.',
                              'Debian HTTPS package indexes and SHA256 are checked; OpenPGP verification is not added.']}
    previous_env = dict(os.environ)
    previous_signals = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}
    made_zip = False
    pending = args.records / 'archive.pending'

    def interrupted(number, frame):
        raise InterruptedError(f'Interrupted by signal {number}')

    try:
        manifest, seal = verify_inputs(args.arena, args.candidate)
        record['input_seal'] = seal
        write(args.records / 'manifest.json', manifest)
        for program in ('prlimit', 'timeout'):
            require(shutil.which(program), 'Missing runtime limiter: ' + program)
        for sig in previous_signals:
            signal.signal(sig, interrupted)
        try:
            with gcc12_toolchain(record['toolchain'], budget_seconds=args.toolchain_budget_seconds) as toolchain:
                os.environ.clear()
                os.environ.update(toolchain['env'])
                record['compiler_path'] = toolchain['compiler_wrapper']
                validate_archive(args, manifest, seal, record, toolchain['compiler_wrapper'])
            require(record['toolchain'].get('temporary_directory_removed') is True,
                    'GCC12 temporary cleanup not confirmed')
        finally:
            os.environ.clear()
            os.environ.update(previous_env)
            for sig, handler in previous_signals.items():
                signal.signal(sig, handler)
        _, after = verify_inputs(args.arena, args.candidate)
        require(after == seal, 'Frozen inputs or validation tools changed during packaging')
        record['input_seal_unchanged'] = True
        require(sha(pending) == record['zip']['sha256'], 'Staged ZIP hash differs')
        args.output_zip.parent.mkdir(parents=True, exist_ok=True)
        with args.output_zip.open('xb') as output, pending.open('rb') as source:
            made_zip = True
            shutil.copyfileobj(source, output)
        require(sha(args.output_zip) == record['zip']['sha256'], 'Published ZIP hash differs')
        record.update(status='validated', output_zip=str(args.output_zip))
    except BaseException as exc:
        record.update(status='failed', error=f'{type(exc).__name__}: {exc}')
        (args.records / 'failure.txt').write_text(traceback.format_exc())
        if made_zip:
            args.output_zip.unlink(missing_ok=True)
    finally:
        os.environ.clear()
        os.environ.update(previous_env)
        for sig, handler in previous_signals.items():
            signal.signal(sig, handler)
        pending.unlink(missing_ok=True)
        record['environment_restored'] = dict(os.environ) == previous_env
        record['signal_handlers_restored'] = all(signal.getsignal(sig) == handler for sig, handler in previous_signals.items())
        record['finished_utc'] = package.stamp()
        write(args.records / 'validation.json', record)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('arena', 'output-zip', 'records'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--candidate', required=True)
    parser.add_argument('--cpu-seed-start', type=int, default=22400)
    parser.add_argument('--toolchain-budget-seconds', type=int, default=300)
    args = parser.parse_args()
    try:
        report = run(args)
    except (OSError, ValueError, KeyError) as exc:
        print(f'{type(exc).__name__}: {exc}', file=sys.stderr)
        return 1
    print(json.dumps({'status': report['status'], 'purpose': report['purpose'],
                      'zip': report.get('output_zip'), 'error': report.get('error'),
                      'records': str(args.records)}, ensure_ascii=False), flush=True)
    return 0 if report['status'] == 'validated' else 1


if __name__ == '__main__':
    raise SystemExit(main())
