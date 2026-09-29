# guard1 independent review — 2026-09-29

Verdict: **no action-legality or resource-conservation defect found in the reviewed diff. Keep as an experimental candidate pending paired-match results.** One concrete arrival-time coverage gap and two performance risks remain. Review was read-only; no candidate source was modified and no test/benchmark result is invented here.

Reviewed guard1 source SHA256: `0ebf7b35214b57b49e86b67a751868bad8d284340969fcd1573bef50c170696f`.

## Findings

1. **Enemy F teleport is absent from the arrival deadline (main.cpp:956–965).** `flag_eta` uses only ordinary board distance. A flag on a distant enemy-owned STATION can teleport to a second enemy-owned STATION next to our economic building, then arrive the following turn; ordinary distance can exceed six and cause the threat to be omitted entirely. Enemy W teleport is separately represented in the one-step `danger` calculation, so that protection does not fix F timing. This is a real coverage gap in the stated deadline interpretation, not an illegal emitted action. No current-match occurrence has been established.
2. **Defense patches are applied after search with no re-evaluation (main.cpp:1020–1021).** Taking one W from a winning attack, critical F escort, or another defensive position can reduce the actual result. The patch limits scope to at most two bare-F threats against home ENG/HALL before turn 150, but legality alone does not establish a strategic improvement. Benchmark and representative replay review are required.
3. **Any enemy W that can arrive no later than F disables the mission (main.cpp:965).** This is conservative for one-W defense, but makes the candidate a bare-F infiltration guard rather than general joint defense against a supported attack. State this scope when interpreting wins/losses.

## Legality reasoning

- Seed action is sanitized before deriving stock. Only original W plus same-turn production fund departures.
- Every assigned unit increments `locked[source]`; selection requires `stock > locked`, preventing double spending across two missions.
- Production relocation removes one W and adds one W at a currently legal owned hospital or base. Unit cost is team/state dependent, not production-site dependent; total spending is unchanged.
- Donor relocation requires remaining stock beyond locked reservations before decrementing stock.
- Original W departures are clamped to `stock - locked`; reserved departures are appended afterward. A reserved unit at its target simply remains there.
- Final `a_clean` rechecks movement adjacency, teleport use, production sites and counts.
- Only defender geometric distance <= enemy F deadline is accepted, and the immediate step decreases that distance. The distance is obstacle-aware, but excludes teleport as noted above.
- The guard has no internal clock check, so it adds small bounded work after the 135 ms search. It must be included in measured full-protocol response latency.

## endgame1 full-source/test audit

Reviewed main SHA256 remains `5e4d6834dcec7d89ebec46ecd0e97226210e871e45e38420291f9ab5c4ebb927`.

The diff preserves transition, evaluation, observation, opponent policies and pre-turn-157 search. `e1_groups` includes targets at distance <= remaining turns; after one step `e1_choices` requires remaining distance < remaining turns. This correctly retains terminal neutralization-only actions. Same-turn production is included through `s3_stock`; `s3_move` and `a_clean` preserve stock and legal routes.

`check.cpp` contains three synthetic candidate-presence/legality scenarios and **36 full endgame decisions** (18 random states × both teams), plus an expired-budget pre-endgame fallback comparison. Maximum measured decision latency was 90.5331 ms on this host with GCC16/O2. The two-origin scenario checks that a winning combined action is generated; it does not prove the actual bounded beam always selects that action. The tests are not 36 full games.

The principal strategic risk remains that its guard protects the shortened 80 ms seed rather than the unmodified 135 ms v4 action. Beam width five can also prune individually weak moves whose combination would be strong. The single-F move removes other F departures at that origin and leaves remaining flags stationary; it does not simultaneously send those other flags elsewhere.

For version control, include only `main.cpp`, `protocol.hpp`, `generated.hpp`, `submission.json`, `check.cpp`, `audit.json` and chosen documentation. The local `bot` and `check` binaries are build artifacts and must be excluded. No ZIP was produced by this worker.
