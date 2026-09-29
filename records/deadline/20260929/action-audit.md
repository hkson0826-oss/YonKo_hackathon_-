# Development2 semantic action audit — 2026-09-29

**No silently ignored semantic command, production/movement clipping, or raw-command parsing mismatch was found in the 320 completed development2 replays.** This includes the v4 baseline, all three tested candidates, and all opponent outputs. Original code, replays and result records were read only.

## Why a separate audit was necessary

`runner/replay.py::turn_entry` names the parsed command list `applied`; it is not a list of commands after state-dependent engine acceptance. `runner/match.py` explicitly permits individual malformed commands to be ignored without a match error. Comparing raw output with `applied` can detect parsing differences, but not insufficient stock, resource clipping, wrong TELE ownership or exceeding a TELE limit.

The official SDK `CheckedBot` additionally checks syntax, coordinates, blocked movement paths and explicit hospital spawn sites. Its current implementation does **not** check full shared stock/resource budgets or TELE state/use limits. Therefore a clean CheckedBot result alone should not be described as proving every semantic command was fully applied.

## Scope and method

Input: `/tmp/yk-loop2-20260929/runs/development2/results.jsonl` and its 320 replay paths.

Results file SHA256: `975dfb182033a07620bd85b4e2162421dc163d6ac1053be9629296fe50ecd54a`.

The read-only script parses original commands with the official parser and compares normalized dataclass contents to replay `applied`; JSON list/tuple normalization and command ordering are preserved rather than counted as invalid. It then uses the actual pre-turn replay state to perform production-budget accounting followed by shared movement-stock accounting, matching `engine/pipeline.py`. Arrivals never fund later departures in the same turn.

Checks cover explicit spawn-site ownership/type, actual ENG production discount/floor, resource clipping, passable MOVE/MOVE2 destinations and intermediate cells, stock clipping, TELE station ownership/count, same-station TELE, per-turn usage, five-unit capacity, and stock availability. Engine-permitted partial production/movement would be reported separately as clipping rather than conflated with a malformed command. No clipping was found either.

Initial state reconstruction uses empty starting units, neutral initial buildings and configured starting resources, as constructed by official `mapgen.to_state`/`new_game`. Later checks use the previous recorded snapshot. This is a semantic-command audit over recorded states; it is not a full independent recomputation of every combat/capture transition.

## Results

320 replays, 43,757 turns, 3,067,722 commands across both sides. Execution took 15.84 seconds locally.

| Candidate side | Decisions | Raw command lines | Syntax/semantic problems | Clipped requests |
|---|---:|---:|---:|---:|
| v4 | 10,883 | 423,172 | 0 | 0 |
| guard2 | 10,798 | 449,959 | 0 | 0 |
| midgame1 | 11,122 | 438,829 | 0 | 0 |
| endgame2 | 10,954 | 430,015 | 0 | 0 |

Opponent outputs from v3, teammate, s3_selective_contact, j_balanced_portfolio and raid1 also had zero findings. Candidate source hashes and official reference-file hashes are recorded in the JSON result.

## Auditor self-check and artifacts

An isolated temporary fixture injected syntax rejection, an invalid production site, an over-budget spawn, an over-stock move, same-station TELE and a blocked/out-of-map move. All six categories were detected. The temporary fixture was removed; no real replay was edited.

- Script: `/tmp/yk-audit-actions.py`
- Detailed result: `/tmp/yk-action-audit.json`
- Injected-error check: `/tmp/yk-action-audit-selftest.json`

These results apply to the frozen development2 candidate versions above. They do not certify guard3, an untested later source, a different official SDK, or the unavailable website v7 source.

The reusable CLI is now tracked at `experiments/audit_deadline_actions.py`. Re-run against a preserved run directory with `python3 -B experiments/audit_deadline_actions.py --run-dir RUN_DIRECTORY --output NEW_AUDIT_JSON`. The CLI reproduced all320 replay counts and findings exactly; this does not change the original audit result.
