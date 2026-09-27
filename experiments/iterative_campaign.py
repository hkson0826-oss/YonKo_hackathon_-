"""Run one frozen iteration; code review and revision happen between TMP runs."""
import argparse
import itertools
import json
from pathlib import Path
import time

import local_league as league
from league_campaign import ranking, select_diverse, paired_interval, crossplay_table, load_rows

MODULES = ['repairs', 'causal_repairs', 'joint_allocator', 'adaptive_search']
OPPONENTS = ['v2', 'teammate', 'r_combined', 'r_joint_escort', 'r_terminal_margin']


def promotion(rows, summary, candidate):
    comparisons = {side: paired_interval(rows, candidate, side) for side in 'YK'}
    opponents = {op: paired_interval([r for r in rows if r['opponent'] == op], candidate)
                 for op in OPPONENTS}
    own, base = summary['by_candidate'][candidate], summary['by_candidate']['v2']
    cmp = comparisons['Y']
    gates = {
        'Y_gain_at_least_3pp': cmp is not None and cmp['point_rate_difference'] >= .03,
        'map_cluster_lower_bound_positive': cmp is not None and cmp['map_cluster_bootstrap_95pct'][0] > 0,
        'no_opponent_Y_regression_over_10pp': all(x and x['point_rate_difference'] >= -.1 for x in opponents.values()),
        'no_error_or_forfeit': not any(x['errors'] or x['forfeits'] for x in [own, base]),
    }
    return {'comparisons': comparisons, 'opponents': opponents, 'gates': gates,
            'promoted': all(gates.values())}


def campaign(args):
    started = time.perf_counter()
    arena = args.arena.resolve()
    spec = {'modules': MODULES, 'include_parameters': False, 'deduplicate': True,
            'include_ids': ['v2', 'v1', *OPPONENTS[2:]], 'include_prefixes': ['q_', 'j_', 'a_'],
            'revision': args.revision}
    requested = args.candidates.split(',') if args.candidates else None
    if requested:
        spec['include_ids'] = list(dict.fromkeys(['v2', 'v1', *OPPONENTS[2:], *requested]))
        spec['include_prefixes'] = []
    league.prepare(arena, spec)
    manifest = json.loads((arena / 'manifest.json').read_text())
    bots = manifest['bots']
    if requested:
        names = [name for name in requested if name in bots and name not in OPPONENTS]
    else:
        names = [name for name in bots if name.startswith(('q_', 'j_', 'a_'))]
    candidates = ['v2', *names]
    if not names:
        raise ValueError('No new candidates')
    # Old repairs stay fixed opponents, not extra easy wins in a mixed pool.
    required = set(OPPONENTS)
    if required - bots.keys():
        raise ValueError('A required opponent was deduplicated or omitted')
    plans = arena / 'plans'
    plans.mkdir()
    policy = {
        'phase': args.phase, 'candidate_ids': candidates, 'opponents': OPPONENTS,
        'primary_metric': 'Y point rate; K is a separate diagnostic',
        'development_seeds': list(range(args.seed_start, args.seed_start + args.maps)),
        'selection_seeds': list(range(args.selection_start, args.selection_start + 16)) if args.phase == 'final' else [],
        'holdout_seeds': list(range(args.holdout_start, args.holdout_start + 64)) if args.phase == 'final' else [],
        'replay_policy': 'all games, including baseline wins for paired causal review',
        'promotion': 'First selection finalist only; Y gain >=3pp, map-cluster bootstrap lower bound >0, no opponent regression worse than 10pp, no candidate/baseline error or forfeit.',
        'review_policy': 'No code edits inside a frozen iteration. Read losses and revise before a separate run with new IDs and map ranges.',
        'limits': '300ms official per-turn timeout; no reduced turn limit',
    }
    league.write(arena / 'campaign-policy.json', policy)
    reports = {}

    def stage(name, plan):
        league.write(plans / f'{name}.json', plan)
        print(json.dumps({'event': 'stage_start', 'stage': name,
                          'jobs': len(league.make_jobs(plan, bots))}), flush=True)
        league.run(arena, plans / f'{name}.json', name, args.workers, False)
        report = json.loads((arena / 'runs' / name / 'summary.json').read_text())
        reports[name] = report
        league.write(arena / 'progress.json', {'completed': list(reports)})
        print(json.dumps({'event': 'stage_complete', 'stage': name, 'overall': report['overall']}), flush=True)
        return report

    smoke_ids = list(dict.fromkeys([*candidates, *OPPONENTS]))
    smoke = stage('smoke', {'candidates': smoke_ids, 'opponents': ['v2'],
                           'map_seeds': [args.seed_start - 1], 'replays': 'all'})
    broken = [name for name, s in smoke['by_candidate'].items() if s['errors'] or s['forfeits']]
    league.write(arena / 'smoke-exclusions.json', {'excluded': broken})
    if required.intersection(broken):
        raise RuntimeError('A fixed opponent failed; do not interpret the run as strategy evidence')
    candidates = [name for name in candidates if name not in broken]
    screen = stage('development', {'candidates': candidates, 'opponents': OPPONENTS,
                                   'map_seeds': policy['development_seeds'], 'replays': 'all'})
    ordered = ranking(screen, candidates)
    chosen = select_diverse(ordered, bots, count=6)
    league.write(arena / 'development-selection.json', {'ranking': ordered, 'selected': chosen})
    result = {'status': 'complete', 'phase': args.phase, 'candidate_count': len(candidates),
              'development_ranking': ordered, 'selected': chosen, 'recommended': 'v2',
              'recommendation_scope': 'Development only, no submission promotion' }
    if args.phase == 'final':
        selection = stage('selection', {'candidates': chosen, 'opponents': OPPONENTS,
                                        'map_seeds': policy['selection_seeds'], 'replays': 'all'})
        ordered_final = ranking(selection, chosen)
        finalists = [name for name in ordered_final if name != 'v2'][:2]
        if not finalists:
            raise RuntimeError('No healthy finalist')
        league.write(arena / 'locked-finalists.json', {'ranking': ordered_final,
                     'finalists': finalists, 'primary_candidate': finalists[0]})
        holdout = stage('holdout', {'candidates': ['v2', *finalists], 'opponents': OPPONENTS,
                                   'map_seeds': policy['holdout_seeds'], 'replays': 'all'})
        rows = load_rows(arena / 'runs/holdout')
        decisions = {name: promotion(rows, holdout, name) for name in finalists}
        primary = finalists[0]
        result.update(finalists=finalists, primary_candidate=primary, selection_ranking=ordered_final,
                      promotion_decisions=decisions,
                      recommended=primary if decisions[primary]['promoted'] else 'v2',
                      recommendation_scope='Internal fixed strong-opponent league; separate submission CPU validation required')
        cross = list(dict.fromkeys(['v2', *finalists, 'r_combined', 'r_joint_escort']))
        stage('crossplay', {'pairs': list(itertools.combinations(cross, 2)),
                           'map_seeds': [args.holdout_start + 100, args.holdout_start + 101], 'replays': 'all'})
        league.write(arena / 'crossplay-table.json', crossplay_table(load_rows(arena / 'runs/crossplay')))
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
    parser.add_argument('--revision', type=int, default=1)
    parser.add_argument('--seed-start', type=int, required=True)
    parser.add_argument('--maps', type=int, default=8)
    parser.add_argument('--selection-start', type=int, default=7200)
    parser.add_argument('--holdout-start', type=int, default=7300)
    parser.add_argument('--candidates', help='Comma-separated exact IDs; fixed opponents always retained')
    parser.add_argument('--workers', type=int, default=16)
    args = parser.parse_args()
    ranges = [{args.seed_start - 1}, set(range(args.seed_start, args.seed_start + args.maps))]
    if args.phase == 'final':
        ranges += [set(range(args.selection_start, args.selection_start + 16)),
                   set(range(args.holdout_start, args.holdout_start + 64)),
                   {args.holdout_start + 100, args.holdout_start + 101}]
    if args.workers < 1 or args.maps < 1 or args.seed_start < 1 or args.revision < 1:
        parser.error('Invalid worker count or seed range')
    if any(a & b for a, b in itertools.combinations(ranges, 2)):
        parser.error('Map ranges must be disjoint')
    campaign(args)


if __name__ == '__main__':
    main()
