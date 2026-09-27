import ctypes as C
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("gpu_probe", ROOT / "experiments/gpu_probe/run_probe.py")
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class GPUProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="yk-gpu-probe-test-")
        cls.library, _ = probe.compile_cpu(Path(cls.temporary.name))

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_all_observations_match_unmodified_v2_evaluator(self):
        values = [state for path in sorted((ROOT / "artifacts/firstround_results").glob("*.json"))
                  for state in probe.legal_positions(path)]
        self.assertGreater(len(values), 400)
        positions = (probe.Position * len(values))(*values)
        baseline = (probe.Parameters * 1)(probe.Parameters(110, 35, 1.3))
        expected, actual = (C.c_double * len(values))(), (C.c_double * len(values))()
        self.library.probe_original(positions, len(values), expected)
        self.library.probe_cpu(positions, len(values), baseline, 1, actual, len(values), 1)
        self.assertLessEqual(probe.finite_max_difference(expected, actual), 1e-8)

    def test_parity_rejects_nan_infinity_and_overflow(self):
        for value in (float("nan"), float("inf"), float("-inf")):
            for index in range(3):
                bad = [1.0, 2.0, 3.0]
                bad[index] = value
                for expected, actual in ((bad, [1.0, 2.0, 3.0]), ([1.0, 2.0, 3.0], bad), (bad, bad)):
                    with self.subTest(value=value, index=index, expected=expected, actual=actual):
                        with self.assertRaises(ValueError):
                            probe.finite_max_difference(expected, actual)
        with self.assertRaises(ValueError):
            probe.finite_max_difference([1e308], [-1e308])
        self.assertEqual(probe.finite_max_difference([1.0, 2.0], [1.25, 2.0]), .25)

    def test_later_revealed_scores_cannot_change_earlier_input(self):
        path = ROOT / "artifacts/firstround_results/replay (3).json"
        original = json.loads(path.read_text())
        for row in original["turns"][10:]:
            for building in row["observation"]["buildings"]:
                building["score"] = 99
        changed_path = Path(self.temporary.name) / "changed.json"
        changed_path.write_text(json.dumps(original))
        earlier = list(probe.legal_positions(path))[:10]
        changed = list(probe.legal_positions(changed_path))[:10]
        self.assertEqual([bytes(s) for s in earlier], [bytes(s) for s in changed])

    def test_parameters_affect_evaluation_and_threads_preserve_values(self):
        state = probe.Position()
        state.nb = 3
        state.turn = 80
        state.owner[0], state.owner[1], state.owner[2] = 0, 1, -1
        state.type[0], state.type[1], state.type[2] = 4, 0, 1
        state.score[0] = state.score[1] = state.score[2] = 2
        state.army_value[0] = 30
        positions = (probe.Position * 1)(state)
        parameters = (probe.Parameters * 2)(probe.Parameters(110, 35, 1.3), probe.Parameters(140, 35, 1.8))
        single, threaded = (C.c_double * 1024)(), (C.c_double * 1024)()
        self.library.probe_cpu(positions, 1, parameters, 2, single, 1024, 1)
        self.library.probe_cpu(positions, 1, parameters, 2, threaded, 1024, 2)
        self.assertEqual(bytes(single), bytes(threaded))
        self.assertAlmostEqual(single[1] - single[0], 45)


if __name__ == "__main__":
    unittest.main()
