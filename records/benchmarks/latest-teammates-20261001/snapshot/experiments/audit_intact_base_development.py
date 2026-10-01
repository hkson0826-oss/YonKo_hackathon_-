"""Inspect fixed paired intact-base/screen-refine reversals from a completed development run."""
from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'yk-development-tools'))
from engine.pipeline import run_turn
from mapgen import generate, to_state
from runner.protocol import parse_commands, serialize_init, serialize_turn
from runner.replay import snapshot
from audit_v3_decision import TRACE, change
from audit_s3_failures import stats

PARENT = 's3_screen_refine'
CANDIDATE = 's3_v2_screen_intact_base'
RULE = 'For each loss-to-win and win-to-loss: descending absolute own-score-margin change, then map seed, opponent ID, side ascending.'

PROBE = r'''
Action audit_seed;
double audit_base_ms=0,audit_base_value=0;
int audit_base_aborts=0,audit_continuation=0,audit_shallow=0,audit_deep=0;
bool audit_seed_done=false;
void intact_audit(const Action& chosen,double elapsed) {
    cerr<<setprecision(12)<<"{\"search_ms\":"<<elapsed<<",\"base_ms\":"<<audit_base_ms
        <<",\"base_aborts\":"<<audit_base_aborts<<",\"all_aborts\":"<<audit_aborted
        <<",\"base_value\":"<<audit_base_value<<",\"continuation\":"<<audit_continuation
        <<",\"shallow_completed\":"<<audit_shallow<<",\"deep_completed\":"<<audit_deep
        <<",\"chosen_is_base\":"<<(a_equal(chosen,audit_seed)?"true":"false")<<",\"base_action\":";
    audit_action(audit_seed);cerr<<",\"chosen\":";audit_action(chosen);cerr<<"}\n";
}
'''


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def instrument(source):
    source = change(source, 'using AClock=chrono::steady_clock;', TRACE + '\nusing AClock=chrono::steady_clock;')
    source = change(source, 'bool a_evaluate(', PROBE + '\nbool a_evaluate(')
    # The revision also carries an unused paired evaluator; instrument the original first evaluator only.
    source = source.replace('>=limit) return false;', '>=limit) {++audit_aborted;return false;}', 1)
    source = change(source, '    result=count==1?scenarios[0]:min(scenarios[0],scenarios[1]);',
                    '    if(audit_seed_done) {if(horizon==1) ++audit_shallow;else ++audit_deep;}\n'
                    '    result=count==1?scenarios[0]:min(scenarios[0],scenarios[1]);')
    source = change(source, '    return incumbent.action;\n}',
                    '    audit_seed=incumbent.action;audit_base_value=incumbent.value;audit_continuation=incumbent.continuation;\n'
                    '    audit_base_ms=chrono::duration<double,milli>(AClock::now()-start).count();\n'
                    '    audit_base_aborts=audit_aborted;audit_seed_done=true;\n    return incumbent.action;\n}')
    anchor = next(line for line in source.splitlines() if 'Action a=forced_policy>=' in line)
    return change(source, anchor,
                  '    audit_seed_done=false;audit_aborted=audit_shallow=audit_deep=0;\n' + anchor +
                  '\n    if(v.turn==atoi(getenv("YK_AUDIT_TURN"))) intact_audit(a,chrono::duration<double,milli>(AClock::now()-start).count());')


def select(rows):
    indexed = {(r['candidate'], r['map_seed'], r['opponent'], r['team']): r for r in rows}
    if len(indexed) != len(rows) or any(r['status'] != 'complete' for r in rows):
        raise ValueError('Duplicate or incomplete development rows')
    cases = []
    for kind in ('loss_to_win', 'win_to_loss'):
        pairs = []
        for row in rows:
            if row['candidate'] != CANDIDATE:
                continue
            parent = indexed[PARENT, row['map_seed'], row['opponent'], row['team']]
            win = lambda r: r['result']['winner'] == r['team']
            loss = lambda r: r['result']['winner'] not in ('DRAW', r['team'])
            qualifies = win(row) and loss(parent) if kind == 'loss_to_win' else loss(row) and win(parent)
            if not qualifies:
                continue
            delta = row['score_margin'] - parent['score_margin']
            pairs.append(((-abs(delta), row['map_seed'], row['opponent'], row['team']), row, parent, delta))
        if not pairs:
            raise ValueError('No completed pair for ' + kind)
        _, row, parent, delta = min(pairs, key=lambda item: item[0])
        cases.append({'kind': kind, 'seed': row['map_seed'], 'opponent': row['opponent'], 'team': row['team'],
                      'margin_delta': delta, 'eligible_pairs': len(pairs), 'rows': {'candidate': row, 'baseline': parent}})
    return cases


def analyze(development):
    rows_path = development / 'results.jsonl'
    rows = [json.loads(line) for line in rows_path.read_text().splitlines() if line.strip()]
    cases = select(rows)
    source = (ROOT / 'submissions/iterative-v3/main.cpp').read_text()
    module_path = ROOT / 'experiments/local_league/v3_action_search.py'
    spec = importlib.util.spec_from_file_location('intact_audit_generator', module_path)
    module = importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    population = module.variants(source) + module.variants_iteration2(source)
    sources = {c['id']: c['source'] for c in population if c['id'] in (PARENT, CANDIDATE)}
    sources.update(v3_135=source, v3_65=change(source, 'double limit=135.0)', 'double limit=65.0)'))
    with tempfile.TemporaryDirectory(prefix='yk-intact-build-', dir='/tmp') as temporary:
        directory = Path(temporary)
        binaries = {}
        instrumented = {}
        for name, text in sources.items():
            cpp = directory / (name + '.cpp');cpp.write_text('#define NDEBUG\n' + instrument(text))
            binary = directory / name
            done = subprocess.run(['g++', '-std=c++20', '-O2', '-I', str(ROOT / 'submissions/iterative-v3'),
                                   str(cpp), '-o', str(binary)], capture_output=True, text=True, timeout=90)
            if done.returncode:
                raise RuntimeError(done.stderr)
            binaries[name] = binary;instrumented[name] = sha(cpp)
        for case in cases:
            replays = {}
            for label, row in case['rows'].items():
                relative = 'replays/' + row['job_id'] + '.json.gz'
                replay = json.loads(gzip.decompress((development / relative).read_bytes()))
                replay_state = to_state(generate(replay['seed'], replay['config']))
                for frame in replay['turns']:
                    replay_state, _ = run_turn(replay_state, parse_commands(frame['commands']['Y']), parse_commands(frame['commands']['K']))
                    assert snapshot(replay_state) == frame['state']
                replays[label] = replay
                case[label] = {'job_id': row['job_id'], 'result': row['result'], 'replay_sha256': sha(development / relative),
                               'canonical_path': 'records/league/loop3-iteration2/runs/development/' + relative,
                               'official_transitions_verified': len(replay['turns'])}
            own = case['team'];enemy = 'K' if own == 'Y' else 'Y'
            candidate, parent = replays['candidate'], replays['baseline']
            paired = list(zip(candidate['turns'], parent['turns']))
            first = next(i + 1 for i, (a, b) in enumerate(paired) if a['commands'][own] != b['commands'][own])
            first_state = next(i + 1 for i, (a, b) in enumerate(paired) if a['state'] != b['state'])
            initial = to_state(generate(candidate['seed'], candidate['config']));state = initial
            blocks = [serialize_init(initial, own)]
            for i in range(first):
                blocks.append(serialize_turn(state, own, i + 1))
                if i < first - 1:
                    frame = candidate['turns'][i]
                    state, _ = run_turn(state, parse_commands(frame['commands']['Y']), parse_commands(frame['commands']['K']))
            payload = ''.join(blocks)
            runs = {}
            for name, binary in binaries.items():
                result = subprocess.run([str(binary)], input=payload, text=True, capture_output=True, timeout=30,
                                        check=True, env={**os.environ, 'YK_AUDIT_TURN': str(first)})
                lines = result.stdout.split('END\n')[-2].strip().splitlines()
                runs[name] = {'commands': lines, 'trace': json.loads(result.stderr),
                              'source_sha256': hashlib.sha256(sources[name].encode()).hexdigest(),
                              'instrumented_source_sha256': instrumented[name]}
            fixed = parse_commands(candidate['turns'][first - 1]['commands'][enemy])
            one_step = {}
            for name, run in runs.items():
                action = parse_commands(run['commands'])
                after, _ = run_turn(copy.deepcopy(state), action if own == 'Y' else fixed, fixed if own == 'Y' else action)
                one_step[name] = snapshot(after)
            case.update(first_command_divergence=first, first_state_divergence=first_state,
                        previous_states_equal=all(a['state'] == b['state'] for a, b in paired[:first-1]),
                        opponent_first_action_equal=candidate['turns'][first-1]['commands'][enemy] == parent['turns'][first-1]['commands'][enemy],
                        pre_state=snapshot(state), legal_observation=blocks[-1], payload_sha256=hashlib.sha256(payload.encode()).hexdigest(),
                        runs=runs, one_step_fixed_opponent=one_step,
                        candidate_output_reproduced=runs[CANDIDATE]['commands'] == candidate['turns'][first-1]['commands'][own],
                        parent_output_reproduced=runs[PARENT]['commands'] == parent['turns'][first-1]['commands'][own],
                        base_action_equal=runs[PARENT]['trace']['base_action'] == runs[CANDIDATE]['trace']['base_action'])
            for label, row in case['rows'].items():
                case[label]['first_turn_response_ms'] = row['response_ms'][first-1]
                case[label]['recorded_first_commands'] = replays[label]['turns'][first-1]['commands'][own]
            case['recorded_first_opponent_commands'] = candidate['turns'][first-1]['commands'][enemy]
            building_map = {b['id']: b for b in candidate['map']['buildings']}
            case['trajectory'] = {label: [stats(f, building_map) for f in replay['turns'] if f['turn'] in (first, first+1, 30, 45, 60, 90, 120)]
                                  for label, replay in replays.items()}
            del case['rows']
    return {'scope': 'Post-development diagnosis only; no source, selection, or campaign changes.',
            'rows': len(rows), 'errors': sum(r['status'] != 'complete' for r in rows), 'forfeits': sum(r['forfeit'] for r in rows),
            'results_sha256': sha(rows_path), 'selection_rule': RULE, 'cases': cases,
            'generator_sha256': sha(module_path), 'audit_script_sha256': sha(Path(__file__)),
            'compiler': subprocess.check_output(['g++', '--version'], text=True).splitlines()[0],
            'platform': platform.platform(), 'cpu_affinity': sorted(os.sched_getaffinity(0)),
            'temporary_build_removed': not directory.exists(),
            'limits': ['Largest absolute reversals are biased diagnostic examples, not a strength estimate.',
                       'Local timing and instrumentation can change completed search work; exact remote causation is not presumed.',
                       'A first divergence does not establish the cause of the eventual win or loss.',
                       'One-step counterfactuals fix the observed enemy command; they are not full-match interventions.']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--development', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Refusing to replace an audit record')
    result = analyze(args.development)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps([{'kind': c['kind'], 'turn': c['first_command_divergence'], 'candidate_reproduced': c['candidate_output_reproduced'],
                      'parent_reproduced': c['parent_output_reproduced'], 'base_action_equal': c['base_action_equal']} for c in result['cases']]))
