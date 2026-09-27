# 실제 코드 재수정의 대응 비교

같은 개발 맵·상대·진영에서 수정 전후를 비교한다. 여러 비교를 탐색한 8개 개발 맵 결과이므로 독립적인 최종 검증이나 단일 원인의 일반화 증명은 아니다.

| 수정 후보 | 대조 부모 | Y 승점/경기 | 부모 Y 승점/경기 | 차이와 맵 95% 구간 |
|---|---|---|---|---|
| q_v2_window_guard | q_threat_window | 32/40 | 9/40 | +57.5%p [+40.0, +75.0] |
| q_v2_tactical_mean | q_threat_window | 12/40 | 9/40 | +7.5%p [+0.0, +22.5] |
| q_v2_tactical_worst | q_threat_window | 19/40 | 9/40 | +25.0%p [+7.5, +42.5] |
| q_v2_guard_tactical | q_v2_window_guard | 29/40 | 32/40 | -7.5%p [-17.5, +0.0] |
| q_v2_guard_tactical | q_v2_tactical_mean | 29/40 | 12/40 | +42.5%p [+20.0, +62.5] |
| j_v2_defensive_delayed | j_defensive_portfolio | 29/40 | 33/40 | -10.0%p [-32.5, +12.5] |
| j_v2_reclaim_flags7 | j_reclaim_portfolio | 27/40 | 28/40 | -2.5%p [-22.5, +12.5] |
| j_v2_reclaim_relay | j_reclaim_portfolio | 29/40 | 28/40 | +2.5%p [-20.0, +20.0] |
| j_v2_reclaim_relay_delayed | j_v2_reclaim_relay | 29/40 | 29/40 | +0.0%p [-32.5, +32.5] |
| a_v2_terminal_local | a_local_unabstracted | 36/40 | 36/40 | +0.0%p [+0.0, +0.0] |
| a_v2_tactical_local | a_v2_terminal_local | 32/40 | 36/40 | -10.0%p [-32.5, +7.5] |
| a_v2_tactical_fit | a_v2_tactical_local | 37/40 | 32/40 | +12.5%p [+0.0, +32.5] |
| a_v2_continuous_mix | a_opponent_fit | 13/40 | 25/40 | -30.0%p [-57.5, +2.5] |
