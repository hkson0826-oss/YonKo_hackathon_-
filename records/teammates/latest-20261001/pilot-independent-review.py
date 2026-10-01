from pathlib import Path
from collections import Counter
import json,hashlib,itertools,shlex,datetime,gzip
A=Path('/tmp/yk-latest-teammates-arena-20261001');R=Path('/tmp/yk-new-bot-20261001');D=R/'records/teammates/latest-20261001'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
load=lambda p:json.loads(p.read_text())
m=load(A/'manifest.json');plan=load(D/'plan.json');src=load(D/'source-manifest.json'); findings=[]; mismatches=[]
for p,h in m['frozen_sha256'].items():
 f=A/p
 if not f.is_file() or sha(f)!=h:mismatches.append(p)
assert not mismatches
botchecks={}
for name,source in plan['candidates'].items():
 b=m['bots'][name];actual_dir=(A/b['source']).parent;expected_args=plan['runtime_args'].get(name,[])
 checks={'args_match':b.get('runtime_args',[])==expected_args and shlex.split(b['command'])[1:]==expected_args,'binary_hash_match':sha(Path(shlex.split(b['command'])[0]))==b['binary_sha256'],'source_hash_match':sha(A/b['source'])==b['source_sha256'],'source_files':{},'build_success':all(x['returncode']==0 for x in b['builds'])}
 for f,h in b['input_files_sha256'].items():
  same=sha(actual_dir/f)==h==sha(R/source/f);assert same
  if name in src:assert h==src[name]['files'][f]['sha256']
  checks['source_files'][f]={'sha256':h,'original_and_snapshot_match':same,'branch_manifest_match':name in src}
 assert all(checks[k] for k in ['args_match','binary_hash_match','source_hash_match','build_success'])
 checks.update(command=b['command'],source_sha256=b['source_sha256'],binary_sha256=b['binary_sha256'],source_provenance=src.get(name,{'path':source}))
 botchecks[name]=checks
sdk=[]
for path,h in m['frozen_sha256'].items():
 if path.startswith('snapshot/yk-development-tools/'):
  inp=path[len('snapshot/'):];assert m['input_sha256'][inp]==h
  sdk.append({'path':path,'sha256':h,'matches_preparation_input':True})
# ZIP provenance is not a claim about any server upload.
zips={}
for name,s in src.items():
 if 'zip' in s:z=s['zip'];zips[name]={'path':z['path'],'sha256':sha(R/z['path']),'matches_source_manifest':sha(R/z['path'])==z['sha256']};assert zips.get(name,{'matches_source_manifest':True})['matches_source_manifest']
runs={}; workers=0
key=lambda x:(x['candidate'],x['opponent'],x['map_seed'],x['team'])
for st in plan['stages'][:2]:
 name=st['run_id'];p=load(A/'plans'/(name+'.json'));q=load(A/'runs'/name/'plan.json');policy=load(A/'plans'/(name+'-policy.json'));jobs=load(A/'runs'/name/'jobs.json'); sessions=[load(f) for f in sorted((A/'runs'/name).glob('session-*.json'))];session=sessions[-1]
 candidates=st.get('candidates',[st.get('candidate')]);expected=set(itertools.product(candidates,st['opponents'],st['maps'],['Y','K']))
 assert p==q and p['candidates']==candidates and p['opponents']==st['opponents'] and p['map_seeds']==st['maps'] and p['replays']=='all'
 assert len(jobs)==len(expected)==st['games']==policy['scheduled_jobs'] and {key(j) for j in jobs}==expected
 assert policy['source_commit']==m['source_commit'] and session['plan_sha256']==sha(A/'plans'/(name+'.json'))
 assert policy['candidate_runtime_args']=={b:m['bots'][b]['runtime_args'] for b in candidates+st['opponents'] if m['bots'][b].get('runtime_args')}
 assert all(policy['source_sha256'][b]==m['bots'][b]['source_sha256'] for b in candidates+st['opponents'])
 assert session['workers']==policy['workers'];workers+=policy['workers']
 data=(A/'runs'/name/'results.jsonl').read_bytes();complete=data[:data.rfind(b'\n')+1];rows=[json.loads(x) for x in complete.splitlines()];keys=[key(r) for r in rows]
 assert len(set(keys))==len(keys) and set(keys)<=expected
 jobindex={key(x):x['job_id'] for x in jobs};assert all(r['job_id']==jobindex[key(r)] for r in rows)
 errors=[r for r in rows if r['status']!='complete'];forfeits=[r for r in rows if r.get('forfeit')]; times={}; replay_checked=0
 for r in rows:
  if r['status']!='complete':continue
  for role,field in [('candidate','response_ms'),('opponent','opponent_response_ms')]:
   vals=r[field];v=times.setdefault(r[role],{'first_max_ms':0,'regular_max_ms':0,'first_over_3000':0,'regular_over_300':0});v['first_max_ms']=max(v['first_max_ms'],vals[0]);v['regular_max_ms']=max(v['regular_max_ms'],max(vals[1:],default=0));v['first_over_3000']+=int(vals[0]>3000);v['regular_over_300']+=sum(x>300 for x in vals[1:])
  replay=load_gz=None
  replay=json.loads(gzip.decompress((A/'runs'/name/r['replay']).read_bytes()));assert replay['seed']==r['map_seed'];assert replay['result']==r['result'];assert replay['teams'][r['team']]['name']==r['candidate'];assert replay['teams']['K' if r['team']=='Y' else 'Y']['name']==r['opponent'];replay_checked+=1
 nowcomplete=len(rows)==len(expected) and session['status']=='complete'
 grouped={}
 for candidate in candidates:
  for opponent in st['opponents']:
   rr=[r for r in rows if r['candidate']==candidate and r['opponent']==opponent and r['status']=='complete']
   grouped[candidate+' vs '+opponent]={side:{'games':len(qq:=[r for r in rr if side=='both' or r['team']==side]),'wins':sum(r['win'] for r in qq),'draws':sum(r['draw'] for r in qq),'losses':sum(not r['win'] and not r['draw'] for r in qq)} for side in ['Y','K','both']}
 limit=load(A/(name+'-resource-limit.json'));assert limit['effective_soft_bytes']==384*1024*1024
 runs[name]={'status':'complete' if nowcomplete else 'partial_snapshot','observed_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'planned_games':len(expected),'completed_records':len(rows),'result_snapshot_sha256':hashlib.sha256(complete).hexdigest(),'partial_trailing_bytes_ignored':len(data)-len(complete),'schedule_and_both_sides_match':True,'no_duplicate_jobs':True,'plan_sha256':sha(A/'plans'/(name+'.json')),'policy_sha256':sha(A/'plans'/(name+'-policy.json')),'session':session,'expected_missing_jobs':len(expected-set(keys)),'errors':len(errors),'forfeits':len(forfeits),'replay_metadata_verified':replay_checked,'runtime':times,'observed_outcomes_not_selection':grouped,'memory_limit_record':limit}
assert workers<=plan['limits']['workers']
assert all(not t['first_over_3000'] and not t['regular_over_300'] for r in runs.values() for t in r['runtime'].values())
findings=[{'severity':'limitation','finding':'Manifest policy_rng_seed=20260927 is the legacy base-policy seed, not a global seed for every bot. v9_main attack RNG explicitly uses20261001; v9_lock all-in RNG is initialized from steady_clock and is intentionally unseeded externally.'},{'severity':'documentation','finding':'Master plan memory_per_match_mib says384, while executable RLIMIT_AS is384MiB per process inherited by workers and bots, not a summed per-match RSS cap. Policy files and resource-limit records accurately name RLIMIT_AS scope.'},{'severity':'scope','finding':'This review checks configuration, provenance, schedule, replay metadata, and recorded timings. No action-semantic replay audit has been newly executed; await root audits before declaring all commands legal.'}]
report={'reviewed_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'verdict':'CONFIGURATION_AND_PROVENANCE_PASS','recorded_runtime_violations':[],'source_or_arena_mutations':False,'source_commit':m['source_commit'],'master_plan_sha256':sha(D/'plan.json'),'source_manifest_sha256':sha(D/'source-manifest.json'),'arena_manifest_sha256':sha(A/'manifest.json'),'frozen_files_verified':len(m['frozen_sha256']),'frozen_mismatches':mismatches,'sdk_files_verified':len(sdk),'sdk':sdk,'bots':botchecks,'zip_provenance':zips,'runs':runs,'concurrent_worker_sum':workers,'master_worker_limit':plan['limits']['workers'],'findings':findings,'source_arg_evidence':{'v9_main':'main.cpp1019–1021 parses --attack-seed and sets custom seed; initialization963–964 seeds attack RNG.','v9_lock':'main.cpp411 initializes v9_rng from steady_clock;1789–1797 only --trace special handling, unknown strings via atoi become forced_policy0.','execution_chain':'deadline_20260929.py64 constructs full manifest command; local_league.py345 supplies commands,258 constructs TimedBot; cpu_sweep.py initialize_worker imports frozen SDK; local_league.py326–330 verifies frozen inputs before pool.'},'limitations':['No Git operations or server access; branch commits taken from frozen source provenance records.','Completed pilot is a protocol/runtime screen on4maps, not final performance evidence.','Immutable content was verified at review time; in-flight result rows are timestamped snapshots.']}
out=Path('/tmp/yk-latest-arena-independent-review-20261001.json');out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
lines=['# 팀원 후보 실험 독립 설정 검토','',f"소스·인자·실행 계획 대조 통과. manifest의 고정 파일 {len(m['frozen_sha256'])}개와 SDK 파일 {len(sdk)}개의 해시를 확인했고 불일치는 없습니다. 세 팀원 후보는 branch source-manifest→저장소 사본→arena 사본 연결이 일치합니다. v8 및 mission4 고정 소스와 실행 바이너리 해시도 일치합니다.",'','`v9_main`에만 `--attack-seed=20261001`을 전달합니다. `v9_lock`, siphon, v8, mission4는 인자 없이 실행합니다. lock은 해당 옵션을 지원하지 않아 넣으면 forced_policy=0이 되는 소스 경로를 확인했습니다. lock의 자체 RNG는 시계 시드이므로 완전 결정적 비교라고 표현할 수 없습니다.','','파일럿 계획은4맵23100–23103 양 진영, siphon32경기와 v9변형16경기입니다. 작업 목록은 계획 조합과 정확히 일치합니다. 실행 병렬 수4+2=6으로 전체 계획 상한6을 지킵니다.']
for n,x in runs.items():lines+=['',f"- {n}: {x['status']}, 관측 {x['completed_records']}/{x['planned_games']}경기, 오류{x['errors']}·기권{x['forfeits']}. 관측 시각{x['observed_at_utc']}."]
lines+=['','진행 중 결과는 중간 스냅샷이며 전체 성능 결론에 사용하지 않습니다. 이번 검토의 통과는 설정·출처·일정·기록된 시간 검사 범위입니다. 실제 명령의 잘림·무시 여부는 별도 의미 감사를 기다립니다.','','문서 표기 한 가지: master plan의 `memory_per_match_mib:384`는 실제로 **프로세스별 RLIMIT_AS384MiB**이며 경기 전체 RSS 합계 제한이 아닙니다. 세부 policy와 resource-limit 파일은 이를 정확히 설명합니다. 원본·arena·Git 상태는 변경하지 않았습니다.']
out.with_suffix('.md').write_text('\n'.join(lines)+'\n')
print(json.dumps({'verdict':report['verdict'],'frozen':report['frozen_files_verified'],'sdk':len(sdk),'runs':{k:{q:v[q] for q in ['status','completed_records','planned_games','errors','forfeits']} for k,v in runs.items()},'workers':workers,'paths':[str(out),str(out.with_suffix('.md'))]},indent=2))
