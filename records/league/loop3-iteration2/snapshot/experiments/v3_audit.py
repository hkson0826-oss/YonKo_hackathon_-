"""New-map audit of the first locked v3 successor; never choose another finalist."""
import argparse
import json
from pathlib import Path
import time

import local_league as league
import v3_campaign as campaign
from cross_family_audit import submission_address_space
from league_campaign import load_rows

MAPS = campaign.AUDIT_MAPS


def audit_result(rows, candidate, opponents):
    assessment = campaign.promotion(rows, candidate, opponents, MAPS)
    added = set(opponents) - set(campaign.FIXED_OPPONENTS)
    fixed = assessment['fixed_pool_comparison']
    challenge = assessment['challenge_pool_comparison']
    overall = assessment['comparisons']['Y']
    gates = {
        'complete_schedule_without_duplicates': assessment['gates']['complete_paired_schedule'] and len(rows) == 2 * len(opponents) * 2 * len(MAPS),
        'no_baseline_or_candidate_errors_or_forfeits': assessment['gates']['no_error_or_forfeit'],
        'overall_Y_no_regression': bool(overall and overall['point_rate_difference'] >= -1e-12),
        'fixed_pool_Y_no_regression': bool(fixed and fixed['point_rate_difference'] >= -1e-12),
        'challenge_pool_Y_no_regression': not added or bool(challenge and challenge['point_rate_difference'] >= -1e-12),
        'no_opponent_Y_regression_over_12_5pp': all(v and v['point_rate_difference'] >= -.125 - 1e-12
                                                for v in assessment['opponents'].values()),
    }
    return {'status': 'complete' if gates['complete_schedule_without_duplicates'] and gates['no_baseline_or_candidate_errors_or_forfeits'] else 'incomplete_or_failed',
            'baseline': campaign.BASELINE, 'candidate': candidate, 'gates': gates,
            'passes_additional_gate': all(gates.values()), 'observed_rows': len(rows),
            'comparisons': assessment['comparisons'], 'opponent_Y_comparisons': assessment['opponents'],
            'fixed_pool_comparison': fixed, 'challenge_pool_comparison': challenge,
            'interpretation': 'Additional audit; cannot rescue a failed original holdout or select a different candidate'}


def run(args):
    started = time.perf_counter()
    lock = json.loads(args.selection_lock_json)
    candidate = lock['primary_candidate']
    if lock.get('baseline') != 'v3' or candidate != lock['finalists'][0] or candidate in ('v3', 'v2', 'teammate'):
        raise ValueError('Invalid original selection lock')
    if not lock.get('map_sets') or any(set(values) & set(MAPS) for values in lock['map_sets'].values()):
        raise ValueError('Original campaign maps are missing or overlap this audit')
    opponents = lock['opponents']
    if len(opponents) != 8 or len(set(opponents)) != 8 or not set(campaign.FIXED_OPPONENTS) <= set(opponents):
        raise ValueError('Expected six frozen references and two development exploiters')
    added = [op for op in opponents if op not in campaign.FIXED_OPPONENTS]
    arena = args.arena.resolve()
    league.prepare(arena, campaign.population_spec(2, [candidate], added))
    manifest = json.loads((arena / 'manifest.json').read_text())
    for name in dict.fromkeys([candidate, *opponents]):
        if manifest['bots'][name]['source_sha256'] != lock['source_sha256'][name]:
            raise ValueError(f'Source changed after final selection: {name}')
    if manifest['bots']['v3']['source_sha256'] != campaign.SOURCE_SHA:
        raise ValueError('Current submission baseline changed')
    policy = {'candidate': candidate, 'baseline': 'v3', 'selection_lock': lock,
              'map_seeds': MAPS, 'opponents': opponents, 'source_commit': manifest['source_commit'],
              'source_sha256': {name: manifest['bots'][name]['source_sha256'] for name in dict.fromkeys([candidate, *opponents])},
              'gates': 'No errors/forfeits/missing/duplicate; non-regression all/fixed/challenge Y; opponent Y regression <=12.5pp',
              'primary_only': True, 'replays': 'all'}
    league.write(arena / 'audit-policy.json', policy)
    league.write(arena / 'selection-lock.json', lock)
    plan = {'candidates': ['v3', candidate], 'opponents': opponents, 'map_seeds': MAPS, 'replays': 'all'}
    plan_path = arena / 'plans/audit.json'
    plan_path.parent.mkdir()
    league.write(plan_path, plan)
    with submission_address_space() as cap:
        league.write(arena / 'audit-resource-limit.json', cap)
        league.run(arena, plan_path, 'audit', args.workers, False)
        rows = load_rows(arena / 'runs/audit')
        result = audit_result(rows, candidate, opponents)
        result.update(elapsed_seconds=time.perf_counter() - started, resource_limit=cap)
        league.write(arena / 'audit-result.json', result)
        summary = json.loads((arena / 'runs/audit/summary.json').read_text())['overall']
        league.write(arena / 'campaign-result.json', {
            'phase': 'audit', 'status': result['status'], 'baseline': 'v3', 'primary_candidate': candidate,
            'stage_match_counts': {'audit': summary['matches']}, 'total_matches': summary['matches'],
            'errors': summary['errors'], 'forfeits': summary['forfeits'],
            'recommended': candidate if result['passes_additional_gate'] else 'v3',
            'elapsed_seconds': result['elapsed_seconds']})
        print(json.dumps({'event': 'audit_complete', **result}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--arena', type=Path, required=True)
    parser.add_argument('--selection-lock-json', required=True)
    parser.add_argument('--workers', type=int, default=16)
    args = parser.parse_args()
    if args.workers < 1:
        parser.error('workers must be positive')
    run(args)
