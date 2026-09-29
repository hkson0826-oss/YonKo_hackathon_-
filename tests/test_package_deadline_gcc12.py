import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import signal
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'experiments'))
import package_deadline_gcc12 as wrapper


class DeadlineGcc12Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='yk-gcc12-wrapper-test-', dir='/tmp')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.decision = self.root / 'decision.json'
        self.decision.write_text(json.dumps({s: {'arena': str(self.root / s)} for s in ('selection', 'final')}))
        self.args = argparse.Namespace(arena=self.root / 'arena', decision_json=self.decision,
                    output_zip=self.root / 'submission.zip', records=self.root / 'records',
                    compiler_record=self.root / 'compiler.json', candidate='new',
                    cpu_seed_start=15000, toolchain_budget_seconds=300)
        self.active = False

    @contextmanager
    def toolchain(self, report, budget_seconds):
        self.assertEqual(budget_seconds, 300)
        report['temporary_directory'] = str(self.root / 'fake-sysroot')
        self.active = True
        try:
            yield {'compiler_wrapper': str(self.root / 'fake-gcc12'),
                   'env': {**os.environ, 'YK_GCC12_WRAPPER_TEST': 'inside'}}
        finally:
            self.active = False
            report['temporary_directory_removed'] = True

    def package(self, args):
        self.assertTrue(self.active)
        self.assertEqual(args.compiler, str(self.root / 'fake-gcc12'))
        self.assertEqual(os.environ['YK_GCC12_WRAPPER_TEST'], 'inside')
        return {'status': 'validated', 'temporary_directory_removed': True}

    def test_runtime_stays_inside_toolchain_and_restores_environment(self):
        before = dict(os.environ)
        signals = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
        with patch.object(wrapper.deadline, 'normalized', side_effect=lambda args: args), \
             patch.object(wrapper.deadline, 'check_decision'), \
             patch.object(wrapper, 'gcc12_toolchain', side_effect=self.toolchain), \
             patch.object(wrapper.deadline, 'run', side_effect=self.package):
            report = wrapper.run(self.args)
        self.assertEqual(report['status'], 'passed')
        self.assertEqual(dict(os.environ), before)
        self.assertEqual({sig: signal.getsignal(sig) for sig in signals}, signals)
        self.assertTrue(report['toolchain']['temporary_directory_removed'])
        self.assertTrue(self.args.compiler_record.is_file())

    def test_failed_decision_never_starts_network_toolchain(self):
        with patch.object(wrapper.deadline, 'normalized', side_effect=lambda args: args), \
             patch.object(wrapper.deadline, 'check_decision', side_effect=ValueError('unaccepted')), \
             patch.object(wrapper, 'gcc12_toolchain') as context, \
             patch.object(wrapper.deadline, 'run') as package:
            report = wrapper.run(self.args)
        self.assertEqual(report['status'], 'failed')
        context.assert_not_called()
        package.assert_not_called()

    def test_packaging_failure_still_cleans_context_and_restores_environment(self):
        before = dict(os.environ)
        with patch.object(wrapper.deadline, 'normalized', side_effect=lambda args: args), \
             patch.object(wrapper.deadline, 'check_decision'), \
             patch.object(wrapper, 'gcc12_toolchain', side_effect=self.toolchain), \
             patch.object(wrapper.deadline, 'run', side_effect=RuntimeError('runtime failed')):
            report = wrapper.run(self.args)
        self.assertEqual(report['status'], 'failed')
        self.assertTrue(report['toolchain']['temporary_directory_removed'])
        self.assertEqual(dict(os.environ), before)


if __name__ == '__main__':
    unittest.main()
