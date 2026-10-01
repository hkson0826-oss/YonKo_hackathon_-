from pathlib import Path
import sys,json,subprocess,hashlib
ROOT=Path('/tmp/yk-new-bot-20261001');OUT=Path('/tmp/yk-v9-latest-review-20261001')
sys.path[:0]=[str(ROOT/'tests'),str(ROOT/'yk-development-tools'),str(ROOT/'yk-development-tools/bots/dist/starter')]
from test_mission_scheduler import audit_commands, flags
from mission_scheduler_cases import tactical_state,official_history_before,state_from_observation
from engine.state import new_game
from engine.config import load_config
from engine.pipeline import run_turn
from runner.bots import SubprocessBot
from runner.protocol import serialize_init,serialize_turn
from mapgen import generate,to_state
from submission import inspect_zip

def cases():
 yield 'opening',to_state(generate(22502,load_config()))
 t=tactical_state(turn=160,resource=5);t.buildings[13].owner,t.buildings[13].stage='N',0;t.buildings[1].owner,t.buildings[1].stage='K',2
 s=new_game(load_config(),buildings=t.sorted_buildings(),bases={'Y':(0,1),'K':(14,13)},resources={'Y':5,'K':0});s.turn=159;s.revealed={x:set(s.buildings) for x in 'YK'}
 yield 'terminal_new_flag',s
 for turn in [140,141,159,160]:
  s=tactical_state(turn=turn);s.add_unit(5,5,'Y','F',1);s.add_unit(7,4,'Y','W',2);s.add_unit(6,5,'K','W',1)
  yield 'escort_path_'+str(turn),s
 s=tactical_state(turn=160);s.add_unit(6,5,'Y','F',1);s.add_unit(7,5,'K','W',100)
 yield 'terminal_visible_army',s
 s=tactical_state(turn=160);s.add_unit(6,5,'Y','F',1)
 yield 'terminal_existing_flag',s
 for wc in [3,4]:
  s=tactical_state(turn=160);s.add_unit(6,5,'Y','F',1);s.add_unit(6,5,'Y','W',wc);s.add_unit(7,5,'K','F',1);s.add_unit(7,5,'K','W',3)
  yield 'terminal_escort_'+str(wc),s

report={'candidates':{},'limitations':['Handcrafted valid protocol states plus official masked history; no new full matches.', 'v9-lock has runtime-seeded randomness with no seed CLI; one trial per input.', 'GCC16.2 local build, not GCC12 exact-ZIP runtime qualification.']}
for label,args in [('branch_v9_2',['--attack-seed=20261001']),('main_v9_2',['--attack-seed=20261001']),('branch_lock',[])]:
 src=OUT/label/'main.cpp';binary=OUT/label/'audit-bot'
 build=subprocess.run(['g++','-std=c++20','-O2',str(src),'-o',str(binary)],capture_output=True,text=True)
 result={'build_returncode':build.returncode,'build_stderr':build.stderr,'argv':[str(binary),*args],'cases':[]};report['candidates'][label]=result
 assert build.returncode==0,build.stderr
 def run_case(name,states,side='Y'):
  bot=SubprocessBot('prlimit --as=402653184 -- '+' '.join([str(binary),*args]));bot.send_init(serialize_init(states[0],side));observations=[]
  try:
   for state in states:
    raw,status=bot.play_turn(serialize_turn(state,side,state.turn+1),3 if bot._first_turn else .3)
    commands=audit_commands(state,side,raw or []) if status=='ok' else []
    observations.append({'turn':state.turn+1,'status':status,'raw':raw,'max_response_ms_so_far':bot.max_turn_ms})
    assert status=='ok',observations[-1]
   after,end=run_turn(state,commands if side=='Y' else [],commands if side=='K' else [])
   result['cases'].append({'name':name,'side':side,'input_init':serialize_init(states[0],side),'last_input':serialize_turn(state,side,state.turn+1),'observations':observations,'flags_before':flags(state,side),'flags_after':flags(after,side),'result':end})
   print(label,name,'F',flags(state,side),'->',flags(after,side),end,flush=True)
  finally:bot.close()
 for name,state in cases():run_case(name,[state])
 side,history=official_history_before(29)
 run_case('official_T1_to_T29_masked',[state_from_observation(o) for o in history],side)
for z in ['submission-v9-lock.zip','submission-v9_2.zip']:report[z]=inspect_zip(OUT/z)
(OUT/'sdk-cases.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
