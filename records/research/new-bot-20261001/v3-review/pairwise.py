"""Pair an existing common-opponent analysis without replaying any match."""
import argparse,hashlib,importlib.util,itertools,json,statistics
from collections import defaultdict
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--analysis',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--analyzer',type=Path,default=Path('/tmp/yk-new-bot-20261001/experiments/analyze_team_strategy_comparison.py'));p.add_argument('--focus',default='mission3,mission3_no_rally,v8');a=p.parse_args()
spec=importlib.util.spec_from_file_location('team_analysis',a.analyzer);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
j=json.loads(a.analysis.read_text());focus=a.focus.split(',');players=j['players'];index={}
for r in players:
 if not r['is_candidate'] or r['bot'] not in focus:continue
 key=(r['bot'],r['team'],r['map_seed'],r['opponent'])
 if key in index:raise ValueError(f'Duplicate paired key {key}: {index[key]["job_id"]} / {r["job_id"]}')
 index[key]=r
out={'input_sha256':hashlib.sha256(a.analysis.read_bytes()).hexdigest(),'analyzer_sha256':hashlib.sha256(a.analyzer.read_bytes()).hexdigest(),'method':'Match candidate/opponent/map/side; resample map means for intervals. Use a common-opponent run without direct matches. No multiple-comparison correction; these are development diagnostics.','pairs':{}}
for left,right in itertools.combinations(focus,2):
 report=m.paired_common(players,[left,right]);margin=defaultdict(list);matched=[]
 for (bot,side,seed,op),r in index.items():
  if bot!=left:continue
  other=index.get((right,side,seed,op))
  if other is None:continue
  delta=r['score_margin']-other['score_margin'];margin[seed].append(delta)
  matched.append({'map_seed':seed,'side':side,'opponent':op,'left_job':r['job_id'],'right_job':other['job_id'],'point_difference':r['point']-other['point'],'score_margin_difference':delta})
 vals=[statistics.mean(v)for v in margin.values()]
 report['score_margin_difference']={'paired_maps':len(vals),'paired_games':len(matched),'mean':statistics.mean(vals)if vals else None,'map_cluster_bootstrap_95pct':m.interval(vals)};report['matched_games']=matched
 out['pairs'][left+' minus '+right]=report
out['candidate_games_before_matching']={bot:sum(r['bot']==bot for r in index.values()) for bot in focus}
a.output.write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'output':str(a.output),'pairs':{k:v['by_side']['both']for k,v in out['pairs'].items()}},ensure_ascii=False))
