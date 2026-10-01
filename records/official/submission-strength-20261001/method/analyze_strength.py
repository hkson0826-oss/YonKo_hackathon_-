"""Descriptive official submission comparison; no invented official adjustment."""
import argparse
import collections
import hashlib
import itertools
import json
import math
from pathlib import Path
import statistics
import numpy as np
HERE=Path(__file__).resolve().parent
DATA=HERE.parent/'data'
parser=argparse.ArgumentParser()
parser.add_argument('--repo-root',type=Path,default=next((p for p in HERE.parents if (p/'records/official').is_dir()),Path('/tmp/yk-new-bot-20261001')))
ARGS=parser.parse_args()
SOURCE=ARGS.repo_root.resolve()
SEED=20261001
BOOTSTRAPS=20000
LATEST='10월 1일 17:00'

def read(path):return json.loads(path.read_text())
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def write(name,value):(HERE/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
def wilson(w,n):
 if not n:return None
 z=1.959963984540054;p=w/n;den=1+z*z/n;center=(p+z*z/(2*n))/den;half=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/den
 return [max(0,center-half),min(1,center+half)]
def record_stats(rows):
 points=[r['points'] for r in rows];n=len(points);w=sum(p==1 for p in points);d=sum(p==.5 for p in points);l=sum(p==0 for p in points)
 return {'n':n,'wins':w,'draws':d,'losses':l,'points':sum(points),'point_rate':sum(points)/n if n else None,'win_rate':w/n if n else None,'win_rate_wilson95_descriptive':wilson(w,n),'distinct_opponents':len({r['opponent'] for r in rows})}

def rank_bucket(rank):return 'top25_rank' if rank<=22 else 'bottom25_rank' if rank>=66 else 'middle50_rank'
def point_bucket(q):return 'above_q75' if q>Q75 else 'below_q25' if q<Q25 else 'q25_to_q75_inclusive'
def summarize(rows,reference='latest'):
 out=record_stats(rows);key='latest' if reference=='latest' else 'contemporaneous'
 attached=[r for r in rows if r.get(key) and r[key]['games']>0]
 out.update(reference=reference,reference_coverage=len(attached),reference_missing=[{'opponent':r['opponent'],'round':r['round_label']} for r in rows if r not in attached])
 ranks=[r[key]['rank'] for r in attached if r[key]['rank'] is not None];qs=[r[key]['point_rate'] for r in attached]
 out['opponent_rank']={'n':len(ranks),'mean':statistics.mean(ranks) if ranks else None,'median':statistics.median(ranks) if ranks else None,'min':min(ranks) if ranks else None,'max':max(ranks) if ranks else None}
 out['opponent_point_rate']={'n':len(qs),'mean':statistics.mean(qs) if qs else None,'median':statistics.median(qs) if qs else None}
 out['opponents_with_any_current_round_errors']=sum(r[key]['errors']>0 for r in attached)
 out['match_specific_forfeits']='partial root-confirmed details; unknown matches are not asserted error-free'
 out['confirmed_opponent_forfeit_wins']=sum(r.get('opponent_match_specific_forfeit') is True and r['points']==1 for r in rows)
 out['individual_forfeit_status_unknown']=sum(r.get('opponent_match_specific_forfeit') is None for r in rows)
 out['confirmed_normal_only']=record_stats([r for r in rows if r.get('termination_class')=='normal'])
 out['excluding_confirmed_opponent_forfeit_wins']=record_stats([r for r in rows if not (r.get('opponent_match_specific_forfeit') is True and r['points']==1)])
 if reference=='latest':
  loo=[r['latest']['point_rate_without_latest_our_match'] for r in attached]
  out['opponent_point_rate_latest_loo']={'n':len(loo),'mean':statistics.mean(loo) if loo else None,'median':statistics.median(loo) if loo else None,'actually_adjusted_rows':sum(r['latest']['loo_removed_our_latest_match'] for r in attached)}
  out['rank_buckets']={b:record_stats([r for r in attached if rank_bucket(r['latest']['rank'])==b]) for b in ['top25_rank','middle50_rank','bottom25_rank']}
  out['top12']=record_stats([r for r in attached if r['latest']['rank']<=12])
  out['point_rate_buckets']={b:record_stats([r for r in attached if point_bucket(r['latest']['point_rate'])==b]) for b in ['above_q75','q25_to_q75_inclusive','below_q25']}
  out['error_free_opponent_team_sensitivity']=record_stats([r for r in attached if r['latest']['errors']==0])
  unique={r['opponent']:r['latest'] for r in attached}
  out['unique_opponent_weighted']={'n':len(unique),'mean_rank':statistics.mean(v['rank'] for v in unique.values()) if unique else None,'mean_point_rate':statistics.mean(v['point_rate'] for v in unique.values()) if unique else None,'mean_latest_loo_point_rate':statistics.mean(v['point_rate_without_latest_our_match'] for v in unique.values()) if unique else None}
 return out

def compare(a,b,groups):
 left=collections.defaultdict(list);right=collections.defaultdict(list)
 for r in groups[a]:left[r['opponent']].append(r)
 for r in groups[b]:right[r['opponent']].append(r)
 common=sorted(left.keys()&right.keys());details=[]
 for opponent in common:
  ls=record_stats(left[opponent]);rs=record_stats(right[opponent])
  details.append({'opponent':opponent,'a':ls,'b':rs,'difference':ls['point_rate']-rs['point_rate'],'a_rounds':[r['round_label'] for r in left[opponent]],'b_rounds':[r['round_label'] for r in right[opponent]],'a_outcomes':[r['points'] for r in left[opponent]],'b_outcomes':[r['points'] for r in right[opponent]],'latest_rank':BOARD.get(opponent,{}).get('rank'),'opponent_version':'unknown','maps':'unmatched/unknown'})
 differences=np.array([r['difference'] for r in details]);n=len(details)
 if n:
  rng=np.random.default_rng(SEED+sum(ord(x) for x in a+'|'+b));draws=rng.choice(differences,size=(BOOTSTRAPS,n),replace=True).mean(axis=1);ci=[float(x) for x in np.quantile(draws,[.025,.975])]
 else:ci=None
 cells=[]
 for bucket in ['top25_rank','middle50_rank','bottom25_rank']:
  aa=[r for r in groups[a] if r['latest'] and rank_bucket(r['latest']['rank'])==bucket];bb=[r for r in groups[b] if r['latest'] and rank_bucket(r['latest']['rank'])==bucket]
  if aa and bb:cells.append({'bucket':bucket,'a':record_stats(aa),'b':record_stats(bb),'difference':record_stats(aa)['point_rate']-record_stats(bb)['point_rate']})
 return {'a':a,'b':b,'common_opponents':n,'a_covered_games':sum(r['a']['n'] for r in details),'b_covered_games':sum(r['b']['n'] for r in details),'a_common_macro_point_rate':statistics.mean(r['a']['point_rate'] for r in details) if n else None,'b_common_macro_point_rate':statistics.mean(r['b']['point_rate'] for r in details) if n else None,'macro_difference_a_minus_b':float(differences.mean()) if n else None,'common_opponent_bootstrap95':ci,'bootstrap_seed':SEED+sum(ord(x) for x in a+'|'+b),'bootstrap_replicates':BOOTSTRAPS,'positive_opponents':int(sum(differences>0)),'negative_opponents':int(sum(differences<0)),'tied_opponents':int(sum(differences==0)),'caveat':'same team and recordedY label only; actual engine position unknown; changing opponent versions and different maps/rounds; not randomized or causal; interval conditions on this small common-team sample','details':details,'latest_rank_standardization':{'cells':cells,'shared_cells':len(cells),'equal_shared_bucket_difference_a_minus_b':statistics.mean(r['difference'] for r in cells) if cells else None,'caveat':'retrospective 17:00 rank, overlap only; not official adjusted score'}}

matches=read(DATA/'matches.json');table=read(DATA/'leaderboard-latest.json')
rows=[dict(zip(matches['columns'],r)) for r in matches['rows']];board=[dict(zip(table['columns'],r)) for r in table['rows']]
assert len(rows)==131 and len(board)==87
assert all(r['wins']+r['draws']+r['losses']==r['games'] for r in board)
assert all(r['points']=={'승리':1,'무승부':.5,'패배':0}[r['result']] for r in rows)
keys=[(r['round_label'],r['submission'],r['opponent'],r['side']) for r in rows];assert len(keys)==len(set(keys))
assert all(r['side']=='Y' for r in rows)
BOARD={r['team']:r for r in board};assert len(BOARD)==87
latest_ours={r['opponent']:r for r in rows if r['round_label']==LATEST};assert len(latest_ours)==24
for r in board:
 r['point_rate']=(r['wins']+.5*r['draws'])/r['games'] if r['games'] else None
 r['loo_removed_our_latest_match']=r['team'] in latest_ours
 if r['team'] in latest_ours:
  ours=latest_ours[r['team']]['points'];opp_points=1-ours
  assert r['games']>1 and r['wins']+.5*r['draws']>=opp_points
  r['point_rate_without_latest_our_match']=(r['wins']+.5*r['draws']-opp_points)/(r['games']-1)
  r['loo_removed_opponent_points']=opp_points;r['loo_denominator']=r['games']-1
 else:r['point_rate_without_latest_our_match']=r['point_rate'];r['loo_removed_opponent_points']=0;r['loo_denominator']=r['games']
Q25,Q75=[float(x) for x in np.quantile([r['point_rate'] for r in board],[.25,.75])]
old=read(SOURCE/'records/official/opponent-intel-20260928/leaderboard-live-followup.json');oldboard={r['team']:dict(r,point_rate=(r['wins']+.5*r['draws'])/r['games'] if r['games'] else None) for r in old['teams']}
for r in rows:
 r['latest']=BOARD.get(r['opponent']);r['contemporaneous']=oldboard.get(r['opponent']) if r['round_label']=='9월 28일 10:00' else None
 r['own_match_specific_forfeit']=None;r['opponent_match_specific_forfeit']=True if (r['submission'],r['opponent']) in [(9,'신촌도 우리땅'),(9,'개우진보러갈까'),(11,'Re:verse')] else None;r['opponent_version']=None;r['match_id']=None;r['actual_engine_side']=None
known_path=HERE.parent/'history/known-termination.json'
known=read(known_path) if known_path.exists() else {'matches':[]}
known_index={(r['round'],r['submission'],r['opponent']):r for r in known['matches']}
for row in rows:
 proof=known_index.get((row['round_label'],row['submission'],row['opponent']),{})
 row['termination_class']='unknown'
 row['termination_reason']=None
 if proof.get('gameId'):row['match_id']=proof['gameId']
 if proof.get('reason') is not None:
  assert proof.get('outcome') in ({1:'win',0:'loss',.5:'draw'}[row['points']],None)
  row['termination_class']=proof['termination_class'];row['termination_reason']=proof['reason'];row['termination_source']=proof['source']
  if proof['termination_class']=='normal':row['own_match_specific_forfeit']=False;row['opponent_match_specific_forfeit']=False
  elif proof['termination_class']=='forfeit':row['opponent_match_specific_forfeit']=row['points']==1;row['own_match_specific_forfeit']=row['points']==0
 elif row['opponent_match_specific_forfeit'] is True:
  row['termination_class']='forfeit';row['termination_reason']='forfeit';row['termination_source']={'kind':'root_authenticated_UI_review','note':'latest detail source merge pending'}
latest_details_path=HERE.parent/'latest-detail/details.json'
latest_details=read(latest_details_path) if latest_details_path.exists() else []
if latest_details:
 assert len(latest_details)==24
 index={(r['round_label'],r['submission'],r['opponent']):r for r in rows}
 joined=[]
 for position,proof in enumerate(latest_details):
  key=(proof['round_label'].removesuffix(' 리더보드'),proof['submission'],proof['opponent'])
  row=index[key];assert row['result']==proof['result'] and row['side']==proof['side']
  if row['match_id'] is not None:assert row['match_id']==proof['game_id']
  row['match_id']=proof['game_id'];row['termination_reason']=proof['end_reason'];row['termination_class']='forfeit' if proof['end_reason']=='bot_error' else 'normal'
  assert proof['end_reason'] in ('instant','score','bot_error')
  row['opponent_match_specific_forfeit']=row['termination_class']=='forfeit' and row['points']==1
  row['own_match_specific_forfeit']=row['termination_class']=='forfeit' and row['points']==0
  row['termination_source']={'kind':'rendered_official_ui','path':'../latest-detail/details.json','record_index':position,'sha256':sha(latest_details_path),'official_url':proof['official_url']}
  joined.append(key)
 assert len(set(joined))==24
known_ids=[r['match_id'] for r in rows if r['match_id'] is not None];assert len(known_ids)==len(set(known_ids))
by_sub=collections.defaultdict(list);by_round=collections.defaultdict(list)
for r in rows:by_sub[str(r['submission'])].append(r);by_round[r['round_label']].append(r)
groups=dict(by_sub);groups['8+11']=by_sub['8']+by_sub['11']
pairs=list(itertools.combinations(sorted(by_sub,key=int),2))+[(s,'8+11') for s in sorted(by_sub,key=int) if s not in ('8','11')]
comparisons=[compare(a,b,groups) for a,b in pairs]
result={'data_validation':{'games':len(rows),'teams':len(board),'wins':sum(r['points']==1 for r in rows),'losses':sum(r['points']==0 for r in rows),'draws':sum(r['points']==.5 for r in rows),'unique_compound_keys':len(set(keys)),'missing_match_ids':sum(r['match_id'] is None for r in rows),'termination_counts':dict(collections.Counter(r['termination_class'] for r in rows)),'latest_ours_equals_latest_board':record_stats(list(latest_ours.values()))['wins']==BOARD['강릉']['wins'] and len(latest_ours)==BOARD['강릉']['games']},'sources':{'matches':sha(DATA/'matches.json'),'leaderboard_latest':sha(DATA/'leaderboard-latest.json'),'latest_details':sha(latest_details_path) if latest_details_path.exists() else None,'known_termination':sha(known_path) if known_path.exists() else None,'historical_round2':sha(SOURCE/'records/official/opponent-intel-20260928/leaderboard-live-followup.json')},'latest_reference':{'published_at_kst':table['published_at_kst'],'historical_use':'retrospective sensitivity only; opponent strength/version at match time unknown','rank_bands':{'top25':'ranks<=22','middle50':'ranks23..65','bottom25':'ranks>=66','top12':'ranks<=12'},'point_rate_quantiles':{'q25':Q25,'q75':Q75,'tie_policy':'q<q25 bottom; q>q75 top; all boundary ties in middle; group sizes may differ from25/50/25'},'loo_rule':'remove only the known 17:00 match against our team from opponent latest single-round W/D/L; do not remove historical matches from latest table'},'submissions':{s:summarize(rs) for s,rs in sorted(by_sub.items(),key=lambda x:int(x[0]))},'rounds':{s:summarize(rs) for s,rs in by_round.items()},'source_group_8_plus_11':{'mapping_basis':'root confirms same source; server submission IDs retained separately','summary':summarize(groups['8+11'])},'round2_contemporaneous':summarize(by_round['9월 28일 10:00'],'contemporaneous'),'common_opponent_comparisons':comparisons,'limitations':['Current rank does not measure historical opponent version strength.','131 list rows lack maps, opponent submission IDs and engine-side coordinates; historical match IDs/terminations are joined when verified, remaining status is unknown.','Latest errors are team-round totals, not proof of a forfeit in our match.','Round1 now contains6 matches while the older snapshot contained5; do not silently reuse old denominator.','Wilson intervals are descriptive independent-Bernoulli summaries and do not correct clustered/nonrandom Swiss schedules.','Common-team bootstrap is conditional on observed teams; periods and opponent upgrades remain confounded.','No full all-team fixture graph, so no identifiable opponent-adjusted Bradley-Terry recommendation is fit.','8+11 pooling is a same-source time sensitivity; the opponent pool and time differ.']}
write('strength-analysis.json',result);write('enriched-matches.json',rows);write('latest-opponents-loo.json',board);write('termination-merged.json',[{k:r.get(k) for k in ['round_label','submission','opponent','match_id','result','termination_class','termination_reason','termination_source']} for r in rows])
print(json.dumps({'submissions':{s:{'n':r['n'],'w':r['wins'],'l':r['losses'],'rate':r['point_rate'],'opponent_mean_rank':r['opponent_rank']['mean'],'mean_opp_q':r['opponent_point_rate']['mean'],'mean_opp_latest_loo_q':r['opponent_point_rate_latest_loo']['mean'],'coverage':r['reference_coverage'],'top12':r['top12']} for s,r in result['submissions'].items()},'group8+11':result['source_group_8_plus_11']['summary'],'q25':Q25,'q75':Q75},ensure_ascii=False,indent=2))
