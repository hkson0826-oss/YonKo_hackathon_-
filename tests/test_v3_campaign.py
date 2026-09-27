import argparse
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'experiments'))
import v3_campaign as campaign
import v3_audit as audit


def rows_for(opponents):
    return [{'candidate': name, 'opponent': op, 'map_seed': seed, 'team': side,
             'status': 'complete', 'win': name == 'new', 'draw': False, 'forfeit': False,
             'score_margin': 10 if name == 'new' else -10}
            for name in ['v3', 'new'] for op in opponents for seed in range(8400, 8404) for side in 'YK']


class V3CampaignTests(unittest.TestCase):
    def test_paired_baseline_is_v3_not_obsolete_v2(self):
        rows = rows_for(['v3'])
        rows += [{**r, 'candidate': 'v2', 'win': True} for r in rows if r['candidate'] == 'v3']
        self.assertEqual(campaign.paired(rows, 'new')['point_rate_difference'], 1)

    def test_full_improvement_passes_but_missing_pair_blocks(self):
        ops = [*campaign.FIXED_OPPONENTS, 'challenger_one', 'challenger_two']
        rows = rows_for(ops)
        passed = campaign.promotion(rows, 'new', ops, range(8400, 8404))
        self.assertTrue(passed['promoted'], passed['gates'])
        self.assertFalse(campaign.promotion(rows[:-1], 'new', ops, range(8400, 8404))['promoted'])
        self.assertFalse(campaign.promotion([*rows, rows[0]], 'new', ops, range(8400, 8404))['promoted'])

    def test_opponent_regression_and_forfeit_cannot_hide_in_average(self):
        ops = [*campaign.FIXED_OPPONENTS, 'challenger_one', 'challenger_two']
        rows = rows_for(ops)
        for r in rows:
            if r['opponent'] == 'teammate':
                r['win'] = r['candidate'] == 'v3'
        decision = campaign.promotion(rows, 'new', ops, range(8400, 8404))
        self.assertTrue(decision['gates']['Y_gain_at_least_3pp'])
        self.assertFalse(decision['gates']['no_opponent_Y_regression_over_10pp'])
        self.assertFalse(decision['promoted'])
        rows = rows_for(ops)
        rows[0]['forfeit'] = True
        self.assertFalse(campaign.promotion(rows, 'new', ops, range(8400, 8404))['promoted'])

    def test_strengthened_opponents_do_not_replace_fixed_pool_gate(self):
        ops = [*campaign.FIXED_OPPONENTS, 'challenger_one', 'challenger_two']
        rows = rows_for(ops)
        for r in rows:
            if r['opponent'] in campaign.FIXED_OPPONENTS:
                r['win'] = False
                r['draw'] = True
        result = campaign.promotion(rows, 'new', ops, range(8400, 8404))
        self.assertTrue(result['gates']['Y_gain_at_least_3pp'])
        self.assertFalse(result['gates']['fixed_pool_Y_gain_at_least_3pp'])
        self.assertFalse(result['promoted'])

    def test_exploiter_diversity_and_error_exclusion(self):
        names = ['s3_one', 's3_two', 'r3_one', 'f3_broken']
        bots = {name: {'source_sha256': name} for name in names}
        rows = []
        for name in names:
            for seed in range(4):
                rows.append({'candidate': name, 'opponent': 'v3', 'map_seed': seed,
                             'team': 'Y', 'status': 'complete', 'win': True, 'draw': False,
                             'forfeit': name == 'f3_broken', 'score_margin': 10 if name.startswith('s3') else 5})
        chosen = campaign.challenge_selection(rows, bots, names)
        self.assertEqual(chosen['opponents'], ['s3_one', 'r3_one'])

    def test_post_holdout_forfeit_blocks_delivery_even_as_opponent(self):
        rows = [{'candidate': 'challenger', 'opponent': 'new', 'status': 'complete', 'forfeit': False}]
        self.assertTrue(campaign.runtime_health(rows, 'new'))
        rows[0]['forfeit'] = True
        self.assertFalse(campaign.runtime_health(rows, 'new'))

    def test_additional_audit_cannot_ignore_unexpected_or_missing_games(self):
        ops = [*campaign.FIXED_OPPONENTS, 'challenger_one', 'challenger_two']
        rows = [{**r, 'map_seed': seed} for r in rows_for(ops) if r['map_seed'] == 8400 for seed in audit.MAPS]
        self.assertTrue(audit.audit_result(rows, 'new', ops)['passes_additional_gate'])
        unexpected = {**rows[0], 'candidate': 'unexpected'}
        self.assertFalse(audit.audit_result([*rows, unexpected], 'new', ops)['passes_additional_gate'])
        self.assertFalse(audit.audit_result(rows[:-1], 'new', ops)['passes_additional_gate'])

    def test_first_revision_does_not_import_second_revision(self):
        spec = campaign.population_spec(1, None, [])
        self.assertEqual(spec['revision'], 2)
        self.assertTrue(all(value == 1 for value in spec['module_revisions'].values()))
        self.assertEqual(spec['module_sources']['v3_action_search'], campaign.SOURCE)

    def test_overlapping_or_reused_seeds_rejected(self):
        args = argparse.Namespace(seed_start=8100, maps=8, phase='final', selection_start=8300,
                                  selection_maps=24, holdout_start=8400, holdout_maps=80)
        self.assertEqual(len(campaign.seed_ranges(args)['holdout']), 80)
        args.holdout_start = 8301
        with self.assertRaises(ValueError):
            campaign.seed_ranges(args)
        args.phase = 'explore'
        args.seed_start = 7501
        with self.assertRaises(ValueError):
            campaign.seed_ranges(args)


if __name__ == '__main__':
    unittest.main()
