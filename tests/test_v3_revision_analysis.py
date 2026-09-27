from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('analyze_v3_revisions', ROOT/'experiments/analyze_v3_revisions.py')
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def fixture():
    names = list(dict.fromkeys([*MODULE.PARENTS, *MODULE.PARENTS.values()]))
    added = ['s3_selective_contact', 'r3_opponent_league']
    ops = [*MODULE.FIXED_OPPONENTS, *added]
    bots = {name: {'source_sha256': name + '-sha'} for name in set(names + ops)}
    manifest = {'status': 'ready', 'source_commit': 'synthetic', 'bots': bots,
                'population_spec': {'module_revisions': {name: 2 for name in MODULE.NEW_MODULES}}}
    plan = {'candidates': names, 'opponents': ops, 'map_seeds': [8200, 8201], 'replays': 'all'}
    policy = {'baseline': 'v3', 'opponents': ops, 'fixed_opponents': MODULE.FIXED_OPPONENTS,
              'map_sets': {'development': plan['map_seeds']},
              'challenge_lock': {'opponents': added, 'source_sha256': {name: bots[name]['source_sha256'] for name in added}}}
    jobs = MODULE.make_jobs(plan, bots)
    rows = []
    for job in jobs:
        side = job['team']; other = 'K' if side == 'Y' else 'Y'
        win = side == 'K' or job['opponent'] in added
        if job['candidate'] == 'f3_v2_soft_matching' and side == 'Y':
            win = job['opponent'] in MODULE.FIXED_OPPONENTS
        rows.append({**job, 'status': 'complete', 'win': win, 'draw': False, 'forfeit': False,
                     'score_margin': 1 if win else -1,
                     'result': {'winner': side if win else other, 'reason': 'turn_limit',
                                'score': {side: 1 if win else 0, other: 0 if win else 1}},
                     'replay': 'replays/' + job['job_id'] + '.json.gz'})
    summary = {'expected_jobs': len(jobs), 'finished_jobs': len(rows),
               'overall': {'matches': len(rows), 'errors': 0, 'forfeits': 0}}
    return dict(manifest=manifest, policy=policy, progress={'completed': ['smoke', 'development']},
                plan=plan, copied_plan=copy.deepcopy(plan), jobs=jobs, rows=rows,
                summary=summary, session={'status': 'complete'})


def write_arena(folder, data):
    arena = Path(folder); stage = arena/'runs/development'; stage.mkdir(parents=True)
    (arena/'plans').mkdir()
    paths = {'manifest': arena/'manifest.json', 'policy': arena/'campaign-policy.json',
             'progress': arena/'progress.json', 'plan': stage/'plan.json',
             'copied_plan': arena/'plans/development.json', 'jobs': stage/'jobs.json',
             'summary': stage/'summary.json', 'session': stage/'session-1.json'}
    for name, path in paths.items():
        path.write_text(json.dumps(data[name]))
    (stage/'results.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in data['rows']))
    return arena


class RevisionAnalysisTests(unittest.TestCase):
    def test_twelve_explicit_parent_mappings_and_control_caveat(self):
        self.assertEqual(len(MODULE.PARENTS), 12)
        self.assertEqual(MODULE.PARENTS['f3_v2_safe_econ_mission'], 'f3_econ_mission')
        self.assertEqual(MODULE.PARENTS['f3_v2_warrior_reserve'], 'v3')
        self.assertEqual(MODULE.PARENTS['r3_v2_y_tail'], 'r3_lower_tail')
        self.assertIn('완전한 단일 요소 제거 실험이 아니다', MODULE.NOTES['r3_v2_mean_control'])

    def test_exact_pairing_separate_pools_map_bootstrap_and_signed_cases(self):
        data = fixture(); pools = MODULE.validate_inputs(**data)
        item = MODULE.compare(data['rows'], 'f3_v2_soft_matching', 'f3_matching', pools)
        y = item['pools']['all']['Y']
        self.assertEqual(y['point_rate_difference'], .5)
        self.assertEqual(y['interval']['maps'], 2)
        self.assertEqual(y['interval']['paired_games'], 16)
        self.assertEqual(y['interval']['map_cluster_bootstrap_95pct'], [.5, .5])
        self.assertEqual(y['interval']['baseline'], 'f3_matching')
        self.assertEqual(item['pools']['fixed']['Y']['point_rate_difference'], 1)
        self.assertEqual(item['pools']['added']['Y']['point_rate_difference'], -1)
        self.assertEqual(item['pools']['all']['K']['point_rate_difference'], 0)
        self.assertEqual(len(item['matched_cases']['loss_to_win']), 12)
        self.assertEqual(len(item['matched_cases']['win_to_loss']), 4)
        self.assertEqual(len(item['matched_cases']['score_margin_sign_reversals']), 16)
        case = item['matched_cases']['loss_to_win'][0]
        self.assertNotEqual(case['candidate_job_id'], case['parent_job_id'])
        self.assertTrue(case['candidate_replay'].startswith('runs/development/replays/'))

    def test_draw_is_half_point_and_wdl_difference_is_counted(self):
        data = fixture(); rows = data['rows']
        chosen = next(r for r in rows if r['candidate'] == 'f3_v2_soft_matching' and r['team'] == 'Y' and r['opponent'] in MODULE.FIXED_OPPONENTS)
        chosen.update(win=False, draw=True, score_margin=0)
        chosen['result'] = {'winner': 'DRAW', 'reason': 'turn_limit', 'score': {'Y': 0, 'K': 0}}
        pools = MODULE.validate_inputs(**data)
        y = MODULE.compare(rows, 'f3_v2_soft_matching', 'f3_matching', pools)['pools']['all']['Y']
        self.assertEqual(y['point_rate_difference'], .5 - .5/16)
        self.assertEqual(y['wdl_count_difference']['draws'], 1)

    def test_any_forfeit_excludes_whole_pair_including_mutual_draw(self):
        data = fixture(); row = next(r for r in data['rows'] if r['candidate'] == 'f3_v2_soft_matching')
        row.update(win=False, draw=True, forfeit=True, score_margin=0)
        row['result'] = {'winner': 'DRAW', 'reason': 'forfeit', 'score': {'Y': 0, 'K': 0}, 'forfeit': {'team': 'both'}}
        data['summary']['overall']['forfeits'] = 1
        pools = MODULE.validate_inputs(**data)
        item = MODULE.compare(data['rows'], 'f3_v2_soft_matching', 'f3_matching', pools)
        self.assertEqual(item['status'], 'excluded_unhealthy_pair')
        self.assertEqual(item['pools'], {})
        self.assertEqual(item['health']['mutual_forfeits'], 1)
        self.assertIn(row['job_id'], item['health']['problem_job_ids'])

    def test_error_excludes_whole_pair_instead_of_reducing_sample(self):
        data = fixture(); row = next(r for r in data['rows'] if r['candidate'] == 'f3_matching')
        row['status'] = 'error'
        data['summary']['overall'].update(matches=len(data['rows'])-1, errors=1)
        data['session']['status'] = 'complete_with_errors'
        pools = MODULE.validate_inputs(**data)
        item = MODULE.compare(data['rows'], 'f3_v2_soft_matching', 'f3_matching', pools)
        self.assertEqual(item['status'], 'excluded_unhealthy_pair')
        self.assertEqual(item['pools'], {})

    def test_missing_duplicate_stale_running_wrong_lock_and_wrong_identity_rejected(self):
        changes = [
            lambda d: d['rows'].pop(),
            lambda d: d['rows'].append(copy.deepcopy(d['rows'][0])),
            lambda d: d['summary'].update(finished_jobs=1),
            lambda d: d['session'].update(status='running'),
            lambda d: d['progress'].update(completed=['smoke']),
            lambda d: d['policy']['challenge_lock']['source_sha256'].update(s3_selective_contact='wrong'),
            lambda d: d['rows'][0].update(job_id='wrong'),
            lambda d: d['manifest']['population_spec']['module_revisions'].update(v3_repairs=1),
            lambda d: d['copied_plan'].update(replays='losses'),
            lambda d: d['rows'][0].update(win=not d['rows'][0]['win']),
        ]
        for change in changes:
            data = fixture(); change(data)
            with self.assertRaises(ValueError): MODULE.validate_inputs(**data)
        data = fixture()
        with self.assertRaisesRegex(ValueError, 'Incomplete exact parent pairing'):
            rows = [r for r in data['rows'] if r['candidate'] != 'f3_matching' or r['team'] == 'Y']
            MODULE.compare(rows, 'f3_v2_soft_matching', 'f3_matching', {'all': data['plan']['opponents']})

    def test_progress_completion_required_before_reading_results(self):
        with tempfile.TemporaryDirectory(prefix='yk-revision-analysis-', dir='/tmp') as folder:
            arena = Path(folder)
            (arena/'progress.json').write_text('{"completed":["smoke"]}')
            with self.assertRaisesRegex(ValueError, 'development completed'): MODULE.analyze(arena)
            self.assertFalse((arena/'revision-comparison.json').exists())

    def test_complete_arena_outputs_12_comparisons_without_overwrite_or_selection_edit(self):
        with tempfile.TemporaryDirectory(prefix='yk-revision-analysis-', dir='/tmp') as folder:
            arena = write_arena(folder, fixture())
            policy = (arena/'campaign-policy.json').read_bytes()
            report = MODULE.analyze(arena)
            self.assertEqual(len(report['comparisons']), 12)
            self.assertEqual(report['maps'], 2)
            self.assertEqual((arena/'campaign-policy.json').read_bytes(), policy)
            self.assertTrue((arena/'revision-comparison.json').is_file())
            text = (arena/'revision-comparison.md').read_text()
            self.assertIn('선택 편향', text)
            self.assertIn('r3_v2_mean_control → v3', text)
            with self.assertRaises(FileExistsError): MODULE.analyze(arena)
            (arena/'runs/development/session-2.json').write_text('{"status":"running"}')
            with self.assertRaises(ValueError): MODULE.analyze(arena, arena/'new-report')
            self.assertFalse((arena/'new-report.json').exists())


if __name__ == '__main__':
    unittest.main()
