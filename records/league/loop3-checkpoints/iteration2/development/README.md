# 완료된 2차 개발 단계

2026-09-28 KST. 8개 맵·8상대·양 진영, 20후보의 **2,560경기**를 완료했다. 오류·몰수 0, 후보 최대 응답 187.02ms였다. 선택·holdout은 아직 진행 중이며 제출 추천은 v3를 유지한다.

| 후보 | Y 승/64 | K 승/64 | 선택 단계 진출 |
|---|---:|---:|---|
| r3_lower_tail | 47 | 43 | 예 |
| s3_v2_screen_intact_base | 46 | 46 | 예 |
| r3_v2_y_tail | 46 | 42 | 예 |
| s3_v2_screen_paired_guard | 43 | 44 | 예 |
| f3_v2_warrior_reserve | 42 | 49 | 예 |
| r3_v2_pareto_local | 42 | 39 | 예 |
| s3_v2_screen_continuation | 42 | 44 |  |
| f3_matching | 42 | 40 |  |
| s3_screen_refine | 41 | 47 |  |
| f3_v2_movement_matching | 41 | 45 |  |
| s3_v2_screen_roundrobin | 40 | 45 |  |
| f3_econ_mission | 37 | 43 |  |
| s3_joint_origins | 37 | 36 |  |
| s3_selective_contact | 36 | 39 |  |
| f3_v2_safe_econ_mission | 35 | 43 |  |
| f3_v2_soft_matching | 33 | 39 |  |
| r3_v2_tail_recheck | 33 | 44 |  |
| v3 | 33 | 41 | 예 |
| r3_v2_mean_control | 33 | 41 |  |
| r3_opponent_league | 32 | 37 |  |

무승부는 없었다. 현재 표는 후보 선택에 사용한 개발 자료이며 독립 검증 성적이 아니다. 1차 리그와 맵·상대가 달라 원시 승률을 직접 비교하지 않는다. 수정 전후 비교는 이번 리그에서 같은 조건으로 돌린 부모와 비교한다.

선택 단계는 24개 새 맵에서 위의 7후보(기준선 포함)를 비교한다. 이후 최초로 잠근 주 후보만 승격할 수 있다. 전체 원본은 원격 작업이 끝난 후 회수·해시 검증한다. [완료 시점의 파일 해시](capture.json).
