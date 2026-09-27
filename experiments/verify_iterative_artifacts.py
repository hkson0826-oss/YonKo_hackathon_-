"""Check frozen sources, every saved logical trace, original inputs, and TMP cleanup."""
import argparse
import datetime
import gzip
import hashlib
import json
from pathlib import Path
import subprocess


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(arena, host=None):
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((arena / 'manifest.json').read_text())
    frozen, omitted = 0, 0
    for name, expected in manifest['frozen_sha256'].items():
        path = arena / name
        if name.startswith('bin/'):
            assert not path.exists(), name
            omitted += 1
        else:
            assert sha(path) == expected, name
            frozen += 1
    result = json.loads((arena / 'campaign-result.json').read_text())
    stages, seeds, games, errors, forfeits, replay_count, maximum = {}, set(), 0, 0, 0, 0, 0.0
    for stage, count in result['stage_match_counts'].items():
        run = arena / 'runs' / stage
        rows = [json.loads(line) for line in (run / 'results.jsonl').read_text().splitlines()]
        indexed = {row['job_id']: row for row in rows}
        assert len(indexed) == len(rows), stage
        completed = [r for r in rows if r['status'] == 'complete']
        assert len(completed) == count, stage
        games += count
        errors += len(rows) - count
        forfeits += sum(row.get('forfeit', False) for row in rows)
        seeds.update(row['map_seed'] for row in rows)
        for row in completed:
            assert 'replay' in row and (run / row['replay']).is_file(), row['job_id']
            maximum = max(maximum, row['max_turn_ms'], row['opponent_max_turn_ms'])
        saved = 0
        for path in sorted((run / 'replays').glob('*.json.gz')):
            replay = json.loads(gzip.decompress(path.read_bytes()))
            row = indexed[path.name.removesuffix('.json.gz')]
            assert replay['result'] == row['result'], str(path)
            value = {'turns': replay['turns'], 'result': replay['result']}
            actual = hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
            assert actual == row['logical_trace_sha256'], str(path)
            saved += 1
        assert saved == len(completed), stage
        replay_count += saved
        stages[stage] = {'games': count, 'full_replays_verified': saved,
                         'distinct_maps': len({row['map_seed'] for row in rows})}
        print(json.dumps({'verified_stage': stage, **stages[stage]}), flush=True)
    originals = json.loads((root / 'records/official/round1/source-manifest.json').read_text())['files']
    for original in originals:
        assert sha(root / original['path']) == original['sha256'], original['path']
    zip_hash = sha(root / 'artifacts/submission-v2.zip')
    assert zip_hash == 'f90eca7cac0024ab4cc7c00d79595f71e4eb9bab92ec57e0527c7b977098b64a'
    receipt = json.loads((arena / 'transport_receipt.json').read_text())
    assert receipt['returncode'] == 0 and receipt['cleanup']['archive_accepted']
    assert receipt['cleanup']['exists'] is False
    report = {'checked_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'status': 'passed', 'source_commit': manifest['source_commit'],
              'frozen_source_files_verified': frozen, 'binaries_intentionally_omitted': omitted,
              'games': games, 'distinct_maps': len(seeds), 'stages': stages,
              'full_replays_trace_hash_verified': replay_count, 'errors': errors, 'forfeits': forfeits,
              'maximum_response_ms_both_bots': maximum, 'official_originals_unchanged': len(originals),
              'submission_v2_sha256': zip_hash, 'transport_cleanup': receipt['cleanup']}
    if host:
        directory = receipt['cleanup']['path']
        if not directory.startswith('/tmp/yk-league-') or '/' in directory[len('/tmp/'):]:
            raise ValueError('Unexpected remote TMP path')
        script = '''import pathlib,json,os
root=ROOT_VALUE
matched=[]
for proc in pathlib.Path('/proc').iterdir():
 if not proc.name.isdigit() or int(proc.name)==os.getpid():continue
 try:
  if str((proc/'cwd').readlink()).startswith(root) or root.encode() in (proc/'cmdline').read_bytes():matched.append(int(proc.name))
 except OSError:pass
print(json.dumps({'path':root,'path_exists':pathlib.Path(root).exists(),'matching_process_ids':matched}))
'''.replace('ROOT_VALUE', repr(directory))
        check = subprocess.run(['ssh', '-T', host, 'python3', '-'], input=script,
                               text=True, capture_output=True, check=True, timeout=30)
        cleanup = json.loads(check.stdout)
        assert not cleanup['path_exists'] and not cleanup['matching_process_ids'], cleanup
        report['independent_cleanup_check'] = cleanup
    (arena / 'artifact-verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('arena', type=Path)
    parser.add_argument('--host')
    args = parser.parse_args()
    print(json.dumps(verify(args.arena.resolve(), args.host), ensure_ascii=False))
