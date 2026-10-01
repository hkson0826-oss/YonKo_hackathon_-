from pathlib import Path
import json,hashlib,gzip
ROOT=Path(__file__).resolve().parent
j=json.loads((ROOT/'analysis.json').read_text());plan=json.loads((ROOT/'plan.json').read_text());execution=json.loads((ROOT/'execution.json').read_text())
lines=[f"봇별 실제 0.25 vCPU cgroup 조건의 10경기와 같은 맵 normal CPU 대조 4경기를 완료했다. 맵은 23400 하나이며, 이는 실행 조건을 확인하는 작은 로컬 시험이다. 공식 서버 경기나 최종 승률 검증으로 표시하지 않는다.", '',
 f"실행 전 연구 동결 커밋은 `{execution['frozen_research_commit']}`이다. `plan.json` SHA-256은 `{execution['plan_sha256']}`이며, 실행 종료 후 봇 소스·SDK·감사 도구 54파일, 5개 바이너리, harness3파일의 원래 해시를 다시 확인했다. 불변 확인 결과는 `{j['frozen_files_unchanged']}`이다. 연구 대상 봇과 실행 코드를 실험 도중 수정하지 않았다.", '',
 f"실제 기록은 {j['recorded_games']}경기, complete {j['completed']}경기, 몰수 {len(j['forfeits'])}건, 인프라/실행 오류 {len(j['errors'])}건이다. 각 봇을 별도 임시 systemd user scope에 넣고 SDK/runner는 두 scope 밖에서 실행했다. {len(j['scope_checks'])}개 scope의 제한과 분리를 확인했으며 모든 scope 제거 확인은 `{j['all_scope_cleanup_verified']}`이다. 전역 설정이나 기존 사용자 서비스를 변경하지 않았다.", '',
 'quarter 조건의 실제 `cpu.max`는 `25000 100000`(매100ms당25ms), burst는0이다. CPU 계산0.25초 calibration에서 throttling도 실제 발생했다. 양 조건 모두 memory.max와 RLIMIT_AS를384MiB로 제한했다. 첫3초에는 로컬 systemd scope·Python launcher·봇 시작·INIT가 포함되며 일반300ms는 입력 전송부터 END 수신까지의 wall 시간이다. 전체 경기180초 제한도 유지했다.', '',
 '| 후보 | 25% CPU 대전 수 | 대 v8 승/무/패 | Y 진영 점수 | K 진영 점수 |', '|---|---:|---|---|---|']
for name in plan['candidates']:
 c=j['candidate_results'].get('quarter/'+name,{})
 scores={s['side']:f"{s['own']}:{s['other']} (T{s['turns']})" for s in c.get('scores',[])}
 record='자기 대전 기준선' if name=='v8' else f"{c.get('wins',0)}/{c.get('draws',0)}/{c.get('losses',0)}"
 lines.append(f"| {name} | {c.get('games',0)} | {record} | {scores.get('Y','—')} | {scores.get('K','—')} |")
lines+=['', '점수는 후보:상대 순서다. v8 자기 대전 두 경기는 양 프로세스의 제한 동작을 검사하는 기준선이므로 후보 우열의 승률로 읽지 않는다.', '', '| 조건 / 봇 | 봇 출현 수 | 일반 응답 수 | 일반 p95 / 최대(ms) | 첫 응답 최대(ms) | cgroup 메모리 최대(MiB) |', '|---|---:|---:|---:|---:|---:|']
for key,x in sorted(j['runtime'].items()):
 r=x['regular_response_ms'];f=x['first_response_ms'];memory=x['memory_peak_bytes']/2**20 if x['memory_peak_bytes'] is not None else 0
 lines.append(f"| {key} | {x['appearances']} | {r['n']} | {r['p95']:.2f} / {r['max']:.2f} | {f['max']:.2f} | {memory:.2f} |")
lines+=['', '이 응답 분포는 성공한 응답만 집계하며 timeout·crash는 별도 결과 항목으로 보존한다. v8은 여러 후보의 공통 상대라 출현 수가 더 많다. 메모리는 Python launcher를 포함한 전체 cgroup의 peak이며 C++ 봇 단독 사용량과 같다고 단정하지 않는다.', '', '| 후보 | normal Y 점수 | quarter Y 점수 | normal K 점수 | quarter K 점수 |', '|---|---|---|---|---|']
for name in ['v9_main','v9_lock']:
 sides={}
 for cond in ['normal','quarter']:
  sides[cond]={s['side']:f"{s['own']}:{s['other']}" for s in j['candidate_results'][cond+'/'+name]['scores']}
 lines.append(f"| {name} | {sides['normal']['Y']} | {sides['quarter']['Y']} | {sides['normal']['K']} | {sides['quarter']['K']} |")
comparisons=[]
for name in ['v9_main','v9_lock']:
 for side in 'YK':
  replays={c:json.load(gzip.open(ROOT/'games'/f'{c}-{name}-{side}-23400'/'replay.json.gz','rt')) for c in ['normal','quarter']}
  normal=replays['normal']['turns'];quarter=replays['quarter']['turns']
  divergence=next((n['turn'] for n,q in zip(normal,quarter) if n['commands']!=q['commands']),None)
  comparisons.append({'candidate':name,'side':side,'first_joint_command_divergence_turn':divergence})
lines+=['', '같은 시드·진영의 대조에서도 시간 예산 탐색량과 실행 중 난수 때문에 원래 행동 경로가 달라질 수 있다. v9_lock은 시계 기반 난수를 사용한다. 따라서 위 승패 차이를 quota만의 순수 인과 효과나 일반 승률 변화로 해석하지 않는다. CPU 제한 아래에서 기존 normal-CPU 경기 결과를 그대로 전용할 수 없음을 확인하는 자료다.', '',
 f"공식 SDK로 저장 리플레이의 모든 완료 턴을 다시 전이시켜 매 상태가 일치하는지 검사했다. 별도로 실행한 strict 명령 감사 결과는 `{j['strict_action_audit_gate']}`이다. 이 감사는 파싱·applied 대조, 생산지·공유 자원 예산, 이동 출발 재고, 지형, TELE 소유·횟수·수량의 clipping/무시를 검사한다. scope 런타임 검사와 명령 감사는 서로 다른 검증이다.", '',
 '서버 quota period와 CPU 모델·버스트·부하는 미공개다. 이번 시험은 로컬100ms period에서의 실제0.25 CPU 검증이며 서버와 실행 환경이 동일하다는 뜻은 아니다. 1맵에서 통과했다는 결과도 모든 맵의300ms 안전성을 보장하지 않는다. 이전 normal-CPU384경기는 전략 참고 자료로 유지하되, 새 공지의 실행 제한을 통과한 대전으로 다시 분류하지 않는다.', '',
 '재현 자료: [동결 계획](plan.json), [실행 커밋·인자](execution.json), [경기 결과 원본](results.jsonl), [scope·응답·불변 해시 분석](analysis.json), [명령 감사](strict-action-audit.json), [명령 감사 gate](strict-action-audit-gate.json). 각 경기의 원본 리플레이와 개별 launch/cpu.stat/cleanup 결과는 `games/<job>/`에 있다.']
(ROOT/'normal-quarter-divergence.json').write_text(json.dumps(comparisons,indent=2)+'\n')
(ROOT/'report.md').write_text('\n'.join(lines)+'\n')
print('report written',len(lines),'lines')
