# Selection semantic action audit — 2026-09-29

Completed 240 replays / 31,726 turns. All candidate and opponent outputs were checked; syntax rejection, raw/parsed mismatch, invalid production/movement/TELE and requested-unit clipping were all **zero**. This is separate from the runtime error/forfeit count.

Results SHA256: `2c026fa7f7c891a104dd5f1aaaf57eeb277a6021e961ce80a41fadf556006862`.

| Candidate | Decisions | Commands | Findings / clipping |
|---|---:|---:|---:|
| endgame2 | 8,195 | 312,382 | 0 / 0 |
| guard2 | 7,936 | 314,155 | 0 / 0 |
| guard3 | 7,522 | 308,102 | 0 / 0 |
| v4 | 8,073 | 297,229 | 0 / 0 |

The recorded pre-turn states were used to account for production and then shared movement stock. Same-turn arrivals cannot be reused for departures. Official raw parsing was compared with the parsed `applied` replay list, then semantic legality was checked separately because `applied` does not describe post-validation effects. Priority list normalization was not counted as an invalid command. This does not independently replay every combat/capture transition.

Auditor SHA256: `dd71de1e97f87755fc2b62025a747bdbf92b9307164d75dd6d7460e315b5ecd9`.

Command:

```
python experiments/audit_deadline_actions.py --run-dir /tmp/yk-selection-20260929/runs/selection --output /tmp/yk-selection-action-audit.json
```

Full counts, source hashes and SDK hashes: `/tmp/yk-selection-action-audit.json`. Original source and evidence were read only. The same auditor previously detected six intentionally injected syntax/site/budget/stock/TELE/blocked-move errors in an isolated self-test.
