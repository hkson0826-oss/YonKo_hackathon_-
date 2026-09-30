import sys,json,gzip
from pathlib import Path
sys.dont_write_bytecode=True
root=Path('/home/dlwltkd/YonKo_hackathon_-');sys.path.insert(0,str(root/'yk-development-tools'))
from mapgen import generate,to_state
from engine.pipeline import run_turn
from runner.protocol import parse_commands
from runner.replay import snapshot
rows=[]
for rid,team,x,y in [('4c3c7c788e84b8d7e1630fdd','K',10,5),('0bae688770a51815defd7530','K',10,5),('918d12cb7db927282197b8da','Y',4,9),('f1c487612439cfec8e08ea50','Y',4,9)]:
 p=root/f'records/deadline/20260929/selection/run/replays/{rid}.json.gz';r=json.load(gzip.open(p,'rt'));s=to_state(generate(r['seed'],r['config']))
 for f in r['turns'][:8]:
  s,_=run_turn(s,parse_commands(f['commands']['Y']),parse_commands(f['commands']['K']))
  assert snapshot(s)==f['state'],(rid,f['turn'])
 rows.append({'replay_id':rid,'verified_official_turns':8,'team':team,'target':[x,y],'target_w_after_turn8':s.units.get((x,y,team,'W'),0)})
out={'all_passed':True,'official_transitions':32,'cases':rows,'meaning':'Exact candidate equals recorded baseline action at turn8 (C++ probe); official engine replay independently reproduces resulting W6/W4, versus old guard3 W7/W5. No full-game counterfactual or win-rate claim.'}
Path(__file__).with_name('official-check.json').write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(out,indent=2))
