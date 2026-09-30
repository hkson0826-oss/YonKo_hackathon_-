# v4 종반 F 후보 검증

- v3 source SHA256: `5cff84e533234f02fa8665de009ec7b2d10641c5baf5a33ac3fcc7edddb434e1`.
- v4 source SHA256: `b06263e5cffee351fa23e6279b2f6f5f1cda0a5c1106cfc3516c005aad97c9e7`.
- 독립 담당: rules_new_bot. 테스트 소스는 저장소 `tests/test_mission_scheduler.py`, `tests/mission_scheduler_cases.py`다.

공통 상대 seed19010 K/j_balanced_portfolio, job `7b0cbafcd38b265caedd8dd6`의 공식 엔진 상태를 복원했다. 원본 T1–155의 합법 관측을 입력한 뒤 TURN156부터 적을 정지·무생산으로 두고 실제 봇을 5턴 실행했다. 미공개 점수는 공식 serialize_turn의 마스크를 유지했다.

v3는 과거 155개 출력이 모두 원본과 일치했다. 분기 이후 F 생산 없이 WATCH(9,9)를 중립으로 남겨 종반 새 F 생산·점령 계약을 만족하지 못했다. 이 조건에서도 최종 경기 점수는 K17:Y12 승리이므로, ‘v3 실패’는 해당 점령 계약의 실패를 뜻한다.

v4는 과거 관측 출력 154/155개가 원본과 같았다. T156 병원(12,8)에 새 F1을 생산해 (12,9)→(11,9)→(10,9)→(9,9)로 보냈고 T159에 WATCH를 점령했다. 마지막 점수는 K21:Y12이며 F5가 모두 생존했다. 기존 11개를 포함한 전체 12개 검사가 통과했고, 총 241개 관측의 최대 응답은 5.814ms였다. 원본 관측을 강제로 이어 넣은 테스트라 전체 경기 재현이나 상대의 후속 대응을 포함한 승률 검증이 아니다.

`v4-independent-audit.json`과 `.log`가 전체 결과다. `v3-quota-probe.json`, `v4-quota-probe.json`, `quota-probe.py`는 독립 담당의 앞선 개발 탐침이다. 실행 바이너리는 보존하지 않았다. 탐침의 고정 경로는 원 실행 당시 `/tmp` 경로이므로 재실행에는 저장소 테스트를 우선한다.

별도의 원본 적 명령 고정·수동 새 F 경로 반사실은 `records/benchmarks/mission-20261001/v3/diagnosis`에 보존한다. 그 19:16 결과와 여기의 정지 적 실제 정책 21:12 결과는 다른 검사다.

```sh
MISSION_SCHEDULER_AUDIT=/tmp/mission-v4-validation.json python3 -B tests/test_mission_scheduler.py
```
