"""One predeclared s3 confirmation after the separate f3 audit failed."""
from __future__ import annotations

import argparse
import copy
import itertools
import json
from pathlib import Path
import sys
import time

sys.dont_write_bytecode = True
import local_league as league
import v3_campaign as campaign
from cross_family_audit import submission_address_space
from league_campaign import load_rows, crossplay_table

BASELINE = 'v3'
PRIMARY = 's3_v2_screen_paired_guard'
ADDED = ['s3_selective_contact', 'r3_opponent_league', 'f3_v2_warrior_reserve']
OPPONENTS = [*campaign.FIXED_OPPONENTS, *ADDED]
FINAL_MAPS = {'smoke': [9099], 'holdout': list(range(9100, 9228)), 'crossplay': [9400, 9401]}
AUDIT_MAPS = list(range(9300, 9348))
CROSSPLAY = [BASELINE, PRIMARY, 'f3_v2_warrior_reserve', 's3_selective_contact', 'r3_opponent_league', 'teammate']
EXPERIMENT = 'v3-single-s3-confirmation-v1'
SCOPE = ('The prior holdout is now development evidence used to choose this single fixed candidate. '
         'This is a new experiment; the original f3 failed-audit conclusion remains v3. '
         'No reselection or changes after new confirmation outcomes.')
ORIGINAL_FAILED_AUDIT = {'candidate': 'f3_v2_warrior_reserve', 'recommended': BASELINE,
                         'record': 'records/league/loop3-audit/audit-result.json',
                         'status': 'failed_additional_gate', 'overridden_by_this_experiment': False}
PINNED = {
    BASELINE: campaign.SOURCE_SHA,
    PRIMARY: '1703701340ede10b652b0aa024e29c3fd411e2809ae34de1e3d0b39620d496df',
    'v2': '53bb019625fabbbd3aa8a5b65af971912bb4cbdad8a9fde3009fadad5ba6d4c5',
    'teammate': '571397e3c84998b27f8ce0468bc49333663c69b0b84162ad8dfc27e7a47f2365',
    'a_v2_tactical_local': '9d9d6ecd763b84f88c0d5e48f65524798f998e9912f774c0dd22e27f3f78219a',
    'j_balanced_portfolio': '534f55f1d6641ed788ca637663456e43375297d8016ac9832c589b0a012c8422',
    'j_v2_reclaim_relay': '0882dc3284c33db9f4687c085e0c570d156a439365aa229fa6cca6f81e909045',
    's3_selective_contact': 'db83d9aa0e8809aaffd6b36ffc47972996d832d987947187af600d3a8419d96c',
    'r3_opponent_league': '33020d61999456342ea39b3f99e53388914b0ccf98536e2b99ae5e60c31f66cf',
    'f3_v2_warrior_reserve': '20fa2eb5635cd9035c1f2c3f659943e7f98d03c4434bc84c5d5772c6a00e58cf',
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def input_hashes(manifest, prefix):
    return {name: value for name, value in manifest['input_sha256'].items() if name.startswith(prefix)}


def validate_sources(manifest):
    require(manifest.get('status') == 'ready', 'Prepared manifest is not ready')
    for name, expected in PINNED.items():
        require(manifest['bots'].get(name, {}).get('source_sha256') == expected, 'Frozen bot source changed: ' + name)
    require(manifest['input_sha256'].get(campaign.SOURCE) == campaign.SOURCE_SHA, 'Original v3 input changed')
    require(bool(input_hashes(manifest, 'yk-development-tools/')), 'Missing frozen SDK inputs')


def validate_maps(maps, reserved):
    groups = [*maps.values(), reserved]
    require(all(values and len(values) == len(set(values)) for values in groups), 'Missing or duplicate map seeds')
    require(not any(set(a) & set(b) for a, b in itertools.combinations(groups, 2)), 'Overlapping confirmation/audit maps')
    require(maps == FINAL_MAPS and reserved == AUDIT_MAPS, 'Predeclared map sets changed')


def make_lock(manifest):
    validate_sources(manifest)
    lock = {'experiment': EXPERIMENT, 'created_utc': league.stamp(), 'source_commit': manifest['source_commit'],
            'ranking': [PRIMARY], 'finalists': [PRIMARY], 'primary_candidate': PRIMARY, 'baseline': BASELINE,
            'opponents': list(OPPONENTS), 'map_sets': copy.deepcopy(FINAL_MAPS), 'reserved_audit_maps': list(AUDIT_MAPS),
            'source_sha256': dict(PINNED), 'sdk_input_sha256': input_hashes(manifest, 'yk-development-tools/'),
            'submission_input_sha256': input_hashes(manifest, 'submissions/'),
            'selection_scope': SCOPE, 'original_failed_audit': dict(ORIGINAL_FAILED_AUDIT)}
    validate_lock(lock, manifest)
    return lock


def validate_lock(lock, manifest=None):
    require(lock.get('experiment') == EXPERIMENT and lock.get('baseline') == BASELINE, 'Wrong confirmation experiment or baseline')
    require(lock.get('primary_candidate') == PRIMARY and lock.get('ranking') == lock.get('finalists') == [PRIMARY],
            'Only the predeclared primary may be confirmed')
    require(lock.get('opponents') == OPPONENTS and lock.get('source_sha256') == PINNED, 'Opponent or source lock changed')
    validate_maps(lock.get('map_sets', {}), lock.get('reserved_audit_maps', []))
    require(lock.get('selection_scope') == SCOPE and lock.get('original_failed_audit') == ORIGINAL_FAILED_AUDIT,
            'Prior failed audit must remain a separate conclusion')
    require(bool(lock.get('sdk_input_sha256')) and bool(lock.get('submission_input_sha256')), 'Missing SDK/submission input locks')
    if manifest is not None:
        validate_sources(manifest)
        for key, prefix in (('sdk_input_sha256', 'yk-development-tools/'), ('submission_input_sha256', 'submissions/')):
            require(lock[key] == input_hashes(manifest, prefix), 'Frozen ' + key + ' changed after predeclaration')


def plans():
    return {
        'smoke': {'candidates': list(PINNED), 'opponents': [BASELINE], 'map_seeds': FINAL_MAPS['smoke'], 'replays': 'all'},
        'holdout': {'candidates': [BASELINE, PRIMARY], 'opponents': OPPONENTS, 'map_seeds': FINAL_MAPS['holdout'], 'replays': 'all'},
        'crossplay': {'pairs': list(itertools.combinations(CROSSPLAY, 2)), 'map_seeds': FINAL_MAPS['crossplay'], 'replays': 'all'},
        'audit': {'candidates': [BASELINE, PRIMARY], 'opponents': OPPONENTS, 'map_seeds': AUDIT_MAPS, 'replays': 'all'},
    }


def final_assessment(rows, cross_rows):
    decision = campaign.promotion(rows, PRIMARY, OPPONENTS, FINAL_MAPS['holdout'])
    decision['gates']['complete_paired_schedule'] &= len(rows) == 4608
    decision['gates']['crossplay_candidate_and_baseline_runtime_healthy'] = campaign.runtime_health(cross_rows, PRIMARY)
    decision['promoted'] = all(decision['gates'].values())
    return decision


def audit_assessment(rows):
    assessment = campaign.promotion(rows, PRIMARY, OPPONENTS, AUDIT_MAPS)
    y, fixed, added = assessment['comparisons']['Y'], assessment['fixed_pool_comparison'], assessment['challenge_pool_comparison']
    gates = {
        'complete_schedule_without_duplicates': assessment['gates']['complete_paired_schedule'] and len(rows) == 1728,
        'no_baseline_or_candidate_errors_or_forfeits': assessment['gates']['no_error_or_forfeit'],
        'overall_Y_no_regression': bool(y and y['point_rate_difference'] >= -1e-12),
        'fixed_pool_Y_no_regression': bool(fixed and fixed['point_rate_difference'] >= -1e-12),
        'challenge_pool_Y_no_regression': bool(added and added['point_rate_difference'] >= -1e-12),
        'no_opponent_Y_regression_over_12_5pp': all(value and value['point_rate_difference'] >= -.125 - 1e-12
                                                for value in assessment['opponents'].values()),
    }
    return {'status': 'complete' if gates['complete_schedule_without_duplicates'] and gates['no_baseline_or_candidate_errors_or_forfeits'] else 'incomplete_or_failed',
            'baseline': BASELINE, 'candidate': PRIMARY, 'gates': gates, 'passes_additional_gate': all(gates.values()),
            'observed_rows': len(rows), 'comparisons': assessment['comparisons'],
            'opponent_Y_comparisons': assessment['opponents'], 'fixed_pool_comparison': fixed, 'challenge_pool_comparison': added,
            'interpretation': 'Additional gate for this new single-candidate confirmation only; cannot rescue its failed final gate or replace any primary.'}


def campaign_run(args):
    require(args.phase in ('final', 'audit') and args.workers > 0, 'Invalid phase or worker count')
    supplied = json.loads(args.selection_lock_json) if args.selection_lock_json else None
    require(args.phase != 'audit' or supplied is not None, 'Audit requires the original confirmation selection lock JSON')
    if supplied is not None:
        validate_lock(supplied)
    started = time.perf_counter()
    arena = args.arena.resolve()
    league.prepare(arena, campaign.population_spec(2, [PRIMARY], ADDED))
    manifest = json.loads((arena / 'manifest.json').read_text())
    lock = supplied if supplied is not None else make_lock(manifest)
    validate_lock(lock, manifest)
    league.write(arena / 'locked-finalists.json', lock)
    policy = {'experiment': EXPERIMENT, 'phase': args.phase, 'baseline': BASELINE,
              'candidate_ids': [BASELINE, PRIMARY], 'primary_candidate': PRIMARY, 'fixed_opponents': campaign.FIXED_OPPONENTS,
              'opponents': list(OPPONENTS), 'map_sets': copy.deepcopy(FINAL_MAPS), 'reserved_audit_maps': list(AUDIT_MAPS),
              'selection_scope': SCOPE, 'original_failed_audit': dict(ORIGINAL_FAILED_AUDIT),
              'primary_only_can_promote': True, 'selection_count': 1, 'finalists': 1,
              'source_sha256': dict(PINNED), 'selection_lock': lock, 'replay_policy': 'all',
              'resource_policy': '384MiB inherited RLIMIT_AS after compilation; official 300ms turn timeout'}
    league.write(arena / 'campaign-policy.json', policy)
    if args.phase == 'audit':
        league.write(arena / 'audit-policy.json', {**policy, 'candidate': PRIMARY, 'source_commit': manifest['source_commit'],
                                                 'map_seeds': list(AUDIT_MAPS), 'primary_only': True})
        league.write(arena / 'selection-lock.json', lock)
    (arena / 'plans').mkdir()
    reports = {}

    def stage(name):
        plan = plans()[name]
        path = arena / 'plans' / (name + '.json')
        league.write(path, plan)
        print(json.dumps({'event': 'stage_start', 'stage': name, 'jobs': len(league.make_jobs(plan, manifest['bots']))}), flush=True)
        league.run(arena, path, name, args.workers, False)
        reports[name] = json.loads((arena / 'runs' / name / 'summary.json').read_text())
        league.write(arena / 'progress.json', {'completed': list(reports)})
        return load_rows(arena / 'runs' / name)

    result = {'status': 'running', 'phase': args.phase, 'experiment': EXPERIMENT, 'baseline': BASELINE,
              'primary_candidate': PRIMARY, 'finalists': [PRIMARY], 'selection_ranking': [PRIMARY],
              'candidate_count': 2, 'recommended': BASELINE, 'recommendation_scope': SCOPE,
              'original_failed_audit': dict(ORIGINAL_FAILED_AUDIT)}
    try:
        with submission_address_space() as cap:
            league.write(arena / ('audit-resource-limit.json' if args.phase == 'audit' else 'resource-limit.json'), cap)
            if args.phase == 'final':
                smoke = stage('smoke')
                require(len(smoke) == 20 and all(r['status'] == 'complete' and not r.get('forfeit') for r in smoke), 'A frozen bot failed smoke')
                holdout = stage('holdout')
                cross = stage('crossplay')
                require(len(cross) == 60, 'Incomplete crossplay')
                league.write(arena / 'crossplay-table.json', crossplay_table(cross))
                decision = final_assessment(holdout, cross)
                result.update(status='complete', promotion_decisions={PRIMARY: decision},
                              recommended=PRIMARY if decision['promoted'] else BASELINE)
            else:
                audit = audit_assessment(stage('audit'))
                audit.update(elapsed_seconds=time.perf_counter() - started, resource_limit=cap, original_failed_audit=dict(ORIGINAL_FAILED_AUDIT))
                league.write(arena / 'audit-result.json', audit)
                result.update(status=audit['status'], recommended=PRIMARY if audit['passes_additional_gate'] else BASELINE)
    except BaseException as exc:
        result.update(status='failed', recommended=BASELINE, error=f'{type(exc).__name__}: {exc}')
        raise
    finally:
        result.update(stage_match_counts={name: r['overall']['matches'] for name, r in reports.items()},
                      total_matches=sum(r['overall']['matches'] for r in reports.values()),
                      errors=sum(r['overall']['errors'] for r in reports.values()),
                      forfeits=sum(r['overall']['forfeits'] for r in reports.values()), elapsed_seconds=time.perf_counter() - started)
        league.write(arena / 'campaign-result.json', result)
    print(json.dumps({'event': 'confirmation_complete', **result}), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--arena', type=Path, required=True)
    parser.add_argument('--phase', choices=['final', 'audit'], required=True)
    parser.add_argument('--selection-lock-json', help='Literal JSON of this confirmation experiment\'s original lock; mandatory for audit')
    parser.add_argument('--workers', type=int, default=24)
    args = parser.parse_args()
    if args.workers < 1 or (args.phase == 'audit' and not args.selection_lock_json):
        parser.error('Positive workers and an audit selection lock are required')
    campaign_run(args)


if __name__ == '__main__':
    main()
