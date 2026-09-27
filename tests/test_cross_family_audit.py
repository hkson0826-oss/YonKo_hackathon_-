from __future__ import annotations

from pathlib import Path
import argparse
import contextlib
import io
import json
import tempfile
import resource
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments"))
import cross_family_audit as audit
import local_league as league


class CrossFamilyAuditTests(unittest.TestCase):
    candidate = "a_local_unabstracted"

    def rows(self):
        plan = audit.make_plan(self.candidate)
        bots = dict.fromkeys([*plan["candidates"], *plan["opponents"]])
        return [{**job, "status": "complete", "win": True, "draw": False, "forfeit": False}
                for job in league.make_jobs(plan, bots)]

    def test_schedule_preserves_768_games_and_symmetric_self_opponent(self):
        rows = self.rows()
        self.assertEqual(len(rows), 768)
        self.assertEqual(len({row["job_id"] for row in rows}), 768)
        for name in ("v2", self.candidate):
            for side in "YK":
                selected = [row for row in rows if row["candidate"] == name and row["opponent"] == self.candidate and row["team"] == side]
                self.assertEqual(len(selected), 32)
        self.assertEqual(audit.MAP_SEEDS[0], 7500)
        self.assertEqual(audit.MAP_SEEDS[-1], 7531)

    def test_gate_accepts_ties_and_inclusive_four_of_32_opponent_regression(self):
        rows = self.rows()
        for row in rows:
            if row["team"] != "Y" or row["map_seed"] >= 7504:
                continue
            if (row["candidate"], row["opponent"]) in ((self.candidate, audit.OPPONENTS[0]), ("v2", audit.OPPONENTS[1])):
                row["win"] = False
        result = audit.audit_result(rows, self.candidate)
        self.assertTrue(result["passes_additional_gate"])
        self.assertEqual(result["comparisons"]["Y"]["point_rate_difference"], 0)
        self.assertEqual(result["opponent_Y_comparisons"][audit.OPPONENTS[0]]["point_rate_difference"], -.125)

    def test_gate_rejects_fifth_regression_even_if_overall_tied(self):
        rows = self.rows()
        for row in rows:
            if row["team"] != "Y" or row["map_seed"] >= 7505:
                continue
            if (row["candidate"], row["opponent"]) in ((self.candidate, audit.OPPONENTS[0]), ("v2", audit.OPPONENTS[1])):
                row["win"] = False
        result = audit.audit_result(rows, self.candidate)
        self.assertTrue(result["gates"]["no_overall_Y_regression"])
        self.assertFalse(result["gates"]["no_opponent_Y_regression_worse_than_12_5pp"])
        self.assertFalse(result["passes_additional_gate"])

    def test_missing_duplicate_error_and_forfeit_cannot_pass(self):
        original = self.rows()
        variants = [original[:-1], [*original, original[0]],
                    [{**original[0], "status": "error"}, *original[1:]],
                    [{**original[0], "forfeit": True}, *original[1:]]]
        for rows in variants:
            self.assertFalse(audit.audit_result(rows, self.candidate)["passes_additional_gate"])

    def test_compile_precedes_memory_cap_and_run_writes_complete_audit(self):
        events = []
        previous = (768 * 1024 * 1024, 768 * 1024 * 1024)
        def prepare(arena, spec):
            events.append("prepare")
            arena.mkdir()
            self.assertEqual(spec["revision"], 2)
            bots = {name: {"source_sha256": "test-only"} for name in ["v2", self.candidate, *audit.OPPONENTS]}
            league.write(arena / "manifest.json", {"bots": bots, "source_commit": "mock-test"})
        def limit(kind, values):
            events.append("cap" if values[0] == audit.ADDRESS_SPACE_BYTES else "restore")
        def run(arena, plan_path, run_id, workers, resume):
            events.append("run")
            self.assertEqual(events[:3], ["prepare", "cap", "run"])
            self.assertEqual(json.loads(plan_path.read_text())["replays"], "all")
            folder = arena / "runs" / run_id
            folder.mkdir(parents=True)
            (folder / "results.jsonl").write_text("".join(json.dumps(row) + "\n" for row in self.rows()))
        with tempfile.TemporaryDirectory(prefix="yk-audit-test-") as directory:
            args = argparse.Namespace(arena=Path(directory) / "audit", candidate=self.candidate, workers=1, selection_lock=None,
                                      selection_lock_json=json.dumps({"primary_candidate": self.candidate}))
            with patch.object(audit.league, "prepare", side_effect=prepare), patch.object(audit.league, "run", side_effect=run), \
                    patch.object(audit.resource, "getrlimit", return_value=previous), patch.object(audit.resource, "setrlimit", side_effect=limit), \
                    contextlib.redirect_stdout(io.StringIO()):
                result = audit.campaign(args)
            self.assertEqual(events, ["prepare", "cap", "run", "restore"])
            self.assertTrue(result["passes_additional_gate"])
            self.assertEqual(result["selection_lock_verification"], "inline JSON verified")
            compatibility = json.loads((args.arena / "campaign-result.json").read_text())
            self.assertEqual(compatibility["phase"], "audit")
            self.assertEqual(compatibility["stage_match_counts"], {"audit": 768})
            self.assertEqual(compatibility["recommended"], self.candidate)
            self.assertEqual(json.loads((args.arena / "audit-result.json").read_text())["resource_limit"]["effective_soft_bytes"], audit.ADDRESS_SPACE_BYTES)

    def test_inline_selection_lock_mismatch_is_rejected_before_prepare(self):
        args = argparse.Namespace(arena=Path("/tmp/unused-audit-test"), candidate=self.candidate, workers=1,
                                  selection_lock=None, selection_lock_json=json.dumps({"primary_candidate": "another_candidate"}))
        with patch.object(audit.league, "prepare") as prepare:
            with self.assertRaisesRegex(ValueError, "first locked"):
                audit.campaign(args)
            prepare.assert_not_called()

    def test_memory_cap_is_inherited_soft_only_and_restored(self):
        previous = (768 * 1024 * 1024, 768 * 1024 * 1024)
        with patch.object(audit.resource, "getrlimit", return_value=previous), patch.object(audit.resource, "setrlimit") as setter:
            with audit.submission_address_space() as cap:
                self.assertEqual(cap["effective_soft_bytes"], 384 * 1024 * 1024)
                setter.assert_called_once_with(resource.RLIMIT_AS, (384 * 1024 * 1024, previous[1]))
            self.assertEqual(setter.call_args.args, (resource.RLIMIT_AS, previous))
        previous = (256 * 1024 * 1024, resource.RLIM_INFINITY)
        with patch.object(audit.resource, "getrlimit", return_value=previous), patch.object(audit.resource, "setrlimit"):
            with audit.submission_address_space() as cap:
                self.assertEqual(cap["effective_soft_bytes"], previous[0])


if __name__ == "__main__":
    unittest.main()
