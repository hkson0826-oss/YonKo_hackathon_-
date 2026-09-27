import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("cpu_sweep", ROOT / "experiments/cpu_sweep.py")
sweep = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sweep)


class CpuSweepTests(unittest.TestCase):
    def setUp(self):
        self.config = sweep.normalize_config(json.loads((ROOT / "experiments/cpu_sweep_example.json").read_text()))

    def test_baseline_is_exact_original_and_edits_are_guarded(self):
        source = (ROOT / "submissions/tuned/main.cpp").read_text()
        self.assertEqual(sweep.render_candidate(source, {}), source)
        modified = sweep.render_candidate(source, {"eng_bonus": 140})
        self.assertEqual(modified, source.replace("bonus += 110;", "bonus += 140;"))
        with self.assertRaises(ValueError):
            sweep.render_candidate(source + "\nif (has(s,team,ENG)) bonus += 110;", {})
        with self.assertRaises(ValueError):
            sweep.render_candidate(source, {"army_weight": float("nan")})

    def test_cartesian_jobs_and_duplicate_input_guard(self):
        jobs = sweep.make_jobs(self.config)
        self.assertEqual(len(jobs), 8)
        self.assertEqual(len({job["job_id"] for job in jobs}), 8)
        self.config["map_seeds"].append(self.config["map_seeds"][0])
        with self.assertRaises(ValueError):
            sweep.normalize_config(self.config)

    def test_resume_rejects_changed_sources_or_configuration(self):
        expected = sweep.identity(self.config, {"source.cpp": "original"})
        manifest = {"identity": expected, "identity_sha256": sweep.json_hash(expected)}
        sweep.check_resume_identity(manifest, expected)
        with self.assertRaises(ValueError):
            sweep.check_resume_identity(manifest, sweep.identity(self.config, {"source.cpp": "changed"}))
        changed = json.loads(json.dumps(self.config))
        changed["map_seeds"].append(1)
        with self.assertRaises(ValueError):
            sweep.check_resume_identity(manifest, sweep.identity(changed, {"source.cpp": "original"}))

    def test_source_manifest_uses_each_bot_original_headers(self):
        self.config["opponents"] = ["v1", "v2"]
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            contents = {
                "experiments/cpu_sweep.py": "script",
                "submissions/tuned/main.cpp": "tuned source",
                "submissions/tuned/protocol.hpp": "tuned protocol",
                "submissions/tuned/generated.hpp": "tuned generated",
                "submissions/first/main.cpp": "first source",
                "submissions/first/protocol.hpp": "first protocol",
                "submissions/first/generated.hpp": "first generated",
                "yk-cpp-sample/protocol.hpp": "different sample protocol",
            }
            for relative, content in contents.items():
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content)
            with patch.object(sweep, "ROOT", root):
                inputs = sweep.source_inputs(self.config)
                self.assertEqual(inputs["submissions/tuned/protocol.hpp"], sweep.digest(b"tuned protocol"))
                self.assertEqual(inputs["submissions/first/protocol.hpp"], sweep.digest(b"first protocol"))
                self.assertNotIn("yk-cpp-sample/protocol.hpp", inputs)
                (root / "submissions/first/generated.hpp").write_text("new first generated")
                self.assertNotEqual(inputs, sweep.source_inputs(self.config))

    def test_resume_archives_unfinished_tail_and_rejects_duplicates(self):
        jobs = sweep.make_jobs(self.config)
        row = {**jobs[0], "status": "complete"}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "results.jsonl"
            line = json.dumps(row) + "\n"
            path.write_text(line + '{"partial":')
            self.assertEqual(sweep.load_completed(path, jobs), [row])
            self.assertEqual(path.read_text(), line)
            self.assertEqual(len(list(Path(folder).glob("*.unfinished-*"))), 1)
            path.write_text(line + line)
            with self.assertRaisesRegex(ValueError, "Duplicate"):
                sweep.load_completed(path, jobs)
            path.write_text(line + '{"broken":\n')
            with self.assertRaises(json.JSONDecodeError):
                sweep.load_completed(path, jobs)

    def test_summary_separates_engine_errors_from_match_losses(self):
        jobs = sweep.make_jobs(self.config)
        rows = [{**jobs[0], "status": "complete", "win": True, "draw": False,
                 "forfeit": False, "score_margin": 9, "max_turn_ms": 10, "opponent_max_turn_ms": 5},
                {**jobs[1], "status": "error", "error": "test infrastructure failure"}]
        summary = sweep.summarize(rows, jobs)
        self.assertEqual(summary["overall"]["matches"], 1)
        self.assertEqual(summary["overall"]["losses"], 0)
        self.assertEqual(summary["overall"]["errors"], 1)


if __name__ == "__main__":
    unittest.main()
