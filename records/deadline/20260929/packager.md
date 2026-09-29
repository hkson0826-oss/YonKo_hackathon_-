# Deadline candidate packager

Implemented `/tmp/yk-deadline-20260929/experiments/package_deadline_candidate.py` and `tests/test_package_deadline_candidate.py`. No Git actions, original-source changes, packaging runs, or old gate modifications were performed.

CLI:

```bash
python3 -B experiments/package_deadline_candidate.py \
  --arena /tmp/FINAL_FROZEN_ARENA \
  --candidate CANDIDATE_ID \
  --decision-json /tmp/FINAL_DECISION.json \
  --output-zip /tmp/NEW_submission.zip \
  --records /tmp/NEW_package_records \
  --cpu-seed-start 15000
```

Optional `--compiler /path/to/gcc12-wrapper`; default `g++`. Existing outputs are refused. Output paths must not overlap any evidence arena. Records are retained on failure; a ZIP is published only after all checks succeed. Existing official submission ZIPs are untouched.

Decision JSON schema:

```json
{
  "schema_version": 1,
  "approved": true,
  "candidate": "CANDIDATE_ID",
  "baseline": "v4",
  "source_sha256": "MANIFEST_BOTS_CANDIDATE_SOURCE_SHA256",
  "baseline_source_sha256": "MANIFEST_BOTS_BASELINE_SOURCE_SHA256",
  "rationale": "Concrete selection and independent final acceptance rationale, including current-live-baseline limitations.",
  "gates": {
    "predeclared_final_acceptance_passed": true,
    "opponent_regressions_reviewed": true
  },
  "selection": {
    "arena": "/tmp/SELECTION_FROZEN_ARENA",
    "run_id": "selection",
    "summary_sha256": "SHA256_OF_runs/selection/summary.json",
    "results_sha256": "SHA256_OF_runs/selection/results.jsonl"
  },
  "final": {
    "arena": "/tmp/FINAL_FROZEN_ARENA",
    "run_id": "final",
    "summary_sha256": "SHA256_OF_runs/final/summary.json",
    "results_sha256": "SHA256_OF_runs/final/results.jsonl"
  }
}
```

`gates` must contain the actual declared acceptance decisions, all strict booleans true. This script validates the decision/evidence link and evaluation health; it does not invent a performance threshold or choose a winner. An inconclusive/failed final should not receive `approved:true`. Original `package_frozen_candidate.check_gates` is neither called nor altered, and this new experiment is not represented as having passed the old v3/s3 experiment.

Required evidence details:

- Selection policy `stage` must be `selection`, final policy `stage` must be `final`, each with matching `baseline` and frozen source map.
- Both plans include candidate and baseline; all declared jobs complete exactly once; every candidate result has a matched baseline result.
- No errors or forfeits. Saved `jobs.json` equals regenerated jobs, results hashes equal decision links, and every statistic in `summary.json` equals a fresh calculation from original rows. Completed session record required.
- Selection completes before final starts; map sets do not overlap. Final maps cannot overlap smoke/development/selection policies in its arena. CPU seeds15000/15001 must be separate from selection/final maps.
- The **opponent pool and its source hashes must match** between selection and final; choose that pool before selection. Candidate/baseline source and header bytes match across selection, final, and packaging arena. SDK engine/runner/mapgen/config inputs match all snapshots and the installed SDK.
- Every frozen file hash and every original frozen input hash is checked, including snapshot and binary files. Do not delete binaries or move arenas before packaging.
- Input `arena` may be the final arena or another arena containing precisely the same candidate/baseline/header/SDK sources.

The clean package contains exactly `generated.hpp`, `main.cpp`, `protocol.hpp`, `submission.json`; metadata comes from candidate snapshot, or the already-frozen tuned C++ metadata if the generator did not store a candidate-local file. SDK builds/inspects/extracts the ZIP; deterministic ZIP bytes are compared against source; the extracted source is recompiled. Shared `validate_runtime` runs SDK smoke plus four CPU matches(two fresh maps,both sides), each bot under384MiB address-space/300ms turn/3000ms first turn/180s process wall limit, checking protocol and stdout/stderr limits. This verifies execution and format; those four games are not promotion samples.

Records retain exact packaged source, decision, manifest, selection/final plans, summaries, raw result rows, jobs, policies and manifests, ZIP/member hashes, SDK/compiler hashes, compile logs, smoke, CPU replays and runtime statistics. Host GCC/CPU isolation is recorded and not claimed to equal the official container. Use GCC12 wrapper or the existing temporary-toolchain verifier to establish official compiler compatibility before upload.

Validation performed: AST parse;6 new evidence/guard tests;8 existing frozen-packager tests. All14 passed. Tests reject source tampering, failed gates, incomplete results even with refreshed hashes, forged summaries even with refreshed hashes, stage relabeling, CPU-map reuse and output paths inside evidence. Actual ZIP packaging is deferred to root once a candidate is accepted.

## Temporary GCC12 wrapper

```bash
python3 -B experiments/package_deadline_gcc12.py \
  --arena /tmp/FINAL_FROZEN_ARENA \
  --candidate CANDIDATE_ID \
  --decision-json /tmp/FINAL_DECISION.json \
  --output-zip /tmp/NEW_submission.zip \
  --records /tmp/NEW_package_records \
  --compiler-record /tmp/NEW_gcc12_report.json \
  --cpu-seed-start 15000 \
  --toolchain-budget-seconds 300
```

The independent wrapper reuses the existing `verify_gcc12_tmp.gcc12_toolchain` without changing its trusted URL/package-hash rules. It verifies the acceptance decision before downloading, then runs the entire exact-ZIP compile/smoke/four-match validation while the temporary Debian compiler, loader and libraries still exist. Only after packaging completes does the context remove the toolchain. The separate compiler report retains official Debian URLs, package versions and hashes, compiler provenance, package result, cleanup, environment restoration and signal restoration. There is no network activity during unit tests. The300-second budget applies to toolchain setup; per-compiler/per-game time limits remain separate.

Subsequent review fixed policy metadata checking: `map_seeds`, `scheduled_jobs`, `source_commit`, and `policy_rng_seed` must match the actual plan/manifest. Frozen SDK provenance now also requires `engine/pipeline.py`. Validation after these changes: wrapper3 tests + deadline packager7 tests + original packager8 tests =18 passing tests. Original campaign gates remain unchanged.
