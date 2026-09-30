import sys,json,gzip,hashlib
from pathlib import Path
ROOT=next((p for p in Path(__file__).resolve().parents if (p/'yk-development-tools').is_dir()),Path('/tmp/yk-new-bot-20261001'));OUT=Path(__file__).resolve().parent;sys.path[:0]=[str(ROOT/'yk-development-tools'),str(ROOT/'tests')]
from engine.pipeline import run_turn,step_spawn,step_move,unit_cost
from engine.config import load_config
from mapgen import generate,to_state
from runner.protocol import parse_commands,serialize_init,serialize_turn
from test_mission_scheduler import audit_commands
P=ROOT/'records/benchmarks/mission-20261001/v3/runs/development-common/replays/7b0cbafcd38b265caedd8dd6.json.gz';r=json.load(gzip.open(P,'rt'));state=to_state(generate(r['seed'],load_config()))
def compare(state,frame):
 s=frame['state']
 assert sorted([t,k,x,y,n]for(x,y,t,k),n in state.units.items())==sorted(s['units'])
 assert state.resources==s['resources']
 assert [(b.id,b.owner,b.stage)for b in state.sorted_buildings()]==[(b['id'],b['owner'],b['stage'])for b in s['buildings']]
def points(s):return {t:sum(b.score for b in s.sorted_buildings()if b.owner==t)for t in 'YK'}
def stock(s,t,k):return sum(v for(x,y,team,kind),v in s.units.items()if team==t and kind==k)
for t in r['turns'][:155]:
 y=audit_commands(state,'Y',t['commands']['Y']);k=audit_commands(state,'K',t['commands']['K']);state,_=run_turn(state,y,k);compare(state,t)
(OUT/'turn156-K-legal-input.txt').write_text(serialize_init(state,'K')+serialize_turn(state,'K',156))
def run(alternative):
 s=state.clone();tr=[]
 for frame in r['turns'][155:160]:
  turn=frame['turn'];y=list(frame['commands']['Y']);k=list(frame['commands']['K']);changes=[]
  if alternative:
   replacements={156:('SPAWN W 6 12 8','SPAWN W 4 12 8'),158:('MOVE 12 8 W 7 L','MOVE 12 8 W 5 L'),159:('MOVE 11 8 W 7 L','MOVE 11 8 W 5 L'),160:('MOVE 10 8 W 7 L','MOVE 10 8 W 5 L')}
   if turn in replacements:
    old,new=replacements[turn];assert k.count(old)==1;k[k.index(old)]=new;changes.append([old,new])
   if turn==156:k.insert(0,'SPAWN F 1 12 8');changes.append([None,'SPAWN F 1 12 8'])
   if turn==160:
    old,new='SPAWN W 6 12 8','SPAWN W 5 12 8';assert k.count(old)==1;k[k.index(old)]=new;changes.append([old,new])
   extra={156:'MOVE 12 8 F 1 L',157:'MOVE 11 8 F 1 L',158:'MOVE 10 8 F 1 L',159:'MOVE 9 8 F 1 D'}
   if turn in extra:k.append(extra[turn]);changes.append([None,extra[turn]])
  
  try:yc=audit_commands(s,'Y',y);kc=audit_commands(s,'K',k)
  except AssertionError:print('FAILED',alternative,turn,s.resources,k);raise
  # Visible-cell enemy one-turn upper bound, same categories used by candidate Forecast.
  dest={156:(11,8),157:(10,8),158:(9,8),159:(9,9),160:(9,9)}[turn]
  ew=sum(n for(x,y,t,kind),n in s.units.items()if t=='Y'and kind=='W'and abs(x-dest[0])+abs(y-dest[1])<=1)
  ef=sum(n for(x,y,t,kind),n in s.units.items()if t=='Y'and kind=='F'and abs(x-dest[0])+abs(y-dest[1])<=1)
  enemy_sites=[s.bases['Y']]+[(b.x,b.y)for b in s.sorted_buildings()if b.owner=='Y'and b.btype=='HOSPITAL']
  if any(abs(x-dest[0])+abs(y-dest[1])<=1 for x,y in enemy_sites):ew+=s.resources['Y']//unit_cost(s,'Y','W')
  movement=s.clone();step_spawn(movement,{'Y':[c for c in yc if c.__class__.__name__=='Spawn'],'K':[c for c in kc if c.__class__.__name__=='Spawn']});step_move(movement,{'Y':[c for c in yc if c.__class__.__name__ in['Move','Move2','Tele']],'K':[c for c in kc if c.__class__.__name__ in['Move','Move2','Tele']]})
  own_arrival=movement.get_unit(*dest,'K','W')
  s,result=run_turn(s,yc,kc)
  if not alternative:compare(s,frame)
  tr.append({'turn':turn,'changes':changes,'K_commands':k,'Y_commands':y,'resources':dict(s.resources),'points':points(s),'K_F':stock(s,'K','F'),'destination':dest,'visible_enemy_reachable_W':ew,'visible_enemy_reachable_F':ef,'K_W_arrival_at_destination':own_arrival,'watch_owner':s.building_at(9,9).owner,'result':result})
 return {'turns':tr,'result':result}
out={'replay':str(P),'replay_sha256':hashlib.sha256(P.read_bytes()).hexdigest(),'source_sha256':hashlib.sha256((OUT/'source-v3/main.cpp').read_bytes()).hexdigest(),'input_turn':156,'baseline':run(False),'alternative':run(True),'limitations':['Five-turn fixed original opponent commands; not a new match and not a response-adaptive opponent.','All original other F actions retained. W production is lower by2 at156 and1 at160 to fund F/capture; later two-W departure reductions prevent stock clipping.','Input file is serialize_turn legal K observation; decision uses no hidden score.','Candidate source is unchanged; this is a feasible action witness, not a tested automatic repair.']}
(OUT/'final_flag_counterfactual.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'baseline':out['baseline']['result'],'alternative':out['alternative']['result'],'alternative_turns':[{k:v for k,v in t.items()if k not in ['K_commands','Y_commands','changes']}for t in out['alternative']['turns']]},ensure_ascii=False,indent=2))
