# Deadline packager independent review — 2026-09-29

Read-only review of `experiments/package_deadline_candidate.py`, its six tests, and the reused exact-ZIP/runtime helpers in `experiments/package_frozen_candidate.py`. No shared source file was modified. Existing unit tests passed; two additional temporary-fixture probes reproduced metadata-validation gaps. No full runtime package job was started by this reviewer.

## Findings

### 1. Policy map declarations are not compared with the actual plan (line 60–67)

`verify_run` checks the policy stage, baseline and source hashes but does not require `policy.map_seeds == plan.map_seeds` (nor policy opponents/candidates where present). The actual plan drives jobs/results and returned maps, while earlier-stage contamination checking uses policy maps. This weakens the link between a predeclared run policy and what was actually executed.

Reproduced with the existing test fixture: change `plans/final-policy.json` map seeds from `[130]` to `[999999]`; `check_decision` still accepts the run whose actual plan/results use `[130]`. A small plan-policy consistency assertion and rejection test would close this gap before final use.

### 2. Acceptance gates are trusted assertions, not independently recomputed (line 110–111)

Any nonempty all-true dictionary is accepted. A temporary probe replaced the fixture gates with `{"arbitrary_unverified_label": true}` and `check_decision` passed. Therefore the tool verifies linked evidence integrity and explicit acceptance, but it does not itself verify declared improvement/regression thresholds or require specific gate names. This may be intentional given the explicit-decision design; if retained, compute the real acceptance gates separately, preserve their inputs/results, and describe this boundary accurately.

### 3. Smaller provenance limitations

- SDK completeness only requires four paths, excluding core transition file `engine/pipeline.py` (line 45). All SDK inputs actually present are hash-checked correctly. Current loop1 and loop2 manifests each contain 27 SDK files including `engine/pipeline.py`, so no missing core SDK hash was observed in the current real data. The six tests' minimal fixture nevertheless demonstrates that an incomplete four-file SDK provenance set is accepted.
- Across different evidence arenas, candidate/baseline headers are compared, but opponent header hashes are not. Comparing opponent main-source hashes alone does not ensure unchanged parsing/helper behavior. This does not create a discrepancy when both stages use the same frozen arena.
- `--compiler` defaults to `g++` and is recorded but not required to be GCC12. The hardcoded official-compiler string is a target specification, not proof of the compiler used. Explicitly supply the intended GCC12 compiler for the final run or report the actual host-compiler limitation.

## Confirmed packaging/runtime chain

The code does perform the material exact-artifact checks:

1. Checks frozen-file and bot-source hashes, and compares all declared installed SDK inputs with their frozen copies.
2. Checks complete, unique job identities; no errors/forfeits; result/summary digests; recomputed summary; matched baseline games; distinct selection/final maps and CPU maps; stage chronology.
3. Copies the four frozen submission files, builds via the official SDK packer, canonicalizes exactly those members, checks ZIP size/expanded size/CRC/content hashes, and requires clean SDK ZIP inspection.
4. Extracts the actual ZIP, checks member hashes again and compiles its extracted `main.cpp` and headers. The runtime candidate is not an earlier unrelated binary.
5. Runs SDK runtime/output smoke plus four paired CPU matches through the checked bot implementation with 384 MiB address-space restriction, 300 ms ordinary turns, 3,000 ms first turn, and 180-second process/game bounds. Errors, forfeits and output warnings reject packaging.
6. Publishes the output ZIP only after successful checks, verifies its final hash, and removes a partially published ZIP on later failure. Validation failure and temporary cleanup status are recorded.

The four CPU games are runtime/protocol checks, not an additional win-rate promotion gate. This distinction is appropriate if the explicit acceptance decision is independently justified.

## Independent tests run

```
python -m unittest discover -s tests -p 'test_package_deadline_candidate.py' -v
```

Result: 6 tests passed in 0.040 seconds.

Additional temporary fixture probes:

```
PROBE arbitrary_gate_label=accepted
PROBE policy_plan_map_mismatch=accepted
```

The probes used `DeadlinePackagingTests.setUp()` to create isolated `/tmp` fixtures, modified only those fixtures, called `check_decision`, and cleaned the fixtures. No real arena, decision, candidate or ZIP was changed.

No blocker was found in exact-ZIP compilation or the shared runtime validation sequence. The policy/plan consistency omission is the most direct small correction; the gate-computation boundary must remain explicit in the final acceptance record.

Coordinator clarification after review: the performance-gate dictionary intentionally records the coordinator's separately calculated, predefined acceptance decision. The packager is not intended to recalculate performance gates and will not be described as doing so. Policy/plan/source-commit/RNG/job-count consistency is being tightened separately; a GCC12 compiler wrapper is being prepared. This reviewer will recheck the corrected consistency logic without changing shared source.

## Follow-up independent verification after correction

The implementation worker added policy map/job-count/source-commit/RNG consistency checks and made `engine/pipeline.py` required. I reran the updated seven-test suite independently: all seven tests passed in 0.070 seconds. I then recreated isolated fixtures and separately changed each final-policy field. All four were rejected with the expected error:

```
REJECTED map_seeds Policy maps differ from run plan
REJECTED scheduled_jobs Policy scheduled job count differs from run plan
REJECTED source_commit Policy source commit differs from frozen manifest
REJECTED policy_rng_seed Policy RNG seed differs from frozen manifest
```

A separate fixture with the pipeline hash removed was rejected as missing frozen SDK provenance. The policy/plan mismatch finding and missing-pipeline minimum finding are therefore corrected. The acceptance gate remains intentionally supplied by the coordinator. No shared source was edited by this reviewer, and no full package/runtime operation was rerun here.
