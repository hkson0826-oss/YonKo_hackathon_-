# Final semantic action audit — 2026-09-29

Completed 200 replays / 24,919 turns. All guard3, v4 and opponent outputs were checked. Syntax rejection, raw/parsed mismatch, invalid production/movement/TELE and requested-unit clipping were all **zero**. These command-level findings are separate from the runtime error/forfeit count.

Results SHA256: `ca4b04adae3861e47b90d1cd91d2c2d7cf25e3b8ea9fd0e4d6620e4ffd7acef8`.

| Candidate | Decisions | Commands | Findings / clipping |
|---|---:|---:|---:|
| guard3 | 12,057 | 475,875 | 0 / 0 |
| v4 | 12,862 | 465,362 | 0 / 0 |

Recorded pre-turn states were used to account for production followed by shared movement stock. Same-turn arrivals could not fund new departures. Official raw parsing was compared with the normalized parsed `applied` replay list, then semantic validity was checked separately; `applied` itself is not a post-validation movement log. Priority representation normalization was not counted as an invalid command. Combat/capture transitions were not independently recomputed.

Guard3 source SHA256: `61a4f25113d9bf2c387a59ddc770a3143de6311e3fd2e004827a66eb78edfbc9`.
Auditor SHA256: `dd71de1e97f87755fc2b62025a747bdbf92b9307164d75dd6d7460e315b5ecd9`.

Command:

```
python experiments/audit_deadline_actions.py --run-dir /tmp/yk-selection-20260929/runs/final --output /tmp/yk-final-action-audit.json
```

Run completed in 6.25 seconds. Detailed counts, source hashes and SDK hashes: `/tmp/yk-final-action-audit.json`. Original source/evidence were not modified. The same auditor detected six injected error categories in its isolated self-test.

This result covers the frozen final-league sources. The exact GCC12 ZIP build and runtime validation remain separate packaging checks.
