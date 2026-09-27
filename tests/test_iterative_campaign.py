import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'experiments'))
import local_league as league
import iterative_campaign as campaign
sys.path.insert(0, str(ROOT / 'yk-development-tools'))
from engine.config import load_config
from runner.bots import InProcessBot
from runner.match import run_match


class IterativeCampaignTests(unittest.TestCase):
    def test_duplicate_code_is_one_candidate_without_changing_original_ids(self):
        population = [{'id': 'v2', 'source': 'baseline'}, {'id': 'one', 'source': 'changed'},
                      {'id': 'alias', 'source': 'changed'}, {'id': 'old', 'source': 'unused'}]
        chosen, aliases = league.filter_population(population, {
            'include_ids': ['v2', 'one', 'alias'], 'deduplicate': True})
        self.assertEqual([x['id'] for x in chosen], ['v2', 'one'])
        self.assertEqual(aliases, {'alias': 'one'})
        self.assertEqual(len(population), 4)
        chosen, _ = league.filter_population(population, {
            'include_ids': ['v2'], 'include_prefixes': ['one'], 'deduplicate': True})
        self.assertEqual([x['id'] for x in chosen], ['v2', 'one'])
        with self.assertRaises(ValueError):
            league.filter_population(population, {'include_ids': ['typo']})

    def test_concentration_uses_actual_spawn_and_late_frames(self):
        def spawn(view, init):
            return ['SPAWN W 100']
        replay, _ = run_match(7019, load_config(), InProcessBot(spawn),
                              InProcessBot(lambda v, i: []), max_turns=125)
        stats = league.diagnostics(replay)
        self.assertEqual(stats['Y']['late_frames'], 5)
        self.assertEqual(stats['Y']['late_w_concentration_mean'], 1)
        self.assertGreater(stats['Y']['late_largest_w_stack'], 0)
        self.assertEqual(stats['K']['late_w_concentration_mean'], 0)

    def test_promotion_rejects_aggregate_gain_with_large_opponent_regression(self):
        rows = []
        for seed in range(20):
            for opponent in campaign.OPPONENTS:
                for name in ['v2', 'candidate']:
                    win = (name == 'v2') if opponent == 'teammate' else (name != 'v2')
                    rows.append({'candidate': name, 'opponent': opponent, 'map_seed': seed,
                                 'team': 'Y', 'status': 'complete', 'win': win, 'draw': False})
        summary = {'by_candidate': {name: {'errors': 0, 'forfeits': 0} for name in ['v2', 'candidate']}}
        result = campaign.promotion(rows, summary, 'candidate')
        self.assertTrue(result['gates']['Y_gain_at_least_3pp'])
        self.assertTrue(result['gates']['map_cluster_lower_bound_positive'])
        self.assertFalse(result['gates']['no_opponent_Y_regression_over_10pp'])
        self.assertFalse(result['promoted'])

    def test_forfeit_blocks_otherwise_better_candidate(self):
        rows = [{'candidate': name, 'opponent': op, 'map_seed': seed, 'team': 'Y',
                 'status': 'complete', 'win': name == 'candidate', 'draw': False}
                for name in ['v2', 'candidate'] for op in campaign.OPPONENTS for seed in range(4)]
        summary = {'by_candidate': {name: {'errors': 0, 'forfeits': int(name == 'candidate')}
                                    for name in ['v2', 'candidate']}}
        result = campaign.promotion(rows, summary, 'candidate')
        self.assertFalse(result['promoted'])
        self.assertFalse(result['gates']['no_error_or_forfeit'])


if __name__ == '__main__':
    unittest.main()
