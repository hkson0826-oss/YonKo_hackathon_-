import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("official_analysis", ROOT / "experiments/analyze_official_round1.py")
analysis = importlib.util.module_from_spec(spec)
spec.loader.exec_module(analysis)


class OfficialReplayAnalysisTests(unittest.TestCase):
    def test_symmetric_inference_does_not_use_later_knowledge(self):
        buildings = [{"id": 1, "x": 4, "y": 2, "owner": "Y"},
                     {"id": 2, "x": 10, "y": 12, "owner": "K"}]
        self.assertEqual(analysis.mirrored_scores(buildings, {}), {})
        self.assertIsNone(analysis.score_totals(buildings, {})["K"])
        self.assertEqual(analysis.mirrored_scores(buildings, {1: 2}), {1: 2, 2: 2})

    def test_all_recorded_transitions_and_source_hashes(self):
        manifest = json.loads((ROOT / "records/official/round1/source-manifest.json").read_text())
        checked = 0
        outcomes = []
        for entry in manifest["files"]:
            path = ROOT / entry["path"]
            self.assertEqual(analysis.digest(path), entry["sha256"])
            result = analysis.analyze(path)["summary"]
            checked += result["own_spawn_move_transitions_checked"]
            outcomes.append(result["our_result"])
            self.assertEqual(result["command_status_counts"], {"ok": result["turn_count"]})
        self.assertEqual(checked, 483)
        self.assertEqual(outcomes.count("loss"), 1)

    def test_loss_production_balance_is_not_mislabelled_combat_inefficiency(self):
        s = analysis.analyze(ROOT / "artifacts/firstround_results/replay (3).json")["summary"]
        self.assertEqual(s["our_production"]["W"], 698)
        self.assertEqual(s["enemy_w_production_inferred_from_equal_w_losses"], 758)
        self.assertEqual(s["our_casualties"]["W"], 637)
        self.assertEqual(s["final_scores_reconstructed"], {"Y": 11, "K": 28, "N": 4})
        self.assertEqual(s["final_occupation_reconstructed"], {"Y": 2980, "K": 2852})

    def test_equal_warriors_require_flag_contest_to_hold_building(self):
        result = analysis.watch_defense_probe(ROOT / "artifacts/firstround_results/replay (3).json")
        owners = {key: value["watch_owner"] for key, value in result["outcomes"].items()}
        self.assertEqual(owners, {"recorded_local_own_action": "N", "hold_three_warriors_only": "N",
                                 "hold_warriors_and_contest_with_adjacent_flag": "Y"})


if __name__ == "__main__":
    unittest.main()
