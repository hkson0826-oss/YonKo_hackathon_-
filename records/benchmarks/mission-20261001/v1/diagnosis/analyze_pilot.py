"""Read-only raw-order diagnostics for the frozen mission scheduler arena."""
from collections import Counter, defaultdict
from pathlib import Path
import argparse, gzip, hashlib, json, statistics, sys

default_arena=Path(__file__).resolve().parent.parent
if not (default_arena/'manifest.json').exists():default_arena=Path('/tmp/yk-mission-arena-v1-20261001')
ap=argparse.ArgumentParser();ap.add_argument('--arena',type=Path,default=default_arena);ap.add_argument('--output',type=Path,default=Path(__file__).parent);args=ap.parse_args()
sys.path.insert(0,str(args.arena/'snapshot/yk-development-tools'))
from engine.commands import Move, Move2, Spawn, Tele, DIRECTIONS
from engine.pipeline import run_turn,step_spawn,step_move
from engine.state import Building,new_game
from runner.protocol import parse_commands
from runner.replay import snapshot

def h(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def load(p):return json.loads(gzip.decompress(p.read_bytes()) if p.suffix=='.gz' else p.read_bytes())
def starts(r):
 b=r['map'];return new_game(r['config'],terrain=[list(s) for s in b['terrain']],buildings=[Building(x['id'],x['x'],x['y'],x['type'],x['score']) for x in b['buildings']],bases={t:tuple(p) for t,p in b['bases'].items()})
def stock(s,t,k):return sum(n for (x,y,side,kind),n in s.units.items() if side==t and kind==k)
def flows(s,cmds):
 # Mirror only command acceptance to retain directed edge flow; assert the resulting
 # pool exactly matches SDK step_move before trusting movement diagnostics.
 pool=dict(s.units);arrival=Counter();out=[]
 for t in 'YK':
  teleused=0
  for c in cmds[t]:
   if isinstance(c,Move):
    if c.direction not in DIRECTIONS:continue
    dx,dy=DIRECTIONS[c.direction];src=(c.x,c.y);dst=(c.x+dx,c.y+dy);k=c.kind;want=c.count
    if not s.is_passable(*dst):continue
   elif isinstance(c,Move2):
    d1=DIRECTIONS.get(c.dir1);d2=DIRECTIONS.get(c.dir2)
    if not d1 or not d2:continue
    src=(c.x,c.y);mid=(c.x+d1[0],c.y+d1[1]);dst=(mid[0]+d2[0],mid[1]+d2[1]);k='S';want=c.count
    if not s.is_passable(*mid) or not s.is_passable(*dst):continue
   elif isinstance(c,Tele):
    src=(c.x,c.y);dst=(c.tx,c.ty);k=c.kind;want=min(c.count,s.config['tele']['max_units'])
    bs=s.building_at(*src);bd=s.building_at(*dst)
    if teleused>=s.config['tele']['per_turn'] or src==dst or not bs or not bd:continue
    if bs.btype!='STATION' or bd.btype!='STATION' or bs.owner!=t or bd.owner!=t:continue
    if sum(b.btype=='STATION' and b.owner==t for b in s.buildings.values())<s.config['tele']['min_stations']:continue
   else:continue
   key=(*src,t,k);n=min(max(0,want),pool.get(key,0))
   if n<=0:continue
   if isinstance(c,Tele):teleused+=1
   pool[key]-=n;arrival[(*dst,t,k)]+=n
   out.append({'team':t,'kind':k,'from':list(src),'to':list(dst),'count':n,'tele':isinstance(c,Tele)})
 result=Counter({k:v for k,v in pool.items() if v>0});result.update(arrival)
 return out,{k:v for k,v in pool.items() if v>0},dict(result)

def analyze(row,r,run):
 s=starts(r);bypos={(b['x'],b['y']):b for b in r['map']['buildings']};byid={b['id']:b for b in r['map']['buildings']}
 stats={t:Counter() for t in 'YK'};events={t:[] for t in 'YK'};details={t:[] for t in 'YK'};prevflow={t:Counter() for t in 'YK'};streak={t:Counter() for t in 'YK'};streakmax={t:Counter() for t in 'YK'};firstcap={t:{} for t in 'YK'};lastgain={t:0 for t in 'YK'};windows={t:[] for t in 'YK'}
 for frame in r['turns']:
  turn=frame['turn'];cmds={t:parse_commands(frame['commands'][t]) for t in 'YK'}
  prod=s.clone();step_spawn(prod,{t:[c for c in cmds[t] if isinstance(c,Spawn)] for t in 'YK'})
  edge,pool,expected=flows(prod,cmds);arr=prod.clone();step_move(arr,cmds)
  assert arr.units==expected,(row['job_id'],turn,'flow accounting mismatch')
  after,res=run_turn(s,cmds['Y'],cmds['K'])
  assert snapshot(after)==frame['state'],(row['job_id'],turn,'full transition mismatch')
  for t in 'YK':
   e='K' if t=='Y' else 'Y';st=stats[t];st['frames']+=1
   edgecnt=Counter((tuple(x['from']),tuple(x['to'])) for x in [])
   for x in edge:
    if x['team']==t and x['kind']=='F':edgecnt[(tuple(x['from']),tuple(x['to']))]+=x['count']
   rev=sum(min(n,prevflow[t][(dst,src)]) for (src,dst),n in edgecnt.items());prevflow[t]=edgecnt
   totals=Counter({'F_reverse_flow':rev,'F_moved':sum(edgecnt.values())})
   for k in 'FW':
    totals['produced_'+k]=stock(prod,t,k)-stock(s,t,k);totals['lost_'+k]=stock(arr,t,k)-stock(after,t,k);totals['stock_'+k]=stock(after,t,k)
   for (x,y,side,kind),n in pool.items():
    if side!=t:continue
    if kind=='F':
     b=s.building_at(x,y);label='off_building' if b is None else 'own_building' if b.owner==t else 'other_building'
     totals['F_stationary_'+label]+=n
    if kind=='W':totals['W_stationary']+=n
   ownf={(x,y):n for (x,y,side,k),n in s.units.items() if side==t and k=='F'}
   nextstreak=Counter()
   for pos,n in ownf.items():
    stationary=pool.get((*pos,t,'F'),0)
    if stationary:
     nextstreak[pos]=streak[t][pos]+1;streakmax[t][pos]=max(streakmax[t][pos],nextstreak[pos])
   streak[t]=nextstreak
   death=[]
   for (x,y,side,k),n in arr.units.items():
    if side==t and k=='F' and n>after.units.get((x,y,t,k),0):
     b=s.building_at(x,y);death.append({'x':x,'y':y,'count':n-after.units.get((x,y,t,k),0),'own_W_arrival':arr.get_unit(x,y,t,'W'),'enemy_W_arrival':arr.get_unit(x,y,e,'W'),'enemy_W_before':s.get_unit(x,y,e,'W'),'building':None if b is None else {'id':b.id,'type':b.btype,'owner_before':b.owner},'incoming':[]})
   # Store without guessing unit identity. A repeated stationary cell can contain different F.
   for d in death:
    d['incoming']=[v for v in edge if v['to']==[d['x'],d['y']]]
   changed=[];gain=False
   for bid,b in after.buildings.items():
    old=s.buildings[bid]
    if b.owner!=old.owner:
     changed.append({'building':byid[bid],'from':old.owner,'to':b.owner})
     if b.owner==t:firstcap[t].setdefault(str(bid),turn);gain=True
   score=sum(b.score for b in after.buildings.values() if b.owner==t)
   if gain:
    if turn-lastgain[t]-1>=10:windows[t].append({'start':lastgain[t]+1,'end':turn-1,'length':turn-lastgain[t]-1})
    lastgain[t]=turn
   for k,v in totals.items():
    if not k.startswith('stock_'):st[k]+=v;st[('early20_' if turn<=20 else 'later_')+k]+=v
   ownw=[n for (x,y,side,k),n in after.units.items() if side==t and k=='W'];totals['largest_W']=max(ownw,default=0);totals['score']=score
   totals['owned_buildings']=sum(b.owner==t for b in after.buildings.values())
   info={'turn':turn,**totals,'F_cells':[[x,y,n] for (x,y,side,k),n in after.units.items() if side==t and k=='F']}
   details[t].append(info)
   if death or rev>=2 or (changed and turn<=25):
    events[t].append({'turn':turn,'deaths':death,'reversed_F_edge_flow':rev,'ownership_changes':changed,'commands':frame['commands'][t],'enemy_commands':frame['commands'][e],'before_units':snapshot(s)['units'],'after_units':frame['state']['units'],'before_resources':s.resources,'after_resources':after.resources})
  s=after
 out=[]
 for t in 'YK':
  if len(r['turns'])-lastgain[t]>=10:windows[t].append({'start':lastgain[t]+1,'end':len(r['turns']),'length':len(r['turns'])-lastgain[t]})
  bot=row['candidate'] if row['team']==t else row['opponent'];opp=row['opponent'] if row['team']==t else row['candidate']
  st=stats[t];out.append({'run':run,'job_id':row['job_id'],'seed':row['map_seed'],'team':t,'bot':bot,'opponent':opp,'candidate_view':t==row['team'],'win':r['result']['winner']==t,'turns':len(r['turns']),'score':r['result']['score'][t], 'stats':st,'first_capture':firstcap[t],'stationary_cell_streaks': [{'cell':list(p),'length':n,'building':bypos.get(p)} for p,n in streakmax[t].most_common(8)],'no_new_owned_building_windows':windows[t],'events':events[t],'timeline':details[t]})
 return out

players=[];hashes={};verified=0
for run in ('pilot-direct','development-common'):
 path=args.arena/'runs'/run/'results.jsonl';hashes[str(path)]=h(path)
 for row in [json.loads(x) for x in path.read_text().splitlines() if x.strip()]:
  if row['status']!='complete':continue
  p=path.parent/row['replay'];hashes[str(p)]=h(p);r=load(p)
  players.extend(analyze(row,r,run));verified+=len(r['turns'])
manifest=load(args.arena/'manifest.json')
summary={'games':len(players)//2,'verified_turns':verified,'input_sha256':hashes,'mission_source_sha256':manifest['bots']['mission']['source_sha256'],'v8_source_sha256':manifest['bots']['v8']['source_sha256'],'groups':{}}
for run in ('pilot-direct','development-common'):
 for bot in ('mission','v8'):
  rows=[r for r in players if r['run']==run and r['bot']==bot]
  keys=sorted({k for r in rows for k in r['stats']})
  group={'games':len(rows),'wins':sum(r['win'] for r in rows),'W_stationary_fraction':sum(r['stats']['W_stationary'] for r in rows)/sum(t['stock_W']+t['lost_W'] for r in rows for t in r['timeline']),'means':{k:statistics.mean(r['stats'][k] for r in rows) for k in keys}}
  for turn in (10,20,40,80,120):
   pts=[r['timeline'][turn-1] for r in rows if len(r['timeline'])>=turn]
   group[str(turn)]={'count':len(pts),**{k:statistics.mean(p.get(k,0) for p in pts) for k in ('score','owned_buildings','stock_F','stock_W','largest_W')}}
  summary['groups'][run+'/'+bot]=group
args.output.mkdir(parents=True,exist_ok=True)
(args.output/'diagnostics.json.gz').write_bytes(gzip.compress(json.dumps({'method':{'movement':'Accepted movement flow mirrors SDK rules and is asserted equal to official step_move each frame. Opposite flow is aggregate proxy, not tracked individual F.','full_transitions':'Both recorded raw command lists parsed and replayed through official run_turn; every complete snapshot must match.','stationary':'Units remaining in origin pool before arrivals; staying is not inherently wasteful. Cell streak is continuity of some resident F, not identity.','targets':'No internal goal recorded; no-new-ownership intervals and cell stagnation are observable proxies only.','hidden':'Full replay data used offline only.'},'players':players},ensure_ascii=False).encode()))
(args.output/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'games':summary['games'],'verified_turns':verified,'groups':{k:{'games':v['games'],'wins':v['wins'],'F_reverse_flow':v['means'].get('F_reverse_flow'),'F_stationary_off_building':v['means'].get('F_stationary_off_building')} for k,v in summary['groups'].items()}},ensure_ascii=False))
