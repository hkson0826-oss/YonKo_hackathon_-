import collections,gzip,hashlib,itertools,json,random,statistics
from pathlib import Path
BASE=Path('/tmp/yk-mission-arena-v4-20261001'); REPO=Path('/tmp/yk-new-bot-20261001')
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
point=lambda r: float(r['win'])+.5*float(r['draw'])
def ci(vals):
 rng=random.Random(20261001); s=sorted(statistics.mean(rng.choices(vals,k=len(vals))) for _ in range(4000)); return [s[99],s[3899]]
def summary(rows):
 maps=collections.defaultdict(list)
 for r in rows: maps[r['map_seed']].append(point(r))
 return dict(games=len(rows),wins=sum(r['win'] for r in rows),draws=sum(r['draw'] for r in rows),point_rate=statistics.mean(map(point,rows)),point_rate_map_bootstrap95=ci([statistics.mean(v) for k,v in sorted(maps.items())]),mean_score_margin=statistics.mean(r['score_margin'] for r in rows))
def diff(rows):
 a={(r['map_seed'],r['team'],r['opponent']):r for r in rows if r['candidate']=='mission4'}; b={(r['map_seed'],r['team'],r['opponent']):r for r in rows if r['candidate']=='v8'}; assert a.keys()==b.keys()
 maps=collections.defaultdict(list)
 for k in sorted(a): maps[k[0]].append(point(a[k])-point(b[k]))
 vals=[statistics.mean(v) for k,v in sorted(maps.items())]
 return dict(paired_games=len(a),point_rate_difference=statistics.mean(vals),paired_map_bootstrap95=ci(vals),map_mean_differences={str(k):statistics.mean(v) for k,v in sorted(maps.items())})
plan=json.loads((REPO/'records/research/new-bot-20261001/final-plan.json').read_text())
sel=json.loads((REPO/'records/research/new-bot-20261001/selection-plan.json').read_text())
runs={n:[json.loads(x) for x in (BASE/'runs'/n/'results.jsonl').read_text().splitlines()] for n in ['final-common','final-direct']}
audits={n:json.loads((BASE/(n+'-action-audit.json')).read_text()) for n in runs}
checks={}; issues=[]; outputs={'frames_both_teams':0,'max_lines_including_END':0,'max_line_bytes_including_newline':0,'max_turn_bytes_including_END':0,'violations':[]}; runtimes={}
for n,rows in runs.items():
 expected=set(itertools.product(plan['common']['candidates'] if n=='final-common' else ['mission4'],plan['common']['opponents'] if n=='final-common' else ['v8'],plan['maps'],['Y','K']))
 keys=[(r['candidate'],r['opponent'],r['map_seed'],r['team']) for r in rows]
 check={'complete':all(r['status']=='complete' for r in rows),'forfeits':sum(bool(r.get('forfeit')) for r in rows),'schedule_exact':set(keys)==expected and len(keys)==len(expected),'audit_results_hash_matches':audits[n]['results_sha256']==sha(BASE/'runs'/n/'results.jsonl'),'audit_has_no_issues':not audits[n]['examples'] and all(not (set(v)-{'turns','commands'}) for v in audits[n]['counts'].values())}; checks[n]=check
 assert all([check['complete'],check['schedule_exact'],check['audit_results_hash_matches'],check['audit_has_no_issues']]) and not check['forfeits']
 for r in rows:
  assert r['win']==(r['result']['winner']==r['team']); assert r['draw']==(r['result']['winner']=='DRAW')
  assert r['score_margin']==r['result']['score'][r['team']]-r['result']['score']['K' if r['team']=='Y' else 'Y']
  for role,field in [('candidate','response_ms'),('opponent','opponent_response_ms')]:
   ts=r[field]; key=n+':'+r[role]; s=runtimes.setdefault(key,{'first_max_ms':0,'regular_max_ms':0,'first_violations':0,'regular_violations':0,'observations':0}); s['first_max_ms']=max(s['first_max_ms'],ts[0]); s['regular_max_ms']=max(s['regular_max_ms'],max(ts[1:],default=0)); s['observations']+=len(ts); s['first_violations']+=int(ts[0]>3000); s['regular_violations']+=sum(t>300 for t in ts[1:])
  replay=json.loads(gzip.decompress((BASE/'runs'/n/r['replay']).read_bytes()))
  assert len(replay['turns'])==r['result']['turns']; assert replay['result']==r['result']
  for f in replay['turns']:
   for team in ['Y','K']:
    lines=f['commands'][team]+['END']; b=[len(x.encode())+1 for x in lines]; outputs['frames_both_teams']+=1; outputs['max_lines_including_END']=max(outputs['max_lines_including_END'],len(lines)); outputs['max_line_bytes_including_newline']=max(outputs['max_line_bytes_including_newline'],max(b)); outputs['max_turn_bytes_including_END']=max(outputs['max_turn_bytes_including_END'],sum(b))
    if len(lines)>4096 or max(b)>1024 or sum(b)>65536: outputs['violations'].append([n,r['job_id'],f['turn'],team])
common=runs['final-common']; direct=runs['final-direct']; metrics={}
for scope,pred in [('overall',lambda r:True),('Y',lambda r:r['team']=='Y'),('K',lambda r:r['team']=='K')]+[(o,lambda r,o=o:r['opponent']==o) for o in plan['common']['opponents']]:
 rows=[r for r in common if pred(r)]; metrics[scope]={b:summary([r for r in rows if r['candidate']==b]) for b in ['mission4','v8']}; metrics[scope]['paired_difference']=diff(rows)
# Include side-by-opponent strata rather than letting the aggregate conceal a side weakness.
side_opponent={}
for side in ['Y','K']:
 for o in plan['common']['opponents']:
  rows=[r for r in common if r['team']==side and r['opponent']==o]; side_opponent[side+':'+o]={b:summary([r for r in rows if r['candidate']==b]) for b in ['mission4','v8']}; side_opponent[side+':'+o]['paired_difference']=diff(rows)
directmetrics={s:summary([r for r in direct if s=='overall' or r['team']==s]) for s in ['overall','Y','K']}
source=REPO/'experiments/mission_scheduler_20261001/main.cpp'; assert sha(source)==plan['source_sha256']
assert not outputs['violations'] and all(not v['first_violations'] and not v['regular_violations'] for v in runtimes.values())
gate={'legality_and_execution_limits':True,'overall_at_least_v8':metrics['overall']['paired_difference']['point_rate_difference']>=0,'registered_Y_at_least_v8':metrics['Y']['paired_difference']['point_rate_difference']>=0,'positive_in_overall_or_Y':any(metrics[s]['paired_difference']['point_rate_difference']>0 for s in ['overall','Y']),'each_opponent_regression_at_least_minus_0_25':all(metrics[o]['paired_difference']['point_rate_difference']>=-.25 for o in plan['common']['opponents']),'direct_at_least_0_5':directmetrics['overall']['point_rate']>=.5}; gate['pass']=all(gate.values())
report={'verdict':'FINAL_GATE_FAIL_RESEARCH_ONLY','source_sha256':sha(source),'source_unchanged_from_final_preregistration':True,'plans':{'final_path':str(REPO/'records/research/new-bot-20261001/final-plan.json'),'final_sha256':sha(REPO/'records/research/new-bot-20261001/final-plan.json'),'selection_adoption_gate':sel['adoption_gate']},'schedule_checks':checks,'common':metrics,'side_by_opponent':side_opponent,'direct':directmetrics,'gate':gate,'audit':{'scope':'Independent result/schedule/hash/runtime/output-size recomputation; semantic correctness from completed root action audits bound to identical result/source hashes. No new games or source edits.','semantic_frames':sum(a['frames'] for a in audits.values()),'semantic_issues':0,'audits':audits,'output_size_checks':outputs,'output_size_limitation':'Replay command strings plus an END line; not a separate raw pipe capture.'},'runtime':runtimes,'memory_run_constraints':{n:json.loads((BASE/(n+'-resource-limit.json')).read_text()) for n in runs},'uncertainty_method':{'resampling_unit':'map; both sides and all selected opponents remain in their map cluster','maps':8,'replicates':4000,'random_seed':20261001,'percentiles':'sorted sample indices 99 and 3899 (zero based)','paired_difference':'mission4 minus v8 matched on map, side, opponent; differences averaged within map before resampling','caveats':['Only eight maps; intervals are descriptive and broad.','Time-budgeted opponent policies can vary despite fixed source and RNG seed.','Gate uses preregistered raw point thresholds; intervals do not establish equivalence or excuse gate failure.']},'disposition':{'family_representative':'mission4','status':'research artifact only; no promotion','server':'Leave externally selected serverv9 unchanged. This independent review did not access or mutate the server.','cycle':'Finished; no further code tuning, revisions, or post-final switch to another family member.'}}
out=Path('/tmp/yk-mission-final-review-20261001.json'); out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
lines=['# 최종 독립 검토 — mission4 채택 기준 미달','', '별도 최종 맵 19200–19207의 공통 상대 128경기와 직접 대결 16경기를 확인했습니다. 소스는 고정 SHA256 `'+sha(source)+'`와 같습니다.','', '| 범위 | mission4 승/경기 | v8 승/경기 | 승점률 차이 | 차이의 95% 구간 |','|---|---:|---:|---:|---:|']
for scope,x in metrics.items():
 d=x['paired_difference']; a=x['mission4'];b=x['v8'];lo,hi=d['paired_map_bootstrap95'];lines.append(f"| {scope} | {a['wins']}/{a['games']} | {b['wins']}/{b['games']} | {d['point_rate_difference']:+.5f} | [{lo:+.5f}, {hi:+.5f}] |")
lines += ['', '무승부는 없습니다. 직접 대결은 mission4 9/16승(Y 5/8, K 4/8), 승점률 0.5625로 직접 대결 조건만 충족했습니다. 공통 상대 전체 평균 점수차는 mission4 +8.21875, v8 +11.28125입니다.','', '**실패한 사전 기준:** 전체 승점률이 v8 이상, 등록 진영 Y 승점률이 v8 이상이어야 하는 두 조건이 모두 미달입니다. j_balanced_portfolio 대비 차이 −0.375도 허용 하한 −0.25를 넘는 하락입니다. 전체 또는 Y에서 양의 차이를 요구한 조건도 미달입니다.','', '**실행 검증:** 144경기 모두 완료, 중복·누락 없이 계획된 조합과 일치하며 기권·오류가 없습니다. 결과·소스 해시가 일치하는 의미 감사 19,532프레임에서 잘못되거나 잘린 명령이 0건입니다. 양측 응답 시간과 재생 명령 크기를 다시 계산해 초과 0건을 확인했습니다. mission4 일반 턴 최대 6.614ms, 첫 응답 최대 7.145ms입니다. 메모리는 실행기 기록상 프로세스별 RLIMIT_AS 384MiB를 적용했으며, 실제 최대 RSS나 서버 컨테이너 재현을 측정한 결과는 아닙니다.','', '구간은 맵을 군집으로 둔 4,000회 부트스트랩(시드 20261001)이며 차이는 동일 맵·진영·상대 조건을 짝지었습니다. 8개 맵의 표본은 작고 시간 예산을 사용하는 상대의 행동도 변할 수 있습니다. 이 구간으로 통계적 우열을 단정하지 않습니다. 채택 여부는 미리 정한 관측 승점 기준으로 결정하므로 이번 결과는 실패입니다.','', '**결정:** mission4를 새 전략 계열의 연구 산출물로 보존합니다. 외부에서 선택된 serverv9는 변경하지 않습니다. 이번 주기의 추가 튜닝·수정 또는 최종 결과를 본 뒤 다른 후보로 교체하는 작업은 진행하지 않습니다. 서버 상태는 root가 확인한 컨텍스트이며 본 검토는 서버에 접근하지 않았습니다.','', '전체 진영×상대 수치, 개별 구간, 감사 해시와 실행 제한은 같은 이름의 JSON에 보존했습니다.']
Path('/tmp/yk-mission-final-review-20261001.md').write_text('\n'.join(lines)+'\n')
print(json.dumps({'gate':gate,'metrics':{k:v['paired_difference'] for k,v in metrics.items()},'outputs':outputs,'artifacts':[str(out),str(out.with_suffix('.md'))]},ensure_ascii=False,indent=2))

# Reconcile finite bootstrap sampling with the root report's insertion-order clusters.
from pathlib import Path
from collections import defaultdict
import json, random, statistics, hashlib
review_path=Path('/tmp/yk-mission-final-review-20261001.json')
root_path=Path('/tmp/yk-new-bot-20261001/records/benchmarks/mission-20261001/final-summary.json')
review=json.loads(review_path.read_text()); root=json.loads(root_path.read_text())['final']['paired']
def reconcile_ci(vals):
    rng=random.Random(20261001)
    draws=sorted(statistics.mean(rng.choices(vals,k=len(vals))) for _ in range(4000))
    return [draws[99],draws[3899]]
reproduced={}
for side,scope in [('both','overall'),('Y','Y'),('K','K')]:
    grouped=defaultdict(list)
    for row in root['matched_games']:
        if side=='both' or row['side']==side:
            grouped[row['map_seed']].append(row['point_difference'])
    values={k:statistics.mean(v) for k,v in grouped.items()}
    expected={int(k):v for k,v in review['common'][scope]['paired_difference']['map_mean_differences'].items()}
    assert values==expected
    insertion_ci=reconcile_ci(list(values.values()))
    sorted_ci=reconcile_ci([values[k] for k in sorted(values)])
    assert insertion_ci==root['by_side'][side]['map_cluster_bootstrap_95pct']
    assert sorted_ci==review['common'][scope]['paired_difference']['paired_map_bootstrap95']
    reproduced[side]={'root_cluster_order':list(values),'review_cluster_order':sorted(values),'root_ci_reproduced':insertion_ci,'review_ci_reproduced':sorted_ci,'map_means_identical':True}
review['uncertainty_method']['cluster_order']='Ascending map_seed before sampling; stable against concurrent result completion order.'
review['uncertainty_method']['root_report_reconciliation']={'root_path':str(root_path),'root_sha256':hashlib.sha256(root_path.read_bytes()).hexdigest(),'cause':'Same 4000 replicates, Random(20261001), and sample percentile indices 99/3899. Root preserves first-seen map order from matched records; independent review sorts by map_seed. Random.choices draws indices, so the same random indices address different map means. This changes a finite Monte Carlo sample, not the underlying empirical bootstrap distribution or observed game metrics.','reproduced':reproduced,'impact':'No score, outcome, gate, or disposition changes; retain each reported interval with its explicit sampling order.'}
review_path.write_text(json.dumps(review,ensure_ascii=False,indent=2)+'\n')
md_path=review_path.with_suffix('.md'); md=md_path.read_text(); marker='신뢰구간 계산 순서 보충:'
if marker not in md:
    md += '\n'+marker+' root 요약의 전체 차이 구간 [−0.21875, +0.140625]와 본 검토의 [−0.21875, +0.125]는 **맵 배열 순서 차이로 생긴 유한 부트스트랩 표본 차이**입니다. 두 계산 모두 4,000회, 난수 시드 20261001, 정렬 표본 인덱스 99·3899를 사용합니다. root는 결과에서 맵이 처음 나온 순서, 본 검토는 맵 시드 오름차순을 사용합니다. 동일한 난수 인덱스가 서로 다른 맵 평균을 뽑아 상한이 한 단계 달라졌으며, 각 순서로 계산해 두 결과를 정확히 재현했습니다. Y 구간 상한도 같은 이유로 root +0.1875, 본 검토 +0.15625입니다. 원경기·맵별 평균·승점 차이와 채택 실패 결론은 모두 같습니다.\n'
md_path.write_text(md)
print(json.dumps(reproduced,indent=2))
