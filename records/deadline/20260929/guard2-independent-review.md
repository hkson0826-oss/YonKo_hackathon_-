# guard2 independent review — 2026-09-29

Verdict: **no action-legality/resource-conservation defect found, but the known 12015 escort split is NOT prevented by guard2.** Do not describe that specific regression as fixed. The new guard prevents a narrower class: removing W when doing so exposes a seed F to currently reachable enemy W on its immediate destination.

Reviewed source SHA256: `e73cf900936c62f616aea26c00e68ea53f9e94a2df7c307ca3f77f6d1b68efaa`. Candidate source was read only and not changed.

## Exact known-case check

Baseline replay: `/tmp/yk-loop1-20260929/runs/development1/replays/5bf6e9460652d73d8498fd99.json.gz`.

Used the actual state after turn 15 and v4's actual Y turn-16 commands from the same replay, then called `deadline_guard` directly. This removes differences from a fresh wall-clock-limited search and tests the repair function itself. No enemy unit is within Manhattan distance four of the F destination (2,7); the guard's one-step `danger` there is zero.

Reproducer: `/tmp/yk-guard2-replay-review.cpp`.

Observed guard2 output at source (1,7):

```
F 1,7 -> 2,7 n=1
W 1,7 -> 1,6 n=1
escort_to_F_destination=0
```

The existing F/W escort still splits exactly as in the reported guard1 first divergence. This does not prove that this one action caused the final loss. It does show guard2's danger-based condition cannot be cited as fixing that specific observed action. The condition intentionally allows W removal from an immediately safe F destination and therefore leaves multi-turn escort requirements outside its guarantee.

## Legality, stock and production audit

- The new seed F/W landing arrays start from sanitized stock and apply the complete seed movement, so they include same-turn production and TELE destinations.
- Each tentative reservation is assembled against all previously accepted reservations. This cumulative check prevents a second reservation from silently reusing the first reservation's stock.
- `stock > locked` controls donor eligibility, and `assemble` clamps old W departures to the remaining stock before appending reserved departures.
- A failed production relocation restores donor count, donor stock, appended production and recipient stock. A successful relocation replaces one W with one W at a legal site, preserving total cost.
- `a_clean` remains the final legality/TELE-count check. No new illegal movement or extra teleport was found.
- Enemy F/W currently standing on an enemy-owned station use the one-TELE ETA only if the destination is also enemy-owned. Walking to a station before teleporting remains intentionally unmodeled and is documented in the candidate's README.
- Removing W from an owned building without a seed F, W needed to kill an enemy F rather than merely tie enemy W, multi-turn escorts and attack opportunity cost remain outside this check.
- `safe_reservation` performs extra action assembly inside the source loop after the original search and has no deadline check. Full-response latency must include that work; syntax/unit success is not a server timing result.

## Independent validation run

```
g++ -std=c++20 -O2 -fsyntax-only experiments/deadline_candidates/guard2/main.cpp
g++ -std=c++20 -O2 experiments/deadline_candidates/guard2_test.cpp -o /tmp/yk-guard2-independent-tests
/tmp/yk-guard2-independent-tests
```

Both passed with GCC16.2.1. Test output:

```
guard2: all guard1 checks plus escort, safe alternate, production escort, TELE ETA/ownership and W TELE checks passed
```

The synthetic escort tests correctly verify immediate danger protection, a safe alternate defender, and equivalent protection when moving production. They do not test the actual immediately-safe 12015 destination, whose continued split is demonstrated above. No full-game benchmark or GCC12 compilation was performed for this review.
