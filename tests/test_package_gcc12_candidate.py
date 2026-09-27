import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import signal
import tempfile
import unittest
from unittest.mock import patch

from experiments import package_gcc12_candidate as helper


class Gcc12PackagingWrapperTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='yk-gcc12-wrapper-test-', dir='/tmp')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.args = argparse.Namespace(**{name: self.root / name for name in helper.PATHS}, cpu_seed_start=8800)
        self.env = dict(os.environ)
        self.handlers = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}

    @contextmanager
    def toolchain(self, report):
        work = self.root / 'toolchain-tmp'
        work.mkdir()
        report['temporary_directory'] = str(work)
        try:
            yield {'compiler_wrapper': str(work / 'compiler'),
                   'env': {'PATH': self.env.get('PATH', ''), 'YK_WRAPPER_TEST': 'clean', 'TMPDIR': str(work)}}
        finally:
            work.rmdir()
            report['temporary_directory_removed'] = not work.exists()

    def invoke(self, packaging):
        with patch.object(helper.package, 'check_gates', return_value=('candidate', {}, {}, 0)), \
             patch.object(helper, 'gcc12_toolchain', self.toolchain), \
             patch.object(helper.package, 'run', side_effect=packaging):
            return helper.run(self.args)

    def assert_restored(self):
        self.assertEqual(dict(os.environ), self.env)
        self.assertEqual({sig: signal.getsignal(sig) for sig in self.handlers}, self.handlers)
        self.assertFalse((self.root / 'toolchain-tmp').exists())

    def test_signal_during_package_restores_environment_handlers_and_records_failure(self):
        def interrupted(args):
            self.assertEqual(os.environ.get('YK_WRAPPER_TEST'), 'clean')
            self.assertNotIn('HOME', os.environ)
            self.assertTrue(Path(args.compiler).parent.exists())
            signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)

        result = self.invoke(interrupted)
        self.assertEqual(result['status'], 'failed')
        self.assertIn('InterruptedError', result['error'])
        self.assertTrue(result['toolchain']['temporary_directory_removed'])
        self.assertEqual(json.loads(self.args.compiler_record.read_text()), result)
        self.assert_restored()

    def test_success_records_only_after_context_cleanup_and_restores_environment(self):
        def completed(args):
            self.assertTrue(Path(args.compiler).parent.exists())
            self.assertTrue(all(getattr(args, name).is_absolute() for name in helper.PATHS))
            os.environ['YK_WRAPPER_TEST'] = 'changed-by-package'
            return {'status': 'validated', 'tmp_cleanup': {'exists': False}, 'cpu_matches': 4, 'sdk_smoke_matches': 1}

        result = self.invoke(completed)
        self.assertEqual(result['status'], 'passed')
        self.assertTrue(result['toolchain']['temporary_directory_removed'])
        self.assertTrue(result['environment_restored'] and result['signal_handlers_restored'])
        self.assert_restored()

    def test_existing_record_and_overlapping_paths_are_protected_before_work(self):
        self.args.compiler_record.write_text('preserve this')
        with self.assertRaises(ValueError), patch.object(helper.package, 'check_gates') as gate:
            helper.run(self.args)
        gate.assert_not_called()
        self.assertEqual(self.args.compiler_record.read_text(), 'preserve this')
        self.args.compiler_record = self.args.record_output / 'compiler.json'
        with self.assertRaises(ValueError):
            helper.run(self.args)
        self.assertFalse(self.args.record_output.exists())
        self.assert_restored()

    def test_cleanup_failure_cannot_report_success(self):
        @contextmanager
        def failed_cleanup(report):
            with self.toolchain(report) as toolchain:
                yield toolchain
            report['temporary_directory_removed'] = False

        with patch.object(helper.package, 'check_gates', return_value=('candidate', {}, {}, 0)), \
             patch.object(helper, 'gcc12_toolchain', failed_cleanup), \
             patch.object(helper.package, 'run', return_value={'status': 'validated', 'tmp_cleanup': {'exists': False}}):
            result = helper.run(self.args)
        self.assertEqual(result['status'], 'failed')
        self.assertIn('cleanup', result['error'])
        self.assert_restored()


if __name__ == '__main__':
    unittest.main()
