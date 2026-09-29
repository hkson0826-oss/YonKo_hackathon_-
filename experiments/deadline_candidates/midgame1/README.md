# midgame1: optional multi-origin defense

Experimental candidate; no match-level improvement established by the implementation smoke tests.

The existing v4 S3 mode 5 modifies one origin at a time. A threatened owned building can require holding its F while bringing W from two adjacent origins at once; either partial change alone can still lose ownership. This candidate adds at most three such joint actions after the full original 135 ms search. The total time budget is 170 ms. A timeout preserves the seed or a fully evaluated accepted candidate.

Candidate generation reuses the reservation scheme from `experiments/local_league/causal_repairs.py`, but does not force its repair onto the returned plan. Each repair must improve the existing rollout objective and must not reduce the three-turn value against any of the four existing opponent policies relative to the actual v4 seed. Opponent policies, transition rules, production allocation and all evaluation weights are unchanged. The extra stage is disabled at state turn 157 and later.

The reservation holds one existing F on an owned building, then funds sufficient W from that cell and its neighbors to meet the visible one-step incoming W bound. Existing planned reinforcement is preferred. Same-turn production is available; same-turn arrivals cannot move twice. No extra production or remote teleport is generated.

The hypothesis relates to the observed late territory collapse only through the rule that an F killed on its owned building neutralizes it. No replay-specific causal claim is made for the current website v7 failures because their full turn data was unavailable to this worker.

Validation on 2026-09-29 with GCC16.2.1, `-std=c++20 -O2`:

- Main source and `check.cpp` compile.
- Two partial repairs each lose ownership; the joint F hold plus two-origin W reinforcement retains it.
- Insufficient stock and reusing arrivals are rejected; same-turn hospital production can contribute.
- 18 random states × both teams = 36 full decisions are legal, with nine additional mission candidates checked. Maximum measured decision latency: 129.81 ms.
- Official engine check confirms `joint Y`, `only_flag K`, `only_w N`.

Reproduce from this folder:

```
g++ -std=c++20 -O2 main.cpp -o bot
g++ -std=c++20 -O2 check.cpp -o check
./check
python check_engine.py
```

Remaining limitations: four related opponent models do not cover all adversarial actions; withdrawing neighbor W can expose another site; overly conservative one-step concentration bounds can omit useful candidates; GCC12/protocol/server latency and paired-match performance require coordinator validation. These checks prove legality and a missing joint action, not a guaranteed strategic improvement.

Do not track the local `bot` or `check` binaries.
