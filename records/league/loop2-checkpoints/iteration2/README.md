# 두 번째 반복의 완료 검사 체크포인트

동결 소스 `c64d583`, 원격 TMP `/tmp/yk-league-1c1csuif`에서 실행 중인 두 번째 반복의 **smoke 52경기**만 완료 기록으로 보존했다. 오류 0·몰수 0이며 개발·선택·최종 검증이 완료됐다는 뜻은 아니다.

실행은 `iterative_campaign.py --phase final --revision 2`, 개발 7100–7107, 선택 7200–7215, 최종 7300–7363이며 전체 예정 4,892경기다. 정확한 21개 후보 목록은 [사전 계획](../../loop2-design/iteration2-plan.json)에 있다.

[자원 스냅샷](server-usage.json)은 2026-09-27T15:50:52.097599+00:00의 82개 프로세스 합계 RSS 817,836KiB다. 최대값은 아니며, 관측한 affinity는 모두 `0-45`로 전체 허용 52개 CPU의 88.46%였다.

여기 `results.jsonl`의 replay 상대경로는 완료 후 회수할 `records/league/loop2-iteration2/runs/smoke/`를 기준으로 한다. 체크포인트에는 리플레이 중복 사본을 넣지 않는다. 전체 전송·해시 검증·TMP 삭제는 완료 후 본 실행 폴더에서 확인한다.

## 개발 단계 완료

개발 1,760경기까지 회수했다. 오류·몰수는 0이며 이 시점에는 선택·최종 검증이 진행 중이다. [선택 목록](development-selection.json), [전체 개발 요약](runs/development/summary.json), [수정 전후 대응 비교](revision-effects.md)를 보존했다.

Y40경기에서 a_v2_tactical_fit 37승, a_v2_terminal_local·a_local_unabstracted 36승, j_defensive_portfolio 33승, q_v2_window_guard 32승, v2 24승이었다. 첫 배치에서 좋았던 q_threat_window는 이번 9승으로 떨어졌다. 수비 범위를 줄이는 단독 변경의 맵 의존성을 드러낸다. 같은 조건에서 즉시 수비를 함께 넣은 q_v2_window_guard가 32승인 점은 수정의 추가 검증 근거다.

새 수정이 전부 좋아진 것은 아니다. a_v2_continuous_mix는 부모 25승에서 13승으로 악화됐고, j_v2_defensive_delayed는 부모 33승에서 29승이었다. a_v2_terminal_local은 부모와 Y/K 승패가 같아서 점수 차 평가만의 승률 이득은 확인되지 않았다. 국소 행동 확장과 상대 적합도를 함께 쓴 후보는 후속 선택에 남겼지만, 개발 순위만으로 최종 승격하지 않는다.

## 선택 단계와 주 후보 잠금

선택 1,120경기도 완료했다. v2 Y43/80·K40/80, a_v2_terminal_local과 a_local_unabstracted는 각각 Y63/80·K68/80이다. 사전에 정한 순위 규칙으로 **a_v2_terminal_local**을 주 후보로 고정했고 a_local_unabstracted는 보조 후보다. [잠금 기록](locked-finalists.json).

새 종반 점수차 변경이 부모보다 승률을 올렸다고 볼 수는 없다. 두 후보의 개발·선택 승패는 같았다. 최종 검증은 이 비교를 보고 다시 선택하지 않으며, 최초 잠금 주 후보만 기존 승격 기준으로 판단한다. 개발 1위였던 a_v2_tactical_fit은 선택 Y58/80으로 순위가 바뀌었다.

소스 변경 없이 7300–7363의64개 새 맵, 같은5상대,3후보,양진영1,920경기가 이어진다. 완료 전에는 결과를 확정하지 않는다.
