# 두 번째 반복의 완료 검사 체크포인트

동결 소스 `c64d583`, 원격 TMP `/tmp/yk-league-1c1csuif`에서 실행 중인 두 번째 반복의 **smoke 52경기**만 완료 기록으로 보존했다. 오류 0·몰수 0이며 개발·선택·최종 검증이 완료됐다는 뜻은 아니다.

실행은 `iterative_campaign.py --phase final --revision 2`, 개발 7100–7107, 선택 7200–7215, 최종 7300–7363이며 전체 예정 4,892경기다. 정확한 21개 후보 목록은 [사전 계획](../../loop2-design/iteration2-plan.json)에 있다.

[자원 스냅샷](server-usage.json)은 2026-09-27T15:50:52.097599+00:00의 82개 프로세스 합계 RSS 817,836KiB다. 최대값은 아니며, 관측한 affinity는 모두 `0-45`로 전체 허용 52개 CPU의 88.46%였다.

여기 `results.jsonl`의 replay 상대경로는 완료 후 회수할 `records/league/loop2-iteration2/runs/smoke/`를 기준으로 한다. 체크포인트에는 리플레이 중복 사본을 넣지 않는다. 전체 전송·해시 검증·TMP 삭제는 완료 후 본 실행 폴더에서 확인한다.
