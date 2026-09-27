import argparse
import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'experiments'))
import v3_confirmation as confirmation
import package_frozen_candidate as package


def manifest():
    sdk = 'yk-development-tools/engine/config.py'
    return {'status': 'ready', 'source_commit': 'synthetic-test-only',
            'bots': {name: {'source_sha256': digest} for name, digest in confirmation.PINNED.items()},
            'input_sha256': {confirmation.campaign.SOURCE: confirmation.campaign.SOURCE_SHA,
                             sdk: package.sha(ROOT / sdk)}}


def rows_for(stage):
    jobs = confirmation.league.make_jobs(confirmation.plans()[stage], confirmation.PINNED)
    return [dict(job, status='complete', forfeit=False, draw=False,
                 win=job['candidate'] == confirmation.PRIMARY,
                 score_margin=10 if job['candidate'] == confirmation.PRIMARY else -10)
            for job in jobs]


class ConfirmationTests(unittest.TestCase):
    def test_disjoint_predeclared_schedule_and_counts(self):
        confirmation.validate_maps(confirmation.FINAL_MAPS, confirmation.AUDIT_MAPS)
        self.assertEqual({stage: len(rows_for(stage)) for stage in confirmation.plans()},
                         {'smoke': 20, 'holdout': 4608, 'crossplay': 60, 'audit': 1728})
        for reserved in ([9100], [9300, 9300], [9500]):
            with self.subTest(reserved=reserved), self.assertRaises(ValueError):
                confirmation.validate_maps(confirmation.FINAL_MAPS, reserved)
        lock = confirmation.make_lock(manifest())
        self.assertEqual(lock['finalists'], [confirmation.PRIMARY])
        self.assertNotIn('audit', lock['map_sets'])
        self.assertFalse(lock['original_failed_audit']['overridden_by_this_experiment'])

    def test_source_sdk_primary_and_prior_conclusion_are_locked(self):
        original = confirmation.make_lock(manifest())
        changes = [lambda lock: lock.update(primary_candidate='f3_v2_warrior_reserve'),
                   lambda lock: lock.update(finalists=[confirmation.PRIMARY, 'other']),
                   lambda lock: lock.update(ranking=['other', confirmation.PRIMARY]),
                   lambda lock: lock['source_sha256'].update(v3='changed'),
                   lambda lock: lock['source_sha256'].update(teammate='changed'),
                   lambda lock: lock['sdk_input_sha256'].update({'yk-development-tools/engine/config.py': 'changed'}),
                   lambda lock: lock['submission_input_sha256'].update({confirmation.campaign.SOURCE: 'changed'}),
                   lambda lock: lock['original_failed_audit'].update(overridden_by_this_experiment=True)]
        for change in changes:
            locked = copy.deepcopy(original)
            change(locked)
            with self.subTest(change=change), self.assertRaises(ValueError):
                confirmation.validate_lock(locked, manifest())
        changed = manifest()
        changed['bots'][confirmation.PRIMARY]['source_sha256'] = 'changed'
        with self.assertRaisesRegex(ValueError, 'Frozen bot source changed'):
            confirmation.make_lock(changed)

    def test_invalid_audit_lock_cannot_prepare_or_start_games(self):
        for locked in (None, json.dumps({'primary_candidate': 'other'})):
            args = argparse.Namespace(phase='audit', workers=24, selection_lock_json=locked, arena=Path('/tmp/not-created'))
            with patch.object(confirmation.league, 'prepare') as prepare:
                with self.assertRaises(ValueError):
                    confirmation.campaign_run(args)
                prepare.assert_not_called()

    def test_final_gate_blocks_opponent_regression_and_opponent_side_forfeit(self):
        rows, cross = rows_for('holdout'), rows_for('crossplay')
        decision = confirmation.final_assessment(rows, cross)
        self.assertTrue(decision['promoted'])
        self.assertEqual(len(decision['gates']), 11)
        broken_cross = copy.deepcopy(cross)
        # The submission also has to remain healthy when it is the row's opponent.
        broken_cross[0].update(candidate='teammate', opponent=confirmation.PRIMARY, forfeit=True)
        self.assertFalse(confirmation.final_assessment(rows, broken_cross)['promoted'])
        for row in rows:
            if row['opponent'] == 'j_v2_reclaim_relay' and row['team'] == 'Y':
                row['win'] = not row['win']
        bad = confirmation.final_assessment(rows, cross)
        self.assertTrue(bad['gates']['Y_gain_at_least_3pp'])
        self.assertFalse(bad['gates']['no_opponent_Y_regression_over_10pp'])
        self.assertFalse(bad['promoted'])

    def test_audit_missing_duplicate_and_regression_fail(self):
        rows = rows_for('audit')
        healthy = confirmation.audit_assessment(rows)
        self.assertTrue(healthy['passes_additional_gate'])
        self.assertEqual(len(healthy['gates']), 6)
        for broken in (rows[:-1], [*rows[:-1], rows[0]]):
            result = confirmation.audit_assessment(broken)
            self.assertFalse(result['gates']['complete_schedule_without_duplicates'])
            self.assertFalse(result['passes_additional_gate'])
        for row in rows:
            if row['opponent'] == 'j_v2_reclaim_relay' and row['team'] == 'Y':
                row['win'] = not row['win']
        result = confirmation.audit_assessment(rows)
        self.assertTrue(result['gates']['overall_Y_no_regression'])
        self.assertFalse(result['gates']['no_opponent_Y_regression_over_12_5pp'])
        self.assertFalse(result['passes_additional_gate'])

    def test_synthetic_orchestration_matches_packager_schema(self):
        spec = importlib.util.spec_from_file_location('confirmation_test_search', ROOT / 'experiments/local_league/v3_action_search.py')
        search = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(search)
        source = (ROOT / confirmation.campaign.SOURCE).read_text()
        primary = next(v['source'] for v in search.variants_iteration2(source) if v['id'] == confirmation.PRIMARY)

        def prepare(arena, population):
            self.assertIn(confirmation.PRIMARY, population['include_ids'])
            self.assertEqual(set(population['include_ids']), set(confirmation.PINNED) - {'teammate'})
            arena.mkdir()
            data = manifest()
            data['frozen_sha256'] = {}
            for name, body in ((confirmation.PRIMARY, primary), (confirmation.BASELINE, source)):
                parent = arena / 'snapshot/candidates' / name
                parent.mkdir(parents=True)
                for filename in ('main.cpp', 'protocol.hpp', 'generated.hpp'):
                    path = parent / filename
                    path.write_bytes(body.encode() if filename == 'main.cpp' else
                                     (ROOT / 'submissions/iterative-v3' / filename).read_bytes())
                    data['frozen_sha256'][str(path.relative_to(arena))] = package.sha(path)
                self.assertEqual(package.sha(parent / 'main.cpp'), confirmation.PINNED[name])
                data['bots'][name]['source'] = str((parent / 'main.cpp').relative_to(arena))
            original = arena / 'snapshot' / confirmation.campaign.SOURCE
            original.parent.mkdir(parents=True)
            original.write_text(source)
            data['frozen_sha256'][str(original.relative_to(arena))] = package.sha(original)
            confirmation.league.write(arena / 'manifest.json', data)

        def run(arena, plan, stage, workers, resume):
            lock = json.loads((arena / 'locked-finalists.json').read_text())
            self.assertEqual(lock['finalists'], [confirmation.PRIMARY])
            target = arena / 'runs' / stage
            target.mkdir(parents=True)
            rows = rows_for(stage)
            (target / 'results.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in rows))
            confirmation.league.write(target / 'summary.json', {'overall': {'matches': len(rows), 'errors': 0, 'forfeits': 0}})

        with tempfile.TemporaryDirectory(prefix='yk-confirmation-tests-', dir='/tmp') as temporary:
            arena, audit = Path(temporary) / 'final', Path(temporary) / 'audit'
            with patch.object(confirmation.league, 'prepare', side_effect=prepare), \
                 patch.object(confirmation.league, 'run', side_effect=run), \
                 patch.object(confirmation, 'submission_address_space', return_value=contextlib.nullcontext({'synthetic': True})), \
                 contextlib.redirect_stdout(io.StringIO()):
                final = confirmation.campaign_run(argparse.Namespace(arena=arena, phase='final', workers=24, selection_lock_json=None))
                locked = (arena / 'locked-finalists.json').read_text()
                result = confirmation.campaign_run(argparse.Namespace(arena=audit, phase='audit', workers=24, selection_lock_json=locked))
            self.assertEqual(final['total_matches'], 4688)
            self.assertEqual(result['total_matches'], 1728)
            self.assertEqual(final['recommended'], confirmation.PRIMARY)
            for directory, outcome in ((arena, final), (audit, result)):
                # Synthetic verifier receipts exercise schema only; no matches or validation ran.
                package.write(directory / 'artifact-verification.json',
                              {'status': 'passed', 'errors': 0, 'forfeits': 0, 'source_commit': 'synthetic-test-only',
                               'games': outcome['total_matches']})
            self.assertEqual(package.check_gates(arena, audit)[0], confirmation.PRIMARY)
            policy = package.read(audit / 'audit-policy.json')
            policy['selection_lock']['sdk_input_sha256']['yk-development-tools/engine/config.py'] = 'changed'
            package.write(audit / 'audit-policy.json', policy)
            with self.assertRaisesRegex(ValueError, 'original selection lock'):
                package.check_gates(arena, audit)
        self.assertFalse(Path(temporary).exists())


if __name__ == '__main__':
    unittest.main()
