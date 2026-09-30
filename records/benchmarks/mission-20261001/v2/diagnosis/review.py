"""Bounded v1/v2 review: existing outcome tables and snapshot-based W movement accounting."""
from collections import Counter
from pathlib import Path
import argparse,ast,gzip,hashlib,json,statistics,sys
ap=argparse.ArgumentParser();ap.add_argument('--v1',type=Path,default=Path('/tmp/yk-mission-arena-v1-20261001'));ap.add_argument('--v2',type=Path,default=Path('/tmp/yk-mission-arena-v2-20261001'));ap.add_argument('--output',type=Path,default=Path(__file__).parent);args=ap.parse_args()
sys.path.insert(0,str(args.v2/'snapshot/yk-development-tools'))
from engine.commands import Move,Move2,Spawn,Tele,DIRECTIONS
from engine.pipeline import step_spawn,step_move
from engine.state import Building,new_game
from runner.protocol import parse_commands

def read(p):return json.loads(gzip.decompress(p.read_bytes()) if p.suffix=='.gz' else p.read_bytes())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def initial(r):
 b=r['map'];return new_game(r['config'],terrain=[list(x) for x in b['terrain']],buildings=[Building(x['id'],x['x'],x['y'],x['type'],x['score']) for x in b['buildings']],bases={t:tuple(v) for t,v in b['bases'].items()})

# Reuse only the previously validated accepted-flow function, without executing
# its full-match verification entry point or importing candidate source.
flow_source=Path('/tmp/yk-new-bot-20261001/records/benchmarks/mission-20261001/v1/diagnosis/analyze_pilot.py')
node=next(n for n in ast.parse(flow_source.read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='flows')
exec(compile(ast.Module(body=[node],type_ignores=[]),str(flow_source),'exec'))

out={'scope':'No full run_turn replay repeated. Existing audited results plus official step_spawn/step_move snapshot accounting for W residency; representative raw frames preserved.','flow_function_sha256':hashlib.sha256(ast.get_source_segment(flow_source.read_text(),node).encode()).hexdigest(),'input_sha256':{},'versions':{},'representatives':{}}
for label,root,candidate,jid in [('v1',args.v1,'mission','ca61304a881abc2d17a4d2c8'),('v2',args.v2,'mission2','926f5990f21dee0d30a9187c')]:
 p=root/'development-common-analysis.json';a=read(p);out['input_sha256'][str(p)]=sha(p);m=read(root/'manifest.json')
 groups={}
 for bot in (candidate,'v8'):
  b=a['by_bot'][bot];groups[bot]={'overall':b['overall'],'t20':b['behavior']['checkpoints']['20'],'t40':b['behavior']['checkpoints']['40'],'final':b['behavior']['checkpoints']['final'],'mean_losses':b['behavior']['mean_losses'],'source_sha256':m['bots'][bot]['source_sha256']}
 row=next(r for r in a['players'] if r['job_id']==jid and r['bot']==candidate)
 p=root/'runs/development-common'/row['replay'];r=read(p);out['input_sha256'][str(p)]=sha(p)
 enemy=next(r for r in a['players'] if r['job_id']==jid and r['bot']=='j_balanced_portfolio')
 selected=[]
 for turn in range(10,21):
  f=r['turns'][turn-1];before=r['turns'][turn-2]['state'];changes=[{'id':b['id'],'from':before['buildings'][b['id']]['owner'],'to':b['owner']} for b in f['state']['buildings'] if b['owner']!=before['buildings'][b['id']]['owner']]
  selected.append({'turn':turn,'commands':f['commands'],'before_units':before['units'],'after_units':f['state']['units'],'ownership_changes':changes})
 repeated=next(x for x in a['players'] if x['bot']=='v8' and x['map_seed']==19013 and x['team']=='K' and x['opponent']=='j_balanced_portfolio')
 out['representatives'][label]={'candidate':candidate,'job_id':jid,'replay':str(p),'result':r['result'],'first_capture':row['first_capture_turn_by_building'],'economic_losses':row['home_economy_loss_events'],'t20':row['checkpoints']['20'],'final':row['checkpoints']['final'],'losses':row['losses'],'enemy_losses':enemy['losses'],'frames':selected,'v8_same_condition':{'job_id':repeated['job_id'],'turns':repeated['turns'],'score_margin':repeated['score_margin'],'final':repeated['checkpoints']['final']}}
 out['versions'][label]={'candidate':candidate,'j_balanced_source_sha256':m['bots']['j_balanced_portfolio']['source_sha256'],'groups':groups}

# Only v2 common is newly counted; the v1 metric was already fully verified.
rows=[json.loads(x) for x in (args.v2/'runs/development-common/results.jsonl').read_text().splitlines()]
counts={b:Counter() for b in ['mission2','v8']};game_metrics=[]
for row in rows:
 p=args.v2/'runs/development-common'/row['replay'];r=read(p);s=initial(r);t=row['team'];metrics=Counter()
 for f in r['turns']:
  cmds={team:parse_commands(f['commands'][team]) for team in 'YK'}
  produced=s.clone();step_spawn(produced,{team:[c for c in cmds[team] if isinstance(c,Spawn)] for team in 'YK'})
  _,pool,expected=flows(produced,cmds);moved=produced.clone();step_move(moved,cmds)
  assert moved.units==expected
  metrics['frames']+=1
  metrics['W_pre_move']+=sum(n for (x,y,side,k),n in produced.units.items() if side==t and k=='W')
  metrics['W_stationary']+=sum(n for (x,y,side,k),n in pool.items() if side==t and k=='W')
  snap=f['state'];s.units={(x,y,side,k):n for side,k,x,y,n in snap['units']};s.resources=dict(snap['resources'])
  for b in snap['buildings']:s.buildings[b['id']].owner=b['owner'];s.buildings[b['id']].stage=b['stage']
 metrics['games']=1;counts[row['candidate']].update(metrics)
 game_metrics.append({'job_id':row['job_id'],'candidate':row['candidate'],'seed':row['map_seed'],'team':t,'opponent':row['opponent'],**metrics,'W_stationary_fraction':metrics['W_stationary']/metrics['W_pre_move']})
for b,c in counts.items():out['versions']['v2']['groups'][b]['movement']={**c,'W_stationary_fraction':c['W_stationary']/c['W_pre_move']}
v1summary=read(Path('/tmp/yk-new-bot-20261001/records/benchmarks/mission-20261001/v1/diagnosis/summary.json'))
for b in ['mission','v8']:
 g=v1summary['groups']['development-common/'+b];out['versions']['v1']['groups'][b]['movement']={'W_stationary_fraction':g['W_stationary_fraction'],'mean_W_stationary':g['means']['W_stationary']}
out['v2_movement_by_game']=game_metrics
args.output.mkdir(exist_ok=True);(args.output/'evidence.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
for label,v in out['versions'].items():
 for bot,g in v['groups'].items():print(label,bot,'wins',g['overall']['wins'],'t20 score',g['t20']['means']['score_full_replay'],'Wstill',g['movement']['W_stationary_fraction'])
