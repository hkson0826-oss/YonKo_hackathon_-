"""Package an explicitly accepted deadline candidate with linked match evidence."""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import traceback

sys.dont_write_bytecode = True
import local_league as league
import package_frozen_candidate as package

require = package.require
read = package.read
sha = package.sha
write = package.write


def safe_file(root, relative):
    path = root / relative
    require(path.resolve().is_relative_to(root.resolve()) and path.is_file() and not path.is_symlink(),
            'Missing, linked or escaped evidence file: ' + str(relative))
    return path


def verify_manifest(arena):
    manifest = read(arena / 'manifest.json')
    require(manifest.get('status') == 'ready', 'Frozen arena is not ready')
    require(bool(manifest.get('frozen_sha256')), 'Missing frozen file hashes')
    for relative, expected in manifest['frozen_sha256'].items():
        require(sha(safe_file(arena, relative)) == expected, 'Frozen hash mismatch: ' + relative)
    sdk = {}
    for relative, expected in manifest.get('input_sha256', {}).items():
        require(sha(safe_file(arena, 'snapshot/' + relative)) == expected, 'Input hash mismatch: ' + relative)
        if relative.startswith('yk-development-tools/'):
            require(sha(safe_file(package.ROOT, relative)) == expected, 'Installed SDK differs from frozen SDK: ' + relative)
            sdk[relative] = expected
    required = ['engine/config.py', 'engine/pipeline.py', 'runner/match.py', 'mapgen/generator.py', 'config/balance.json']
    require(all('yk-development-tools/' + name in sdk for name in required), 'Missing frozen SDK provenance')
    for name, bot in manifest['bots'].items():
        if 'source' in bot:
            require(sha(safe_file(arena, bot['source'])) == bot['source_sha256'], 'Bot source hash mismatch: ' + name)
    return manifest, sdk


def verify_run(reference, stage, candidate, baseline, expected_sources):
    arena = Path(reference['arena']).resolve()
    manifest, sdk = verify_manifest(arena)
    run_id = reference['run_id']
    require(isinstance(run_id, str) and re.fullmatch(r'[A-Za-z0-9_-]+', run_id), 'Invalid evidence run ID')
    folder = arena / 'runs' / run_id
    plan = read(safe_file(folder, 'plan.json'))
    policy = read(safe_file(arena, 'plans/' + run_id + '-policy.json'))
    require(policy.get('stage') == stage and policy.get('baseline') == baseline, 'Run stage/baseline differs: ' + stage)
    require(candidate in plan.get('candidates', []) and baseline in plan.get('candidates', []), 'Missing candidate/baseline in ' + stage)
    for name, expected in expected_sources.items():
        require(manifest['bots'].get(name, {}).get('source_sha256') == expected and
                policy.get('source_sha256', {}).get(name) == expected, 'Evidence source differs: ' + name)
    for name in set(plan['candidates'] + plan['opponents']):
        require(policy.get('source_sha256', {}).get(name) == manifest['bots'][name]['source_sha256'], 'Opponent source differs: ' + name)
    for name in ('summary', 'results'):
        filename = 'summary.json' if name == 'summary' else 'results.jsonl'
        require(sha(safe_file(folder, filename)) == reference[name + '_sha256'], 'Evidence digest differs: ' + filename)
    jobs = league.make_jobs(plan, manifest['bots'])
    require(policy.get('map_seeds') == plan.get('map_seeds'), 'Policy maps differ from run plan')
    require(type(policy.get('scheduled_jobs')) is int and policy['scheduled_jobs'] == len(jobs),
            'Policy scheduled job count differs from run plan')
    require(policy.get('source_commit') == manifest.get('source_commit') and bool(manifest.get('source_commit')),
            'Policy source commit differs from frozen manifest')
    require(type(manifest.get('policy_rng_seed')) is int and
            type(policy.get('policy_rng_seed')) is int and policy['policy_rng_seed'] == manifest['policy_rng_seed'],
            'Policy RNG seed differs from frozen manifest')
    require(read(safe_file(folder, 'jobs.json')) == jobs, 'Stored jobs differ from declared plan')
    raw = safe_file(folder, 'results.jsonl').read_bytes()
    require(raw.endswith(b'\n'), 'Results have an unfinished trailing row')
    rows = [json.loads(line) for line in raw.splitlines()]
    expected = {job['job_id']: job for job in jobs}
    require(len(rows) == len(expected) and len({r['job_id'] for r in rows}) == len(rows), 'Incomplete or duplicate results')
    for row in rows:
        job = expected.get(row.get('job_id'))
        require(job is not None and all(row.get(key) == value for key, value in job.items()), 'Unexpected result identity')
        require(row.get('status') == 'complete' and row.get('forfeit') is False, 'Error/forfeit in evaluation')
        if plan.get('replays') == 'all':
            require(bool(row.get('replay')), 'Missing required replay')
            safe_file(folder, row['replay'])
    summary = read(folder / 'summary.json')
    require(league.summarize(rows, jobs) == summary, 'Summary does not match original results')
    sessions = [read(p) for p in folder.glob('session-*.json')]
    require(sessions and any(s.get('status') == 'complete' for s in sessions), 'No completed run session')
    pairs = {(r['candidate'], r['map_seed'], r['team'], r['opponent']) for r in rows}
    require(all((baseline, r['map_seed'], r['team'], r['opponent']) in pairs
                for r in rows if r['candidate'] == candidate), 'Candidate lacks matched baseline games')
    maps = set(plan['map_seeds'])
    require(maps and len(maps) == len(plan['map_seeds']), 'Duplicate or empty map set')
    return {'arena': str(arena), 'run_id': run_id, 'maps': sorted(maps), 'games': len(rows),
            'manifest_sha256': sha(arena / 'manifest.json'), 'summary_sha256': sha(folder / 'summary.json'),
            'results_sha256': sha(folder / 'results.jsonl'), 'sdk_input_sha256': sdk,
            'source_sha256': {name: manifest['bots'][name]['source_sha256'] for name in expected_sources},
            'opponents': plan['opponents'], 'opponent_sha256': {n: manifest['bots'][n]['source_sha256'] for n in plan['opponents']},
            'created_utc': policy.get('created_utc'),
            'finished_utc': max(s.get('finished_utc', '') for s in sessions if s.get('status') == 'complete')}


def check_decision(arena, candidate, decision_path, cpu_seed_start):
    decision = read(decision_path)
    require(decision.get('schema_version') == 1 and decision.get('approved') is True, 'Decision is not explicitly approved')
    require(decision.get('candidate') == candidate, 'Decision candidate differs')
    baseline = decision.get('baseline')
    require(isinstance(baseline, str) and baseline != candidate, 'Missing distinct evaluation baseline')
    require(isinstance(decision.get('rationale'), str) and decision['rationale'].strip(), 'Missing acceptance rationale')
    gates = decision.get('gates')
    require(isinstance(gates, dict) and gates and all(value is True for value in gates.values()), 'Acceptance gates missing or failed')
    manifest, sdk = verify_manifest(arena)
    sources = {candidate: decision['source_sha256'], baseline: decision['baseline_source_sha256']}
    for name, expected in sources.items():
        require(manifest['bots'].get(name, {}).get('source_sha256') == expected, 'Packaging source differs from decision: ' + name)
    selection = verify_run(decision['selection'], 'selection', candidate, baseline, sources)
    final = verify_run(decision['final'], 'final', candidate, baseline, sources)
    require(not set(selection['maps']) & set(final['maps']), 'Selection and final maps overlap')
    require(selection['sdk_input_sha256'] == final['sdk_input_sha256'] == sdk, 'SDK changed between evidence stages')
    require(selection['opponent_sha256'] == final['opponent_sha256'], 'Opponent pool changed between selection and final')
    require(selection['finished_utc'] and final['created_utc'] and
            datetime.fromisoformat(selection['finished_utc']) <= datetime.fromisoformat(final['created_utc']),
            'Final evidence started before selection completed')
    require(not set(package.cpu_seeds(cpu_seed_start)) & set(selection['maps'] + final['maps']), 'CPU validation maps reuse evaluation maps')
    # A final map reused in any earlier stage in the same arena is development evidence.
    final_arena = Path(final['arena'])
    for path in (final_arena / 'plans').glob('*-policy.json'):
        prior = read(path)
        if path.name == final['run_id'] + '-policy.json':
            continue
        if prior.get('stage') in ('smoke', 'development', 'selection'):
            require(not set(prior.get('map_seeds', [])) & set(final['maps']), 'Final maps overlap earlier arena maps')
    for evidence in (selection, final):
        evidence_arena = Path(evidence['arena'])
        evidence_manifest = read(evidence_arena / 'manifest.json')
        for name in sources:
            left = Path(manifest['bots'][name]['source']).parent
            right = Path(evidence_manifest['bots'][name]['source']).parent
            for header in ('protocol.hpp', 'generated.hpp'):
                require(sha(safe_file(arena, str(left / header))) == sha(safe_file(evidence_arena, str(right / header))),
                        'Candidate or baseline header changed: ' + header)
    return decision, manifest, {'selection': selection, 'final': final}


def normalized(args):
    args = argparse.Namespace(**vars(args))
    for name in ('arena', 'decision_json', 'output_zip', 'records'):
        raw = Path(getattr(args, name))
        require(not raw.is_symlink(), 'Refusing symlink path: ' + str(raw))
        setattr(args, name, raw.resolve())
    package.cpu_seeds(args.cpu_seed_start)
    decision = read(args.decision_json)
    inputs = [args.arena, args.decision_json]
    for stage in ('selection', 'final'):
        reference = decision.get(stage, {})
        if isinstance(reference, dict) and isinstance(reference.get('arena'), str):
            inputs.append(Path(reference['arena']).resolve())
    for path in (args.output_zip, args.records):
        require(not path.exists(), 'Refusing to overwrite output: ' + str(path))
        for other in inputs:
            require(not path.is_relative_to(other) and not other.is_relative_to(path), 'Output overlaps frozen input')
    require(not args.output_zip.is_relative_to(args.records) and not args.records.is_relative_to(args.output_zip), 'Output paths overlap')
    return args


def run(args):
    args = normalized(args)
    args.records.parent.mkdir(parents=True, exist_ok=True)
    args.records.mkdir()
    record = {'status': 'running', 'started_utc': package.stamp(), 'candidate': args.candidate,
              'helper_sha256': sha(Path(__file__)), 'shared_helper_sha256': sha(Path(package.__file__)),
              'scope': 'Separate deadline experiment acceptance evidence and exact-ZIP runtime checks; original campaign gates are unchanged.'}
    made_zip = False
    temporary_path = None
    try:
        decision, manifest, evidence = check_decision(args.arena, args.candidate, args.decision_json, args.cpu_seed_start)
        for stage in evidence.values():
            for output in (args.output_zip, args.records):
                root = Path(stage['arena'])
                require(not output.is_relative_to(root) and not root.is_relative_to(output), 'Output overlaps evidence arena')
        baseline = decision['baseline']
        record.update(source_commit=manifest['source_commit'], source_sha256=decision['source_sha256'],
                      baseline=baseline, baseline_source_sha256=decision['baseline_source_sha256'],
                      decision_sha256=sha(args.decision_json), evidence=evidence,
                      cpu_map_seeds=list(package.cpu_seeds(args.cpu_seed_start)))
        shutil.copyfile(args.decision_json, args.records / 'decision.json')
        write(args.records / 'manifest.json', manifest)
        for stage_name, stage in evidence.items():
            stage_root = Path(stage['arena'])
            target = args.records / 'evidence' / stage_name
            target.mkdir(parents=True)
            for filename in ('plan.json', 'summary.json', 'results.jsonl', 'jobs.json'):
                shutil.copyfile(stage_root / 'runs' / stage['run_id'] / filename, target / filename)
            shutil.copyfile(stage_root / 'plans' / (stage['run_id'] + '-policy.json'), target / 'policy.json')
            shutil.copyfile(stage_root / 'manifest.json', target / 'manifest.json')
        for program in (args.compiler, 'prlimit', 'timeout'):
            require(shutil.which(program) is not None, 'Missing program: ' + program)
        compiler = shutil.which(args.compiler)
        record['compiler'] = subprocess.check_output([compiler, '--version'], text=True, timeout=10).splitlines()[0]
        record['compiler_path'] = compiler
        record['python'] = sys.version
        record['runtime_limits'] = {'memory_address_space_mib': 384, 'turn_ms': 300, 'first_turn_ms': 3000,
                                    'process_wall_seconds': 180, 'official_compiler': 'GCC12.2/C++20',
                                    'limitation': 'Host environment is recorded; this does not certify official server isolation.'}
        record['sdk_tools_sha256'] = {name: sha(package.KIT / name) for name in ('submission.py','run_tests.py','output_usage.py','limits.json')}
        with tempfile.TemporaryDirectory(prefix='yk-deadline-package-', dir='/tmp') as temporary:
            tmp = Path(temporary)
            temporary_path = tmp
            source = tmp / 'source'
            source.mkdir()
            folder = Path(manifest['bots'][args.candidate]['source']).parent
            record['source_files'] = {}
            for name in package.FILES:
                relative = str(folder / name)
                if name == 'submission.json' and relative not in manifest['frozen_sha256']:
                    relative = 'snapshot/submissions/tuned/submission.json'
                original = package.frozen_file(args.arena, manifest, relative)
                shutil.copyfile(original, source / name)
                record['source_files'][name] = {'sha256': sha(original), 'frozen_path': relative}
            packer, checker = package.load_sdk()
            packer.build_zip(source, tmp / 'sdk.zip')
            archive = tmp / 'submission.zip'
            package.canonical_zip(tmp / 'sdk.zip', archive)
            record['zip'] = package.validate_zip(archive, source)
            inspection = packer.inspect_zip(archive)
            write(args.records / 'zip-inspection.json', inspection)
            require(inspection.get('ok') is True and not inspection.get('issues') and not inspection.get('warnings'), 'SDK ZIP inspection failed')
            extracted = tmp / 'extracted'
            require(packer.extract_zip(archive, extracted) == 'cpp', 'ZIP is not C++')
            for name in package.FILES:
                require(sha(extracted / name) == record['zip']['members'][name]['sha256'], 'Extracted file differs')
            package.compile_bot(compiler, extracted / 'main.cpp', tmp / 'candidate', args.records, 'candidate-from-zip')
            baseline_source = package.frozen_file(args.arena, manifest, manifest['bots'][baseline]['source'])
            package.compile_bot(compiler, baseline_source, tmp / 'baseline', args.records, 'baseline')
            rows = package.validate_runtime(checker, tmp / 'candidate', tmp / 'baseline', args.candidate, args.records,
                                            baseline=baseline, cpu_seed_start=args.cpu_seed_start)
            require(len(rows) == 4, 'Four paired CPU validation games did not complete')
            # Do not publish a ZIP until all source, protocol, resource and output checks passed.
            shutil.copytree(source, args.records / 'source')
            args.output_zip.parent.mkdir(parents=True, exist_ok=True)
            with args.output_zip.open('xb') as target, archive.open('rb') as incoming:
                made_zip = True
                shutil.copyfileobj(incoming, target)
            require(sha(args.output_zip) == record['zip']['sha256'], 'Published ZIP hash differs')
            record.update(status='validated', errors=0, forfeits=0, cpu_matches=4, sdk_smoke_matches=1,
                          maximum_candidate_response_ms=max(r['candidate_max_turn_ms'] for r in rows))
    except BaseException as exc:
        record.update(status='failed', error=f'{type(exc).__name__}: {exc}')
        (args.records / 'failure.txt').write_text(traceback.format_exc())
        if made_zip:
            args.output_zip.unlink(missing_ok=True)
        raise
    finally:
        record['temporary_directory_removed'] = temporary_path is None or not temporary_path.exists()
        record['finished_utc'] = package.stamp()
        write(args.records / 'validation.json', record)
    print(json.dumps({'status': record['status'], 'zip': str(args.output_zip), 'sha256': record['zip']['sha256'], 'records': str(args.records)}), flush=True)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('arena', 'decision-json', 'output-zip', 'records'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--candidate', required=True)
    parser.add_argument('--cpu-seed-start', type=int, default=15000)
    parser.add_argument('--compiler', default='g++')
    run(parser.parse_args())


if __name__ == '__main__':
    main()
