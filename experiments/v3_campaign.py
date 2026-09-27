"""Compare revisions against v3 and opponents strengthened between frozen runs."""
import argparse
import itertools
import json
from pathlib import Path
import random
import time

import local_league as league
from cross_family_audit import submission_address_space
from league_campaign import load_rows, point, ranking, crossplay_table

BASELINE = 'v3'
NEW_MODULES = ['v3_repairs', 'v3_action_search', 'v3_robust_search']
MODULES = ['repairs', 'joint_allocator', 'adaptive_search', *NEW_MODULES]
FIXED_OPPONENTS = ['v3', 'v2', 'teammate', 'a_v2_tactical_local',
                   'j_balanced_portfolio', 'j_v2_reclaim_relay']
SOURCE = 'submissions/iterative-v3/main.cpp'
SOURCE_SHA = '52268569e17d7fc40fd46f0996b2da684768902b4af27ec059c4b068911c4473'
AUDIT_MAPS = list(range(8700, 8732))


def paired(rows, candidate, team='Y', opponents=None):
    indexed = {(r['candidate'], r['map_seed'], r['team'], r['opponent']): r
               for r in rows if r['status'] == 'complete'}
    per_map = {}
    for (name, seed, side, opponent), row in indexed.items():
        if name != candidate or side != team or (opponents is not None and opponent not in opponents):
            continue
        reference = indexed.get((BASELINE, seed, side, opponent))
        if reference is not None:
            per_map.setdefault(seed, []).append(point(row) - point(reference))
    if not per_map:
        return None
    values = [sum(v) / len(v) for _, v in sorted(per_map.items())]
    rng = random.Random(927608)
    samples = sorted(sum(rng.choices(values, k=len(values))) / len(values) for _ in range(5000))
    return {'team': team, 'baseline': BASELINE, 'maps': len(values),
            'paired_games': sum(map(len, per_map.values())),
            'point_rate_difference': sum(values) / len(values),
            'map_cluster_bootstrap_95pct': [samples[125], samples[4874]],
            'resamples': 5000, 'seed': 927608, 'per_map': per_map,
            'limitation': 'Internal fixed opponent distribution; no estimate of leaderboard or unseen participant win rate'}


def select_diverse(ordered, bots, count=6):
    selected = []
    for cap in [2, count]:
        for name in ordered:
            if name in {BASELINE, 'v2'} or name in selected:
                continue
            if sum(bots[n]['family'] == bots[name]['family'] for n in selected) >= cap:
                continue
            selected.append(name)
            if len(selected) == count:
                return [BASELINE, *selected]
    return [BASELINE, *selected]


def challenge_selection(rows, bots, candidate_ids, count=2):
    """Pick strong v3 exploiters on development only, with different generator families."""
    table = []
    for name in candidate_ids:
        if name == BASELINE:
            continue
        selected = [r for r in rows if r['candidate'] == name]
        direct = [r for r in selected if r['opponent'] == BASELINE]
        if not direct or any(r['status'] != 'complete' or r.get('forfeit') for r in selected):
            continue
        table.append({'id': name, 'family': name.split('_', 1)[0],
                      'games': len(direct), 'point_rate': sum(point(r) for r in direct) / len(direct),
                      'mean_score_margin': sum(r['score_margin'] for r in direct) / len(direct),
                      'source_sha256': bots[name]['source_sha256']})
    table.sort(key=lambda r: (-r['point_rate'], -r['mean_score_margin'], r['id']))
    chosen, families = [], set()
    for row in table:
        if row['family'] in families:
            continue
        chosen.append(row)
        families.add(row['family'])
        if len(chosen) == count:
            break
    return {'selection_scope': 'Development-only exploiters; freeze before the next run and new-map selection',
            'rule': 'Direct both-side point rate against v3, then mean margin, then id; distinct generator prefixes',
            'ranking': table, 'opponents': [r['id'] for r in chosen],
            'source_sha256': {r['id']: r['source_sha256'] for r in chosen}}


def promotion(rows, candidate, opponents, expected_maps):
    fixed = set(FIXED_OPPONENTS)
    added = set(opponents) - fixed
    comparisons = {side: paired(rows, candidate, side) for side in 'YK'}
    fixed_comparison = paired(rows, candidate, opponents=fixed)
    challenge_comparison = paired(rows, candidate, opponents=added) if added else None
    by_opponent = {op: paired(rows, candidate, opponents={op}) for op in opponents}
    expected = {(name, seed, side, op) for name in [BASELINE, candidate]
                for seed in expected_maps for side in 'YK' for op in opponents}
    selected = [r for r in rows if r['candidate'] in {BASELINE, candidate}]
    observed = [(r['candidate'], r['map_seed'], r['team'], r['opponent']) for r in selected]
    complete = len(observed) == len(set(observed)) == len(expected) and set(observed) == expected
    direct = [r for r in selected if r['candidate'] == candidate and r['opponent'] == BASELINE
              and r['status'] == 'complete']
    direct_rate = sum(point(r) for r in direct) / len(direct) if direct else None
    y, k = comparisons['Y'], comparisons['K']
    gates = {
        'complete_paired_schedule': complete,
        'no_error_or_forfeit': complete and all(r['status'] == 'complete' and not r.get('forfeit') for r in selected),
        'Y_gain_at_least_3pp': bool(y and y['point_rate_difference'] >= .03 - 1e-12),
        'Y_map_cluster_lower_bound_positive': bool(y and y['map_cluster_bootstrap_95pct'][0] > 0),
        'fixed_pool_Y_gain_at_least_3pp': bool(fixed_comparison and fixed_comparison['point_rate_difference'] >= .03 - 1e-12),
        'fixed_pool_Y_lower_bound_positive': bool(fixed_comparison and fixed_comparison['map_cluster_bootstrap_95pct'][0] > 0),
        'challenge_pool_Y_no_regression': not added or bool(challenge_comparison and challenge_comparison['point_rate_difference'] >= -1e-12),
        'no_opponent_Y_regression_over_10pp': all(v and v['point_rate_difference'] >= -.10 - 1e-12 for v in by_opponent.values()),
        'K_overall_regression_no_more_than_5pp': bool(k and k['point_rate_difference'] >= -.05 - 1e-12),
        'direct_v3_both_side_point_rate_at_least_half': direct_rate is not None and direct_rate >= .5,
    }
    return {'baseline': BASELINE, 'comparisons': comparisons, 'opponents': by_opponent,
            'fixed_pool_comparison': fixed_comparison, 'challenge_pool_comparison': challenge_comparison,
            'direct_v3_both_side_point_rate': direct_rate, 'gates': gates, 'promoted': all(gates.values())}


def runtime_health(rows, candidate):
    involved = [r for r in rows if {r['candidate'], r['opponent']} & {BASELINE, candidate}]
    return bool(involved) and all(r['status'] == 'complete' and not r.get('forfeit') for r in involved)


def population_spec(revision, requested, challenge):
    return {'modules': MODULES, 'module_sources': {name: SOURCE for name in NEW_MODULES},
            'module_revisions': {name: revision for name in NEW_MODULES},
            'extra_baselines': [{'id': BASELINE, 'source': SOURCE}],
            'include_parameters': False, 'deduplicate': True, 'revision': max(2, revision),
            'include_ids': list(dict.fromkeys([op for op in FIXED_OPPONENTS if op != 'teammate'] +
                                             list(challenge) + (requested or []))),
            'include_prefixes': [] if requested else ['f3_', 's3_', 'r3_']}


def seed_ranges(args):
    result = {'smoke': [args.seed_start - 1],
              'development': list(range(args.seed_start, args.seed_start + args.maps))}
    if args.phase == 'final':
        result.update(selection=list(range(args.selection_start, args.selection_start + args.selection_maps)),
                      holdout=list(range(args.holdout_start, args.holdout_start + args.holdout_maps)),
                      crossplay=[args.holdout_start + 200, args.holdout_start + 201])
    if any(set(a) & set(b) for a, b in itertools.combinations(result.values(), 2)):
        raise ValueError('Map sets must be disjoint')
    if min(min(values) for values in result.values()) < 8000:
        raise ValueError('Loop3 reserves fresh map seeds >=8000')
    if any(set(values) & set(AUDIT_MAPS) for values in result.values()):
        raise ValueError('Campaign maps overlap the reserved independent audit')
    return result


def campaign(args):
    started = time.perf_counter()
    arena = args.arena.resolve()
    maps = seed_ranges(args)
    challenge_lock = json.loads(args.challenge_lock_json) if args.challenge_lock_json else None
    extra = challenge_lock['opponents'] if challenge_lock else []
    if len(extra) != len(set(extra)) or any(op in FIXED_OPPONENTS for op in extra):
        raise ValueError('Challenge opponents must be distinct and outside the fixed pool')
    if args.phase == 'final' and len(extra) != 2:
        raise ValueError('Final campaign requires two previously locked development exploiters')
    opponents = [*FIXED_OPPONENTS, *extra]
    requested = args.candidates.split(',') if args.candidates else None
    spec = population_spec(args.revision, requested, extra)
    league.prepare(arena, spec)
    manifest = json.loads((arena / 'manifest.json').read_text())
    bots = manifest['bots']
    if bots[BASELINE]['source_sha256'] != SOURCE_SHA:
        raise ValueError('Current submission source changed')
    if challenge_lock:
        for op in extra:
            if bots[op]['source_sha256'] != challenge_lock['source_sha256'][op]:
                raise ValueError(f'Frozen exploiter changed: {op}')
    names = requested or [name for name in bots if name.startswith(('f3_', 's3_', 'r3_'))]
    if len(names) != len(set(names)) or set(names) - bots.keys() or not names:
        raise ValueError('Candidate list is empty, duplicated or missing after deduplication')
    candidates = [BASELINE, *[name for name in names if name != BASELINE]]
    policy = {'created_utc': league.stamp(), 'phase': args.phase, 'baseline': BASELINE,
              'candidate_ids': candidates, 'fixed_opponents': FIXED_OPPONENTS,
              'challenge_lock': challenge_lock, 'opponents': opponents,
              'map_sets': maps, 'primary_metric': 'Y point rate against frozen fixed and strengthened pools',
              'selection_count': 6, 'finalists': 2, 'primary_only_can_promote': True,
              'promotion': 'Complete and error-free; Y gain >=3pp and map CI lower>0 both all/fixed pools; challenge Y non-regression; each opponent Y regression <=10pp; overall K regression <=5pp; direct v3 both-side point rate >=.5.',
              'replay_policy': 'all games, including wins',
              'resource_policy': 'After compilation, workers and bots inherit 384MiB RLIMIT_AS; official 300ms turn timeout',
              'interpretation': 'Development exploiters strengthen training; report fixed/expanded pools separately. No code or opponent changes after final selection starts.'}
    league.write(arena / 'campaign-policy.json', policy)
    (arena / 'plans').mkdir()
    reports = {}

    def stage(name, plan):
        plan_path = arena / 'plans' / f'{name}.json'
        league.write(plan_path, plan)
        print(json.dumps({'event': 'stage_start', 'stage': name,
                          'jobs': len(league.make_jobs(plan, bots))}), flush=True)
        league.run(arena, plan_path, name, args.workers, False)
        report = json.loads((arena / 'runs' / name / 'summary.json').read_text())
        reports[name] = report
        league.write(arena / 'progress.json', {'completed': list(reports)})
        print(json.dumps({'event': 'stage_complete', 'stage': name, 'overall': report['overall']}), flush=True)
        return report

    def plan(ids, stage_name, ops=opponents):
        return {'candidates': ids, 'opponents': ops, 'map_seeds': maps[stage_name], 'replays': 'all'}

    with submission_address_space() as cap:
        league.write(arena / 'resource-limit.json', cap)
        smoke = stage('smoke', plan(list(dict.fromkeys([*candidates, *opponents])), 'smoke', [BASELINE]))
        broken = [name for name, values in smoke['by_candidate'].items() if values['errors'] or values['forfeits']]
        league.write(arena / 'smoke-exclusions.json', {'excluded': broken})
        if set(broken) & set(opponents):
            raise RuntimeError('Fixed opponent failed smoke; do not interpret strategy results')
        candidates = [name for name in candidates if name not in broken]
        screen = stage('development', plan(candidates, 'development'))
        ordered = ranking(screen, candidates)
        selected = select_diverse(ordered, bots)
        league.write(arena / 'development-selection.json', {'ranking': ordered, 'selected': selected})
        challengers = challenge_selection(load_rows(arena / 'runs/development'), bots, candidates)
        challengers['source_commit'] = manifest['source_commit']
        league.write(arena / 'next-opponents.json', challengers)
        result = {'status': 'complete', 'phase': args.phase, 'baseline': BASELINE,
                  'candidate_count': len(candidates), 'development_ranking': ordered,
                  'selected': selected, 'recommended': BASELINE,
                  'recommendation_scope': 'Development only; no submission promotion'}
        if args.phase == 'final':
            selection = stage('selection', plan(selected, 'selection'))
            final_order = ranking(selection, selected)
            finalists = [name for name in final_order if name != BASELINE][:2]
            if not finalists:
                raise RuntimeError('No healthy finalist')
            primary = finalists[0]
            lock = {'ranking': final_order, 'finalists': finalists, 'primary_candidate': primary,
                    'baseline': BASELINE, 'opponents': opponents,
                    'map_sets': maps,
                    'source_sha256': {name: bots[name]['source_sha256'] for name in [BASELINE, *finalists, *opponents]}}
            league.write(arena / 'locked-finalists.json', lock)
            stage('holdout', plan([BASELINE, *finalists], 'holdout'))
            rows = load_rows(arena / 'runs/holdout')
            decisions = {name: promotion(rows, name, opponents, maps['holdout']) for name in finalists}
            result.update(primary_candidate=primary, finalists=finalists, selection_ranking=final_order,
                          promotion_decisions=decisions,
                          recommended=primary if decisions[primary]['promoted'] else BASELINE,
                          recommendation_scope='First locked finalist only; separate ZIP/CPU checks required')
            cross = list(dict.fromkeys([BASELINE, *finalists, *extra, 'teammate']))
            stage('crossplay', {'pairs': list(itertools.combinations(cross, 2)),
                               'map_seeds': maps['crossplay'], 'replays': 'all'})
            cross_rows = load_rows(arena / 'runs/crossplay')
            league.write(arena / 'crossplay-table.json', crossplay_table(cross_rows))
            for name, decision in decisions.items():
                decision['gates']['crossplay_candidate_and_baseline_runtime_healthy'] = runtime_health(cross_rows, name)
                decision['promoted'] = all(decision['gates'].values())
            result['recommended'] = primary if decisions[primary]['promoted'] else BASELINE
        result.update(stage_match_counts={name: report['overall']['matches'] for name, report in reports.items()},
                      total_matches=sum(report['overall']['matches'] for report in reports.values()),
                      elapsed_seconds=time.perf_counter() - started,
                      errors=sum(report['overall']['errors'] for report in reports.values()),
                      forfeits=sum(report['overall']['forfeits'] for report in reports.values()))
        league.write(arena / 'campaign-result.json', result)
        print(json.dumps({'event': 'campaign_complete', **result}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--arena', type=Path, required=True)
    parser.add_argument('--phase', choices=['explore', 'final'], required=True)
    parser.add_argument('--revision', type=int, choices=[1, 2], default=1)
    parser.add_argument('--seed-start', type=int, required=True)
    parser.add_argument('--maps', type=int, default=8)
    parser.add_argument('--selection-start', type=int, default=8300)
    parser.add_argument('--selection-maps', type=int, default=24)
    parser.add_argument('--holdout-start', type=int, default=8400)
    parser.add_argument('--holdout-maps', type=int, default=80)
    parser.add_argument('--candidates')
    parser.add_argument('--challenge-lock-json')
    parser.add_argument('--workers', type=int, default=16)
    args = parser.parse_args()
    if min(args.maps, args.selection_maps, args.holdout_maps, args.workers) < 1:
        parser.error('Map and worker counts must be positive')
    campaign(args)


if __name__ == '__main__':
    main()
