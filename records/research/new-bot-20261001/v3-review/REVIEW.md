# Frozen v3 review, 2026-10-01

Reviewed source SHA256: `5cff84e533234f02fa8665de009ec7b2d10641c5baf5a33ac3fcc7edddb434e1`.
No candidate source, test, or Git changes were made. This is the implementer's second review; the separate HALL/protocol checks are owned by the prior/rules reviewers.

## Reservation accounting

The v3 changes preserve source stock accounting. Rendezvous groups subtract from availableW before committing the copied plan and credit supplied W once. Defense reservations do the same. F escort credit uses only the newly added arrivalW delta; sharing an already protected cell does not create a second goalSupply credit. Production preference is a copy of the actual goal ledger and does not mutate it. Each defense assignment takes at most remaining need; every iteration either consumes positive W or leaves the entire remaining stack in place, so the new loop terminates.

A temporary copy adds assertions after rendezvous, defense, F assignment, and completed W assignment. It checks nonnegative stock/resources, conservation of source+production = available+arrivals, departure limits, total credited W <= actual reserved W, final arrivals matching emitted movement, and one TELE of at most five. All 11 public protocol tests passed with 81 observations; observed maximum response6.27ms. This is targeted development evidence, not a worst-case runtime proof. Evidence: `instrumented-v3.cpp`, `ledger-audit.json`, `ledger-audit.log`.

## Macro scope

`MISSION_RENDEZVOUS=0` only skips the rendezvous call. supportMemory/supportIntents start empty and have no other writer, so no intent filter or restored W reservation remains active. Defense, F mission memory, value, beam, production, and safety checks remain the same. The normal binary passed the hospital rendezvous contract; the off binary failed that single contract while passing the other original nine. Both passed the new HALL raid contract in the independent reviewer run.

## SDK ordering and limitations

The official pipeline is spawn -> simultaneous movement -> combat -> income -> capture. A currently observed enemy F at distance D>=1 can threaten the building after D actions, and a W arriving on that same action can kill it before capture. The existing next-distance < deadline check has the correct indexing, including newborn W movement. Current owned stations can shorten enemy F ETA by walk-to-station + one TELE action + walk-to-target. Future station ownership is assumed, not guaranteed.

Defense need is a heuristic rather than a survival bound: it sums current enemy W within walking distance of the enemy F ETA and adds one. It omits enemy future production and W TELE, and when enemy F is already on a building eta=0 is used for W pressure even though the action deadline is clamped to1. These are inherited v1/v2 limitations; v3 broadens target coverage and fixes duplicate allocation, without claiming a full adversarial defense guarantee. Emergency defense production can also choose a risk-delayed warriorStep; later anti-drip cancellation can invalidate an expected arrival. The next observation replans, but future deadline delivery is not guaranteed. Do not expand the frozen revision during its league solely on this static review.

## Three-way comparison

`--focus mission3,mission3_no_rally,v8` produces aggregate/outcome/behavior sections for all three. `paired_common()` explicitly returns `{}` unless focus length is2. Existing player records permit the three pairwise comparisons without rerunning matches.

`pairwise.py` reads the common-opponent analysis JSON, rejects duplicate candidate/opponent/map/side keys, invokes the existing two-candidate paired point comparison for every pair, and adds paired score-margin differences plus matched job IDs. Direct matches should be analyzed separately: mixing schedules changes aggregate opponent weights, and the existing pairing index otherwise silently overwrites duplicate keys. Map-cluster bootstrap intervals with only four maps remain development summaries, not strong generalization evidence; no multiple-comparison correction is applied.

```sh
python3 /tmp/yk-mission-v3-review-20261001/pairwise.py \
  --analysis /absolute/path/to/common-analysis.json \
  --output /absolute/path/to/common-paired.json
```

A hand-computed one-map/two-side smoke fixture verifies expected point differences +0.5, -0.5, -1.0. It is synthetic validation of the aggregation script, not a bot match result.
