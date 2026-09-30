"""Publication, provenance and failure-path checks without network downloads."""
import argparse
from contextlib import contextmanager
import copy
import json
import os
from pathlib import Path
import shutil
import signal
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'experiments'))
import package_mission_candidate as helper


class MissionPackagingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='yk-mission-package-test-', dir='/tmp')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.arena = self.root / 'arena'
        self.arena.mkdir()
        manifest = {'status': 'ready', 'source_commit': 'fixture-commit', 'bots': {},
                    'input_sha256': {}, 'frozen_sha256': {}}
        for relative in ('engine/config.py', 'engine/pipeline.py', 'runner/match.py',
                         'mapgen/generator.py', 'config/balance.json'):
            name = 'yk-development-tools/' + relative
            target = self.arena / 'snapshot' / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(helper.package.ROOT / name, target)
            manifest['input_sha256'][name] = helper.sha(target)
        original = helper.package.ROOT / 'submissions/deadline-20260929-guard3'
        for name in ('mission', 'v8'):
            folder = self.arena / 'snapshot/candidates' / name
            folder.mkdir(parents=True)
            for member in helper.package.FILES:
                shutil.copyfile(original / member, folder / member)
            if name == 'mission':
                (folder / 'main.cpp').write_text('int main() { return 0; }\n')
            source = folder / 'main.cpp'
            manifest['bots'][name] = {'source': str(source.relative_to(self.arena)),
                                      'source_sha256': helper.sha(source)}
        manifest['frozen_sha256'] = {str(path.relative_to(self.arena)): helper.sha(path)
                                      for path in self.arena.rglob('*') if path.is_file()}
        helper.write(self.arena / 'manifest.json', manifest)
        self.manifest = manifest
        self.args = argparse.Namespace(arena=self.arena, candidate='mission',
                                       output_zip=self.root / 'candidate.zip', records=self.root / 'records',
                                       cpu_seed_start=22400, toolchain_budget_seconds=300)
        self.environment = dict(os.environ)
        self.handlers = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
        self.active = False

    @contextmanager
    def toolchain(self, report, budget_seconds):
        self.assertEqual(budget_seconds, 300)
        folder = self.root / 'toolchain'
        folder.mkdir()
        report['temporary_directory'] = str(folder)
        self.active = True
        try:
            yield {'compiler_wrapper': str(folder / 'gcc12'),
                   'env': {**self.environment, 'MISSION_PACKAGING_TEST': 'inside'}}
        finally:
            self.active = False
            folder.rmdir()
            report['temporary_directory_removed'] = not folder.exists()

    def rows(self):
        # All four games are losses. Runtime validity must never masquerade as promotion.
        return [{'map_seed': seed, 'team': team, 'candidate': 'mission', 'opponent': 'v8',
                 'result': {'winner': 'K' if team == 'Y' else 'Y', 'reason': 'score', 'turns': 160},
                 'elapsed_seconds': 10, 'candidate_max_turn_ms': 10,
                 'candidate_response_ms': [10] * 160, 'opponent_response_ms': [20] * 160,
                 'candidate_issues': [], 'opponent_issues': [],
                 'candidate_output_usage': {'warnings': []}, 'opponent_output_usage': {'warnings': []}}
                for seed in (22400, 22401) for team in 'YK']

    def runtime(self, checker, own, other, candidate, records, **kwargs):
        self.assertTrue(self.active)
        self.assertEqual(os.environ['MISSION_PACKAGING_TEST'], 'inside')
        self.assertEqual(kwargs, {'baseline': 'v8', 'cpu_seed_start': 22400})
        self.assertFalse(self.args.output_zip.exists())
        return self.rows()

    def compile(self, compiler, source, binary, records, label):
        self.assertTrue(self.active)
        if label == 'candidate-from-zip':
            self.assertEqual(source.parent.name, 'extracted')
            self.assertEqual(source.read_bytes(), (self.arena / self.manifest['bots']['mission']['source']).read_bytes())
        binary.write_text('unit test placeholder, never executed')

    def invoke(self, runtime=None, context=None, action_audit=None):
        with patch.object(helper, 'gcc12_toolchain', context or self.toolchain), \
             patch.object(helper.package, 'compile_bot', side_effect=self.compile), \
             patch.object(helper.package, 'validate_runtime', side_effect=runtime or self.runtime), \
             patch.object(helper, 'audit_actions', side_effect=action_audit or (lambda *args: {'issues': 0, 'frames': 640})), \
             patch.object(helper.evidence, 'check_decision', side_effect=AssertionError('promotion gate must remain separate')):
            return helper.run(self.args)

    def assert_restored(self):
        self.assertEqual(dict(os.environ), self.environment)
        self.assertEqual({sig: signal.getsignal(sig) for sig in self.handlers}, self.handlers)
        self.assertFalse((self.root / 'toolchain').exists())
        self.assertFalse((self.args.records / 'archive.pending').exists())

    def test_losing_research_candidate_publishes_only_validated_four_file_zip(self):
        result = self.invoke()
        self.assertEqual(result['status'], 'validated')
        self.assertEqual(result['purpose'], 'research_candidate_only')
        self.assertFalse(result['promotion_evaluated'] or result['promotion_approved'] or result['server_upload_performed'])
        self.assertEqual(result['runtime_results'], {'wins': 0, 'draws': 0, 'losses': 4})
        self.assertEqual(set(result['zip']['members']), set(helper.package.FILES))
        self.assertEqual(helper.sha(self.args.output_zip), result['zip']['sha256'])
        self.assertTrue(result['input_seal_unchanged'])
        self.assertTrue(result['packaging_temporary_directory_removed'])
        self.assertTrue(result['toolchain']['temporary_directory_removed'])
        self.assertEqual(helper.read(self.args.records / 'validation.json'), result)
        self.assert_restored()

    def test_tampered_source_fails_before_toolchain_download(self):
        (self.arena / self.manifest['bots']['mission']['source']).write_text('tampered')
        with patch.object(helper, 'gcc12_toolchain') as network:
            result = helper.run(self.args)
        self.assertEqual(result['status'], 'failed')
        self.assertIn('Frozen hash mismatch', result['error'])
        network.assert_not_called()
        self.assertFalse(self.args.output_zip.exists())
        self.assert_restored()

    def test_existing_outputs_and_arena_overlap_are_rejected(self):
        self.args.output_zip.write_text('preserve')
        with self.assertRaises(ValueError):
            helper.run(self.args)
        self.assertEqual(self.args.output_zip.read_text(), 'preserve')
        self.args.output_zip = self.arena / 'do-not-write.zip'
        with self.assertRaises(ValueError):
            helper.run(self.args)
        self.assertFalse(self.args.output_zip.exists())
        self.assertFalse(self.args.records.exists())

    def test_source_mutation_during_validation_prevents_publication(self):
        def mutated(*args, **kwargs):
            rows = self.runtime(*args, **kwargs)
            (self.arena / self.manifest['bots']['mission']['source']).write_text('changed during runtime')
            return rows
        result = self.invoke(runtime=mutated)
        self.assertEqual(result['status'], 'failed')
        self.assertFalse(self.args.output_zip.exists())
        self.assertIn('Frozen hash mismatch', result['error'])
        self.assert_restored()

    def test_runtime_failure_retains_logs_cleans_temporary_files_and_blocks_zip(self):
        def failed(*args, **kwargs):
            self.runtime(*args, **kwargs)
            raise ValueError('forfeit or output warning')
        result = self.invoke(runtime=failed)
        self.assertEqual(result['status'], 'failed')
        self.assertIn('forfeit or output warning', result['error'])
        self.assertTrue((self.args.records / 'failure.txt').is_file())
        self.assertTrue(result['packaging_temporary_directory_removed'])
        self.assertFalse(self.args.output_zip.exists())
        self.assert_restored()

    def test_interruption_restores_environment_and_signal_handlers(self):
        def interrupted(*args, **kwargs):
            signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
        result = self.invoke(runtime=interrupted)
        self.assertEqual(result['status'], 'failed')
        self.assertIn('InterruptedError', result['error'])
        self.assertFalse(self.args.output_zip.exists())
        self.assert_restored()

    def test_cleanup_must_succeed_before_publication(self):
        @contextmanager
        def bad_cleanup(report, budget_seconds):
            with self.toolchain(report, budget_seconds) as toolchain:
                yield toolchain
            report['temporary_directory_removed'] = False
        result = self.invoke(context=bad_cleanup)
        self.assertEqual(result['status'], 'failed')
        self.assertIn('cleanup', result['error'])
        self.assertFalse(self.args.output_zip.exists())
        self.assert_restored()

    def test_clipped_action_audit_blocks_zip_even_when_match_did_not_forfeit(self):
        def failed(*args):
            raise ValueError('Runtime commands were rejected or clipped')
        result = self.invoke(action_audit=failed)
        self.assertEqual(result['status'], 'failed')
        self.assertIn('clipped', result['error'])
        self.assertFalse(self.args.output_zip.exists())
        self.assert_restored()

    def test_duplicate_pairs_forfeit_output_warning_and_late_response_are_rejected(self):
        original = self.rows()
        bad = [original[:-1], [original[0], original[0], *original[2:]]]
        for change in ('forfeit', 'warning', 'late'):
            rows = copy.deepcopy(original)
            if change == 'forfeit':
                rows[0]['result']['reason'] = 'forfeit'
            elif change == 'warning':
                rows[0]['candidate_output_usage']['warnings'] = ['stdout limit']
            else:
                rows[0]['candidate_response_ms'][1] = 301
            bad.append(rows)
        for rows in bad:
            with self.subTest(rows=rows[0].get('result')):
                with self.assertRaises(ValueError):
                    helper.validate_cpu_rows(rows, 'mission', 22400)

    def test_v8_identity_cannot_be_replaced_by_updating_manifest_digests(self):
        path = self.arena / self.manifest['bots']['v8']['source']
        path.write_text('different baseline')
        self.manifest['bots']['v8']['source_sha256'] = helper.sha(path)
        self.manifest['frozen_sha256'][str(path.relative_to(self.arena))] = helper.sha(path)
        helper.write(self.arena / 'manifest.json', self.manifest)
        with self.assertRaisesRegex(ValueError, 'v8 baseline differs'):
            helper.verify_inputs(self.arena, 'mission')


if __name__ == '__main__':
    unittest.main(verbosity=2)
