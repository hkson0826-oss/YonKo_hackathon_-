import sys,json,gzip,subprocess,hashlib
from pathlib import Path
sys.path.insert(0,'/tmp/yk-new-bot-20261001/yk-development-tools')
from engine.pipeline import run_turn
from engine.config import load_config
from mapgen import generate,to_state
from runner.protocol import serialize_init,serialize_turn,parse_commands
P=Path('/tmp/yk-mission-arena-v1-20261001/runs/development-common/replays/ca61304a881abc2d17a4d2c8.json.gz')
r=json.load(gzip.open(P,'rt'));s=to_state(generate(r['seed'],load_config()));data=[serialize_init(s,'K')];states=[]
for t in r['turns']:
 data.append(serialize_turn(s,'K',t['turn']))
 if 12<=t['turn']<=20:states.append({'turn':t['turn'],'units':[list(k)+[v] for k,v in s.units.items()], 'buildings':[(b.id,b.owner,b.stage)for b in s.sorted_buildings()]})
 s,_=run_turn(s,parse_commands(t['commands']['Y']),parse_commands(t['commands']['K']))
proc=subprocess.run([str(Path(__file__).resolve().parent/'trace')],input=''.join(data),text=True,capture_output=True,check=True)
commands=[[s for s in p.splitlines()if s.strip()]for p in proc.stdout.strip().split('END')if p.strip()]
assert len(commands)==len(r['turns']);trace=[json.loads(s)for s in proc.stderr.splitlines()]
out={'replay':str(P),'replay_sha256':hashlib.sha256(P.read_bytes()).hexdigest(),'turns':len(r['turns']),'command_reproduction_mismatches':[t['turn']for a,t in zip(commands,r['turns'])if a!=t['commands']['K']], 'map':r['map'],'trace':trace,'input_states':states}
Path(__file__).resolve().with_name('audit.json').write_text(json.dumps(out,ensure_ascii=False,indent=2))
print(json.dumps({'turns':out['turns'],'mismatches':out['command_reproduction_mismatches'],'events':len(trace)}))
