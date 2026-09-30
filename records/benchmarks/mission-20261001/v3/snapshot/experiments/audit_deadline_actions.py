"""Audit recorded bot commands for parser rejection and semantic clipping."""
import argparse
import collections
import gzip
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--sdk-dir', type=Path, default=ROOT / 'yk-development-tools')
    args = parser.parse_args()
    args.sdk_dir = args.sdk_dir.resolve()
    sys.path.insert(0, str(args.sdk_dir))
    from runner.protocol import parse_commands
    from engine.commands import Spawn, Move, Move2, Tele, Priority, DIRECTIONS

    root=args.run_dir.resolve()
    output=args.output.resolve()
    if output.is_relative_to(root):
     raise ValueError('Audit output must be outside the input run directory')
    rows=[json.loads(x) for x in (root/'results.jsonl').read_text().splitlines()]
    counts=collections.defaultdict(collections.Counter); examples=[]; started=time.monotonic(); total_frames=0

    def issue(label,reason,row,frame,team,cmd,**details):
     counts[label][reason]+=1
     if sum(x['label']==label and x['reason']==reason for x in examples)<3:
      examples.append(dict(label=label,reason=reason,job_id=row['job_id'],seed=row['map_seed'],turn=frame['turn'],team=team,command={'cmd':type(cmd).__name__,**vars(cmd)} if cmd else None,**details))

    for index,row in enumerate(rows):
     path=root/row['replay']
     r=json.load(gzip.open(path,'rt'));cfg=r['config'];mp=r['map'];builds={b['id']:b for b in mp['buildings']};at={(b['x'],b['y']):b for b in mp['buildings']}
     # Each next frame starts from the previous recorded state, before production.
     prev={'units':[],'resources':{t:cfg['resource']['start_resource'] for t in 'YK'},'buildings':[dict(id=i,owner='N',stage=0) for i in builds]}
     def passable(x,y):return 0<=x<mp['width'] and 0<=y<mp['height'] and mp['terrain'][y][x]!='#'
     for frame in r['turns']:
      total_frames+=1;owners={b['id']:b['owner'] for b in prev['buildings']};stock={(t,k,x,y):n for t,k,x,y,n in prev['units']}
      for team in 'YK':
       label=('candidate:' + row['candidate']) if team==row['team'] else ('opponent:'+row['opponent'])
       counts[label]['turns']+=1
       raw=frame['commands'][team];parsed=parse_commands(raw);counts[label]['commands']+=len(raw)
       if len(parsed)!=sum(bool(x.split()) for x in raw):
        for line in raw:
         if line.split() and not parse_commands([line]):issue(label,'syntax_ignored',row,frame,team,None,line=line)
       normalized=[]
       for c in parsed:
        d={'cmd':type(c).__name__,**vars(c)}
        if isinstance(c,Priority):d['coords']=[list(x) for x in c.coords]
        normalized.append(d)
       if normalized!=frame['applied'][team]:issue(label,'parsed_applied_mismatch',row,frame,team,None)
       resource=prev['resources'][team]
       eng=sum(b['type']=='ENG' and owners[b['id']]==team for b in builds.values())
       for c in parsed:
        if not isinstance(c,Spawn):continue
        if c.x is None or c.y is None:x,y=mp['bases'][team]
        else:
         x,y=c.x,c.y;b=at.get((x,y))
         if not(b and b['type']=='HOSPITAL' and owners[b['id']]==team):issue(label,'spawn_invalid_site',row,frame,team,c);continue
        cost=cfg['units'][c.kind]['cost']
        if c.kind=='W':cost=max(cfg['buildings']['eng_cost_floor'],cost-eng*cfg['buildings']['eng_discount_per'])
        n=min(c.count,resource//cost)
        if n<c.count:issue(label,'spawn_budget_clip',row,frame,team,c,requested=c.count,applied=n)
        resource-=n*cost;key=(team,c.kind,x,y);stock[key]=stock.get(key,0)+n
       # Departures share pre-movement stock; same-turn arrivals cannot depart again.
       tele_used=0
       for c in parsed:
        if isinstance(c,(Spawn,Priority)):continue
        kind='S' if isinstance(c,Move2) else c.kind
        want=c.count
        if isinstance(c,Move):
         dx,dy=DIRECTIONS[c.direction]
         if not passable(c.x+dx,c.y+dy):issue(label,'move_blocked_destination',row,frame,team,c);continue
        elif isinstance(c,Move2):
         dx,dy=DIRECTIONS[c.dir1];mx,my=c.x+dx,c.y+dy;dx,dy=DIRECTIONS[c.dir2]
         if not(passable(mx,my) and passable(mx+dx,my+dy)):issue(label,'move2_blocked_path',row,frame,team,c);continue
        elif isinstance(c,Tele):
         src,dst=at.get((c.x,c.y)),at.get((c.tx,c.ty))
         if tele_used>=cfg['tele']['per_turn']:issue(label,'tele_usage_limit',row,frame,team,c);continue
         if (c.x,c.y)==(c.tx,c.ty):issue(label,'tele_same_station',row,frame,team,c);continue
         if not(src and dst and src['type']==dst['type']=='STATION' and owners[src['id']]==owners[dst['id']]==team):issue(label,'tele_invalid_station_ownership',row,frame,team,c);continue
         if sum(b['type']=='STATION' and owners[b['id']]==team for b in builds.values())<cfg['tele']['min_stations']:issue(label,'tele_insufficient_stations',row,frame,team,c);continue
         want=min(c.count,cfg['tele']['max_units'])
         if want<c.count:issue(label,'tele_capacity_clip',row,frame,team,c,requested=c.count,applied=want)
        else:raise AssertionError(type(c))
        key=(team,kind,c.x,c.y);available=stock.get(key,0);n=min(want,available)
        if n<want:issue(label,'tele_stock_clip' if isinstance(c,Tele) else 'move_stock_clip',row,frame,team,c,requested=want,applied=n)
        stock[key]=available-n
        if isinstance(c,Tele) and n>0:tele_used+=1
      prev=frame['state']
     if (index+1)%80==0:print('audited',index+1,'frames',total_frames,'seconds',round(time.monotonic()-started,2),flush=True)
    result={'replays':len(rows),'frames':total_frames,'elapsed_seconds':time.monotonic()-started,'results_sha256':hashlib.sha256((root/'results.jsonl').read_bytes()).hexdigest(),'counts':{k:dict(v) for k,v in sorted(counts.items())},'examples':examples}
    manifest_path=root.parent.parent/'manifest.json'
    if manifest_path.is_file():
     manifest=json.loads(manifest_path.read_text())
     result['candidate_source_sha256']={name:manifest['bots'][name]['source_sha256'] for name in sorted({row['candidate'] for row in rows})}
    result['auditor_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    result['sdk_reference_sha256']={name:hashlib.sha256((args.sdk_dir/name).read_bytes()).hexdigest() for name in ['engine/pipeline.py','runner/protocol.py','runner/replay.py']}
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False),flush=True)


if __name__ == "__main__":
    main()
