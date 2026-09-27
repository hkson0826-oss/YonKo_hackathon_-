import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'experiments'))
import analyze_v3_confirmation as analysis
import v3_confirmation as confirmation


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) + '\n')


def synthetic_rows(stage):
    rows = []
    for job in confirmation.league.make_jobs(confirmation.plans()[stage], confirmation.PINNED):
        remainder = job['map_seed'] % 4
        draw = remainder == 1
        win = not draw and (job['candidate'] == confirmation.PRIMARY or remainder == 0)
        side = job['team']
        other = 'K' if side == 'Y' else 'Y'
        own_score, other_score = (10, 10) if draw else ((20, 10) if win else (10, 20))
        rows.append({**job, 'status': 'complete', 'win': win, 'draw': draw, 'forfeit': False,
                     'score_margin': own_score - other_score, 'max_turn_ms': 1.0,
                     'opponent_max_turn_ms': 2.0, 'response_ms': [1.0],
                     'result': {'winner': 'DRAW' if draw else (side if win else other),
                                'score': {side: own_score, other: other_score}, 'reason': 'max_turns'},
                     'replay': 'replays/synthetic.json.gz'})
    return rows


def fixture(arena, phase, lock=None):
    manifest = {'status': 'ready', 'source_commit': 'synthetic-only',
                'bots': {name: {'source_sha256': value} for name, value in confirmation.PINNED.items()},
                'input_sha256': {confirmation.campaign.SOURCE: confirmation.campaign.SOURCE_SHA,
                                 'yk-development-tools/engine/example.py': 'synthetic-sdk-sha'}}
    lock = copy.deepcopy(lock) if lock is not None else confirmation.make_lock(manifest)
    policy = {'experiment': confirmation.EXPERIMENT, 'phase': phase, 'baseline': confirmation.BASELINE,
              'candidate_ids': [confirmation.BASELINE, confirmation.PRIMARY],
              'primary_candidate': confirmation.PRIMARY, 'fixed_opponents': confirmation.campaign.FIXED_OPPONENTS,
              'opponents': confirmation.OPPONENTS, 'map_sets': confirmation.FINAL_MAPS,
              'reserved_audit_maps': confirmation.AUDIT_MAPS, 'selection_lock': lock,
              'source_sha256': confirmation.PINNED, 'selection_scope': confirmation.SCOPE,
              'original_failed_audit': confirmation.ORIGINAL_FAILED_AUDIT, 'primary_only_can_promote': True}
    for name, value in (('manifest.json', manifest), ('locked-finalists.json', lock), ('campaign-policy.json', policy)):
        write(arena / name, value)
    rows_by_stage = {}
    for stage in analysis.STAGES[phase]:
        plan = confirmation.plans()[stage]
        jobs = confirmation.league.make_jobs(plan, manifest['bots'])
        rows = rows_by_stage[stage] = synthetic_rows(stage)
        directory = arena / 'runs' / stage
        write(arena / 'plans' / (stage + '.json'), plan)
        write(directory / 'plan.json', plan)
        write(directory / 'jobs.json', jobs)
        write(directory / 'summary.json', {'expected_jobs': len(rows), 'finished_jobs': len(rows),
                                           'overall': analysis.aggregate(rows)})
        write(directory / 'session-1.json', {'status': 'complete', 'finished_utc': 'synthetic-only'})
        (directory / 'results.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in rows))
        # Only existence is checked here. Full replay/engine verification is a separate tool.
        (directory / 'replays').mkdir()
        (directory / 'replays/synthetic.json.gz').write_bytes(b'synthetic-not-an-actual-replay')
    write(arena / 'progress.json', {'completed': list(analysis.STAGES[phase])})
    result = {'status': 'complete', 'phase': phase, 'experiment': confirmation.EXPERIMENT,
              'baseline': confirmation.BASELINE, 'primary_candidate': confirmation.PRIMARY,
              'finalists': [confirmation.PRIMARY], 'selection_ranking': [confirmation.PRIMARY],
              'original_failed_audit': confirmation.ORIGINAL_FAILED_AUDIT,
              'stage_match_counts': {stage: len(rows) for stage, rows in rows_by_stage.items()},
              'total_matches': sum(map(len, rows_by_stage.values())), 'errors': 0, 'forfeits': 0}
    if phase == 'final':
        decision = confirmation.final_assessment(rows_by_stage['holdout'], rows_by_stage['crossplay'])
        result['promotion_decisions'] = {confirmation.PRIMARY: decision}
        result['recommended'] = confirmation.PRIMARY if decision['promoted'] else confirmation.BASELINE
    else:
        decision = confirmation.audit_assessment(rows_by_stage['audit'])
        decision['original_failed_audit'] = confirmation.ORIGINAL_FAILED_AUDIT
        write(arena / 'audit-result.json', decision)
        write(arena / 'selection-lock.json', lock)
        write(arena / 'audit-policy.json', {**policy, 'candidate': confirmation.PRIMARY,
                                           'map_seeds': confirmation.AUDIT_MAPS})
        result['recommended'] = confirmation.PRIMARY if decision['passes_additional_gate'] else confirmation.BASELINE
    write(arena / 'campaign-result.json', result)
    return lock


class ConfirmationAnalysisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='yk-confirm-analysis-test-', dir='/tmp')
        cls.root = Path(cls.temporary.name)
        cls.final, cls.audit = cls.root / 'final', cls.root / 'audit'
        cls.lock = fixture(cls.final, 'final')
        fixture(cls.audit, 'audit', cls.lock)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def edit_json(self, path, change):
        old = path.read_bytes()
        self.addCleanup(path.write_bytes, old)
        value = json.loads(old)
        change(value)
        write(path, value)

    def test_full_synthetic_final_and_audit_preserve_sources_and_report_rates(self):
        originals = {path: path.read_bytes() for arena in (self.final, self.audit)
                     for path in arena.rglob('*') if path.is_file()}
        output = self.root / 'report'
        with patch.object(confirmation.league, 'run') as run, patch.object(confirmation.league, 'prepare') as prepare:
            report = analysis.analyze(self.final, self.audit, output)
            run.assert_not_called()
            prepare.assert_not_called()
        self.assertEqual(report['final']['campaign']['total_matches'], 4688)
        self.assertEqual(report['audit']['campaign']['total_matches'], 1728)
        self.assertEqual(report['final']['distinct_comparison_maps'], 128)
        self.assertEqual(report['audit']['distinct_comparison_maps'], 48)
        self.assertEqual(report['conclusion']['recommended'], confirmation.PRIMARY)
        self.assertFalse(report['original_failed_audit']['overridden_by_this_experiment'])
        entry = report['final']['pools']['overall']['Y']
        self.assertEqual(entry['candidate']['wins'], 864)
        self.assertEqual(entry['candidate']['draws'], 288)
        self.assertEqual(entry['candidate']['win_rate'], .75)
        self.assertEqual(entry['candidate']['point_rate'], .875)
        self.assertEqual(entry['baseline']['point_rate'], .375)
        self.assertEqual(entry['paired_point_rate_difference']['point_rate_difference'], .5)
        self.assertGreater(entry['paired_point_rate_difference']['map_cluster_bootstrap_95pct'][0], 0)
        self.assertEqual(len(report['final']['per_opponent']), 9)
        self.assertEqual(report['final']['pools']['fixed']['K']['candidate']['matches'], 128 * 6)
        self.assertEqual(report['final']['pools']['added']['K']['candidate']['matches'], 128 * 3)
        self.assertIn('이전 80맵 holdout', (output / 'README.md').read_text())
        self.assertEqual(originals, {path: path.read_bytes() for path in originals})

    def test_live_progress_or_session_cannot_look_complete(self):
        self.edit_json(self.final / 'progress.json', lambda value: value.update(completed=['smoke', 'holdout']))
        with self.assertRaisesRegex(ValueError, 'Progress'):
            analysis.load_completed(self.final, 'final')
        self.doCleanups()
        self.edit_json(self.final / 'runs/holdout/session-1.json', lambda value: value.update(status='running'))
        with self.assertRaisesRegex(ValueError, 'session is not closed'):
            analysis.load_completed(self.final, 'final')

    def test_missing_duplicate_and_wrong_raw_winner_are_rejected(self):
        path = self.final / 'runs/holdout/results.jsonl'
        old = path.read_bytes()
        self.addCleanup(path.write_bytes, old)
        rows = [json.loads(line) for line in old.splitlines()]
        for bad, message in ((rows[:-1], 'incomplete or duplicate'),
                             ([*rows[:-1], rows[0]], 'incomplete or duplicate')):
            path.write_text(''.join(json.dumps(row) + '\n' for row in bad))
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                analysis.load_completed(self.final, 'final')
        altered = copy.deepcopy(rows)
        altered[0]['win'] = not altered[0]['win']
        path.write_text(''.join(json.dumps(row) + '\n' for row in altered))
        with self.assertRaisesRegex(ValueError, 'Raw winner'):
            analysis.load_completed(self.final, 'final')

    def test_stored_gate_and_aggregate_must_match_raw_results(self):
        self.edit_json(self.final / 'campaign-result.json',
                       lambda value: value['promotion_decisions'][confirmation.PRIMARY]['gates'].update(Y_gain_at_least_3pp=False))
        run = analysis.load_completed(self.final, 'final')
        with self.assertRaisesRegex(ValueError, 'Stored final decision'):
            analysis.verify_decision(run)
        self.doCleanups()
        self.edit_json(self.final / 'runs/holdout/summary.json',
                       lambda value: value['overall'].update(wins=value['overall']['wins'] + 1))
        with self.assertRaisesRegex(ValueError, 'raw aggregate differs'):
            analysis.load_completed(self.final, 'final')

    def test_changed_audit_lock_is_rejected_before_statistics(self):
        self.edit_json(self.audit / 'locked-finalists.json', lambda value: value.update(created_utc='changed'))
        with self.assertRaisesRegex(ValueError, 'original confirmation lock'):
            analysis.load_completed(self.audit, 'audit', self.lock)

    def test_audit_cannot_rescue_failed_final_and_absence_is_pending(self):
        for final_passed, audit_passed, healthy in ((False, True, True), (True, False, True),
                                                   (True, None, True), (True, True, False)):
            with self.subTest(final=final_passed, audit=audit_passed, healthy=healthy):
                outcome = analysis.conclusion(final_passed, audit_passed, healthy)
                self.assertEqual(outcome['recommended'], confirmation.BASELINE)
                self.assertFalse(outcome['confirmation_gates_passed'])
        self.assertEqual(analysis.conclusion(True, None)['audit_status'], 'not_provided')

    def test_draw_forfeit_is_health_failure_and_win_rate_differs_from_points(self):
        row = next(row for row in synthetic_rows('audit') if row['draw'])
        row.update(forfeit=True)
        row['result'].update(reason='forfeit', forfeit={'team': 'both'})
        analysis.outcome_check(row)
        self.assertFalse(analysis.health([row])['runtime_gate_passed'])
        self.assertEqual(analysis.stats([row])['win_rate'], 0)
        self.assertEqual(analysis.stats([row])['point_rate'], .5)
        row['forfeit'] = False
        with self.assertRaisesRegex(ValueError, 'forfeit flag'):
            analysis.outcome_check(row)

    def test_consistent_failed_gate_is_reported_without_reselection(self):
        run = analysis.load_completed(self.final, 'final')
        for row in run['rows']['holdout']:
            if row['opponent'] != 'j_v2_reclaim_relay' or row['team'] != 'Y':
                continue
            win = row['candidate'] == confirmation.BASELINE
            row.update(win=win, draw=False, score_margin=10 if win else -10)
            row['result'].update(winner='Y' if win else 'K',
                                 score={'Y': 20 if win else 10, 'K': 10 if win else 20})
            analysis.outcome_check(row)
        decision = confirmation.final_assessment(run['rows']['holdout'], run['rows']['crossplay'])
        run['result'].update(promotion_decisions={confirmation.PRIMARY: analysis.normalized(decision)},
                             recommended=confirmation.BASELINE)
        verified = analysis.verify_decision(run)
        self.assertTrue(verified['gates']['Y_gain_at_least_3pp'])
        self.assertIn('no_opponent_Y_regression_over_10pp', verified['failed_gates'])
        self.assertEqual(analysis.conclusion(verified['promoted'], True)['recommended'], confirmation.BASELINE)
        section = {'campaign': run['result'], 'health': run['health'], 'decision': verified,
                   'distinct_comparison_maps': 128, 'pools': {}, 'per_opponent': {}}
        text = analysis.markdown({'final': section, 'audit': None,
                                  'conclusion': analysis.conclusion(verified['promoted'], None)})
        self.assertIn('`no_opponent_Y_regression_over_10pp`', text)
        self.assertIn('추가 감사 결과는 아직 제공되지 않았다', text)


if __name__ == '__main__':
    unittest.main()
