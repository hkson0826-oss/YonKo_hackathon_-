"""Bounded one-turn official counterfactuals; enemy stays stationary."""
from pathlib import Path
import json, subprocess, sys, hashlib, tempfile
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT)); sys.path.insert(0,str(ROOT/'tests'))
from tests.test_mission_scheduler import audit_commands, flags, parse_commands, run_turn, Spawn, Move, Tele, Priority, DIRECTIONS
from mission_scheduler_cases import state_from_observation, tactical_state
HERE=Path(__file__).resolve().parent
KINDS='FWS'; TYPES=['PLAZA','HALL','STATION','LIBRARY','ENG','HOSPITAL','WATCH','DEPOT']
def encode(state,lines):
 out=[state.turn,0,state.resources['Y'],state.resources['K']]
 out += [int(state.is_passable(x,y)) for y in range(15) for x in range(15)]
 out += [state.bases[t][0]+15*state.bases[t][1] for t in 'YK']; out += [len(state.buildings)]
 bs=list(state.buildings.values())
 for b in bs: out += [b.x+15*b.y,TYPES.index(b.btype),-1 if b.owner=='N' else 'YK'.index(b.owner),b.stage]
 out += [len(state.units)]
 for (x,y,t,k),n in state.units.items():out += ['YK'.index(t),KINDS.index(k),x+15*y,n]
 cmds=parse_commands(lines); spawn=[];moves=[];prio=[]
 for c in cmds:
  if isinstance(c,Spawn):
   x,y=state.bases['Y'] if c.x is None else (c.x,c.y);spawn.append([KINDS.index(c.kind),x+15*y,c.count])
  elif isinstance(c,(Move,Tele)):
   if isinstance(c,Move):dx,dy=DIRECTIONS[c.direction];tx,ty=c.x+dx,c.y+dy
   else:tx,ty=c.tx,c.ty
   moves.append([KINDS.index(c.kind),c.x+15*c.y,tx+15*ty,c.count,int(isinstance(c,Tele))])
  else:prio=[next(i for i,b in enumerate(bs) if (b.x,b.y)==coord) for coord in c.coords]
 out += [len(spawn)]+sum(spawn,[])+[len(moves)]+sum(moves,[])+[len(prio)]+prio
 return ' '.join(map(str,out))+'\n'
def run_case(binary,name,state,original):
 before=audit_commands(state,'Y',original)
 fixed=subprocess.check_output([str(binary)],input=encode(state,original),text=True).splitlines()
 after=audit_commands(state,'Y',fixed)
 old,_=run_turn(state,before,[]);new,_=run_turn(state,after,[])
 assert [x for x in before if isinstance(x,Spawn) or (isinstance(x,(Move,Tele)) and x.kind=='W')]==[x for x in after if isinstance(x,Spawn) or (isinstance(x,(Move,Tele)) and x.kind=='W')]
 return {'case':name,'old_F':flags(old,'Y'),'guarded_F':flags(new,'Y'),'before_F':flags(state,'Y'),'original_commands':original,'guarded_commands':fixed,'strict_command_audit':'pass','W_and_production_preserved':True}
def main():
 evidence=json.loads((ROOT/'records/official/round-20261001-1000/analysis/diagnosis-cases.json').read_text())
 cases=[('2325-T16',evidence['stationary_safety']['evidence']),('占쏙옙-T159',evidence['late_reversal']['stationary_F_loss_evidence'])]
 results=[]
 with tempfile.TemporaryDirectory() as temp:
  binary=Path(temp)/'guard_probe'
  subprocess.run(['g++','-std=c++20','-O2','-x','c++',str(HERE/'guard_probe.txt'),'-o',str(binary)],check=True)
  for name,case in cases:
   result=run_case(binary,name,state_from_observation(case['legal_input_observation']),case['actual_own_commands']['lines'])
   result['gameId']=case['gameId'];result['source_sha256']=case['source_sha256'];result['command_turn']=case['command_turn']
   assert result['guarded_F']==result['old_F']+1,result
   results.append(result)
  # A fresh W can leave its birth site and provide a same-turn escort.
  s=tactical_state(resource=6);s.bases['Y']=(6,5);s.add_unit(6,5,'Y','F',1);s.add_unit(7,5,'K','W',2)
  r=run_case(binary,'newborn_W_escort',s,['SPAWN W 2','MOVE 6 5 W 2 R','MOVE 6 5 F 1 R']);assert r['guarded_commands']==r['original_commands'] and r['guarded_F']==1;results.append(r)
  # W at the destination provides no protection after its actual departure.
  s=tactical_state(resource=6);hospital=s.building_at(2,2);hospital.owner='Y';hospital.stage=2;s.add_unit(3,2,'Y','F',1);s.add_unit(2,2,'K','W',2)
  r=run_case(binary,'departing_newborn_W_is_not_escort',s,['SPAWN W 2 2 2','MOVE 2 2 W 2 D','MOVE 3 2 F 1 L']);assert r['old_F']==0 and r['guarded_F']==1;results.append(r)
 data={'candidate_main_sha256':hashlib.sha256((HERE/'main.cpp').read_bytes()).hexdigest(),'scope':'One legal SDK turn with enemy no production/movement; not a replay of adaptive whole-game outcomes. All fixtures are legal pre-action states; owning a hospital does not prevent enemy W from standing there without an enemy F.','cases':results}
 (HERE/'guard-contracts.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n');print(json.dumps([{k:v for k,v in r.items() if not k.endswith('commands')} for r in results],ensure_ascii=False,indent=2))
if __name__=='__main__':main()
