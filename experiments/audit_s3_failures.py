"""Diagnose fixed completed s3 regression pairs without selecting or changing a bot."""
import argparse
import copy
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
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
from audit_v3_continuation import commands as action_commands

EXTRA = r'''
Action audit_seed;
double audit_seed_value=0,audit_seed_ms=0;
int audit_seed_cont=0,audit_seed_aborted=0;
void s3_audit_post(const State& s,int us,const Action& chosen,double elapsed) {
    cerr<<setprecision(12)<<"{\"search_ms\":"<<elapsed<<",\"base_ms\":"<<audit_seed_ms<<",\"base_aborts\":"<<audit_seed_aborted
        <<",\"all_aborts\":"<<audit_aborted<<",\"base_value\":"<<audit_seed_value<<",\"continuation\":"<<audit_seed_cont;
    cerr<<",\"base_action\":";audit_action(audit_seed);cerr<<",\"chosen\":";audit_action(chosen);
    cerr<<",\"rollouts\":[";
    for(int option=0;option<2;++option) for(int opponent=0;opponent<4;++opponent) {
        if(option || opponent) cerr<<",";
        cerr<<"{\"option\":"<<option<<",\"opponent\":"<<opponent<<",\"steps\":[";State trial=s;
        for(int d=0;d<3;++d) {
            Action own=d?policy(trial,us,audit_seed_cont):(option?chosen:audit_seed),enemy=policy(trial,1-us,opponent);
            if(d)cerr<<",";cerr<<"{\"own\":";audit_action(own);cerr<<",\"enemy\":";audit_action(enemy);
            trial=us==0?advance(trial,own,enemy):advance(trial,enemy,own);
            cerr<<",\"value\":"<<evaluation(trial,us)<<",\"score\":["<<points(trial,0)<<","<<points(trial,1)<<"],\"units\":[";
            bool comma=false;for(int t=0;t<2;++t)for(int k=0;k<3;++k)for(int c=0;c<N;++c)if(trial.u[t][k][c]) {
                if(comma)cerr<<",";comma=true;cerr<<"["<<t<<","<<k<<","<<c<<","<<trial.u[t][k][c]<<"]";
            }
            cerr<<"],\"owners\":[";for(int b=0;b<board.nb;++b){if(b)cerr<<",";cerr<<trial.owner[b];}
            cerr<<"],\"resources\":["<<trial.res[0]<<","<<trial.res[1]<<"]}";
        }
        cerr<<"]}";
    }
    cerr<<"]}\n";
}
'''


def instrument(source):
    source = change(source, 'using AClock=chrono::steady_clock;', TRACE + '\n' + EXTRA + '\nusing AClock=chrono::steady_clock;')
    source = change(source, '>=limit) return false;', '>=limit) {++audit_aborted;return false;}')
    source = change(source, '    return incumbent.action;\n}',
                    '    audit_seed=incumbent.action;audit_seed_value=incumbent.value;audit_seed_cont=incumbent.continuation;\n'
                    '    audit_seed_ms=chrono::duration<double,milli>(AClock::now()-start).count();audit_seed_aborted=audit_aborted;\n'
                    '    return incumbent.action;\n}')
    anchor = next(line for line in source.splitlines() if 'Action a=forced_policy>=' in line)
    replacement = '    audit_aborted=0;\n' + anchor + '\n'
    replacement += '    if(v.turn==atoi(getenv("YK_AUDIT_TURN"))) s3_audit_post(s,us,a,chrono::duration<double,milli>(AClock::now()-start).count());'
    return change(source, anchor, replacement)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stats(frame, buildings):
    state = frame['state']
    return {'turn': frame['turn'], 'scores': {t: sum(buildings[b['id']]['score'] for b in state['buildings'] if b['owner'] == t) for t in 'YK'},
            'units': {t: {k: sum(u[4] for u in state['units'] if u[:2] == [t, k]) for k in 'FW'} for t in 'YK'},
            'owners': {str(b['id']): b['owner'] for b in state['buildings']}}


def verify_rollouts(preview, cases):
    verified = 0
    for case in cases:
        replay = json.loads(gzip.decompress((preview / case['candidate_replay']).read_bytes()))
        initial = to_state(generate(replay['seed'], replay['config']))
        state = initial
        for frame in replay['turns'][:case['first_state_difference'] - 1]:
            state, _ = run_turn(state, parse_commands(frame['commands']['Y']), parse_commands(frame['commands']['K']))
        for run in case['runs'].values():
            for rollout in run['trace']['rollouts']:
                official = state
                for step in rollout['steps']:
                    own = action_commands(step['own'], initial, case['team'])
                    enemy = action_commands(step['enemy'], initial, 'K' if case['team'] == 'Y' else 'Y')
                    official, _ = run_turn(official, own if case['team'] == 'Y' else enemy,
                                          enemy if case['team'] == 'Y' else own)
                    units = sorted([0 if t == 'Y' else 1, 'FWS'.index(k), x + 15 * y, n]
                                   for (x, y, t, k), n in official.units.items() if n)
                    assert units == sorted(step['units'])
                    assert [official.resources[t] for t in 'YK'] == step['resources']
                    assert [{'N': -1, 'Y': 0, 'K': 1}[b.owner] for b in official.sorted_buildings()] == step['owners']
                    verified += 1
    return {'verified_transitions': verified, 'fields': ['units', 'resources', 'owners'],
            'scope': 'Internal estimated scores excluded: unrevealed building scores are hidden from the bot.',
            'verifier_source_sha256': digest(Path(__file__))}


def load_inputs(preview=None, arena=None, case_selection=None):
    if (preview is None) == (arena is None):
        raise ValueError('Provide exactly one of preview or arena.')
    directory = preview if preview is not None else arena / 'runs/development'
    selection_path = case_selection or (preview / 'selected-failure-cases.json' if preview else None)
    if selection_path is None:
        raise ValueError('--case-selection is required with --arena.')
    selection = json.loads(selection_path.read_text())
    cases = [case for case in selection['cases'] if case['candidate'].startswith('s3_')]
    if not cases:
        raise ValueError('Selection has no s3 cases.')
    if arena is not None:
        raw_rows = [json.loads(line) for line in (directory / 'results.jsonl').read_text().splitlines() if line.strip()]
    else:
        raw_rows = json.loads((directory / 'results.json').read_text())['rows']
    rows = {row['job_id']: row for row in raw_rows}
    for case in cases:
        for label in ('candidate', 'baseline'):
            row = rows[case[label + '_job']]
            if row['status'] != 'complete':
                raise ValueError('Selected job is incomplete: ' + case[label + '_job'])
            path = directory / case[label + '_replay']
            if not path.is_file():
                raise FileNotFoundError(path)
    return directory, selection_path, selection, cases, rows


def analyze(preview=None, arena=None, case_selection=None):
    directory, selection_path, selection, cases, rows = load_inputs(preview, arena, case_selection)
    baseline = (ROOT / 'submissions/iterative-v3/main.cpp').read_text()
    spec = importlib.util.spec_from_file_location('audit_s3_generator', ROOT / 'experiments/local_league/v3_action_search.py')
    generator = importlib.util.module_from_spec(spec); spec.loader.exec_module(generator)
    sources = {c['id']: c['source'] for c in generator.variants(baseline)}
    sources.update(v3=baseline, v3_65=baseline.replace('double limit=135.0)', 'double limit=65.0)'))
    records = []
    with tempfile.TemporaryDirectory(prefix='yk-s3-failure-audit-', dir='/tmp') as directory:
        temp = Path(directory)
        binaries = {}
        for name in ['v3', 'v3_65', *[case['candidate'] for case in cases]]:
            source = temp / (name + '.cpp');source.write_text(instrument(sources[name]))
            binary = temp / name
            subprocess.run(['g++', '-std=c++20', '-O2', '-I', str(ROOT / 'submissions/iterative-v3'), str(source), '-o', str(binary)],
                           check=True, capture_output=True, timeout=90)
            binaries[name] = binary
        for case in cases:
            replays = {label: json.loads(gzip.decompress((directory / case[label + '_replay']).read_bytes())) for label in ('candidate', 'baseline')}
            a, b = replays['candidate'], replays['baseline']
            first = next(i + 1 for i, (x, y) in enumerate(zip(a['turns'], b['turns'])) if x['state'] != y['state'])
            command_first = next(i + 1 for i, (x, y) in enumerate(zip(a['turns'], b['turns'])) if x['commands'] != y['commands'])
            verified = {}
            for label, replay in replays.items():
                state = to_state(generate(replay['seed'], replay['config']))
                for frame in replay['turns']:
                    state, _ = run_turn(state, parse_commands(frame['commands']['Y']), parse_commands(frame['commands']['K']))
                    assert snapshot(state) == frame['state']
                verified[label] = len(replay['turns'])
            initial = to_state(generate(a['seed'], a['config']));state = initial
            blocks = [serialize_init(state, case['team'])]
            for i in range(first):
                blocks.append(serialize_turn(state, case['team'], i + 1))
                if i < first - 1:
                    state, _ = run_turn(state, parse_commands(a['turns'][i]['commands']['Y']), parse_commands(a['turns'][i]['commands']['K']))
            payload = ''.join(blocks)
            runs = {}
            for name in ('v3', 'v3_65', case['candidate']):
                done = subprocess.run([str(binaries[name])], input=payload, text=True, capture_output=True, check=True,
                                      env={**os.environ, 'YK_AUDIT_TURN': str(first)}, timeout=30)
                command = done.stdout.split('END\n')[-2].strip().splitlines()
                trace = json.loads(done.stderr)
                values = {}
                for option, label in ((0, 'base'), (1, 'chosen')):
                    scores = [r['steps'][-1]['value'] for r in trace['rollouts'] if r['option'] == option]
                    values[label] = {'per_opponent': scores, 'aggregate': .75 * sum(scores) / 4 + .25 * min(scores)}
                trace['aggregate_values'] = values
                runs[name] = {'commands': command, 'trace': trace,
                              'source_sha256': hashlib.sha256(sources[name].encode()).hexdigest(),
                              'instrumented_source_sha256': digest(temp / (name + '.cpp'))}
            opponent_team = 'K' if case['team'] == 'Y' else 'Y'
            fixed = parse_commands(a['turns'][first - 1]['commands'][opponent_team])
            one_step = {}
            for name, run in runs.items():
                own = parse_commands(run['commands'])
                after, _ = run_turn(copy.deepcopy(state), own if case['team'] == 'Y' else fixed,
                                    fixed if case['team'] == 'Y' else own)
                one_step[name] = snapshot(after)
            building_map = {building['id']: building for building in a['map']['buildings']}
            evidence = {**case, 'first_command_difference': command_first, 'first_state_difference': first,
                        'full_official_transitions_verified': verified, 'buildings': a['map']['buildings'],
                        'pre_state': snapshot(state), 'observation_payload_sha256': hashlib.sha256(payload.encode()).hexdigest(),
                        'legal_observation': blocks[-1], 'runs': runs, 'official_one_step_fixed_opponent': one_step,
                        'trajectory': {label: [stats(f, building_map) for f in replay['turns'] if f['turn'] in (first, first + 1, first + 2, 15, 20, 30, 40, 45, 60, 80, 100, 120)] for label, replay in replays.items()},
                        'recorded_match': {label: {'result': replay['result'], 'replay_sha256': digest(directory / case[label + '_replay']),
                                                 'future_path': 'records/league/loop3-iteration1/runs/development/' + case[label + '_replay'],
                                                 'decision_turn_response_ms': rows[case[label + '_job']]['response_ms'][first - 1],
                                                 'max_response_ms': rows[case[label + '_job']]['max_turn_ms'],
                                                 'diagnostics': rows[case[label + '_job']]['diagnostics'][case['team']]}
                                           for label, replay in replays.items()}}
            evidence['v3_equals_recorded'] = runs['v3']['commands'] == b['turns'][first - 1]['commands'][case['team']]
            evidence['candidate_equals_recorded'] = runs[case['candidate']]['commands'] == a['turns'][first - 1]['commands'][case['team']]
            evidence['v3_65_equals_v3_135'] = runs['v3_65']['commands'] == runs['v3']['commands']
            evidence['candidate_seed_equals_v3_65_action'] = runs[case['candidate']]['trace']['base_action'] == runs['v3_65']['trace']['chosen']
            records.append(evidence)
    return {'scope': selection['scope'], 'selection_rule': selection['selection_rule'],
            'internal_rollout_validation': verify_rollouts(directory, records),
            'script_sha256': digest(Path(__file__)), 'selection_file_sha256': digest(selection_path),
            'preview_path': str(preview) if preview is not None else None,
            'arena_path': str(arena) if arena is not None else None, 'case_selection_path': str(selection_path),
            'compiler': subprocess.check_output(['g++', '--version'], text=True).splitlines()[0],
            'cases': records, 'limits': ['No ranking, candidate selection, promotion, or code revision from partial results.',
                                        'A first divergence is not proof it alone caused the final loss.',
                                        'One-step counterfactuals fix observed simultaneous enemy commands; no full-match intervention is claimed.',
                                        'Timing attribution is local instrumentation; source-matched remote completion counts are unavailable.'],
            'temporary_cleanup': 'All instrumented sources and executables removed by TemporaryDirectory.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument('--preview', type=Path)
    inputs.add_argument('--arena', type=Path)
    parser.add_argument('--case-selection', type=Path)
    parser.add_argument('--check-inputs', action='store_true', help='Check selected cases and replay paths without compiling or executing bots.')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.arena is not None and args.case_selection is None:
        parser.error('--arena requires --case-selection')
    if args.check_inputs:
        directory, selection_path, _, cases, _ = load_inputs(args.preview, args.arena, args.case_selection)
        print(json.dumps({'directory': str(directory), 'selection': str(selection_path),
                          'candidates': [c['candidate'] for c in cases],
                          'replays': {c[label + '_replay']: digest(directory / c[label + '_replay'])
                                      for c in cases for label in ('candidate', 'baseline')}}, indent=2))
        sys.exit(0)
    if args.output is None:
        parser.error('--output is required unless --check-inputs is used')
    result = analyze(args.preview, args.arena, args.case_selection)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps([{k: c[k] for k in ('candidate', 'first_state_difference', 'v3_equals_recorded', 'candidate_equals_recorded', 'v3_65_equals_v3_135', 'candidate_seed_equals_v3_65_action')} for c in result['cases']]))
