import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'experiments'))
SPEC = importlib.util.spec_from_file_location('analyze_v3_campaign', ROOT / 'experiments/analyze_v3_campaign.py')
ANALYZE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ANALYZE)


def write(path, value):
    path.write_text(json.dumps(value))


class V3CampaignAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='yk-v3-analysis-', dir='/tmp')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def fixture(self, *, phase='explore', mutual=False):
        arena = self.root / 'arena'
        arena.mkdir()
        (arena / 'plans').mkdir()
        names = ['v3', 's3_candidate'] + (['s3_runner_up'] if phase == 'final' else [])
        fixed = list(ANALYZE.FIXED_OPPONENTS)
        challenge = ['challenger_one', 'challenger_two'] if phase == 'final' else []
        opponents = fixed + challenge
        bots = {name: {'source_sha256': ANALYZE.SOURCE_SHA if name == 'v3' else name + '-sha',
                       'family': 'fixture', 'parameters': {}} for name in set(names + opponents)}
        write(arena / 'manifest.json', {'bots': bots})
        write(arena / 'campaign-policy.json', {'baseline': 'v3', 'fixed_opponents': fixed, 'opponents': opponents})
        stages = ['smoke', 'development'] + (['selection', 'holdout', 'crossplay'] if phase == 'final' else [])
        totals, errors, forfeits = {}, 0, 0
        for index, stage in enumerate(stages):
            directory = arena / 'runs' / stage
            (directory / 'replays').mkdir(parents=True)
            plan = {'candidates': names, 'opponents': ['v3'] if stage == 'smoke' else opponents,
                    'map_seeds': [8000 + index], 'replays': 'all'}
            write(arena / 'plans' / (stage + '.json'), plan)
            write(directory / 'plan.json', plan)
            jobs = ANALYZE.league.make_jobs(plan, bots)
            write(directory / 'jobs.json', jobs)
            rows = []
            for job in jobs:
                won = lost = False
                if job['opponent'] == 'v2' and job['team'] == 'Y':
                    won = job['candidate'] != 'v3'
                    lost = not won
                if job['opponent'] == 'teammate' and job['team'] == 'K':
                    won = job['candidate'] == 'v3'
                    lost = not won
                forfeit = mutual and stage == 'development' and job['candidate'] == 's3_candidate' and job['opponent'] == 'v3' and job['team'] == 'Y'
                winner = job['team'] if won else ('K' if job['team'] == 'Y' else 'Y') if lost else 'DRAW'
                result = {'winner': winner, 'reason': 'forfeit' if forfeit else 'turn_limit', 'turns': 160}
                if forfeit:
                    result['forfeit'] = {'team': 'both', 'cause': 'Y:timeout,K:timeout'}
                replay = 'replays/' + job['job_id'] + '.json.gz'
                (directory / replay).write_bytes(b'fixture replay; integrity checked by a separate verifier')
                rows.append({**job, 'status': 'complete', 'win': won, 'draw': not won and not lost,
                             'forfeit': forfeit, 'result': result, 'score_margin': 1 if won else -1 if lost else 0,
                             'max_turn_ms': 4, 'opponent_max_turn_ms': 5, 'response_ms': [1, 4],
                             'opponent_response_ms': [2, 5], 'replay': replay, 'diagnostics': {}})
            (directory / 'results.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in rows))
            summary = {'expected_jobs': len(jobs), 'finished_jobs': len(rows), 'overall': ANALYZE.aggregate(rows)}
            write(directory / 'summary.json', summary)
            totals[stage] = len(rows)
            forfeits += summary['overall']['forfeits']
        result = {'status': 'complete', 'phase': phase, 'baseline': 'v3', 'stage_match_counts': totals,
                  'total_matches': sum(totals.values()), 'errors': errors, 'forfeits': forfeits, 'recommended': 'v3'}
        if phase == 'final':
            lock = {'baseline': 'v3', 'primary_candidate': names[1], 'finalists': names[1:],
                    'source_sha256': {name: bots[name]['source_sha256'] for name in names}}
            write(arena / 'locked-finalists.json', lock)
            decisions = {name: {'baseline': 'v3', 'promoted': False, 'gates': {'quality': False, 'health': True}} for name in names[1:]}
            result.update(primary_candidate=names[1], finalists=names[1:], promotion_decisions=decisions)
        write(arena / 'campaign-result.json', result)
        return arena

    def test_both_side_changes_and_runtime_draw_failure(self):
        arena = self.fixture(mutual=True)
        result = ANALYZE.analyze(arena)
        candidate = result['stages']['development']['candidates']['s3_candidate']
        changes = candidate['outcome_changes']
        self.assertEqual([(x['team'], x['opponent']) for x in changes['loss_to_win']], [('Y', 'v2')])
        self.assertEqual([(x['team'], x['opponent']) for x in changes['win_to_loss']], [('K', 'teammate')])
        for item in changes['improvements'] + changes['regressions']:
            self.assertTrue((arena / item['old_replay']).is_file())
            self.assertTrue((arena / item['new_replay']).is_file())
        self.assertEqual(result['overall_health']['mutual_forfeits'], 1)
        self.assertFalse(result['overall_health']['runtime_gate_passed'])
        self.assertEqual(candidate['stats']['Y']['draws'], 5)
        self.assertIsNone(candidate['comparisons']['challenge']['Y'])
        self.assertEqual(candidate['comparisons']['fixed']['Y']['paired_games'], 6)
        self.assertTrue((arena / 'README.md').is_file())

    def test_incomplete_campaign_is_rejected_without_output(self):
        arena = self.fixture()
        path = arena / 'campaign-result.json'
        result = ANALYZE.read(path)
        result['status'] = 'running'
        write(path, result)
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            ANALYZE.analyze(arena)
        self.assertFalse((arena / 'analysis.json').exists())

    def test_missing_or_duplicate_stage_job_is_rejected(self):
        arena = self.fixture()
        path = arena / 'runs/development/results.jsonl'
        lines = path.read_text().splitlines()
        path.write_text('\n'.join(lines[:-1]) + '\n')
        with self.assertRaisesRegex(ValueError, 'incomplete or duplicate'):
            ANALYZE.analyze(arena)
        path.write_text('\n'.join(lines[:-1] + [lines[0]]) + '\n')
        with self.assertRaisesRegex(ValueError, 'incomplete or duplicate'):
            ANALYZE.analyze(arena)
        self.assertFalse((arena / 'analysis.json').exists())

    def test_final_pools_and_first_locked_primary(self):
        arena = self.fixture(phase='final')
        result = ANALYZE.analyze(arena)
        self.assertEqual(len(result['challenge_opponents']), 2)
        candidate = result['stages']['holdout']['candidates']['s3_candidate']
        self.assertEqual(candidate['comparisons']['challenge']['Y']['paired_games'], 2)
        self.assertEqual(candidate['pool_stats']['fixed']['all']['matches'], 12)
        self.assertEqual(candidate['pool_stats']['challenge']['all']['matches'], 4)
        self.assertEqual(result['promotion_review']['primary'], 's3_candidate')
        path = arena / 'campaign-result.json'
        altered = ANALYZE.read(path)
        altered['recommended'] = 's3_runner_up'
        write(path, altered)
        prior = (arena / 'analysis.json').read_bytes()
        with self.assertRaisesRegex(ValueError, 'reselects or bypasses'):
            ANALYZE.analyze(arena)
        self.assertEqual((arena / 'analysis.json').read_bytes(), prior)


if __name__ == '__main__':
    unittest.main()
