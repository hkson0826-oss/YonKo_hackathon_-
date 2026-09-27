# v3 개발 후보 다양성 진단

소스 20종 중 건강한 후보 20개에서 서로 다른 승무패 벡터 19개를 관찰했다. 이 수는 실제 알고리즘 또는 행동 종류의 수가 아니다.

같은 **초기 맵·상대·진영 조건**을 짝지었다. 경기 중간 상태가 같다는 뜻은 아니다. trace 동일은 해당 경기의 강한 동일성 근거지만, trace 차이는 명령 표현·순서 차이일 수도 있어 전략 차이를 보장하지 않는다.

| 후보 | Y 승/무/패 | K 승/무/패 | v3 직접 양진영 승점률 | 최저 상대 승점률 | v3와 결과 일치 | v3와 trace 일치/비교 가능 |
|---|---|---|---:|---|---:|---:|
| v3 | 33/0/31 | 41/0/23 | 50.0% | a_v2_tactical_local 31.2% | 100.0% | 128/128 |
| f3_v2_soft_matching | 33/0/31 | 39/0/25 | 50.0% | a_v2_tactical_local 37.5% | 65.6% | 0/128 |
| f3_v2_movement_matching | 41/0/23 | 45/0/19 | 81.2% | s3_selective_contact 37.5% | 59.4% | 0/128 |
| f3_v2_safe_econ_mission | 35/0/29 | 43/0/21 | 43.8% | a_v2_tactical_local 43.8% | 78.1% | 17/128 |
| f3_v2_warrior_reserve | 42/0/22 | 49/0/15 | 62.5% | j_v2_reclaim_relay 50.0% | 69.5% | 1/128 |
| s3_v2_screen_paired_guard | 43/0/21 | 44/0/20 | 43.8% | v3 43.8% | 57.0% | 0/128 |
| s3_v2_screen_roundrobin | 40/0/24 | 45/0/19 | 31.2% | v3 31.2% | 68.0% | 0/128 |
| s3_v2_screen_continuation | 42/0/22 | 44/0/20 | 81.2% | s3_selective_contact 31.2% | 62.5% | 0/128 |
| s3_v2_screen_intact_base | 46/0/18 | 46/0/18 | 62.5% | s3_selective_contact 56.2% | 65.6% | 0/128 |
| r3_v2_mean_control | 33/0/31 | 41/0/23 | 50.0% | a_v2_tactical_local 31.2% | 100.0% | 127/128 |
| r3_v2_y_tail | 46/0/18 | 42/0/22 | 50.0% | j_balanced_portfolio 50.0% | 79.7% | 62/128 |
| r3_v2_pareto_local | 42/0/22 | 39/0/25 | 43.8% | j_balanced_portfolio 43.8% | 64.8% | 0/128 |
| r3_v2_tail_recheck | 33/0/31 | 44/0/20 | 56.2% | s3_selective_contact 31.2% | 71.1% | 0/128 |
| s3_screen_refine | 41/0/23 | 47/0/17 | 56.2% | j_balanced_portfolio 50.0% | 65.6% | 0/128 |
| s3_joint_origins | 37/0/27 | 36/0/28 | 25.0% | s3_selective_contact 25.0% | 61.7% | 0/128 |
| s3_selective_contact | 36/0/28 | 39/0/25 | 56.2% | j_balanced_portfolio 18.8% | 61.7% | 0/128 |
| f3_matching | 42/0/22 | 40/0/24 | 56.2% | j_balanced_portfolio 31.2% | 64.1% | 0/128 |
| f3_econ_mission | 37/0/27 | 43/0/21 | 43.8% | a_v2_tactical_local 43.8% | 79.7% | 17/128 |
| r3_lower_tail | 47/0/17 | 43/0/21 | 43.8% | v3 43.8% | 64.1% | 0/128 |
| r3_opponent_league | 32/0/32 | 37/0/27 | 25.0% | j_v2_reclaim_relay 18.8% | 60.2% | 0/128 |

기존에 선정한 공략형: `s3_v2_screen_continuation`, `f3_v2_movement_matching`. 선정 규칙과 lock을 그대로 보존했다.
두 공략형 s3_v2_screen_continuation / f3_v2_movement_matching: 결과 일치 70.3%, trace 동일 0/128경기.

전체 제외 후보: {}. 오류·몰수가 있는 후보는 일부 경기만 골라 집계하지 않았다.

하위 상대 3종·상대별 양 진영 승무패·전체 후보 쌍의 비교·동일 벡터 그룹은 JSON에 있다. 개발 성적은 공략형 선정에 이미 사용됐으므로 새 맵에서 재검증해야 한다. 이 보고서는 사후 재선정이나 승격 기준 변경에 사용하지 않는다.
