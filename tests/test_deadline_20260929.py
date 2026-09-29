import argparse
import importlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'experiments'))
deadline = importlib.import_module('deadline_20260929')


class DeadlineTests(unittest.TestCase):
    def test_names_reject_blank_duplicate_and_trailing_separator(self):
        for value in ('', 'v4,v4', 'v4,'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                deadline.csv(value)
        self.assertEqual(deadline.csv('v4,v7'), ['v4', 'v7'])

    def test_pairing_uses_selected_baseline_and_keeps_sides_separate(self):
        rows = []
        for seed in (1, 2):
            for side in 'YK':
                for name in ('sitev7', 'new'):
                    rows.append({'candidate': name, 'map_seed': seed, 'team': side,
                                 'opponent': 'fixed', 'status': 'complete',
                                 'win': name == 'new' and side == 'Y', 'draw': False})
        rows.append({'candidate': 'new', 'map_seed': 999, 'team': 'Y',
                     'opponent': 'unpaired', 'status': 'error'})
        comparison = deadline.compare(rows, 'sitev7', ['sitev7', 'new'])['comparisons']['new']
        self.assertEqual(comparison['Y']['paired_maps'], 2)
        self.assertEqual(comparison['Y']['point_rate_difference'], 1)
        self.assertEqual(comparison['K']['point_rate_difference'], 0)
        self.assertEqual(comparison['Y']['map_cluster_bootstrap_95pct'], [1, 1])

    def test_resume_cannot_relabel_prior_development_as_final(self):
        with tempfile.TemporaryDirectory() as tmp:
            arena = Path(tmp)
            plans = arena / 'plans'
            plans.mkdir()
            manifest = {'source_commit': 'frozen', 'policy_rng_seed': 20260927,
                        'bots': {'v4': {'source_sha256': 'a'}, 'new': {'source_sha256': 'b'}}}
            (arena / 'manifest.json').write_text(json.dumps(manifest))
            plan = {'candidates': ['v4', 'new'], 'opponents': ['v4'], 'map_seeds': [1],
                    'replays': 'all', 'order_seed': 20260929}
            (plans / 'run.json').write_text(json.dumps(plan))
            (plans / 'run-policy.json').write_text(json.dumps({'stage': 'development'}))
            args = argparse.Namespace(arena=arena, candidates='v4,new', opponents='v4', baseline='v4',
                                      maps=1, workers=1, seed_start=1, run_id='run', stage='final',
                                      hypothesis='same', resume=True)
            with patch.object(deadline.league, 'run') as runner:
                with self.assertRaisesRegex(ValueError, 'Resume policy mismatch: stage'):
                    deadline.run(args)
                runner.assert_not_called()


if __name__ == '__main__':
    unittest.main()
