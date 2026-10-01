"""Arithmetic for the three current official sorting metrics, not old adjusted score."""
import hashlib
import json
from pathlib import Path
H=Path(__file__).resolve().parent;D=H.parent/'data'
m=json.loads((D/'matches.json').read_text());rows=[dict(zip(m['columns'],r)) for r in m['rows'] if r[0]=='10월 1일 17:00']
b=json.loads((D/'leaderboard-latest.json').read_text());board={r[2]:dict(zip(b['columns'],r)) for r in b['rows']}
assert len(rows)==board['강릉']['games']==24 and sum(r['points']==1 for r in rows)==board['강릉']['wins']==12
items=[]
for row in rows:
 if row['points']:
  opponent=board[row['opponent']];q=(opponent['wins']+.5*opponent['draws'])/opponent['games'];items.append({'opponent':row['opponent'],'outcome_points':row['points'],'opponent_point_rate':q,'weighted_contribution':row['points']*q})
result={'round':'10월 1일 17:00','submission':11,'point_rate':sum(r['points'] for r in rows)/len(rows),'win_rate':sum(r['points']==1 for r in rows)/len(rows),'opponent_weighted_tiebreak_numerator':sum(x['weighted_contribution'] for x in items),'games':len(rows),'opponent_weighted_tiebreak':sum(x['weighted_contribution'] for x in items)/len(rows),'winning_drawn_opponent_contributions':items,'scope':'Arithmetic from latest help and full own24/leaderboard87; no displayed third-tiebreak value or all-team fixtures to independently verify rank55. This is not the historical adjusted score.','source_sha256':{name:hashlib.sha256((D/name).read_bytes()).hexdigest() for name in ['matches.json','leaderboard-latest.json','leaderboard-help.json']}}
(H/'latest-official-metrics.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
