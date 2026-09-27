from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('analyze_v3_diversity',ROOT/'experiments/analyze_v3_diversity.py')
MODULE=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def fixture():
    plan={'candidates':['v3','r3_clone','s3_attack'],'opponents':['v3','teammate'],'map_seeds':[8100,8101]}
    bots={name:{'source_sha256':name+'-sha','family':name.split('_')[0]} for name in plan['candidates']}
    rows=[]
    for name in plan['candidates']:
        for seed in plan['map_seeds']:
            for op in plan['opponents']:
                for side in 'YK':
                    win=(op=='v3') if name=='s3_attack' else side=='Y'
                    rows.append({'candidate':name,'opponent':op,'map_seed':seed,'team':side,
                                 'job_id':f'{name}-{seed}-{op}-{side}','status':'complete',
                                 'win':win,'draw':False,'forfeit':False,'score_margin':5 if win else -5,
                                 'logical_trace_sha256':f'{"clone" if name!="s3_attack" else name}-{seed}-{op}-{side}'})
    jobs=[{k:r[k] for k in ['candidate','opponent','map_seed','team','job_id']} for r in rows]
    summary={'expected_jobs':len(jobs),'finished_jobs':len(rows),'overall':{'errors':0,'forfeits':0}}
    lock={'opponents':['r3_clone','s3_attack'],'source_sha256':{name:bots[name]['source_sha256'] for name in ['r3_clone','s3_attack']},'rule':'existing rule'}
    return plan,bots,rows,jobs,summary,lock


class DiversityTests(unittest.TestCase):
    def test_unique_sources_can_have_identical_outcome_and_trace_vectors(self):
        plan,bots,rows,_,_,lock=fixture()
        report=MODULE.diagnose(plan,rows,bots,lock)
        self.assertEqual(report['distinct_source_count'],3)
        self.assertEqual(report['distinct_healthy_outcome_vectors'],2)
        self.assertEqual(report['distinct_complete_trace_vectors'],2)
        self.assertIn(['v3','r3_clone'],report['identical_outcome_groups'])
        comparison=report['candidates']['r3_clone']['vs_v3_same_conditions']
        self.assertEqual(comparison['matched_initial_conditions'],8)
        self.assertEqual(comparison['outcome_agreement'],1)
        self.assertEqual(comparison['trace_agreement'],1)
        self.assertEqual(report['locked_challengers']['existing_lock'],lock)
        self.assertEqual(report['locked_challengers']['mutual_comparisons'][0]['outcome_agreement'],.5)

    def test_direct_strength_and_worst_matchup_are_distinct(self):
        plan,bots,rows,_,_,lock=fixture()
        attack=MODULE.diagnose(plan,rows,bots,lock)['candidates']['s3_attack']
        self.assertEqual(attack['direct_vs_v3']['both']['point_rate'],1)
        self.assertEqual(attack['direct_vs_v3']['both']['games'],4)
        self.assertEqual(attack['weakest_matchups'][0]['opponent'],'teammate')
        self.assertEqual(attack['weakest_matchups'][0]['both']['point_rate'],0)
        self.assertEqual(attack['both']['point_rate'],.5)

    def test_error_or_forfeit_excludes_entire_candidate_without_changing_lock(self):
        plan,bots,rows,_,_,lock=fixture()
        broken=copy.deepcopy(rows)
        next(r for r in broken if r['candidate']=='r3_clone')['status']='error'
        next(r for r in broken if r['candidate']=='s3_attack')['forfeit']=True
        report=MODULE.diagnose(plan,broken,bots,lock)
        self.assertEqual(set(report['candidates']),{'v3'})
        self.assertEqual(report['healthy_candidates'],1)
        self.assertEqual(report['locked_challengers']['existing_lock'],lock)
        self.assertIsNone(report['locked_challengers']['opponents']['s3_attack']['statistics'])
        self.assertEqual(report['pairwise'],[])

    def test_missing_trace_is_not_counted_as_equal(self):
        plan,bots,rows,_,_,lock=fixture()
        for row in rows:
            if row['candidate']=='r3_clone': row.pop('logical_trace_sha256')
        report=MODULE.diagnose(plan,rows,bots,lock)
        comparison=report['candidates']['r3_clone']['vs_v3_same_conditions']
        self.assertEqual(comparison['outcome_agreement'],1)
        self.assertEqual(comparison['trace_comparable_games'],0)
        self.assertIsNone(comparison['trace_agreement'])
        self.assertEqual(comparison['trace_coverage'],0)
        self.assertEqual(report['candidates_with_complete_traces'],2)

    def test_partial_running_duplicate_stale_or_wrong_identity_schedule_rejected(self):
        plan,_,rows,jobs,summary,_=fixture()
        MODULE.validate_schedule(plan,jobs,rows,summary,{'status':'complete'})
        variants=[(rows[:-1],summary,{'status':'complete'}),
                  (rows+[rows[0]],summary,{'status':'complete'}),
                  (rows,summary,{'status':'running'}),
                  (rows,{**summary,'finished_jobs':1},{'status':'complete'}),
                  ([{**rows[0],'job_id':'wrong'},*rows[1:]],summary,{'status':'complete'})]
        for data,report,session in variants:
            with self.assertRaises(ValueError): MODULE.validate_schedule(plan,jobs,data,report,session)

    def test_source_lock_mismatch_is_rejected(self):
        plan,bots,rows,_,_,lock=fixture()
        lock['source_sha256']['r3_clone']='changed'
        with self.assertRaisesRegex(ValueError,'source mismatch'):MODULE.diagnose(plan,rows,bots,lock)

    def test_completed_arena_outputs_diagnostic_only_and_refuses_overwrite(self):
        plan,bots,rows,jobs,summary,lock=fixture()
        with tempfile.TemporaryDirectory(prefix='yk-v3-diversity-',dir='/tmp') as directory:
            arena=Path(directory);folder=arena/'runs/development';folder.mkdir(parents=True)
            for path,value in [(arena/'manifest.json',{'status':'ready','source_commit':'synthetic','bots':bots}),
                               (arena/'next-opponents.json',lock),(folder/'plan.json',plan),(folder/'jobs.json',jobs),
                               (folder/'summary.json',summary),(folder/'session-1.json',{'status':'complete'})]:
                path.write_text(json.dumps(value))
            (folder/'results.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in rows))
            lock_bytes=(arena/'next-opponents.json').read_bytes()
            report=MODULE.analyze(arena)
            self.assertEqual(report['development_games'],24)
            self.assertEqual(report['distinct_maps'],2)
            self.assertEqual((arena/'next-opponents.json').read_bytes(),lock_bytes)
            md=(arena/'diversity-analysis.md').read_text()
            self.assertIn('초기 맵·상대·진영 조건',md)
            self.assertIn('사후 재선정',md)
            with self.assertRaises(FileExistsError):MODULE.analyze(arena)
            (folder/'session-2.json').write_text(json.dumps({'status':'running'}))
            with self.assertRaises(ValueError):MODULE.analyze(arena,arena/'another-analysis')
            self.assertFalse((arena/'another-analysis.json').exists())


if __name__=='__main__':
    unittest.main()
