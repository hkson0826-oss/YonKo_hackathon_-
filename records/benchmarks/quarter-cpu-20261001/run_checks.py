"""SDK matches with one independently limited transient scope per bot."""
import argparse
import atexit
import gzip
import hashlib
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import time
import uuid

HERE = Path(__file__).resolve().parent
PLAN = json.loads((HERE / 'plan.json').read_text())
ARENA = Path(PLAN['arena'])
SDK = ARENA / 'snapshot/yk-development-tools'
sys.path.insert(0, str(SDK))
from engine.config import load_config
from engine.pipeline import run_turn
from mapgen import generate, to_state
from runner.bots import SubprocessBot
from runner.match import run_match
from runner.protocol import parse_commands
from runner.replay import snapshot

active_units = set()
unit_metadata = {}

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def unit_call(*args):
    return subprocess.run(['systemctl', '--user', *args], capture_output=True, text=True, timeout=5)

def cleanup_unit(unit):
    if unit not in active_units:
        return {'ok': True, 'already_cleaned': True}
    metadata = unit_metadata.get(unit)
    cg = None
    if metadata and metadata.exists():
        cg = Path(json.loads(metadata.read_text())['cgroup'])
    evidence = {'unit': unit, 'operations': []}
    try:
        for operation in [('kill', '--kill-whom=all', '--signal=KILL', unit), ('stop', unit)]:
            result = unit_call(*operation)
            evidence['operations'].append({'argv': list(operation), 'returncode': result.returncode,
                                           'stdout': result.stdout, 'stderr': result.stderr})
        for _ in range(30):
            result = unit_call('show', unit, '--property=LoadState', '--value')
            state = result.stdout.strip()
            removed = cg is None or not cg.exists()
            if state == 'not-found' and removed:
                break
            time.sleep(.02)
        evidence.update(load_state=state, cgroup_path=str(cg) if cg else None,
                        cgroup_removed=removed, ok=state == 'not-found' and removed)
        if cg and cg.exists() and (cg / 'cgroup.procs').exists():
            evidence['remaining_cgroup_procs'] = (cg / 'cgroup.procs').read_text().strip()
    except Exception as error:
        evidence.update(ok=False, error=repr(error))
    if evidence['ok']:
        active_units.discard(unit)
    return evidence

@atexit.register
def cleanup_all():
    for unit in list(active_units):
        try:
            cleanup_unit(unit)
        except Exception:
            pass

def scope_command(name, condition, metadata, command):
    unit = 'yk-quarter-20261001-' + name + '-' + uuid.uuid4().hex[:10] + '.scope'
    args = ['systemd-run', '--user', '--scope', '--quiet', '--collect', '--no-ask-password',
            '--unit=' + unit, '--property=MemoryMax=402653184']
    if condition == 'quarter':
        args += ['--property=CPUQuota=25%', '--property=CPUQuotaPeriodSec=100ms']
    expected = '25000 100000' if condition == 'quarter' else 'unlimited'
    args += ['--', sys.executable, str(HERE / 'launch_bot.py'), '--metadata', str(metadata),
             '--unit', unit, '--expected-cpu-max', expected, '--', *command]
    active_units.add(unit)
    unit_metadata[unit] = metadata
    return unit, args

def read_metrics(metadata):
    if not metadata.exists():
        return {'metadata_missing': True}
    result = json.loads(metadata.read_text())
    cg = Path(result['cgroup'])
    result['final_metrics'] = {}
    for name in ['cpu.max', 'cpu.stat', 'memory.current', 'memory.peak', 'memory.events', 'cgroup.procs']:
        file = cg / name
        result['final_metrics'][name] = file.read_text().strip() if file.exists() else None
    return result

class ScopedBot(SubprocessBot):
    def __init__(self, name, condition, directory, label):
        self.metadata_path = directory / (label + '-launch.json')
        self.unit, argv = scope_command(label, condition, self.metadata_path, shlex.split(PLAN['bots'][name]['command']))
        self.responses = []
        self.scope_result = None
        self.closed_scope = False
        super().__init__(shlex.join(argv), name=name)

    def collect_turn(self):
        previous = self.max_turn_ms
        self.max_turn_ms = 0.0
        try:
            lines, status = super().collect_turn()
            response = {'turn': len(self.responses) + 1, 'status': status,
                        'response_ms': self.max_turn_ms if status == 'ok' else None,
                        'collection_elapsed_ms': (time.monotonic() - self._start) * 1000}
            if lines is not None:
                response.update(lines=len(lines), bytes=sum(len(line.encode()) + 1 for line in lines))
                if len(lines) + 1 > 4096 or response['bytes'] + 4 > 65536 or any(len((line + '\n').encode()) > 1024 for line in lines):
                    status = response['status'] = 'invalid_output'
                    lines = None
            self.responses.append(response)
            return lines, status
        finally:
            self.max_turn_ms = max(previous, self.max_turn_ms)

    def close(self):
        if not self.closed_scope:
            try:
                self.scope_result = read_metrics(self.metadata_path)
            except Exception as error:
                self.scope_result = {'metadata_error': repr(error)}
            self.scope_result['cleanup'] = cleanup_unit(self.unit)
            self.closed_scope = self.scope_result['cleanup']['ok']
        super().close()


def validate_scopes(bots):
    errors = []
    runner_relative = Path('/proc/self/cgroup').read_text().strip().split('::', 1)[1]
    runner_group = Path('/sys/fs/cgroup') / runner_relative.lstrip('/')
    groups = []
    for bot in bots:
        result = bot.scope_result or {}
        if result.get('metadata_missing') or result.get('metadata_error') or 'cgroup' not in result:
            errors.append({'bot': bot.name, 'cause': 'scope launch verification missing', 'evidence': result})
            continue
        group = Path(result['cgroup'])
        groups.append(str(group))
        if runner_group.is_relative_to(group):
            errors.append({'bot': bot.name, 'cause': 'runner inside bot CPU quota'})
        if not result.get('cleanup', {}).get('ok'):
            errors.append({'bot': bot.name, 'cause': 'scope cleanup not verified', 'evidence': result.get('cleanup')})
    if len(groups) != 2 or len(set(groups)) != 2:
        errors.append({'cause': 'two independent verified bot scopes required', 'groups': groups})
    return {'ok': not errors, 'runner_cgroup': str(runner_group), 'bot_cgroups': groups, 'errors': errors}


def verify_inputs():
    for rel, expected in PLAN['source_sha256'].items():
        assert sha(ARENA / rel) == expected, rel
    for name, item in PLAN['bots'].items():
        assert sha(shlex.split(item['command'])[0]) == item['binary_sha256'], name
    for name, expected in PLAN['harness_sha256'].items():
        assert sha(HERE / name) == expected, name
    calibration = json.loads((HERE / 'calibration/validation.json').read_text())
    assert calibration['passed'], calibration
    assert calibration['harness_sha256'] == PLAN['harness_sha256'], 'Calibration must use frozen harness'
    assert not active_units, 'Existing uncleaned experiment scope'


def calibrate():
    directory = HERE / 'calibration'
    directory.mkdir(exist_ok=True)
    results = []
    for condition in ['normal', 'quarter']:
        metadata = directory / (condition + '-launch.json')
        unit, command = scope_command('calibration-' + condition, condition, metadata,
                                      [sys.executable, str(HERE / 'busy_probe.py')])
        started = time.monotonic()
        try:
            response = subprocess.run(command, text=True, capture_output=True, timeout=10)
            result = {'condition': condition, 'argv': command, 'returncode': response.returncode,
                      'stdout': response.stdout, 'stderr': response.stderr,
                      'wrapper_wall_seconds': time.monotonic() - started,
                      'launch': json.loads(metadata.read_text()) if metadata.exists() else None}
            (directory / (condition + '-attempt-' + str(time.time_ns()) + '.json')).write_text(json.dumps(result, indent=2) + '\n')
            assert response.returncode == 0, result
            result['probe'] = json.loads(response.stdout)
            if condition == 'quarter':
                assert result['probe']['cpu.max'] == '25000 100000', result
                assert .25 <= result['probe']['cpu_seconds'] < .35, result
                assert result['probe']['wall_seconds'] > .65, result
                stat = dict(line.split() for line in result['probe']['cpu.stat'].splitlines())
                assert int(stat.get('nr_throttled', 0)) > 0, result
                result['probe']['cpu_wall_ratio'] = result['probe']['cpu_seconds'] / result['probe']['wall_seconds']
        finally:
            cleanup = cleanup_unit(unit)
        result['cleanup'] = cleanup
        assert cleanup['ok'], cleanup
        result['cgroup_removed'] = not Path(result['launch']['cgroup']).exists()
        results.append(result)
    (directory / 'results.json').write_text(json.dumps(results, indent=2) + '\n')
    validation = {'passed': len(results) == 2 and all(r['cleanup']['ok'] for r in results),
                  'harness_sha256': {n:sha(HERE/n) for n in PLAN['harness_sha256']},
                  'normal_probe':results[0]['probe'], 'quarter_probe':results[1]['probe']}
    (directory / 'validation.json').write_text(json.dumps(validation, indent=2) + '\n')
    print(json.dumps(validation, indent=2), flush=True)


def check_replay(replay):
    state = to_state(generate(replay['seed'], replay['config']))
    count = 0
    for frame in replay['turns']:
        for side in 'YK':
            parsed = parse_commands(frame['commands'][side])
            assert len(parsed) == len(frame['commands'][side]), (frame['turn'], side, 'parser dropped command')
        state, _ = run_turn(state, parse_commands(frame['commands']['Y']), parse_commands(frame['commands']['K']))
        assert snapshot(state) == frame['state'], frame['turn']
        count += 1
    return {'verified_turns': count, 'command_lines_all_parsed': True}


def game_timeout(signum, frame):
    raise TimeoutError('Match exceeded 180 seconds wall time')


def run_games(frozen_commit, conditions):
    verify_inputs()
    execution = {'frozen_research_commit': frozen_commit, 'plan_sha256': sha(HERE / 'plan.json'),
                 'started_unix': time.time(), 'harness_pid': os.getpid(),
                 'harness_cgroup': Path('/proc/self/cgroup').read_text(), 'conditions': conditions}
    (HERE / 'execution.json').write_text(json.dumps(execution, indent=2) + '\n')
    signal.signal(signal.SIGALRM, game_timeout)
    signal.signal(signal.SIGTERM, lambda signum, frame: (_ for _ in ()).throw(KeyboardInterrupt('SIGTERM')))
    results = []
    for index, job in enumerate(PLAN['jobs']):
        if job['condition'] not in conditions:
            continue
        directory = HERE / 'games' / job['id']
        directory.mkdir(parents=True, exist_ok=False)
        bots = []
        row = dict(job, started_unix=time.time())
        started = time.monotonic()
        try:
            for side in 'YK':
                bots.append(ScopedBot(job[side], job['condition'], directory, job['id'] + '-' + side))
            signal.setitimer(signal.ITIMER_REAL, 180)
            replay, result = run_match(job['map_seed'], load_config(str(SDK / 'config/balance.json')),
                                       *bots, turn_timeout_ms=300,
                                       names={s:job[s] for s in 'YK'}, on_bot_error='forfeit')
            signal.setitimer(signal.ITIMER_REAL, 0)
            encoded = json.dumps(replay, ensure_ascii=False, separators=(',', ':')).encode()
            (directory / 'replay.json.gz').write_bytes(gzip.compress(encoded, mtime=0))
            row.update(status='complete', result=result, sdk_replay_audit=check_replay(replay),
                       replay_sha256=sha(directory / 'replay.json.gz'))
        except (Exception, KeyboardInterrupt) as error:
            row.update(status='interrupted' if isinstance(error, KeyboardInterrupt) else 'error', error=repr(error),
                       interrupted=isinstance(error, KeyboardInterrupt))
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            for bot in bots:
                bot.close()
            row['scope_verification'] = validate_scopes(bots)
            if not row['scope_verification']['ok']:
                row['status'] = 'infrastructure_error'
                row['infrastructure_errors'] = row['scope_verification']['errors']
            row['bot_measurements'] = {s:{'name':job[s], 'responses':b.responses, 'scope':b.scope_result}
                                       for s,b in zip('YK', bots)}
            row['elapsed_seconds'] = time.monotonic() - started
            (directory / 'result.json').write_text(json.dumps(row, indent=2) + '\n')
            with (HERE / 'results.jsonl').open('a') as file:
                file.write(json.dumps(row, separators=(',', ':')) + '\n')
        results.append(row)
        if row.get('interrupted'):
            raise KeyboardInterrupt(row['error'])
        if row['status'] == 'infrastructure_error':
            raise RuntimeError('Scope verification failed; remaining games stopped')
        print(json.dumps({'job':job['id'], 'status':row['status'], 'result':row.get('result'),
                          'elapsed':row['elapsed_seconds']}, ensure_ascii=False), flush=True)
    write_strict_audit(results)
    (HERE / 'summary.json').write_text(json.dumps({'execution':execution,'games':[
        {k:v for k,v in row.items() if k!='bot_measurements'} for row in results]}, indent=2) + '\n')

def write_strict_audit(results):
    inputs = HERE / 'strict-audit-input'
    inputs.mkdir(exist_ok=True)
    rows = []
    for row in results:
        if row['status'] != 'complete' or 'replay_sha256' not in row:
            continue
        rows.append({'job_id': row['id'], 'candidate': row['candidate'], 'opponent': 'v8',
                     'team': row['candidate_side'], 'map_seed': row['map_seed'],
                     'replay': '../games/' + row['id'] + '/replay.json.gz'})
    (inputs / 'results.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))
    command = [sys.executable, str(ARENA / 'snapshot/experiments/audit_deadline_actions.py'),
               '--run-dir', str(inputs), '--output', str(HERE / 'strict-action-audit.json'),
               '--sdk-dir', str(SDK)]
    response = subprocess.run(command, text=True, capture_output=True, timeout=30)
    (HERE / 'strict-action-audit.log').write_text(response.stdout + response.stderr)
    assert response.returncode == 0, response.stderr
    audit = json.loads((HERE / 'strict-action-audit.json').read_text())
    issues = {label: {key:value for key,value in counts.items() if key not in ('turns', 'commands') and value}
              for label,counts in audit['counts'].items()}
    issues = {label:counts for label,counts in issues.items() if counts}
    gate = {'passed': not issues and not audit['examples'], 'issues': issues,
            'audited_replays':audit['replays'], 'audited_frames':audit['frames']}
    (HERE / 'strict-action-audit-gate.json').write_text(json.dumps(gate, indent=2) + '\n')
    assert gate['passed'], gate


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--calibrate', action='store_true')
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--frozen-commit')
    parser.add_argument('--conditions', nargs='+', choices=['normal', 'quarter'], default=['quarter', 'normal'])
    args = parser.parse_args()
    if args.calibrate:
        calibrate()
    elif args.run:
        if not args.frozen_commit:
            parser.error('--run requires the research commit recorded after root freezes the plan')
        run_games(args.frozen_commit, args.conditions)
    else:
        parser.error('Choose --calibrate or --run')
