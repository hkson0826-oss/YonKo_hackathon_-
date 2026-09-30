from pathlib import Path
import sys,json,hashlib
ROOT=Path('/tmp/yk-new-bot-20261001');sys.path[:0]=[str(ROOT/'tests'),str(ROOT/'yk-development-tools')]
from mission_scheduler_cases import local_history_before
from test_mission_scheduler import audit_commands,flags
from runner.bots import SubprocessBot
from runner.protocol import serialize_init,serialize_turn,parse_commands
from engine.pipeline import run_turn
path=ROOT/'records/benchmarks/mission-20261001/v3/runs/development-common/replays/7b0cbafcd38b265caedd8dd6.json.gz'
history,replay=local_history_before(path,156)
binary=sys.argv[1] if len(sys.argv)>1 else '/tmp/yk-mission-quota-v3-20261001'
bot=SubprocessBot('prlimit --as=402653184 -- '+binary);bot.send_init(serialize_init(history[0],'K'));matched=0
try:
 for index,state in enumerate(history[:-1]):
  raw,status=bot.play_turn(serialize_turn(state,'K',state.turn+1),3 if bot._first_turn else .3)
  assert status=='ok';audit_commands(state,'K',raw)
  matched+=raw==replay['turns'][index]['commands']['K']
 state=history[-1];trace={'matched':matched,'history_count':len(history)-1,'turns':[]}
 for _ in range(5):
  raw,status=bot.play_turn(serialize_turn(state,'K',state.turn+1),.3);assert status=='ok';commands=audit_commands(state,'K',raw)
  before=flags(state,'K');state,result=run_turn(state,[],commands)
  row={'turn':state.turn,'raw':raw,'flags_before':before,'flags_after':flags(state,'K'),'target_owner':state.building_at(9,9).owner,'result':result}
  trace['turns'].append(row);print(row)
 trace['max_response_ms']=bot.max_turn_ms
 Path('/tmp/yk-mission-quota-'+Path(binary).name+'-20261001.json').write_text(json.dumps(trace,ensure_ascii=False,indent=2)+'\n')
finally:bot.close()
