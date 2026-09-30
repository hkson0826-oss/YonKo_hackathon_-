#!/usr/bin/env python3
"""Apply the locked deadline criteria; never select a different final candidate."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import itertools
import json
import math
from pathlib import Path
import random
import sys

CRITERIA = {
    'selection_Y_point_rate_difference': '> 0',
    'final_Y_point_rate_difference': '>= 0',
    'final_overall_point_rate_difference': '>= 0',
    'final_distinct_maps': 10,
    'final_each_opponent_each_side_win_count_difference': '> -3',
    'all_errors_and_forfeits': 0,
    'confidence_intervals': 'Descriptive only; not an extra acceptance gate',
}
LIMITATION = ('Comparison is against the exact source of submitted v8 (guard3) and the declared local opponent pool. '
              'All acceptance and verification gates are unchanged from the 2026-09-29 decision audit. '
              'Passing does not establish an official leaderboard score improvement.')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text())


def points(row):
    return int(row['win']) + .5 * int(row['draw'])


def aggregate(rows):
    times = sorted(x for r in rows for x in r.get('response_ms', []))
    return {'games': len(rows), 'maps': len({r['map_seed'] for r in rows}),
            'wins': sum(r['win'] for r in rows), 'draws': sum(r['draw'] for r in rows),
            'losses': sum(not r['win'] and not r['draw'] for r in rows),
            'point_rate': sum(map(points, rows)) / len(rows) if rows else None,
            'max_turn_ms': max((r.get('max_turn_ms', 0) for r in rows), default=None),
            'p95_turn_ms': times[math.ceil(.95 * len(times)) - 1] if times else None}


def comparison(rows, candidate, baseline, side=None, opponents=None):
    index = {(r['candidate'], r['map_seed'], r['team'], r['opponent']): r for r in rows}
    own = [r for r in rows if r['candidate'] == candidate and (side is None or r['team'] == side)
           and (opponents is None or r['opponent'] in opponents)]
    refs, paired_own = [], []
    deltas = {}
    for row in own:
        ref = index.get((baseline, row['map_seed'], row['team'], row['opponent']))
        if ref is None:
            continue
        paired_own.append(row)
        refs.append(ref)
        deltas.setdefault(row['map_seed'], []).append(points(row) - points(ref))
    values = [sum(v) / len(v) for _, v in sorted(deltas.items())]
    rng = random.Random(20260929)
    samples = sorted(sum(rng.choices(values, k=len(values))) / len(values) for _ in range(2000)) if values else []
    own = paired_own
    return {'candidate': aggregate(own), 'baseline': aggregate(refs),
            'point_rate_difference': sum(values) / len(values) if values else None,
            'win_count_difference': sum(r['win'] for r in own) - sum(r['win'] for r in refs),
            'map_cluster_bootstrap_95pct': [samples[50], samples[1949]] if samples else None,
            'bootstrap_seed': 20260929, 'bootstrap_resamples': 2000}


def load_stage(arena, run_id, stage, candidate, baseline):
    folder = arena / 'runs' / run_id
    plan = read(folder / 'plan.json')
    policy = read(arena / 'plans' / (run_id + '-policy.json'))
    manifest = read(arena / 'manifest.json')
    require(policy.get('stage') == stage and policy.get('baseline') == baseline, 'Stage or baseline mismatch')
    require(policy.get('map_seeds') == plan.get('map_seeds'), 'Policy maps differ from plan')
    require(policy.get('source_commit') == manifest.get('source_commit'), 'Policy source commit differs')
    require(policy.get('policy_rng_seed') == manifest.get('policy_rng_seed'), 'Policy policy RNG differs')
    require(candidate in plan['candidates'] and baseline in plan['candidates'], 'Missing paired candidate or baseline')
    if stage == 'final':
        require(set(plan['candidates']) == {baseline, candidate}, 'Final must contain exactly the locked candidate and baseline')
    maps = plan['map_seeds']
    require(len(maps) == len(set(maps)) and bool(maps), 'Empty or duplicate maps')
    expected = {(c, seed, side, op) for c, op, seed, side in itertools.product(plan['candidates'], plan['opponents'], maps, 'YK')}
    require(len(expected) == policy['scheduled_jobs'], 'Scheduled count differs from plan')
    raw = (folder / 'results.jsonl').read_bytes()
    require(raw.endswith(b'\n'), 'Unfinished result row')
    rows = [json.loads(line) for line in raw.splitlines()]
    observed = [(r['candidate'], r['map_seed'], r['team'], r['opponent']) for r in rows]
    require(len(observed) == len(set(observed)) == len(expected) and set(observed) == expected, 'Incomplete or duplicate schedule')
    sessions = [read(p) for p in folder.glob('session-*.json')]
    require(any(s.get('status') in ('complete', 'complete_with_errors') for s in sessions), 'No completed session')
    errors = sum(r.get('status') != 'complete' for r in rows)
    forfeits = sum(bool(r.get('forfeit')) for r in rows)
    for r in rows:
        if r.get('status') == 'complete':
            require(r['win'] == (r['result']['winner'] == r['team']) and r['draw'] == (r['result']['winner'] == 'DRAW'),
                    'Win/draw label disagrees with engine result')
            require(r['forfeit'] == (r['result']['reason'] == 'forfeit'), 'Forfeit label disagrees with engine result')
    for name in set(plan['candidates'] + plan['opponents']):
        bot = manifest['bots'][name]
        require(policy['source_sha256'][name] == bot['source_sha256'], 'Policy bot source differs: ' + name)
        if bot.get('source'):
            source = arena / bot['source']
            require(source.resolve().is_relative_to(arena) and sha(source) == bot['source_sha256'], 'Frozen bot source differs: ' + name)
    ref = {'arena': str(arena), 'run_id': run_id, 'summary_sha256': sha(folder / 'summary.json'),
           'results_sha256': sha(folder / 'results.jsonl')}
    return {'rows': rows, 'plan': plan, 'policy': policy, 'manifest': manifest, 'reference': ref,
            'errors': errors, 'forfeits': forfeits,
            'finished_utc': max(s.get('finished_utc', '') for s in sessions if s.get('status') in ('complete', 'complete_with_errors'))}


def metrics(stage, candidate, baseline):
    rows = [r for r in stage['rows'] if r['status'] == 'complete']
    return {'overall': comparison(rows, candidate, baseline),
            **{side: comparison(rows, candidate, baseline, side) for side in 'YK'},
            'opponents': {op: {side: comparison(rows, candidate, baseline, side, {op}) for side in ('Y', 'K', None)}
                          for op in stage['plan']['opponents']}}


def acceptance(selection, final, selection_metrics, final_metrics):
    regressions = {op: {side: final_metrics['opponents'][op][side]['win_count_difference'] for side in 'YK'}
                   for op in final['plan']['opponents']}
    gates = {
        'selection_primary_Y_improves': selection_metrics['Y']['point_rate_difference'] is not None and selection_metrics['Y']['point_rate_difference'] > 0,
        'final_Y_nonregression': final_metrics['Y']['point_rate_difference'] is not None and final_metrics['Y']['point_rate_difference'] >= 0,
        'final_overall_nonregression': final_metrics['overall']['point_rate_difference'] is not None and final_metrics['overall']['point_rate_difference'] >= 0,
        'final_exactly_10_independent_maps': len(set(final['plan']['map_seeds'])) == 10,
        'no_opponent_side_regression_of_3_wins': all(delta > -3 for sides in regressions.values() for delta in sides.values()),
        'selection_and_final_errors_zero': selection['errors'] == final['errors'] == 0,
        'selection_and_final_forfeits_zero': selection['forfeits'] == final['forfeits'] == 0,
    }
    return gates, regressions


def audit(args):
    arena = args.arena.resolve()
    selection = load_stage(arena, args.selection_run, 'selection', args.candidate, args.baseline)
    final = load_stage(arena, args.final_run, 'final', args.candidate, args.baseline)
    require(not set(selection['plan']['map_seeds']) & set(final['plan']['map_seeds']), 'Selection/final maps overlap')
    require(selection['plan']['opponents'] == final['plan']['opponents'], 'Opponent pool changed after selection')
    require(datetime.fromisoformat(selection['finished_utc']) <= datetime.fromisoformat(final['policy']['created_utc']),
            'Final began before selection completed')
    for name in [args.baseline, args.candidate, *selection['plan']['opponents']]:
        require(selection['policy']['source_sha256'][name] == final['policy']['source_sha256'][name], 'Locked source changed')
    sm, fm = metrics(selection, args.candidate, args.baseline), metrics(final, args.candidate, args.baseline)
    gates, regressions = acceptance(selection, final, sm, fm)
    failed = [name for name, value in gates.items() if not value]
    result = {'schema_version': 1, 'approved': not failed, 'candidate': args.candidate, 'baseline': args.baseline,
              'source_sha256': final['manifest']['bots'][args.candidate]['source_sha256'],
              'baseline_source_sha256': final['manifest']['bots'][args.baseline]['source_sha256'],
              'rationale': ('All predeclared local deadline gates passed. ' if not failed else 'Hold: failed predeclared gates: ' + ', '.join(failed) + '. ') + LIMITATION,
              'selection': selection['reference'], 'final': final['reference'], 'gates': gates,
              'failed_gates': failed, 'criteria': CRITERIA,
              'selection_metrics': sm, 'final_metrics': fm,
              'health': {stage: {'errors': data['errors'], 'forfeits': data['forfeits']} for stage, data in [('selection', selection), ('final', final)]}, 'opponent_side_win_differences': regressions,
              'limitation': LIMITATION, 'created_utc': datetime.now(timezone.utc).isoformat(), 'audit_script_sha256': sha(Path(__file__))}
    json_path = Path(str(args.output_prefix) + '.json')
    md_path = Path(str(args.output_prefix) + '.md')
    require(not json_path.exists() and not md_path.exists(), 'Audit outputs exist; preserve previous decision')
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    lines = ['# Deadline final acceptance audit', '\nDecision: **' + ('PASS' if result['approved'] else 'HOLD') + '**. Candidate `' + args.candidate + '`, baseline `' + args.baseline + '`.',
             '\n' + result['rationale'], '\n| Stage | Side | Candidate W/D/L | Baseline W/D/L | Point-rate difference | Map bootstrap95% |', '|---|---|---|---|---:|---|']
    for name, stage_metrics in [('selection', sm), ('final', fm)]:
        for side in ['Y','K','overall']:
            m = stage_metrics[side]; c, b = m['candidate'], m['baseline']
            difference = f"{100*m['point_rate_difference']:+.1f}pp" if m['point_rate_difference'] is not None else 'unavailable'
            interval = str([round(100*v,1) for v in m['map_cluster_bootstrap_95pct']]) + 'pp' if m['map_cluster_bootstrap_95pct'] else 'unavailable'
            lines.append(f"| {name} | {side} | {c['wins']}/{c['draws']}/{c['losses']} | {b['wins']}/{b['draws']}/{b['losses']} | {difference} | {interval} |")
    lines += ['\n| Final opponent | Y win difference | K win difference |', '|---|---:|---:|']
    for op, sides in regressions.items():
        lines.append(f"| {op} | {sides['Y']:+d} | {sides['K']:+d} |")
    lines += ['\n| Fixed gate | Result |','|---|---|']
    lines += [f"| {name} | {'PASS' if passed else 'FAIL'} |" for name, passed in gates.items()]
    lines += ['\nConfidence intervals describe map-sample uncertainty and are not additional gates. The3-win regression threshold is applied to each opponent and each side separately; combined-opponent outcomes are also present in JSON.',
              '\nNo source, arena, or frozen evidence was modified. This audit does not perform ZIP/runtime validation or browser submission.']
    md_path.write_text('\n'.join(lines) + '\n')
    print(json.dumps({'approved': result['approved'], 'failed_gates': failed, 'json': str(json_path), 'md': str(md_path)}), flush=True)


def self_test():
    stage = {'plan': {'map_seeds': list(range(10)), 'opponents': ['op']}, 'errors': 0, 'forfeits': 0}
    def sample(y, overall, regression):
        return {'Y': {'point_rate_difference': y}, 'overall': {'point_rate_difference': overall},
                'opponents': {'op': {side: {'win_count_difference': regression if side=='Y' else 0} for side in 'YK'}}}
    selection = sample(.01, 0, 0)
    assert all(acceptance(stage, stage, selection, sample(0, 0, -2))[0].values())
    assert not acceptance(stage, stage, selection, sample(0, 0, -3))[0]['no_opponent_side_regression_of_3_wins']
    assert not acceptance(stage, stage, sample(0, 0, 0), sample(0, 0, 0))[0]['selection_primary_Y_improves']
    assert not acceptance(stage, stage, selection, sample(0, -.01, 0))[0]['final_overall_nonregression']
    assert not acceptance(stage, {**stage, 'forfeits': 1}, selection, sample(0, 0, 0))[0]['selection_and_final_forfeits_zero']
    print('Fixed acceptance boundary checks passed; no live results read.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--arena', type=Path, default=Path('/tmp/yk-selection-20260929'))
    parser.add_argument('--candidate')
    parser.add_argument('--baseline', default='v4')
    parser.add_argument('--selection-run', default='selection')
    parser.add_argument('--final-run', default='final')
    parser.add_argument('--output-prefix', type=Path, default=Path('/tmp/yk-final-audit'))
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    if args.self_test:
        self_test()
    else:
        parser.error('--candidate is required') if not args.candidate else audit(args)


if __name__ == '__main__':
    main()
