"""Eight independent SDK workers; each bot has its own verified quarter-CPU scope."""
import argparse
import datetime as dt
import gzip
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import traceback
import scope_runtime as rt

HERE = Path(__file__).resolve().parent
PLAN = rt.PLAN
DEADLINE = dt.datetime.fromisoformat(PLAN['hard_cutoff']).timestamp()


def write(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(path)


def interrupted(signum, frame):
    raise KeyboardInterrupt('signal ' + str(signum))


def worker(job_id):
    rt.verify_inputs()
    job = next(j for j in PLAN['jobs'] if j['id'] == job_id)
    directory = HERE / 'games' / job_id
    directory.mkdir(parents=True, exist_ok=False)
    row = dict(job, started_unix=time.time())
    started = time.monotonic()
    bots = []
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGALRM, interrupted)
    try:
        remaining = DEADLINE - time.time()
        if remaining <= 0:
            raise KeyboardInterrupt('hard cutoff before game')
        signal.setitimer(signal.ITIMER_REAL, min(180, remaining))
        for side in 'YK':
            bots.append(rt.ScopedBot(job[side], 'quarter', directory, job_id + '-' + side))
        replay, result = rt.run_match(job['map_seed'], rt.load_config(str(rt.SDK / 'config/balance.json')),
                                     *bots, turn_timeout_ms=300,
                                     names={s: job[s] for s in 'YK'}, on_bot_error='forfeit')
        signal.setitimer(signal.ITIMER_REAL, 0)
        encoded = json.dumps(replay, ensure_ascii=False, separators=(',', ':')).encode()
        (directory / 'replay.json.gz').write_bytes(gzip.compress(encoded, mtime=0))
        row.update(status='complete', result=result, sdk_replay_audit=rt.check_replay(replay),
                   replay_sha256=rt.sha(directory / 'replay.json.gz'))
    except (Exception, KeyboardInterrupt) as error:
        row.update(status='interrupted' if isinstance(error, KeyboardInterrupt) else 'error',
                   error=repr(error), interrupted=isinstance(error, KeyboardInterrupt),
                   traceback=traceback.format_exc())
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        # Ignore a second termination while releasing only this worker's own scopes.
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        for bot in bots:
            bot.close()
        row['scope_verification'] = rt.validate_scopes(bots)
        if not row['scope_verification']['ok']:
            row['status'] = 'infrastructure_error'
        row['bot_measurements'] = {s: {'name': job[s], 'responses': b.responses, 'scope': b.scope_result}
                                   for s, b in zip('YK', bots)}
        row['elapsed_seconds'] = time.monotonic() - started
        write(directory / 'result.json', row)
    return 0 if row['status'] == 'complete' else 2


def emergency_cleanup(job):
    evidence = []
    directory = HERE / 'games' / job['id']
    for metadata in directory.glob('*-launch.json'):
        launch = json.loads(metadata.read_text())
        unit = launch['unit']
        assert unit.startswith('yk-quarter-20261001-' + job['id'] + '-'), unit
        rt.active_units.add(unit)
        rt.unit_metadata[unit] = metadata
        evidence.append(rt.cleanup_unit(unit))
    return evidence


def aggregate(rows):
    groups = {}
    for row in rows:
        name = row['candidate']
        group = groups.setdefault(name, {'n': 0, 'wins': 0, 'draws': 0, 'losses': 0, 'points': 0,
                    'Y_points': 0, 'score_difference': 0, 'opponents': {}, 'errors': 0, 'forfeits': 0})
        group['n'] += 1
        if row['status'] != 'complete':
            group['errors'] += 1
            continue
        result = row['result']
        side = row['candidate_side']
        other = 'K' if side == 'Y' else 'Y'
        winner = result.get('winner')
        outcome = 'wins' if winner == side else 'draws' if winner in (None, 'draw', 'DRAW') else 'losses'
        points = 1 if outcome == 'wins' else .5 if outcome == 'draws' else 0
        group[outcome] += 1
        group['points'] += points
        group['Y_points'] += points if side == 'Y' else 0
        group['forfeits'] += int('forfeit' in str(result).lower())
        score = result.get('score', result.get('scores', {}))
        if isinstance(score, dict):
            group['score_difference'] += score.get(side, 0) - score.get(other, 0)
        opp = group['opponents'].setdefault(row['opponent'], {'n': 0, 'points': 0})
        opp['n'] += 1
        opp['points'] += points
    return groups


def strict_audit(rows, phase):
    directory = HERE / phase
    inputs = directory / 'strict-audit-input'
    inputs.mkdir(parents=True, exist_ok=True)
    index = [{'job_id': r['id'], 'candidate': r['candidate'], 'opponent': r['opponent'],
              'team': r['candidate_side'], 'map_seed': r['map_seed'],
              'replay': str(HERE / 'games' / r['id'] / 'replay.json.gz')}
             for r in rows if r['status'] == 'complete' and 'replay_sha256' in r]
    (inputs / 'results.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in index))
    cmd = [sys.executable, str(rt.ARENA / 'snapshot/experiments/audit_deadline_actions.py'),
           '--run-dir', str(inputs), '--output', str(directory / 'strict-action-audit.json'),
           '--sdk-dir', str(rt.SDK)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    (directory / 'strict-action-audit.log').write_text(proc.stdout + proc.stderr)
    if proc.returncode:
        raise RuntimeError('strict auditor failed: ' + proc.stderr)
    audit = json.loads((directory / 'strict-action-audit.json').read_text())
    issues = {label: {k: v for k, v in counts.items() if k not in ('turns', 'commands') and v}
              for label, counts in audit['counts'].items()}
    issues = {label: counts for label, counts in issues.items() if counts}
    gate = {'passed': not issues and not audit['examples'], 'issues': issues,
            'audited_replays': audit['replays'], 'audited_frames': audit['frames']}
    write(directory / 'strict-action-audit-gate.json', gate)
    return gate


def run(phase, frozen_commit, selected):
    rt.verify_inputs()
    if phase == 'confirmation' and (not selected or selected == 'v8'):
        raise ValueError('confirmation requires one selected non-v8 candidate')
    jobs = [j for j in PLAN['jobs'] if j['phase'] == phase and
            (phase == 'selection' or j['candidate'] in ('v8', selected))]
    assert len(jobs) == (128 if phase == 'selection' else 64), len(jobs)
    directory = HERE / phase
    directory.mkdir(exist_ok=False)
    execution = {'phase': phase, 'selected': selected, 'frozen_commit': frozen_commit,
                 'plan_sha256': rt.sha(HERE / 'plan.json'), 'started_unix': time.time(),
                 'workers': 8, 'expected_games': len(jobs), 'job_ids': [j['id'] for j in jobs]}
    write(directory / 'execution.json', execution)
    signal.signal(signal.SIGTERM, interrupted)
    active = {}
    pending = list(jobs)
    rows = []
    stop = False
    terminated_at = {}
    try:
        while pending or active:
            if time.time() >= DEADLINE - 40:
                stop = True
            while pending and len(active) < 8 and not stop:
                job = pending.pop(0)
                log = (directory / (job['id'] + '.log')).open('w')
                proc = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--worker', job['id']],
                                        stdout=log, stderr=subprocess.STDOUT)
                active[proc.pid] = (proc, job, log)
            if time.time() >= DEADLINE:
                for proc, job, log in active.values():
                    if proc.pid not in terminated_at:
                        proc.terminate()
                        terminated_at[proc.pid] = time.monotonic()
                    elif time.monotonic() - terminated_at[proc.pid] > 30:
                        proc.kill()
            for pid, (proc, job, log) in list(active.items()):
                if proc.poll() is None:
                    continue
                log.close()
                path = HERE / 'games' / job['id'] / 'result.json'
                row = json.loads(path.read_text()) if path.exists() else dict(job, status='worker_crash', returncode=proc.returncode)
                if row['status'] == 'worker_crash':
                    row['emergency_cleanup'] = emergency_cleanup(job)
                rows.append(row)
                with (directory / 'results.jsonl').open('a') as output:
                    output.write(json.dumps(row, ensure_ascii=False, separators=(',', ':')) + '\n')
                del active[pid]
                if row['status'] != 'complete':
                    stop = True
                write(directory / 'progress.json', {'completed': len(rows), 'active': len(active),
                       'pending': len(pending), 'stop': stop, 'results': aggregate(rows)})
                print(json.dumps({'finished': len(rows), 'job': job['id'], 'status': row['status'],
                                  'result': row.get('result'), 'elapsed': row.get('elapsed_seconds')}, ensure_ascii=False), flush=True)
            if stop and not active:
                break
            time.sleep(.1)
    except KeyboardInterrupt:
        stop = True
        for proc, job, log in active.values():
            proc.terminate()
        for proc, job, log in active.values():
            try:
                proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
                emergency_cleanup(job)
            log.close()
            path = HERE / 'games' / job['id'] / 'result.json'
            if path.exists():
                rows.append(json.loads(path.read_text()))
            else:
                rows.append(dict(job, status='worker_crash', returncode=proc.returncode, emergency_cleanup=emergency_cleanup(job)))
        (directory / 'results.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))
    gate = strict_audit(rows, phase)
    rt.verify_inputs()
    summary = {'execution': execution, 'finished_unix': time.time(), 'complete': len(rows) == len(jobs) and
               all(r['status'] == 'complete' for r in rows), 'stop': stop, 'strict_gate': gate,
               'completed_games': len(rows), 'expected_games': len(jobs), 'results': aggregate(rows),
               'unstarted': [j['id'] for j in pending], 'inputs_unchanged': True,
               'all_scope_cleanups_verified': all(r.get('scope_verification', {}).get('ok') for r in rows)}
    write(directory / 'summary.json', summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--worker')
    parser.add_argument('--calibrate', action='store_true')
    parser.add_argument('--phase', choices=['selection', 'confirmation'])
    parser.add_argument('--selected', choices=['mission4', 'v9_lock', 'v8_flagguard'])
    parser.add_argument('--frozen-commit')
    args = parser.parse_args()
    if args.worker:
        sys.exit(worker(args.worker))
    elif args.calibrate:
        rt.calibrate()
    elif args.phase and args.frozen_commit:
        run(args.phase, args.frozen_commit, args.selected)
    else:
        parser.error('Choose calibration, worker, or phase with frozen commit')
