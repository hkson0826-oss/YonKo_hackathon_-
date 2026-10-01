"""Previous-rank movement inference; separate from observed latest ranks."""
import argparse
import hashlib
import json
from pathlib import Path
import statistics
H=Path(__file__).resolve().parent;D=H.parent/'data'
parser=argparse.ArgumentParser();parser.add_argument('--repo-root',type=Path,default=next((p for p in H.parents if (p/'records/official').is_dir()),Path('/tmp/yk-new-bot-20261001')));ARGS=parser.parse_args();SOURCE=ARGS.repo_root.resolve()
r=json.loads((H/'strength-analysis.json').read_text());m=json.loads((D/'matches.json').read_text());matches=[dict(zip(m['columns'],x)) for x in m['rows']];p=json.loads((D/'previous-rank-inference.json').read_text());previous={x['team']:x for x in p['rows']}
assert len(previous)==87
assert all(x['inferred_previous_rank']==x['current_rank']+x['rise_places'] for x in p['rows'])
def stats(xs):
 n=len(xs);w=sum(x['points']==1 for x in xs);l=sum(x['points']==0 for x in xs)
 return {'n':n,'wins':w,'losses':l,'point_rate':sum(x['points'] for x in xs)/n if n else None}
def measure(submission,mode):
 xs=[x for x in matches if x['submission']==submission];rs=[previous[x['opponent']]['inferred_previous_rank' if mode=='inferred_previous' else 'current_rank'] for x in xs];pairs=list(zip(xs,rs))
 return {'submission':submission,'rank_source':mode,'all':stats(xs),'opponent_rank_mean':statistics.mean(rs),'opponent_rank_median':statistics.median(rs),'opponent_rank_min':min(rs),'opponent_rank_max':max(rs),'rank_bands':{'top25_rank':stats([x for x,z in pairs if z<=22]),'middle50_rank':stats([x for x,z in pairs if 22<z<66]),'bottom25_rank':stats([x for x,z in pairs if z>=66]),'top12':stats([x for x,z in pairs if z<=12])},'rows':[{'opponent':x['opponent'],'rank_used':z,'points':x['points'],'round':x['round_label']} for x,z in pairs]}
old=json.loads((SOURCE/'records/official/opponent-intel-20260928/leaderboard-live-followup.json').read_text());active=[r for r in old['teams'] if r['games']>0 and r['rank'] is not None];assert len(active)==56;ob={r['team']:r for r in active};oldmatches=[r for r in matches if r['submission']==4];oldpairs=[(r,ob[r['opponent']]['rank']) for r in oldmatches];assert len(oldpairs)==13
contemp={'submission':4,'active_team_denominator':56,'registered_teams':104,'opponent_mean_rank':statistics.mean(z for _,z in oldpairs),'opponent_median_rank':statistics.median(z for _,z in oldpairs),'opponent_mean_rank_fraction':statistics.mean(z/56 for _,z in oldpairs),'opponent_median_rank_fraction':statistics.median(z/56 for _,z in oldpairs),'normalization':'display rank / number of ranked active teams; lower means stronger relative place in that publication, not cross-era absolute skill','rank_bands':{'top25_rank_1_to14':stats([x for x,z in oldpairs if z<=14]),'middle50_rank_15_to42':stats([x for x,z in oldpairs if 14<z<43]),'bottom25_rank_43_to56':stats([x for x,z in oldpairs if z>=43])},'own_official':{'rank':19,'rank_fraction':19/56,'adjusted_percent':66.2,'wins':9,'losses':4}}
result={'source_sha256':hashlib.sha256((D/'previous-rank-inference.json').read_bytes()).hexdigest(),'basis':p['basis'],'submission4_contemporaneous_active56':contemp,'submission9_at_inferred10am':measure(9,'inferred_previous'),'submission11_at_observed5pm':measure(11,'current'),'submission9_using_observed5pm_retrospective':measure(9,'current'),'caveats':['Previous rank is reconstructed from a movement arrow, not a preserved full10amtable.','Previous timestamp10am is inferred; previous WDL and opponent rates unavailable.','Ranks at different publications include opponent policy upgrades and different schedules.','Latest error-free or LOO rate does not recover historical error-free rates.','No previous-rank LOO is possible without prior opponents results and tiebreak values.']}
for key in ['submission9_at_inferred10am','submission11_at_observed5pm','submission9_using_observed5pm_retrospective']:
 result[key]['opponent_mean_rank_fraction_of87']=result[key]['opponent_rank_mean']/87
 result[key]['opponent_median_rank_fraction_of87']=result[key]['opponent_rank_median']/87
(H/'previous-rank-sensitivity.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:{a:b for a,b in v.items() if a!='rows'} if isinstance(v,dict) else v for k,v in result.items()},ensure_ascii=False,indent=2))
