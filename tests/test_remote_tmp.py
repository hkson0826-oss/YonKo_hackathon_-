from __future__ import annotations

import base64
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "experiments/run_remote_tmp.py"
SPEC = importlib.util.spec_from_file_location("remote_tmp", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class RemoteTmpTests(unittest.TestCase):
    def test_rejects_traversal_links_and_large_files(self):
        for name, kind, maximum in (("../escape", tarfile.REGTYPE, 100),
                                    ("/absolute", tarfile.REGTYPE, 100),
                                    ("link", tarfile.SYMTYPE, 100),
                                    ("large", tarfile.REGTYPE, 0)):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                archive = Path(directory) / "bad.tar.gz"
                with tarfile.open(archive, "w:gz") as stream:
                    info = tarfile.TarInfo(name)
                    info.type = kind
                    if kind == tarfile.REGTYPE:
                        info.size = 1
                        stream.addfile(info, io.BytesIO(b"x"))
                    else:
                        info.linkname = "/etc/passwd"
                        stream.addfile(info)
                with self.assertRaises(ValueError):
                    MODULE.safe_extract(archive, Path(directory) / "out", max_bytes=maximum)

    def test_limits_use_actual_affinity_and_conservative_worker_bound(self):
        limits = MODULE.compute_limits(range(52), 435 * 1024**3, 16)
        self.assertEqual(len(limits["affinity"]), 46)
        self.assertLessEqual(limits["cpu_fraction"], .9)
        self.assertEqual(limits["expected_process_count_bound"], 88)
        self.assertLess(limits["expected_address_space_bound_bytes"], limits["memory_budget_bytes"])
        self.assertEqual(MODULE.compute_limits({2, 7, 9, 12}, 32 * 1024**3, 1)["affinity"], [2, 7, 9])
        with self.assertRaises(ValueError):
            MODULE.compute_limits(range(52), 4 * 1024**3, 16)
        with self.assertRaises(ValueError):
            MODULE.compute_limits(range(52), 435 * 1024**3, 47)
        with self.assertRaises(ValueError):
            MODULE.compute_limits([0], 435 * 1024**3, 1)
        self.assertEqual(MODULE.command_workers(["python3", "run.py", "--workers=16"]), 16)

    def test_source_allowlist_excludes_credentials_git_and_binaries(self):
        paths = MODULE.source_files(ROOT)
        self.assertIn(Path("yk-development-tools/bots/dist/starter/python/campus_bot.py"), paths)
        self.assertIn(Path("submissions/delineate-v1.zip"), paths)
        self.assertFalse(any(".git" in p.parts or "AGENTS.md" in p.parts or p.suffix == ".so" for p in paths))

    def run_local_bootstrap(self, directory, code, timeout=10):
        directory = Path(directory)
        source = directory / "source.tar.gz"
        with tarfile.open(source, "w:gz"):
            pass
        config = {"command": [sys.executable, "-c", code], "remote_output": "output", "process_mib": 256,
                  "wall_seconds": timeout, "source_commit": "test-frozen", "input_sha256": {}}
        encoded = base64.b64encode(json.dumps(config).encode()).decode()
        output = directory / "received"
        with contextlib.redirect_stderr(io.StringIO()):
            result = MODULE.run_transport([sys.executable, str(SCRIPT), "--bootstrap", encoded], config, source, output)
        events = [json.loads(line) for line in (output / "transport.jsonl").read_text().splitlines()]
        return result, output, events

    @unittest.skipUnless(hasattr(os, "sched_getaffinity") and len(os.sched_getaffinity(0)) > 1, "Linux multi-CPU required")
    def test_local_bootstrap_roundtrip_verifies_archive_then_cleans_tmp(self):
        code = """import json, os, pathlib, resource
p=pathlib.Path('output');p.mkdir()
(p/'report.json').write_text(json.dumps({'tmp':os.environ['TMPDIR'],'home':os.environ['HOME'],
 'affinity':sorted(os.sched_getaffinity(0)),'source':os.environ['YK_SOURCE_COMMIT'],
 'no_bytecode':os.environ['PYTHONDONTWRITEBYTECODE'],'as_limit':resource.getrlimit(resource.RLIMIT_AS)[0]}))
(p/'bin').mkdir();(p/'bin'/'bot').write_bytes(b'compiled')
(p/'unknown_executable').write_bytes(b'\\x7fELFmore')
print('finished test')
"""
        with tempfile.TemporaryDirectory() as directory:
            code_result, output, events = self.run_local_bootstrap(directory, code)
            self.assertEqual(code_result, 0)
            report = json.loads((output / "report.json").read_text())
            self.assertEqual(report["home"], os.environ["HOME"])
            self.assertEqual(report["source"], "test-frozen")
            self.assertEqual(report["no_bytecode"], "1")
            self.assertEqual(report["as_limit"], 256 * 1024**2)
            self.assertLessEqual(len(report["affinity"]), len(os.sched_getaffinity(0)) * .9)
            self.assertFalse(Path(report["tmp"]).exists())
            self.assertFalse((output / "bin").exists())
            self.assertFalse((output / "unknown_executable").exists())
            kinds = [event["event"] for event in events]
            self.assertLess(kinds.index("archive_ready"), kinds.index("archive_acknowledgement"))
            self.assertLess(kinds.index("archive_acknowledgement"), kinds.index("cleanup_complete"))
            self.assertFalse(events[-1]["exists"])

    @unittest.skipUnless(hasattr(os, "sched_getaffinity") and len(os.sched_getaffinity(0)) > 1, "Linux multi-CPU required")
    def test_timeout_recovers_partial_output_and_reaps_descendants(self):
        code = """import pathlib, subprocess, sys, time
p=pathlib.Path('output');p.mkdir()
child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'])
(p/'child_pid').write_text(str(child.pid))
time.sleep(60)
"""
        with tempfile.TemporaryDirectory() as directory:
            result, output, events = self.run_local_bootstrap(directory, code, timeout=.5)
            self.assertNotEqual(result, 0)
            metadata = json.loads((output / "remote_supervisor.json").read_text())
            self.assertEqual(metadata["stop_reason"], "wall_timeout")
            child_pid = int((output / "child_pid").read_text())
            with self.assertRaises(ProcessLookupError):
                os.kill(child_pid, 0)
            self.assertTrue(events[-1]["archive_accepted"])
            self.assertFalse(events[-1]["exists"])

    @unittest.skipUnless(hasattr(os, "sched_getaffinity") and len(os.sched_getaffinity(0)) > 1, "Linux multi-CPU required")
    def test_closed_controller_stdin_cancels_work_and_cleans_tmp(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.tar.gz"
            with tarfile.open(source, "w:gz"):
                pass
            config = {"command": [sys.executable, "-c", "import time;time.sleep(60)"],
                      "remote_output": "output", "process_mib": 256, "wall_seconds": 60}
            encoded = base64.b64encode(json.dumps(config).encode()).decode()
            process = subprocess.Popen([sys.executable, str(SCRIPT), "--bootstrap", encoded],
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            MODULE.send_archive(process.stdin, source)
            process.stdin.close();process.stdin = None
            stdout, stderr = process.communicate(timeout=10)
            events = [json.loads(line) for line in stderr.decode().splitlines()]
            cleanup = events[-1]
            self.assertEqual(cleanup["event"], "cleanup_complete")
            self.assertFalse(cleanup["exists"])
            self.assertFalse(cleanup["archive_accepted"])
            self.assertNotEqual(process.returncode, 0)
            self.assertEqual(stdout, b"")


if __name__ == "__main__":
    unittest.main()
