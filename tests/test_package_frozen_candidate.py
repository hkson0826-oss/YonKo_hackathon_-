import argparse
import importlib.util
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('package_frozen_candidate', ROOT / 'experiments/package_frozen_candidate.py')
PACKAGE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PACKAGE)


class FrozenPackagingGateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='yk-package-gates-', dir='/tmp')
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)
        self.count = 0

    def fixture(self, baseline='v2'):
        self.count += 1
        case = self.folder / str(self.count)
        arena, audit = case / 'arena', case / 'audit'
        sdk = 'yk-development-tools/engine/config.py'
        candidate = 'new_candidate'
        for directory in (arena, audit):
            directory.mkdir(parents=True)
            manifest = {'source_commit': 'fixture-commit', 'input_sha256': {sdk: PACKAGE.sha(ROOT / sdk)},
                        'bots': {}, 'frozen_sha256': {}}
            for name in (candidate, baseline):
                source = directory / 'snapshot/candidates' / name
                source.mkdir(parents=True)
                for filename in ('main.cpp', 'protocol.hpp', 'generated.hpp'):
                    path = source / filename
                    content = f'{name}-{filename}'.encode()
                    if name == 'v3' and filename == 'main.cpp':
                        content = (ROOT / 'submissions/iterative-v3/main.cpp').read_bytes()
                    path.write_bytes(content)
                    manifest['frozen_sha256'][str(path.relative_to(directory))] = PACKAGE.sha(path)
                manifest['bots'][name] = {'source': str((source / 'main.cpp').relative_to(directory)),
                                          'source_sha256': PACKAGE.sha(source / 'main.cpp')}
            if baseline == 'v3':
                relative = 'submissions/iterative-v3/main.cpp'
                original = directory / 'snapshot' / relative
                original.parent.mkdir(parents=True)
                original.write_bytes((ROOT / relative).read_bytes())
                manifest['input_sha256'][relative] = PACKAGE.sha(original)
                manifest['frozen_sha256']['snapshot/' + relative] = PACKAGE.sha(original)
            PACKAGE.write(directory / 'manifest.json', manifest)
            PACKAGE.write(directory / 'artifact-verification.json',
                          {'status': 'passed', 'errors': 0, 'forfeits': 0, 'source_commit': 'fixture-commit', 'games': 8})
        result = {'status': 'complete', 'phase': 'final', 'primary_candidate': candidate, 'recommended': candidate,
                  'total_matches': 8, 'promotion_decisions': {candidate: {'promoted': True, 'gates': {'quality': True, 'health': True}}}}
        lock = {'primary_candidate': candidate, 'finalists': [candidate]}
        if baseline == 'v3':
            result['baseline'] = lock['baseline'] = 'v3'
            result['promotion_decisions'][candidate]['baseline'] = 'v3'
        PACKAGE.write(arena / 'campaign-result.json', result)
        PACKAGE.write(arena / 'locked-finalists.json', lock)
        PACKAGE.write(audit / 'campaign-result.json', {'total_matches': 8})
        PACKAGE.write(audit / 'audit-result.json', {'status': 'complete', 'candidate': candidate, 'baseline': baseline,
                                                    'passes_additional_gate': True, 'gates': {'quality': True, 'health': True}})
        manifest = PACKAGE.read(audit / 'manifest.json')
        PACKAGE.write(audit / 'audit-policy.json', {'candidate': candidate,
                    'source_sha256': {name: bot['source_sha256'] for name, bot in manifest['bots'].items()}})
        return arena, audit

    def mutate(self, directory, filename, change):
        path = directory / filename
        value = PACKAGE.read(path)
        change(value)
        PACKAGE.write(path, value)

    def test_legacy_v2_and_v3_acceptance(self):
        for baseline in ('v2', 'v3'):
            with self.subTest(baseline=baseline):
                arena, audit = self.fixture(baseline)
                candidate, manifest, reports, sdk_count = PACKAGE.check_gates(arena, audit)
                self.assertEqual(candidate, 'new_candidate')
                self.assertIn(baseline, manifest['bots'])
                self.assertEqual(set(reports), {'original', 'audit'})
                self.assertEqual(sdk_count, 1)

    def test_both_validation_stages_and_health_are_required(self):
        failures = [
            ('arena', 'campaign-result.json', lambda v: v.update(status='running')),
            ('arena', 'campaign-result.json', lambda v: v.update(recommended='v3')),
            ('arena', 'campaign-result.json', lambda v: v['promotion_decisions']['new_candidate'].update(promoted=False)),
            ('arena', 'campaign-result.json', lambda v: v['promotion_decisions']['new_candidate']['gates'].update(health=False)),
            ('audit', 'audit-result.json', lambda v: v.update(status='running')),
            ('audit', 'audit-result.json', lambda v: v.update(passes_additional_gate=False)),
            ('audit', 'audit-result.json', lambda v: v['gates'].update(health=False)),
            ('arena', 'artifact-verification.json', lambda v: v.update(status='failed')),
            ('arena', 'artifact-verification.json', lambda v: v.update(errors=1)),
            ('audit', 'artifact-verification.json', lambda v: v.update(forfeits=1)),
            ('audit', 'artifact-verification.json', lambda v: v.update(source_commit='other')),
            ('audit', 'artifact-verification.json', lambda v: v.update(games=7)),
        ]
        for side, filename, change in failures:
            with self.subTest(side=side, filename=filename, change=change):
                arena, audit = self.fixture('v3')
                self.mutate(arena if side == 'arena' else audit, filename, change)
                with self.assertRaises(ValueError):
                    PACKAGE.check_gates(arena, audit)
        arena, audit = self.fixture('v3')
        (audit / 'artifact-verification.json').unlink()
        with self.assertRaises(FileNotFoundError):
            PACKAGE.check_gates(arena, audit)

    def test_baseline_identity_must_match_everywhere(self):
        changes = [
            ('arena', 'campaign-result.json', lambda v: v.update(baseline='v1')),
            ('arena', 'locked-finalists.json', lambda v: v.update(primary_candidate='v3', finalists=['v3'])),
            ('arena', 'locked-finalists.json', lambda v: v.update(baseline='v2')),
            ('arena', 'campaign-result.json', lambda v: v['promotion_decisions']['new_candidate'].update(baseline='v2')),
            ('audit', 'audit-result.json', lambda v: v.update(baseline='v2')),
            ('audit', 'audit-policy.json', lambda v: v.update(baseline='v2')),
            ('audit', 'audit-policy.json', lambda v: v['source_sha256'].update(v3='bad')),
        ]
        for side, filename, change in changes:
            with self.subTest(side=side, filename=filename):
                arena, audit = self.fixture('v3')
                self.mutate(arena if side == 'arena' else audit, filename, change)
                with self.assertRaises(ValueError):
                    PACKAGE.check_gates(arena, audit)

    def test_source_and_original_v3_hashes_are_required(self):
        for baseline, changed_name in (('v2', 'new_candidate'), ('v3', 'new_candidate'), ('v3', 'v3')):
            with self.subTest(baseline=baseline, changed_name=changed_name):
                arena, audit = self.fixture(baseline)
                manifest = PACKAGE.read(audit / 'manifest.json')
                (audit / manifest['bots'][changed_name]['source']).write_text('changed source')
                with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                    PACKAGE.check_gates(arena, audit)
        # Consistent hashes in both runs cannot relabel arbitrary code as the submitted v3.
        arena, audit = self.fixture('v3')
        for directory in (arena, audit):
            manifest = PACKAGE.read(directory / 'manifest.json')
            path = directory / manifest['bots']['v3']['source']
            path.write_text('a different bot')
            digest = PACKAGE.sha(path)
            manifest['bots']['v3']['source_sha256'] = digest
            manifest['frozen_sha256'][manifest['bots']['v3']['source']] = digest
            PACKAGE.write(directory / 'manifest.json', manifest)
        with self.assertRaisesRegex(ValueError, 'original submission'):
            PACKAGE.check_gates(arena, audit)
        arena, audit = self.fixture('v3')
        self.mutate(audit, 'manifest.json', lambda v: v['input_sha256'].update({'submissions/iterative-v3/main.cpp': 'bad'}))
        with self.assertRaisesRegex(ValueError, 'original input'):
            PACKAGE.check_gates(arena, audit)

    def test_existing_output_is_never_overwritten(self):
        arena, audit = self.fixture('v3')
        source = self.folder / 'existing-source'
        source.mkdir()
        marker = source / 'main.cpp'
        marker.write_text('preserve me')
        args = argparse.Namespace(arena=arena, audit=audit, source_output=source,
                                  zip_output=self.folder / 'new.zip', record_output=self.folder / 'record')
        with patch.object(PACKAGE, 'compile_bot', side_effect=AssertionError('must not compile')):
            with self.assertRaisesRegex(ValueError, 'overwrite'):
                PACKAGE.run(args)
        self.assertEqual(marker.read_text(), 'preserve me')
        self.assertFalse(args.zip_output.exists())
        self.assertFalse(args.record_output.exists())

    def test_cpu_seed_defaults_and_cli_override(self):
        self.assertEqual(PACKAGE.cpu_seeds(7550), (7550, 7551))
        self.assertEqual(PACKAGE.cpu_seeds(8800), (8800, 8801))
        for bad in (-1, True, 1.5, '8800'):
            with self.assertRaises(ValueError):
                PACKAGE.cpu_seeds(bad)
        required = ['package', '--arena', str(self.folder / 'arena'), '--audit', str(self.folder / 'audit'),
                    '--source-output', str(self.folder / 'v4'), '--zip-output', str(self.folder / 'v4.zip'),
                    '--record-output', str(self.folder / 'v4-record')]
        for extra, expected in (([], 7550), (['--cpu-seed-start', '8800'], 8800)):
            with patch('sys.argv', required + extra), patch.object(PACKAGE, 'run') as run:
                PACKAGE.main()
                self.assertEqual(run.call_args.args[0].cpu_seed_start, expected)
                self.assertEqual(run.call_args.args[0].compiler, 'g++')

    def test_runtime_schedule_labels_without_running_bots(self):
        class FakeBot:
            def __init__(self, *args):
                self.proc = None
                self.max_turn_ms = 1.0
                self.issues = []
                self.usage = types.SimpleNamespace(snapshot=lambda: {'warnings': []})

            def close(self):
                pass

        calls = []

        def fake_match(seed, config, y, k, **kwargs):
            calls.append((seed, kwargs['names'], kwargs['turn_timeout_ms']))
            return {'turns': []}, {'reason': 'turn_limit', 'turns': 160}

        engine, runner = types.ModuleType('engine'), types.ModuleType('runner')
        engine.__path__ = runner.__path__ = []
        config = types.ModuleType('engine.config')
        config.load_config = lambda: {'total_turns': 160}
        match = types.ModuleType('runner.match')
        match.run_match = fake_match
        checker = types.SimpleNamespace(CheckedBot=FakeBot, check=lambda *args, **kwargs: {'ok': True, 'issues': [], 'warnings': []})
        modules = {'engine': engine, 'engine.config': config, 'runner': runner, 'runner.match': match}
        for baseline, start in (('v2', 7550), ('v3', 8800)):
            calls.clear()
            records = self.folder / ('mock-runtime-' + baseline)
            records.mkdir()
            with patch.dict('sys.modules', modules):
                rows = PACKAGE.validate_runtime(checker, self.folder / 'not-executed-candidate',
                                                self.folder / 'not-executed-baseline', 'new_candidate', records,
                                                baseline=baseline, cpu_seed_start=start)
            self.assertIs(checker.CheckedBot, FakeBot)
            self.assertEqual([(r['map_seed'], r['team']) for r in rows],
                             [(start, 'Y'), (start, 'K'), (start + 1, 'Y'), (start + 1, 'K')])
            self.assertTrue(all(r['opponent'] == baseline for r in rows))
            self.assertTrue(all(set(names.values()) == {'new_candidate', baseline} and ms == 300 for _, names, ms in calls))
            self.assertEqual(len(list((records / 'replays').glob('*.json.gz'))), 4)


if __name__ == '__main__':
    unittest.main()
