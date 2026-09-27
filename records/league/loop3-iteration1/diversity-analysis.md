# v3 개발 후보 다양성 진단

소스 22종 중 건강한 후보 22개에서 서로 다른 승무패 벡터 22개를 관찰했다. 이 수는 실제 알고리즘 또는 행동 종류의 수가 아니다.

같은 **초기 맵·상대·진영 조건**을 짝지었다. 경기 중간 상태가 같다는 뜻은 아니다. trace 동일은 해당 경기의 강한 동일성 근거지만, trace 차이는 명령 표현·순서 차이일 수도 있어 전략 차이를 보장하지 않는다.

| 후보 | Y 승/무/패 | K 승/무/패 | v3 직접 양진영 승점률 | 최저 상대 승점률 | v3와 결과 일치 | v3와 trace 일치/비교 가능 |
|---|---|---|---:|---|---:|---:|
| v3 | 27/0/21 | 40/0/8 | 50.0% | a_v2_tactical_local 50.0% | 100.0% | 96/96 |
| f3_matching | 30/0/18 | 35/0/13 | 50.0% | j_v2_reclaim_relay 43.8% | 66.7% | 0/96 |
| f3_supply_flow | 24/0/24 | 26/0/22 | 25.0% | j_balanced_portfolio 18.8% | 59.4% | 0/96 |
| f3_econ_mission | 30/0/18 | 38/0/10 | 37.5% | v3 37.5% | 88.5% | 18/96 |
| f3_matching_mission | 28/0/20 | 38/0/10 | 56.2% | a_v2_tactical_local 50.0% | 71.9% | 0/96 |
| f3_flow_mission | 26/0/22 | 26/0/22 | 37.5% | j_balanced_portfolio 18.8% | 57.3% | 0/96 |
| f3_econ_portfolio | 29/0/19 | 29/0/19 | 43.8% | a_v2_tactical_local 37.5% | 63.5% | 0/96 |
| s3_role_wait | 29/0/19 | 32/0/16 | 43.8% | j_balanced_portfolio 43.8% | 66.7% | 0/96 |
| s3_split_reserve | 34/0/14 | 26/0/22 | 43.8% | v3 43.8% | 57.3% | 0/96 |
| s3_joint_origins | 35/0/13 | 29/0/19 | 37.5% | v3 37.5% | 59.4% | 0/96 |
| s3_beam_actions | 31/0/17 | 28/0/20 | 31.2% | v3 31.2% | 62.5% | 0/96 |
| s3_screen_refine | 38/0/10 | 39/0/9 | 62.5% | j_balanced_portfolio 56.2% | 66.7% | 0/96 |
| s3_selective_contact | 29/0/19 | 40/0/8 | 62.5% | j_balanced_portfolio 56.2% | 66.7% | 0/96 |
| s3_revisit_search | 32/0/16 | 29/0/19 | 43.8% | a_v2_tactical_local 37.5% | 60.4% | 0/96 |
| r3_lower_tail | 37/0/11 | 35/0/13 | 56.2% | j_balanced_portfolio 50.0% | 67.7% | 0/96 |
| r3_opponent_league | 28/0/20 | 28/0/20 | 62.5% | j_balanced_portfolio 25.0% | 59.4% | 0/96 |
| r3_switching_adversary | 28/0/20 | 30/0/18 | 50.0% | j_balanced_portfolio 43.8% | 69.8% | 0/96 |
| r3_local_counter | 30/0/18 | 28/0/20 | 43.8% | a_v2_tactical_local 43.8% | 55.2% | 0/96 |
| r3_joint_counter | 29/0/19 | 34/0/14 | 43.8% | v3 43.8% | 64.6% | 0/96 |
| r3_population_fit | 23/0/25 | 32/0/16 | 25.0% | v3 25.0% | 70.8% | 0/96 |
| r3_minimax_regret | 30/0/18 | 27/0/21 | 43.8% | j_balanced_portfolio 25.0% | 58.3% | 0/96 |
| r3_mixed_matrix | 28/0/20 | 34/0/14 | 31.2% | v3 31.2% | 67.7% | 0/96 |

기존에 선정한 공략형: `s3_selective_contact`, `r3_opponent_league`. 선정 규칙과 lock을 그대로 보존했다.
두 공략형 s3_selective_contact / r3_opponent_league: 결과 일치 61.5%, trace 동일 0/96경기.

전체 제외 후보: {}. 오류·몰수가 있는 후보는 일부 경기만 골라 집계하지 않았다.

하위 상대 3종·상대별 양 진영 승무패·전체 후보 쌍의 비교·동일 벡터 그룹은 JSON에 있다. 개발 성적은 공략형 선정에 이미 사용됐으므로 새 맵에서 재검증해야 한다. 이 보고서는 사후 재선정이나 승격 기준 변경에 사용하지 않는다.
