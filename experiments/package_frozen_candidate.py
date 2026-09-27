"""Package only the locked, independently audited winner; validate the actual ZIP."""
from __future__ import annotations

import argparse
import datetime
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import traceback
import zipfile

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
SDK = ROOT / 'yk-development-tools'
KIT = SDK / 'bots/dist/starter'
FILES = ('generated.hpp', 'main.cpp', 'protocol.hpp', 'submission.json')
MEMORY_BYTES = 384 * 1024 * 1024


def stamp():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def frozen_file(arena, manifest, relative):
    path = arena / relative
    require(path.resolve().is_relative_to(arena), f'Frozen path escaped arena: {relative}')
    require(path.is_file() and not path.is_symlink(), f'Frozen input is not a regular file: {relative}')
    require(sha(path) == manifest['frozen_sha256'][relative], f'Frozen hash mismatch: {relative}')
    return path


def baseline_id(result):
    baseline = result.get('baseline', 'v2')
    require(baseline in ('v2', 'v3'), 'Unsupported evaluation baseline')
    return baseline


def cpu_seeds(start):
    require(type(start) is int and start >= 0, 'CPU seed start must be a nonnegative integer')
    return (start, start + 1)


def check_gates(arena, audit):
    result, lock = read(arena / 'campaign-result.json'), read(arena / 'locked-finalists.json')
    manifest, audit_manifest = read(arena / 'manifest.json'), read(audit / 'manifest.json')
    extra = read(audit / 'audit-result.json')
    baseline = baseline_id(result)
    candidate = lock['primary_candidate']
    require(candidate not in ('v2', 'v1', 'teammate'), 'No promoted new candidate')
    require(candidate != baseline, 'Primary candidate is the evaluation baseline')
    require(lock.get('baseline', baseline) == baseline, 'Selection lock baseline differs')
    require(lock['finalists'][0] == candidate, 'Primary differs from first locked finalist')
    require(result['status'] == 'complete' and result['phase'] == 'final', 'Original final validation incomplete')
    require(result['primary_candidate'] == result['recommended'] == candidate, 'Original recommendation differs from primary')
    require(result['promotion_decisions'][candidate]['promoted'] is True, 'Original promotion gate failed')
    require(result['promotion_decisions'][candidate].get('baseline', baseline) == baseline, 'Promotion decision baseline differs')
    require(all(result['promotion_decisions'][candidate]['gates'].values()), 'Original individual promotion gate failed')
    require(extra['status'] == 'complete' and extra['candidate'] == candidate, 'Audit candidate differs or audit incomplete')
    require(extra.get('baseline') == baseline, 'Audit baseline differs from original evaluation')
    require(extra['passes_additional_gate'] is True and all(extra['gates'].values()), 'Additional audit gate failed')
    verification = {}
    for label, directory, data in (('original', arena, manifest), ('audit', audit, audit_manifest)):
        report = read(directory / 'artifact-verification.json')
        require(report['status'] == 'passed' and report['errors'] == report['forfeits'] == 0, f'{label} artifacts not verified')
        require(report['source_commit'] == data['source_commit'], f'{label} verification commit differs')
        require(report['games'] == read(directory / 'campaign-result.json')['total_matches'], f'{label} verified match count differs')
        verification[label] = report
    for name in (candidate, baseline):
        require(manifest['bots'][name]['source_sha256'] == audit_manifest['bots'][name]['source_sha256'], f'{name} changed between original and audit')
        for directory, data in ((arena, manifest), (audit, audit_manifest)):
            source = frozen_file(directory, data, data['bots'][name]['source'])
            require(sha(source) == data['bots'][name]['source_sha256'], f'{name} source hash differs')
        original_parent = Path(manifest['bots'][name]['source']).parent
        audit_parent = Path(audit_manifest['bots'][name]['source']).parent
        for header in ('protocol.hpp', 'generated.hpp'):
            left = frozen_file(arena, manifest, str(original_parent / header))
            right = frozen_file(audit, audit_manifest, str(audit_parent / header))
            require(sha(left) == sha(right), f'{name} {header} changed between original and audit')
    if baseline == 'v3':
        relative = 'submissions/iterative-v3/main.cpp'
        original_sha = sha(ROOT / relative)
        for directory, data in ((arena, manifest), (audit, audit_manifest)):
            require(data['input_sha256'].get(relative) == original_sha, 'v3 original input source hash differs')
            require(data['bots'][baseline]['source_sha256'] == original_sha, 'v3 baseline differs from original submission source')
            original = frozen_file(directory, data, 'snapshot/' + relative)
            require(sha(original) == original_sha, 'Frozen original v3 source differs')
    # The validator uses the installed SDK. Verify its engine/runner against the match snapshot.
    sdk_checked = 0
    for relative, expected in manifest['input_sha256'].items():
        if relative.startswith('yk-development-tools/'):
            require(sha(ROOT / relative) == expected, f'Local SDK differs from frozen engine: {relative}')
            sdk_checked += 1
    require(sdk_checked > 0, 'Original manifest has no frozen SDK inputs')
    policy = read(audit / 'audit-policy.json')
    require(policy['candidate'] == candidate and policy['source_sha256'][candidate] == manifest['bots'][candidate]['source_sha256'], 'Audit policy/source mismatch')
    require(policy.get('baseline', baseline) == baseline, 'Audit policy baseline differs')
    require(policy['source_sha256'][baseline] == manifest['bots'][baseline]['source_sha256'], 'Audit policy baseline source mismatch')
    return candidate, manifest, verification, sdk_checked


def load_sdk():
    sys.path.insert(0, str(SDK))
    sys.path.insert(0, str(KIT))
    modules = []
    for name in ('submission', 'run_tests'):
        spec = importlib.util.spec_from_file_location('package_sdk_' + name, KIT / (name + '.py'))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        modules.append(module)
    return modules


def compile_bot(compiler, source, binary, record_dir, label):
    command = [compiler, '-std=c++20', '-O2', '-I', str(source.parent), str(source), '-o', str(binary)]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
    try:
        stdout, stderr = process.communicate(timeout=120)
    except BaseException:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        stdout, stderr = process.communicate()
        write(record_dir / f'build-{label}.json', {'command': command, 'returncode': process.returncode, 'stdout': stdout, 'stderr': stderr, 'interrupted': True})
        raise
    write(record_dir / f'build-{label}.json', {'command': command, 'returncode': process.returncode, 'stdout': stdout, 'stderr': stderr})
    require(process.returncode == 0, f'{label} C++20 build failed')


def wrapped(binary):
    return 'exec ' + shlex.join(['timeout', '--kill-after=2s', '180s', 'prlimit', f'--as={MEMORY_BYTES}:{MEMORY_BYTES}', '--', str(binary)])


def canonical_zip(source_zip, target):
    with zipfile.ZipFile(source_zip) as old, zipfile.ZipFile(target, 'x', zipfile.ZIP_DEFLATED) as new:
        require(sorted(old.namelist()) == list(FILES), 'Unexpected SDK ZIP members')
        for name in FILES:
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            new.writestr(info, old.read(name))


def validate_zip(path, source):
    require(path.stat().st_size <= 5 * 1024 * 1024, 'ZIP exceeds 5 MiB')
    with zipfile.ZipFile(path) as archive:
        require(sorted(archive.namelist()) == list(FILES), 'ZIP must contain exactly the four expected files')
        require(len(archive.infolist()) <= 200, 'Too many ZIP members')
        require(sum(x.file_size for x in archive.infolist()) <= 20 * 1024 * 1024, 'Uncompressed ZIP exceeds 20 MiB')
        require(archive.testzip() is None, 'ZIP CRC check failed')
        members = {}
        for name in FILES:
            contents = archive.read(name)
            require(contents == (source / name).read_bytes(), f'ZIP member changed: {name}')
            members[name] = {'sha256': hashlib.sha256(contents).hexdigest(), 'bytes': len(contents)}
    return {'sha256': sha(path), 'bytes': path.stat().st_size, 'members': members, 'deterministic_metadata': True}


def validate_runtime(checker, candidate_binary, baseline_binary, candidate, records, *, baseline='v2', cpu_seed_start=7550):
    from engine.config import load_config
    from runner.match import run_match

    original_checked = checker.CheckedBot

    class TimedCheckedBot(original_checked):
        def __init__(self, *args, **kwargs):
            self.response_ms = []
            super().__init__(*args, **kwargs)

        def collect_turn(self):
            previous = self.max_turn_ms
            self.max_turn_ms = 0.0
            try:
                answer = super().collect_turn()
                if answer[1] == 'ok':
                    self.response_ms.append(self.max_turn_ms)
                return answer
            finally:
                self.max_turn_ms = max(previous, self.max_turn_ms)

        def close(self):
            process = self.proc
            group = None
            if process is not None:
                try:
                    if os.getpgid(process.pid) == process.pid:
                        group = process.pid
                except ProcessLookupError:
                    pass
            try:
                super().close()
            finally:
                if group is not None:
                    try:
                        os.killpg(group, signal.SIGKILL)
                    except ProcessLookupError:
                        pass

    checker.CheckedBot = TimedCheckedBot
    try:
        smoke = checker.check(wrapped(candidate_binary), seed=0)
        write(records / 'sdk-smoke.json', smoke)
        require(smoke.get('ok') is True and not smoke.get('issues') and not smoke.get('warnings'), 'SDK runtime/output smoke failed')
        rows = []
        (records / 'replays').mkdir()
        for seed in cpu_seeds(cpu_seed_start):
            for team in 'YK':
                config = load_config()
                require(config['total_turns'] == 160, 'Official configuration does not use 160 turns')
                config['first_turn_timeout_ms'] = 3000
                bots = []
                started = time.monotonic()
                try:
                    own = TimedCheckedBot(wrapped(candidate_binary), config)
                    bots.append(own)
                    other = TimedCheckedBot(wrapped(baseline_binary), config)
                    bots.append(other)
                    y, k = (own, other) if team == 'Y' else (other, own)
                    replay, result = run_match(seed, config, y, k, turn_timeout_ms=300,
                                               names={team: candidate, 'K' if team == 'Y' else 'Y': baseline})
                finally:
                    for bot in bots:
                        bot.close()
                elapsed = time.monotonic() - started
                replay_name = f'replays/{seed}-{team}.json.gz'
                (records / replay_name).write_bytes(gzip.compress(json.dumps(replay, ensure_ascii=False, separators=(',', ':')).encode(), mtime=0))
                row = {'map_seed': seed, 'team': team, 'candidate': candidate, 'opponent': baseline, 'result': result,
                       'elapsed_seconds': elapsed, 'replay': replay_name,
                       'replay_sha256': sha(records / replay_name),
                       'logical_trace_sha256': hashlib.sha256(json.dumps({'turns': replay['turns'], 'result': result}, sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
                       'candidate_response_ms': own.response_ms, 'opponent_response_ms': other.response_ms,
                       'candidate_max_turn_ms': own.max_turn_ms, 'opponent_max_turn_ms': other.max_turn_ms,
                       'candidate_issues': own.issues, 'opponent_issues': other.issues,
                       'candidate_output_usage': own.usage.snapshot(), 'opponent_output_usage': other.usage.snapshot()}
                rows.append(row)
                write(records / 'cpu-matches.json', rows)
                require(result['reason'] != 'forfeit', f'CPU match {seed}/{team} forfeited')
                require(elapsed <= 180, f'CPU match {seed}/{team} exceeded 180 seconds')
                require(not own.issues and not other.issues and not own.usage.snapshot()['warnings'] and not other.usage.snapshot()['warnings'], f'CPU match {seed}/{team} invalid commands/output')
        return rows
    finally:
        checker.CheckedBot = original_checked


def run(args):
    seed_start = getattr(args, 'cpu_seed_start', 7550)
    seeds = cpu_seeds(seed_start)
    paths = [args.source_output, args.zip_output, args.record_output]
    for path in paths:
        require(not path.exists() and not path.is_symlink(), f'Refusing to overwrite output: {path}')
    for i, left in enumerate(paths):
        for right in paths[i + 1:]:
            require(not left.is_relative_to(right) and not right.is_relative_to(left), 'Output paths overlap')
    for path in paths:
        for input_path in (args.arena, args.audit):
            require(not path.is_relative_to(input_path) and not input_path.is_relative_to(path), 'Output path overlaps frozen inputs')
    record = {'status': 'running', 'started_utc': stamp(), 'helper_sha256': sha(Path(__file__)),
              'arena': str(args.arena), 'audit': str(args.audit), 'outputs': [str(x) for x in paths],
              'validation_scope': 'Packaging and CPU protocol/resource regression only; four games have no win-rate promotion gate'}
    temporary = tempfile.TemporaryDirectory(prefix='yk-package-', dir='/tmp')
    tmp = Path(temporary.name)
    records = tmp / 'records'
    records.mkdir()
    previous_tmp = {name: os.environ.get(name) for name in ('TMPDIR', 'TMP', 'TEMP')}
    previous_tempdir = tempfile.tempdir
    for name in previous_tmp:
        os.environ[name] = str(tmp)
    tempfile.tempdir = str(tmp)
    created_source = created_zip = created_records = False
    record_destination = args.record_output
    failure = None
    try:
        candidate, manifest, verification, sdk_checked = check_gates(args.arena, args.audit)
        baseline = baseline_id(read(args.arena / 'campaign-result.json'))
        record.update(candidate=candidate, source_commit=manifest['source_commit'], source_sha256=manifest['bots'][candidate]['source_sha256'],
                      baseline=baseline, baseline_source_sha256=manifest['bots'][baseline]['source_sha256'],
                      cpu_map_seeds=list(seeds), artifact_verifications=verification, sdk_frozen_files_checked=sdk_checked)
        evidence_paths = [('original', args.arena, ('manifest.json', 'campaign-result.json', 'locked-finalists.json', 'artifact-verification.json')),
                          ('audit', args.audit, ('manifest.json', 'audit-result.json', 'audit-policy.json', 'artifact-verification.json'))]
        record['evaluation_file_sha256'] = {label + '/' + name: sha(directory / name) for label, directory, names in evidence_paths for name in names}
        for program in (args.compiler, 'prlimit', 'timeout'):
            require(shutil.which(program) is not None, f'Missing required program: {program}')
        compiler = shutil.which(args.compiler)
        compiler_version = subprocess.check_output([compiler, '--version'], text=True, timeout=10).splitlines()[0]
        record['environment'] = {'compiler': compiler, 'compiler_version': compiler_version, 'platform': platform.platform(),
                                 'python': sys.version, 'cpu_affinity': sorted(os.sched_getaffinity(0)),
                                 'required_platform_compiler': 'GCC 12.2.0 / C++20',
                                 'limitation': 'Local CPU/OS/compiler are recorded; this does not certify the official platform container.'}
        record['runtime_limits'] = {'RLIMIT_AS_bytes': MEMORY_BYTES, 'first_turn_ms': 3000, 'turn_ms': 300, 'process_wall_seconds': 180,
                                    'scope': 'Per-process virtual address space and timeout wrapper; not full server container isolation'}
        record['sdk_tool_sha256'] = {str(path.relative_to(ROOT)): sha(path) for path in (KIT / 'submission.py', KIT / 'run_tests.py', KIT / 'output_usage.py', KIT / 'limits.json')}
        source = tmp / 'source'
        source.mkdir()
        folder = Path(manifest['bots'][candidate]['source']).parent
        record['source_files'] = {}
        for name in FILES:
            metadata_folder = 'iterative-v3' if baseline == 'v3' else 'tuned'
            relative = str(folder / name) if name != 'submission.json' else f'snapshot/submissions/{metadata_folder}/submission.json'
            original = frozen_file(args.arena, manifest, relative)
            shutil.copyfile(original, source / name)
            record['source_files'][name] = {'arena_relative_path': relative, 'sha256': sha(original), 'bytes': original.stat().st_size}
        packer, checker = load_sdk()
        packer.build_zip(source, tmp / 'sdk.zip')
        archive = tmp / 'submission.zip'
        canonical_zip(tmp / 'sdk.zip', archive)
        record['zip'] = validate_zip(archive, source)
        inspection = packer.inspect_zip(archive)
        write(records / 'zip-inspection.json', inspection)
        require(inspection['ok'] is True and not inspection['issues'] and not inspection.get('warnings'), 'SDK ZIP inspection failed')
        extracted = tmp / 'extracted'
        require(packer.extract_zip(archive, extracted) == 'cpp', 'Unexpected extracted language')
        for name in FILES:
            require(sha(extracted / name) == record['zip']['members'][name]['sha256'], f'Extracted member mismatch: {name}')
        compile_bot(compiler, extracted / 'main.cpp', tmp / 'candidate', records, 'candidate-from-zip')
        baseline_source = frozen_file(args.arena, manifest, manifest['bots'][baseline]['source'])
        compile_bot(compiler, baseline_source, tmp / 'baseline', records, 'frozen-' + baseline)
        rows = validate_runtime(checker, tmp / 'candidate', tmp / 'baseline', candidate, records,
                                baseline=baseline, cpu_seed_start=seed_start)
        require(len(rows) == 4, 'Incomplete CPU validation')
        record.update(status='validated', errors=0, forfeits=0, cpu_matches=4, sdk_smoke_matches=1,
                      full_length_matches=sum(row['result']['turns'] == 160 for row in rows),
                      maximum_candidate_response_ms=max(row['candidate_max_turn_ms'] for row in rows),
                      validated_utc=stamp())
        write(records / 'validation.json', record)
        # Everything published below is newly created; no existing artifact is replaced.
        for path in paths:
            require(not path.exists() and not path.is_symlink(), f'Output appeared during validation: {path}')
            path.parent.mkdir(parents=True, exist_ok=True)
        args.source_output.mkdir()
        created_source = True
        for name in FILES:
            shutil.copyfile(source / name, args.source_output / name)
        with args.zip_output.open('xb') as out, archive.open('rb') as incoming:
            created_zip = True
            shutil.copyfileobj(incoming, out)
        require(sha(args.zip_output) == record['zip']['sha256'], 'Published ZIP hash mismatch')
        args.record_output.mkdir()
        created_records = True
        shutil.copytree(records, args.record_output, dirs_exist_ok=True)
    except BaseException as error:
        failure = error
        record.update(status='failed', failed_utc=stamp(), error=f'{type(error).__name__}: {error}')
        (records / 'failure.txt').write_text(traceback.format_exc())
        write(records / 'validation.json', record)
        if created_zip:
            args.zip_output.unlink(missing_ok=True)
        if created_source:
            shutil.rmtree(args.source_output)
        if not created_records:
            args.record_output.parent.mkdir(parents=True, exist_ok=True)
            try:
                args.record_output.mkdir()
            except FileExistsError:
                # A concurrent writer owns that path; retain failure logs under a new sibling.
                import uuid
                record_destination = args.record_output.with_name(args.record_output.name + '-failure-' + uuid.uuid4().hex)
                record_destination.mkdir()
            created_records = True
        shutil.copytree(records, record_destination, dirs_exist_ok=True)
    finally:
        for name, value in previous_tmp.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        tempfile.tempdir = previous_tempdir
        try:
            temporary.cleanup()
        except BaseException as cleanup_error:
            if failure is None:
                failure = cleanup_error
            else:
                failure.add_note(f'TMP cleanup also failed: {cleanup_error!r}')
            record.update(status='failed', error=f'{type(failure).__name__}: {failure}', cleanup_error=repr(cleanup_error))
            if created_zip:
                args.zip_output.unlink(missing_ok=True)
            if created_source and args.source_output.exists():
                shutil.rmtree(args.source_output)
        record['tmp_cleanup'] = {'path': str(tmp), 'exists': tmp.exists(), 'checked_utc': stamp()}
        record['finished_utc'] = stamp()
        if created_records:
            write(record_destination / 'validation.json', record)
    if failure is not None:
        raise RuntimeError(f'Packaging failed; preserved logs: {record_destination}') from failure
    require(not tmp.exists(), 'TMP cleanup failed')
    print(json.dumps({'status': record['status'], 'candidate': record['candidate'], 'zip': str(args.zip_output),
                      'sha256': record['zip']['sha256'], 'records': str(args.record_output)}, ensure_ascii=False))
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('arena', 'audit', 'source-output', 'zip-output', 'record-output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--compiler', default='g++')
    parser.add_argument('--cpu-seed-start', type=int, default=7550,
                        help='First of two CPU validation map seeds; both sides are checked (default: 7550)')
    args = parser.parse_args()
    for name in ('arena', 'audit', 'source_output', 'zip_output', 'record_output'):
        setattr(args, name, getattr(args, name).resolve())
    previous = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}
    def interrupted(number, frame):
        raise InterruptedError(f'Signal {number}')
    try:
        for sig in previous:
            signal.signal(sig, interrupted)
        run(args)
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


if __name__ == '__main__':
    main()
