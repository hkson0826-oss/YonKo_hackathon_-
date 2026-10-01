"""Read-only analysis of completed frozen-run artifacts."""
from pathlib import Path
import hashlib,json,math,collections
ROOT=Path(__file__).resolve().parent
plan=json.loads((ROOT/'plan.json').read_text())
rows=[json.loads(line) for line in (ROOT/'results.jsonl').read_text().splitlines()]
def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def percentile(values,p):
 if not values:return None
 s=sorted(values);return s[max(0,math.ceil(len(s)*p)-1)]
def stats(values):
 return {'n':len(values),'mean':sum(values)/len(values) if values else None,'p50':percentile(values,.5),'p95':percentile(values,.95),'p99':percentile(values,.99),'max':max(values) if values else None}
def cpu_stat(s):return {k:int(v) for k,v in (line.split() for line in (s or '').splitlines())}
summary={'expected_games':len(plan['jobs']),'recorded_games':len(rows),'unique_map_seeds':sorted(set(r['map_seed'] for r in rows)), 'completed':sum(r['status']=='complete' for r in rows),'errors':[{'job':r['id'],'status':r['status'],'error':r.get('error'),'scope':r.get('scope_verification')} for r in rows if r['status']!='complete'],'forfeits':[{'job':r['id'],'result':r['result']} for r in rows if r.get('result',{}).get('reason')=='forfeit'],'scope_checks':[],'candidate_results':{},'runtime':{},'frozen_files_unchanged':True,'changed_files':[],'method_limits':['1 map; 10 quarter matches plus 4 normal matches, not broad strength evidence.','Server 0.25vCPU quota period, burst, hardware and competing load are unknown. Local period=100ms, burst=0.','Same-map normal comparisons also contain runtime-seeded RNG and time-budget search variation; no single-cause winner attribution.','Successful response latency stats exclude timeout responses; forfeits and failing collection elapsed times are separately retained.','First-turn latency includes local transient-scope and Python-launcher startup in addition to bot initialization.','Resource protocol may permit harmless clipping, but separate strict audit demands no clipping.']}
for rel,sha in {**plan['source_sha256'],**{'bin/'+n:d['binary_sha256'] for n,d in plan['bots'].items()}}.items():
 if digest(Path(plan['arena'])/rel)!=sha:summary['changed_files'].append(str(Path(plan['arena'])/rel))
for rel,sha in plan['harness_sha256'].items():
 if digest(ROOT/rel)!=sha:summary['changed_files'].append(str(ROOT/rel))
summary['frozen_files_unchanged']=not summary['changed_files']
latencies=collections.defaultdict(lambda:{'first':[],'regular':[],'failures':[],'memory_peaks':[],'cpu_usage_usec':0,'throttled_usec':0,'nr_throttled':0,'games':0})
for row in rows:
 key=row['condition']+'/'+row['candidate'];g=summary['candidate_results'].setdefault(key,{'games':0,'wins':0,'draws':0,'losses':0,'scores':[],'forfeits':0});g['games']+=1
 if 'result' in row:
  r=row['result'];side=row['candidate_side'];other='K' if side=='Y' else 'Y';g['wins']+=r['winner']==side;g['draws']+=r['winner']=='DRAW';g['losses']+=r['winner'] not in [side,'DRAW'];g['forfeits']+=r['reason']=='forfeit';g['scores'].append({'side':side,'own':r['score'][side],'other':r['score'][other],'turns':r['turns'],'reason':r['reason']})
 for side,b in row['bot_measurements'].items():
  key=row['condition']+'/'+b['name'];x=latencies[key];x['games']+=1
  for response in b['responses']:
   if response['status']=='ok':x['first' if response['turn']==1 else 'regular'].append(response['response_ms'])
   else:x['failures'].append({'job':row['id'],'side':side,**response})
  scope=b['scope'];meta=scope.get('final_metrics',{});stat=cpu_stat(meta.get('cpu.stat'));x['cpu_usage_usec']+=stat.get('usage_usec',0);x['throttled_usec']+=stat.get('throttled_usec',0);x['nr_throttled']+=stat.get('nr_throttled',0)
  if meta.get('memory.peak'):x['memory_peaks'].append(int(meta['memory.peak']))
  summary['scope_checks'].append({'job':row['id'],'side':side,'bot':b['name'],'scope':scope.get('cgroup'),'initial_cpu_max':scope.get('limits',{}).get('cpu.max'),'final_cpu_max':meta.get('cpu.max'),'memory_max':scope.get('limits',{}).get('memory.max'),'memory_peak':meta.get('memory.peak'),'cpu_stat':stat,'cleanup':scope.get('cleanup'),'independent_scopes_and_runner_outside':row['scope_verification']['ok']})
for k,x in latencies.items():summary['runtime'][k]={'appearances':x['games'],'first_response_ms':stats(x['first']),'regular_response_ms':stats(x['regular']),'response_failures':x['failures'],'memory_peak_bytes':max(x['memory_peaks']) if x['memory_peaks'] else None,'cpu_usage_usec':x['cpu_usage_usec'],'throttled_usec':x['throttled_usec'],'nr_throttled':x['nr_throttled']}
a=ROOT/'strict-action-audit-gate.json';summary['strict_action_audit_gate']=json.loads(a.read_text()) if a.exists() else None
summary['all_scope_cleanup_verified']=len(summary['scope_checks'])==2*len(rows) and all(x['cleanup']['ok'] for x in summary['scope_checks'])
summary['all_planned_games_recorded']=set(r['id'] for r in rows)==set(r['id'] for r in plan['jobs']) and len(rows)==len(plan['jobs'])
(ROOT/'analysis.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:v for k,v in summary.items() if k not in ['scope_checks','runtime','method_limits']},ensure_ascii=False,indent=2))
for k,v in sorted(summary['runtime'].items()):print(k,json.dumps(v))
