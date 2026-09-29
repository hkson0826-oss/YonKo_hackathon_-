# Endgame1 candidate audit — 2026-09-29

Status: compiled and smoke-tested, **experimental; not accepted as a submission**.

## Inputs and scope

- Original repository branch read at start/end: `jisang`.
- Read original `/home/dlwltkd/YonKo_hackathon_-/AGENTS.md` in full, `docs/26-상대정보확장과대응전략.md`, v4 source and existing action-search/repair test harnesses.
- All source mutations confined to `/tmp/yk-deadline-20260929/experiments/deadline_candidates/endgame1/`.
- Base: `/tmp/yk-deadline-20260929/submissions/iterative-v4/`.
- Candidate main SHA256: `5e4d6834dcec7d89ebec46ecd0e97226210e871e45e38420291f9ab5c4ebb927`.
- `protocol.hpp`, `generated.hpp`, `submission.json` copied unchanged.
- No Git mutation, browser access, repository edits or publication performed by this worker.

## Hypothesis and implementation

The current v4 `S3_MODE=5` generates separate modifications at each source and picks one shortlisted action. It does not combine modifications to two separate origins. Official tAIger evidence motivates simultaneous control changes on multiple final-turn sites; no win reconstruction is claimed.

For state turns 157–159 only, preserve the original search with an 80 ms seed budget and add a width-5 beam across at most eight relevant unit origins. Candidate moves include waiting, a single F moving to a reachable site, W moving, and F/W moving together. Single-F movement leaves remaining flags available in place. Sources include units produced by the seed on the same turn. Candidate generation allows enemy-site neutralization, even if there is insufficient time to fully own that site.

Screen the complete combined action against the four existing enemy policies with an exact one-turn transition. Re-evaluate the beam finalists to the terminal turn with the existing continuation and all four opponent models. Accept only when the original robust weighted objective improves and no opponent-specific terminal value is below that of the seed. The existing 135 ms deadline remains the outer bound. Before state turn 157 the original function runs unchanged.

Transition rules, evaluation constants, observation logic, enemy policies and production allocation are unchanged. This candidate jointly rearranges movement of already allocated production; it does **not** search alternative production orders.

## Validation completed

Compiler: `g++ (GCC) 16.2.1 20260810`, `-std=c++20 -O2`.

```
g++ -std=c++20 -O2 experiments/deadline_candidates/endgame1/main.cpp -o experiments/deadline_candidates/endgame1/bot
g++ -std=c++20 -O2 experiments/deadline_candidates/endgame1/check.cpp -o experiments/deadline_candidates/endgame1/check
experiments/deadline_candidates/endgame1/check
```

Result:

```
joint_capture=pass neutralization=pass production_stock=pass random_states=36 legality=pass max_ms=90.5331
```

The harness checks an atomic two-origin capture candidate that wins where either single capture would not, terminal enemy-site neutralization, same-turn spawned F origin availability, action stock/resource/teleport legality, 36 random endgame decisions, and original expired-budget behavior outside the endgame. These are synthetic legality/candidate-presence tests, not a measured tournament win-rate improvement.

## Risks and outstanding checks

1. The last three turns divide the original 135 ms search budget into an 80 ms seed and beam refinement. A weaker seed may regress even though refinement is guarded against that seed. Compare against unmodified v4 and currently selected v7 before adoption.
2. All four opponents still belong to the existing policy family. Beam guards do not cover an unseen final-turn split or coordinated capture strategy.
3. One-step screening can remove an action whose benefit is visible only in two or three turns. Width five is a bounded approximation.
4. Hidden score imputation and cumulative occupation histories are inherited unchanged.
5. Local timing uses GCC16 and synthetic states; official GCC12 compilation and representative protocol latency remain the coordinator's check.
6. No benchmark outcomes have been observed by this worker. Keep v4/v7 submission artifacts until independent comparison passes.
