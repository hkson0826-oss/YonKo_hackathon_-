import gzip,json,hashlib
from pathlib import Path
root=Path('/home/dlwltkd/YonKo_hackathon_-'); out=Path(__file__).parent
sources=[]; cases=[]
for rid,team,name,guardrid in [('4c3c7c788e84b8d7e1630fdd','K','recorded_K_contact','0bae688770a51815defd7530'),('918d12cb7db927282197b8da','Y','recorded_Y_balanced','f1c487612439cfec8e08ea50')]:
 p=root/f'records/deadline/20260929/selection/run/replays/{rid}.json.gz';r=json.load(gzip.open(p,'rt'));s=r['turns'][6]['state'];m=r['map'];lines=['{ p::Init in; in.width=in.height=15;']
 lines += ['in.terrain={'+','.join(json.dumps(x) for x in m['terrain'])+'};']
 for t in 'YK':x,y=m['bases'][t];lines += [f'in.bases[{"YK".index(t)}]={{{x},{y}}};']
 for b in m['buildings']:lines += [f'in.buildings.push_back({{{b["id"]},{b["x"]},{b["y"]},"{b["type"]}"}});']
 lines += ['board=Board{};board.init(in);State s; s.turn=7;']
 for t in 'YK':lines += [f's.res[{"YK".index(t)}]={s["resources"][t]};']
 for t,k,x,y,n in s['units']:lines += [f's.u[{"YK".index(t)}][{"FWS".index(k)}][{x+15*y}]={n};']
 for i,b in enumerate(s['buildings']):lines += [f's.owner[{i}]={"NYK".index(b["owner"])-1};s.stage[{i}]={b["stage"]};']
 def action_cpp(frame,var):
  z=[f'Action {var};']
  for c in frame['applied'][team]:
   typ=c['cmd'];k='FWS'.index(c.get('kind','F'))
   if typ=='Spawn':x,y=(c['x'],c['y']) if c['x'] is not None else m['bases'][team];z += [f'{var}.spawn.push_back({{{k},{x+15*y},{c["count"]}}});']
   elif typ=='Move':d={'U':-15,'D':15,'L':-1,'R':1}[c['direction']];src=c['x']+15*c['y'];z += [f'{var}.moves.push_back({{{k},{src},{src+d},{c["count"]}}});']
   elif typ=='Tele':src=c['x']+15*c['y'];dst=c['tx']+15*c['ty'];z += [f'{var}.moves.push_back({{{k},{src},{dst},{c["count"]},true}});']
   elif typ=='Priority':
    ids={(b['x'],b['y']):i for i,b in enumerate(m['buildings'])};z += [f'{var}.priority={{'+','.join(str(ids[tuple(x)]) for x in c['coords'])+'};']
   else:raise ValueError(typ)
  return z
 gp=root/f'records/deadline/20260929/selection/run/replays/{guardrid}.json.gz';g=json.load(gzip.open(gp,'rt'))
 assert g['turns'][6]['state']==s
 lines += action_cpp(r['turns'][7],'seed')+action_cpp(g['turns'][7],'actual')
 lines += [f'check("{name}_old_exact",equal(old_guard(s,{"YK".index(team)},seed),actual));',f'check("{name}_candidate_preserves_seed",equal(deadline_guard(s,{"YK".index(team)},seed),a_clean(s,{"YK".index(team)},seed)));','}']
 cases.append('\n'.join(lines));sources.append({'baseline':rid,'guard3':guardrid,'baseline_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'guard3_sha256':hashlib.sha256(gp.read_bytes()).hexdigest(),'state_turn':7,'action_turn':8})
(out/'fixtures.inc').write_text('\n'.join(cases));(out/'fixture-sources.json').write_text(json.dumps(sources,indent=2)+'\n')
