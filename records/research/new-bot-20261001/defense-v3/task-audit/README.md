# HALL defense diagnostic, 2026-10-01

Frozen v1 SHA256: `657693b842b738ce92f0e3b99746e3d6d10a44fe8ab5f52b6433b28bc8a950b3`.
Replay: common seed19013, K versus j_balanced_portfolio, job `ca61304a881abc2d17a4d2c8`.
`audit.json` contains actual defenseTasks and reserveDefenders output; `summary.json` records confirmed findings and limits. Both wrappers reproduce all 123 original K command blocks exactly.

TURN14 input enemy F is (11,7). Its position after executing TURN14 is (11,8). HALL (12,9) ETA3 receives rank12.6; ENG (11,11) ETA4 receives15.6. Single-target selection drops HALL in TURN14–16. In TURN15 the remaining W10 at (10,11) are assigned wholesale to ENG after goalSupply reset erases the previously reserved W1. Keeping W1 alone still leaves ENG9.75 versus next goal9.24444, so residual-demand capping is separately necessary.

Detailed production reset and W goal choices are in sibling directory `yk-mission-defense-detail-20261001/audit.json`. Its instrumented-v1.cpp adds only stderr JSON. No candidate/frozen-v1 source was changed to collect these traces.

Reproduce from this directory after adjusting the SDK/replay paths at the top of analyze.py if the archive moved:

```sh
g++ -O2 -std=c++20 trace.cpp -o trace
python3 -B analyze.py
```

The detailed sibling uses the same commands. Counterfactual outcomes are separately owned by prior_research_new_bot; this diagnostic does not claim a full-match win from a local change.
