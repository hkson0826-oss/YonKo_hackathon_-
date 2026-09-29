# Deadline final acceptance audit

Decision: **PASS**. Candidate `guard3`, baseline `v4`.

All predeclared local deadline gates passed. Comparison is against frozen local v4 and the declared local opponent pool. The currently selected live v7 source was not recovered or compared. Passing does not establish improvement over v7 or official leaderboard score.

| Stage | Side | Candidate W/D/L | Baseline W/D/L | Point-rate difference | Map bootstrap95% |
|---|---|---|---|---:|---|
| selection | Y | 24/0/6 | 19/0/11 | +16.7pp | [0.0, 33.3]pp |
| selection | K | 27/0/3 | 21/0/9 | +20.0pp | [0.0, 36.7]pp |
| selection | overall | 51/0/9 | 40/0/20 | +18.3pp | [5.0, 31.7]pp |
| final | Y | 45/0/5 | 31/0/19 | +28.0pp | [20.0, 36.0]pp |
| final | K | 44/0/6 | 38/0/12 | +12.0pp | [6.0, 18.0]pp |
| final | overall | 89/0/11 | 69/0/31 | +20.0pp | [15.0, 25.0]pp |

| Final opponent | Y win difference | K win difference |
|---|---:|---:|
| v3 | +5 | +2 |
| teammate | +0 | +0 |
| j_balanced_portfolio | +3 | +1 |
| s3_selective_contact | +6 | +3 |
| raid1 | +0 | +0 |

| Fixed gate | Result |
|---|---|
| selection_primary_Y_improves | PASS |
| final_Y_nonregression | PASS |
| final_overall_nonregression | PASS |
| final_exactly_10_independent_maps | PASS |
| no_opponent_side_regression_of_3_wins | PASS |
| selection_and_final_errors_zero | PASS |
| selection_and_final_forfeits_zero | PASS |

Confidence intervals describe map-sample uncertainty and are not additional gates. The3-win regression threshold is applied to each opponent and each side separately; combined-opponent outcomes are also present in JSON.

No source, arena, or frozen evidence was modified. This audit does not perform ZIP/runtime validation or browser submission.
