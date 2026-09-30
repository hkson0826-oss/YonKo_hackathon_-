"""Local counterexamples with recorded opponent orders fixed; no full-game claims."""
from pathlib import Path
import argparse,gzip,json,sys
default_arena=Path(__file__).resolve().parent.parent
if not (default_arena/'manifest.json').exists():default_arena=Path('/tmp/yk-mission-arena-v1-20261001')
p=argparse.ArgumentParser();p.add_argument('--arena',type=Path,default=default_arena);p.add_argument('--output',type=Path,default=Path(__file__).parent/'counterfactuals.json');args=p.parse_args();root=args.arena
sys.path.insert(0,str(root/'snapshot/yk-development-tools'))
from engine.pipeline import run_turn
from engine.state import Building,new_game
from runner.protocol import parse_commands
from runner.replay import snapshot
from strict_commands import audit_commands, AUDIT_SOURCE_SHA256, AUDIT_FUNCTION_SHA256

def read(run,jid):return json.load(gzip.open(root/'runs'/run/'replays'/(jid+'.json.gz'),'rt'))
def initial(r):
 b=r['map'];return new_game(r['config'],terrain=[list(x) for x in b['terrain']],buildings=[Building(x['id'],x['x'],x['y'],x['type'],x['score']) for x in b['buildings']],bases={t:tuple(v) for t,v in b['bases'].items()})
def before(r,turn):
 s=initial(r)
 for f in r['turns'][:turn-1]:s,_=run_turn(s,parse_commands(f['commands']['Y']),parse_commands(f['commands']['K']))
 return s

def report(s):return {'score':{t:sum(b.score for b in s.buildings.values() if b.owner==t) for t in 'YK'},'F':{t:sum(n for (x,y,side,k),n in s.units.items() if side==t and k=='F') for t in 'YK'},'W':{t:sum(n for (x,y,side,k),n in s.units.items() if side==t and k=='W') for t in 'YK'},'state':snapshot(s)}

def replace_origin(raw,kind,x,y,extra):
 prefix=f'MOVE {x} {y} {kind} '
 out=[c for c in raw if not c.startswith(prefix)]
 # None of these cases use TELE from the changed origin.
 assert not any(c.startswith(f'TELE {x} {y} {kind} ') for c in raw)
 return out+extra

cases=[]
for jid,side,turn,pos in [('1e24903045bab770a3133569','K',69,(2,7)),('38bd769564bcc22f8fbb4d00','Y',49,(7,9))]:
 r=read('pilot-direct',jid);s=before(r,turn);f=r['turns'][turn-1];n=s.get_unit(*pos,side,'F');enemy='Y' if side=='K' else 'K';raw=f['commands'][side]
 actual,_=run_turn(s,parse_commands(f['commands']['Y']),parse_commands(f['commands']['K']))
 alternatives=[]
 for name,dx,dy in [('hold',0,0),('L',-1,0),('R',1,0),('U',0,-1),('D',0,1)]:
  dst=(pos[0]+dx,pos[1]+dy)
  if not s.is_passable(*dst):continue
  alt=replace_origin(raw,'F',*pos,[] if name=='hold' else [f'MOVE {pos[0]} {pos[1]} F {n} {name}'])
  cmd={side:alt,enemy:f['commands'][enemy]};after,res=run_turn(s,parse_commands(cmd['Y']),parse_commands(cmd['K']))
  alternatives.append({'name':name,'changed_commands':alt,'report':report(after),'result':res})
 cases.append({'case':'pilot first F casualty local alternatives','job_id':jid,'turn':turn,'team':side,'changed_origin':pos,'before_full_snapshot':snapshot(s),'actual_commands':f['commands'],'actual_after':report(actual),'alternatives':alternatives})

jid='ca61304a881abc2d17a4d2c8';r=read('development-common',jid);s=before(r,14);alt=s.clone();legacy=s.clone();records=[];audit_records=[]
for turn in range(14,18):
 f=r['turns'][turn-1];cmds=f['commands'];legacy_changed=list(cmds['K'])
 if turn==14:
  assert 'MOVE 11 11 W 5 L' in legacy_changed
  legacy_changed[legacy_changed.index('MOVE 11 11 W 5 L')]='MOVE 11 11 W 4 L'
  legacy_changed.append('MOVE 11 11 W 1 R')
 if turn==15:legacy_changed.append('MOVE 12 11 W 1 U')
 if turn==16:legacy_changed.append('MOVE 12 10 W 1 U')
 changed=list(legacy_changed)
 if turn==15:
  # The redirected W is absent from this stack; request its actual remaining stock.
  assert 'MOVE 10 11 W 10 R' in changed
  changed[changed.index('MOVE 10 11 W 10 R')]='MOVE 10 11 W 9 R'
 audit={'turn':turn,'original':{},'corrected_alternative':{},'legacy_alternative':{}}
 for label,state,lines in [('original',s,cmds),('corrected_alternative',alt,{'Y':cmds['Y'],'K':changed}),('legacy_alternative',legacy,{'Y':cmds['Y'],'K':legacy_changed})]:
  for side in 'YK':
   try:
    checked=audit_commands(state,side,lines[side])
    audit[label][side]={'status':'pass','commands':len(checked)}
   except AssertionError as error:
    audit[label][side]={'status':'fail','error':str(error)}
    assert label=='legacy_alternative' and turn==15 and side=='K',audit
 audit_records.append(audit)
 s,actualresult=run_turn(s,parse_commands(cmds['Y']),parse_commands(cmds['K']))
 alt,altresult=run_turn(alt,parse_commands(cmds['Y']),parse_commands(changed))
 legacy,legacyresult=run_turn(legacy,parse_commands(cmds['Y']),parse_commands(legacy_changed))
 assert snapshot(alt)==snapshot(legacy) and altresult==legacyresult
 records.append({'turn':turn,'actual_commands':cmds,'alternative_K_commands':changed,'legacy_K_commands':legacy_changed,'command_audit':audit,'corrected_matches_legacy_engine_state':True,'actual_after':report(s),'alternative_after':report(alt),'actual_result':actualresult,'alternative_result':altresult})
cases.append({'case':'HALL deadline: reroute one existing W at t14 and adjust its former stack count at t15','job_id':jid,'team':'K','enemy_F_visible_t14':[11,7,1],'changed_first_turn':14,'route':[[11,11],[12,11],[12,10],[12,9]],'records':records,'additional_count_correction':{'turn':15,'original':'MOVE 10 11 W 10 R','corrected':'MOVE 10 11 W 9 R','reason':'One W was redirected at turn14; only nine remain in this departure pool.'},'limitation':'Four-turn recorded-opponent continuation, not a reactive opponent or replay of an improved policy. All opponent lines and other own lines remain original except the tracked W route and explicit t15 count correction. Both sides pass strict pre-engine syntax, budget, path and departure-stock audit each turn; this establishes immediate local preservation only.'})
audit_result={'source':'tests/test_mission_scheduler.py::audit_commands','source_file_sha256':AUDIT_SOURCE_SHA256,'function_sha256':AUDIT_FUNCTION_SHA256,'frozen_function':'strict_commands.py','original_team_turns':8,'original_failures':0,'corrected_alternative_team_turns':8,'corrected_alternative_failures':0,'legacy_failures':[a for a in audit_records if any(x['status']=='fail' for x in a['legacy_alternative'].values())],'all_four_corrected_full_states_equal_legacy_engine_states':True,'records':audit_records}
args.output.with_name('counterfactual-command-audit.json').write_text(json.dumps(audit_result,ensure_ascii=False,indent=2)+'\n')
out=args.output;out.write_text(json.dumps(cases,ensure_ascii=False,indent=2)+'\n')
for c in cases:
 print(c['job_id'],c['case'])
 if 'alternatives' in c:
  print('actual',c['actual_after']['F'],'alts',[(v['name'],v['report']['F']) for v in c['alternatives']])
 else:
  for v in c['records']:print(v['turn'],v['actual_after']['score'],v['alternative_after']['score'])
