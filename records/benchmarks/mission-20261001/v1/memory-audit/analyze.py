import sys,json,gzip,subprocess,hashlib
from pathlib import Path
from collections import Counter
sys.path.insert(0,'/tmp/yk-new-bot-20261001/yk-development-tools')
from engine.pipeline import run_turn
from engine.config import load_config
from mapgen import generate,to_state
from runner.protocol import serialize_init,serialize_turn,parse_commands

ROOT=Path('/tmp/yk-mission-arena-v1-20261001/runs')
OUT=Path('/tmp/yk-mission-memory-audit-20261001');OUT.mkdir(exist_ok=True)
def audit(run,row):
    path=ROOT/run/'replays'/f"{row['job_id']}.json.gz"
    replay=json.load(gzip.open(path,'rt'));side=row['team']
    state=to_state(generate(row['map_seed'],load_config()))
    data=[serialize_init(state,side)]
    previous=[];statebrief=[]
    for turn in replay['turns']:
        data.append(serialize_turn(state,side,turn['turn']))
        statebrief.append({'turn':turn['turn'],'resources':state.resources[side],
          'F':sum(n for (x,y,t,k),n in state.units.items() if t==side and k=='F'),
          'W':sum(n for (x,y,t,k),n in state.units.items() if t==side and k=='W'),
          'owned':[(b.id,b.btype,b.x,b.y,b.score)for b in state.sorted_buildings()if b.owner==side]})
        state,_=run_turn(state,parse_commands(turn['commands']['Y']),parse_commands(turn['commands']['K']))
    process=subprocess.run(['/tmp/yk-mission-memory-trace-20261001'],input=''.join(data),text=True,capture_output=True,check=True)
    commands=[part.splitlines() for part in process.stdout.strip().split('END') if part.strip()]
    commands=[[s for s in part if s.strip()]for part in commands]
    trace=[json.loads(s)for s in process.stderr.splitlines()]
    assert len(trace)==len(replay['turns'])
    mismatches=[n+1 for n,(a,t)in enumerate(zip(commands,replay['turns']))if a!=t['commands'][side]]
    stats=Counter();samples=[];previous_moves={}
    for t,brief,turn in zip(trace,statebrief,replay['turns']):
        stats['flag_turns']+=sum(1 for _ in t['tokens']);stats['recovered_valid_missions']+=sum(v[1]>=0 for v in t['tokens'])
        stats['continued_missions']+=sum(v[3]>0 for v in t['after'])
        stats['active_output_missions']+=len(t['after'])
        stats['stalled_output_missions']+=sum(v[4]>0 for v in t['after'])
        stats['three_stall_output_missions']+=sum(v[4]>=3 for v in t['after'])
        moveflows=Counter();holds=Counter()
        for cmd in turn['commands'][side]:
            tok=cmd.split()
            if tok[0]=='MOVE' and tok[3]=='F':
                src=int(tok[1])+15*int(tok[2]);dst=src+{'U':-15,'D':15,'L':-1,'R':1}[tok[5]]
                moveflows[(src,dst)]+=int(tok[4]);stats['F_move_units']+=int(tok[4])
        reversed_count=sum(min(n,previous_moves.get((dst,src),0))for(src,dst),n in moveflows.items())
        stats['one_step_reverse_flow_units']+=reversed_count
        births=sum(int(c.split()[2]) for c in turn['commands'][side] if c.startswith('SPAWN F '))
        tele=sum(int(c.split()[4]) for c in turn['commands'][side] if c.startswith('TELE ') and c.split()[3]=='F')
        stats['F_hold_units']+=max(0,brief['F']+births-sum(moveflows.values())-tele)
        if reversed_count or any(v[4]>=3 for v in t['after']):samples.append({'trace':t,'state':brief,'commands':turn['commands'][side],'reverse_flow':reversed_count})
        previous_moves=moveflows
    summary={'run':run,'job_id':row['job_id'],'map_seed':row['map_seed'],'side':side,'opponent':row['opponent'],'result':row['result'],
      'action_reproduction_mismatches':mismatches,'stats':dict(stats),'memory_trace':str(OUT/f"{row['job_id']}.json"),
      'replay_sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    (OUT/f"{row['job_id']}.json").write_text(json.dumps({'summary':summary,'map':replay['map'],'trace':trace,'states':statebrief,'samples':samples},ensure_ascii=False,indent=2))
    print(json.dumps(summary,ensure_ascii=False),flush=True);return summary

summaries=[]
for run in ['pilot-direct','development-common']:
    rows=[json.loads(s)for s in (ROOT/run/'results.jsonl').read_text().splitlines()]
    chosen=[r for r in rows if r['candidate']=='mission']
    if run=='development-common':chosen=[r for r in chosen if r['map_seed']==19012 or (r['map_seed']==19010 and r['team']=='Y')]
    for row in chosen:summaries.append(audit(run,row))
(OUT/'summary.json').write_text(json.dumps(summaries,ensure_ascii=False,indent=2))
