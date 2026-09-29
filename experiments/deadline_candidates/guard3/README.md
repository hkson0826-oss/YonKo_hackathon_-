# guard3: preserve all seed F escorts

Experimental one-condition revision of frozen guard2. Parent source SHA256: `e73cf900936c62f616aea26c00e68ea53f9e94a2df7c307ca3f77f6d1b68efaa`.

Guard2 rejects a defensive reservation when the seed's F destination loses W and becomes immediately unsafe. It still splits escorts at destinations with zero immediate danger. On development map 12015, Y versus s3_selective_contact, applying guard2 to the actual v4 turn-16 command diverts the W at (1,7) upward while the F moves right. The immediate destination has no nearby enemy W, so guard2 allows this exact known divergence.

Guard3 makes one source change: reject a reservation whenever any seed F destination loses W, regardless of immediate danger. All other target selection, deadlines, production relocation, shared-stock checks, TELE handling and search budgets remain unchanged. This protects the seed's projected W count at every F destination, including destinations that are currently safe; it does not guarantee long-term survival or a winning attack.

`check.cpp` copies the existing guard2 synthetic checks. `check_replay.cpp` freezes the actual pre-turn-16 state and v4 command from the development replay, calls only `deadline_guard`, and asserts the W escort still travels from (1,7) to (2,7). This isolates the repair from wall-clock search differences. Preserving this action is not proof that the earlier split caused the full-game loss.

Replay fixture source: `/tmp/yk-loop1-20260929/runs/development1/replays/5bf6e9460652d73d8498fd99.json.gz`, map 12015, Y versus s3_selective_contact. This case guided the change and is development evidence, not an independent final-test case.

Compile and run from this folder:

```
g++ -std=c++20 -O2 main.cpp -o bot
g++ -std=c++20 -O2 check.cpp -o check
g++ -std=c++20 -O2 check_replay.cpp -o check_replay
./check
./check_replay
```

Stricter escort preservation may omit useful defense missions. No league improvement is claimed without matched testing. Do not track `bot`, `check` or `check_replay` binaries.
