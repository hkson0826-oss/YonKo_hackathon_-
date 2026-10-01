"""Reproduce documented point rates; never invent the undisclosed adjusted formula."""
import argparse
import hashlib
import json
from pathlib import Path
HERE=Path(__file__).resolve().parent
parser=argparse.ArgumentParser();parser.add_argument('--repo-root',type=Path,default=next((p for p in HERE.parents if (p/'records/official').is_dir()),Path('/tmp/yk-new-bot-20261001')));ARGS=parser.parse_args();ROOT=ARGS.repo_root.resolve()
paths=['records/official/round1/site-observations.json','records/official/round2/site-observations.json','records/official/opponent-intel-20260928/collection-followup.json','records/official/latest-20261001/leaderboard.json','records/research/new-bot-20261001/site-review.json','docs/10-사이트운영과보정점수.md']
first=json.loads((ROOT/paths[0]).read_text())['leaderboard']
second=json.loads((ROOT/paths[1]).read_text())['leaderboard']
latest=json.loads((ROOT/paths[3]).read_text())
old=[]
for label,row,key in [('2026-09-27 22:00',first,'adjusted_score_percent'),('2026-09-28 10:00',second,'our_adjusted_percent')]:
 rate=(row['wins']+.5*row['draws'])/row['games']
 assert abs(rate-row['raw_point_rate'])<1e-12
 old.append({'published_kst':label,'wins':row['wins'],'draws':row['draws'],'losses':row['losses'],'games':row['games'],'reproduced_raw_point_rate':rate,'displayed_adjusted_percent':row[key],'raw_percent_minus_adjusted_percent':100*rate-row[key],'exact_adjusted_formula_disclosed':row['formula_disclosed']})
checks=[]
for row in latest['rows']:
 assert row['wins']+row['draws']+row['losses']==row['games']
 value=(row['wins']+.5*row['draws'])/row['games']
 assert abs(value-row['point_rate'])<1e-12
 checks.append({'team':row['team'],'games':row['games'],'reproduced':value,'recorded':row['point_rate'],'match':True})
result={'status':'complete_existing_evidence_only_no_new_submission_ranking','old_adjusted_metric':old,'latest_recorded_publication':latest['published_at'],'latest_checked_at':latest['checked_at'],'latest_snapshot_total_teams':latest['total_teams'],'latest_preserved_rows':len(latest['rows']),'point_rate_checks':checks,'conclusions':['All retained point rates reproduce from W/D/L.','No exact old adjusted-score implementation or reproduction is present in the examined official records.','The historical opponent-weighted tiebreak formula is not identified as the old adjusted-score formula.','Latest stored leaderboard is a partial retained snapshot; it cannot represent all teams.'],'source_sha256':{rel:hashlib.sha256((ROOT/rel).read_bytes()).hexdigest() for rel in paths}}
(HERE/'formula-checks.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'old_adjusted_examples':old,'retained_rows_reproduced':len(checks),'total_teams':latest['total_teams']},ensure_ascii=False,indent=2))
