# Loop1 paired loss review

Read-only snapshot: 2026-09-29T10:02:41.937068+00:00; completed 240/240. Errors 0, forfeits 0. Declared batch is complete.

Read prefix SHA256: `2989630a450370e040e207c294857bd62af2d854e6a935d5ab2e1e2738f156ba`. Sources and planned maps: `/tmp/yk-loop1-20260929/plans/development1-policy.json`. Full pair evidence: `/tmp/yk-loop1-loss-review.json`.

## Observed pairs

| Candidate | Completed matched pairs | Candidate wins | v4 wins | v4 win → candidate loss |
|---|---:|---:|---:|---:|
| guard1 | 80 | 59 | 56 | 14 |
| endgame1 | 80 | 57 | 56 | 11 |

Incomplete paired subsets are ordered by job completion and are not an unbiased final result. Report Y and K separately in final selection; these aggregate counts are only an inspection index.

## Confirmed loss conversions

| Candidate | Map | Side | Opponent | Candidate/v4 margin | First raw-command/state divergence |
|---|---:|---|---|---:|---|
| endgame1 | 12010 | K | s3_selective_contact | -35/11 | 20/20 |
| endgame1 | 12010 | Y | s3_selective_contact | -23/10 | 4/4 |
| endgame1 | 12011 | K | v3 | -3/9 | 16/16 |
| endgame1 | 12012 | K | s3_selective_contact | -31/32 | 8/8 |
| endgame1 | 12012 | Y | s3_selective_contact | -24/35 | 9/9 |
| endgame1 | 12013 | Y | s3_selective_contact | -29/30 | 15/15 |
| endgame1 | 12015 | Y | s3_selective_contact | -30/21 | 17/17 |
| endgame1 | 12016 | Y | v3 | -35/27 | 38/38 |
| endgame1 | 12017 | K | s3_selective_contact | -3/15 | 20/20 |
| endgame1 | 12018 | K | v3 | -6/30 | 40/40 |
| endgame1 | 12018 | Y | s3_selective_contact | -25/5 | 17/17 |
| guard1 | 12010 | Y | j_balanced_portfolio | -23/1 | 10/14 |
| guard1 | 12011 | K | s3_selective_contact | -3/5 | 23/23 |
| guard1 | 12011 | K | v3 | -7/9 | 16/16 |
| guard1 | 12011 | Y | j_balanced_portfolio | -28/27 | 17/17 |
| guard1 | 12012 | K | j_balanced_portfolio | -12/31 | 7/9 |
| guard1 | 12012 | K | s3_selective_contact | -29/32 | 7/8 |
| guard1 | 12012 | Y | v3 | -1/18 | 7/8 |
| guard1 | 12013 | K | j_balanced_portfolio | -14/25 | 14/14 |
| guard1 | 12013 | Y | j_balanced_portfolio | -29/25 | 14/14 |
| guard1 | 12014 | K | j_balanced_portfolio | -6/21 | 10/10 |
| guard1 | 12015 | K | teammate | -3/18 | 11/11 |
| guard1 | 12015 | Y | s3_selective_contact | -4/21 | 16/16 |
| guard1 | 12016 | Y | j_balanced_portfolio | -5/33 | 17/20 |
| guard1 | 12018 | Y | s3_selective_contact | -9/5 | 6/7 |

## Guard failures useful for revision

1. **12015 / Y / s3_selective_contact:** guard1 loses −4 where v4 wins +21. First actual state divergence is turn16. Both versions move F1 at(1,7) right; v4 sends its W1 escort right too, while guard1 sends that W1 up to the HALL at(1,6). This directly demonstrates the guard can split an existing F/W escort. It does not prove this one action alone causes the final loss. Guard production W757 versus v4 W832; engineering turns131 versus155.

2. **12010 / Y / j_balanced_portfolio:** guard1 loses −23 versus v4 +1. Raw command text first differs at turn10 but resulting state remains equal until turn14. At turn14 the baseline sends three W at(3,8) down; guard1 sends two down and redirects one left. The original attack/escort allocation is changed by the defensive reservation. Engineering turns138 versus145 and turn120 score5 versus15. Use state equality, not command ordering alone, when identifying the causal branch.

3. **12011 / K / s3_selective_contact:** guard1 loses −3 versus v4 +5. At turn23 it retains one W at ENG(11,12), reducing the north-moving group2→1 while other actions match. Engineering remains nearly equal(157 versus158 turns); final defeat is therefore not evidence of an engineering-holding improvement. Guard-only economy statistics would miss the combat/position tradeoff.

These observations support testing guard2’s escort-preservation check; they do not justify increasing guard strength or assuming any new threshold is better without matched evaluation. strategy_audit has received the cases and independently prepared guard2.

## Endgame attribution problem

Of 80 matched endgame1/v4 games, 71 already differ in actual game state before turn158. The new code only activates at internal s.turn≥157 (protocol turn158). Therefore most current win/loss differences cannot be attributed to the last-three-turn beam. In particular12018/Y/contact changes first in the unchanged opponent K at turn17: F1/W2 at(14,4) move down instead of left, leading to −25 versus+5.12010/K/v3 differs in candidate F movement on turn29 and ends+34 versus+11, before the new terminal search ever acts in the candidate game(end135).

Likely factors include wall-clock-bounded search and CPU contention/binary optimization layout; this inspection does not establish their relative causes. No runtime errors were needed for this divergence. Reuse the same preterminal observation to compare baseline and terminal action under fixed opponent actions, and verify actual full-match performance under comparable load. A full-game gain is a performance observation, not proof of the stated terminal mechanism.

## Scope

All source, arena, manifests and replays were read only. No extra league, bot process, or browser session was launched. These cases are development evidence and cannot remain independent final-test evidence after they guide guard2 or endgame2.

## Completed side-specific results

| Candidate | Side | Matches | Candidate wins | v4 wins |
|---|---|---:|---:|---:|
| guard1 | Y | 40 | 30 | 27 |
| guard1 | K | 40 | 29 | 29 |
| endgame1 | Y | 40 | 28 | 27 |
| endgame1 | K | 40 | 29 | 29 |

Terminal-only actual-state divergences: 0; completely unchanged state trajectories: 9. Thus no completed pair isolates the proposed terminal-search benefit. Endgame1 overall full-game score is57/80 vs v4 56/80, while guard1 is59/80 vs56/80. These10-map results remain development evidence.

## Decision metrics and runtime

| Candidate | Y win rate | Y difference vs v4 | Map bootstrap95% interval | K win rate | Main Y regression |
|---|---:|---:|---:|---:|---|
| v4 | 27/40=67.5% | — | — | 29/40=72.5% | — |
| guard1 | 30/40=75.0% | +7.5pp | −7.5 to+25.0pp | 29/40=72.5% | j_balanced5/10 vs7/10(−20pp) |
| endgame1 | 28/40=70.0% | +2.5pp | −17.5 to+25.0pp | 29/40=72.5% | s3_selective_contact4/10 vs7/10(−30pp) |

Guard1 Y v3 improves3→8/10, teammate remains10/10, contact remains7/10. Guard1 K j_balanced regresses30pp. Endgame1 Y v3 improves3→6/10, j_balanced7→8/10, teammate remains10/10. Both Y intervals include no gain; both have material opponent-specific regressions, so this batch does not support promotion. Guard2’s causal escort repair is justified for new development maps; its improvement remains unmeasured.

All240 games completed without errors or forfeits. Candidate response p95/max: v4 121.77/129.24ms, guard1 121.68/128.99ms, endgame1 121.61/129.95ms. These satisfy the local300ms turn limit but show no substantial timing separation. Wall-time-limited search can diverge while every response remains within the protocol deadline.

Root’s proposed next development schedule(v4,guard2,endgame2,midgame1 × old4+raid1 ×8 new maps12030–12037 ×Y/K) is **320matches**, with map separation from12010–12019. Keep raid1 as an added stress pool and report old4 separately; otherwise changes in average performance can be caused by changing the opponent distribution. This remains development, not final evidence.
