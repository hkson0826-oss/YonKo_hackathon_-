"""Read-only paired replay audit for the frozen s3 confirmation candidate."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import audit_warrior_reserve_development as common

CANONICAL = "records/league/loop3-s3-confirmation/runs/holdout"
CANDIDATE = "s3_v2_screen_paired_guard"
OPPONENT = "s3_selective_contact"


def economy_window(history, start, end):
    return {t: common.economy(history[start-1:end], t, end-start+1) for t in "YK"}


def analyze(arena):
    rows=[json.loads(line) for line in (arena/"results.jsonl").read_text().splitlines()]
    assert len(rows)==4608 and len({r["job_id"] for r in rows})==len(rows)
    assert all(r["status"]=="complete" and not r["forfeit"] for r in rows)
    relevant=[r for r in rows if r["team"]=="Y" and r["opponent"]==OPPONENT]
    old={common.key(r):r for r in relevant if r["candidate"]=="v3"}
    pairs=[(r,old[common.key(r)]) for r in relevant if r["candidate"]==CANDIDATE]
    assert len(pairs)==len(old)==128
    cases=[]
    common.CANONICAL=CANONICAL
    counts={}
    for kind in ("regression","gain"):
        pool=[(r,b) for r,b in pairs if (b["win"] and not r["win"] and not r["draw"] if kind=="regression" else r["win"] and not b["win"] and not b["draw"])]
        pool.sort(key=lambda pair:common.key(pair[0]))
        r,b=pool[0];counts[kind]=len(pool)
        choice=dict(kind=kind,candidate=r,baseline=b,delta_margin=r["score_margin"]-b["score_margin"],eligible_pairs=len(pool))
        # Reuse only generic replay, legal-observation, phase accounting and paired-state helpers.
        case=common.analyze_pair(arena,choice)
        assert all(e["candidate"]["stayed_at_origin"]["W"]==e["baseline"]["stayed_at_origin"]["W"] for e in case["changed_origins"])
        assert not case.pop("hypothetical_adjacent_enemy_F_attack")
        raw={role:common.replay_case(arena/choice[role]["replay"],choice[role]) for role in ("candidate","baseline")}
        first=case["first_physical_difference_turn"]
        end=min(len(raw[role][2]) for role in raw)
        case["economic_windows"]=[dict(start_turn=a,end_turn=z,values={role:economy_window(raw[role][2],a,z) for role in raw})
                                  for a,z in [(1,first-1),(first,min(first+39,end)),(max(first,end-39),end)]]
        before=raw["candidate"][1][first-1]
        tracked={x["building"]["id"] for x in case["changed_origins"] if x["building"]}
        for entry in case["changed_origins"]:
            x,y=entry["position"]
            tracked|={q.id for q in before.buildings.values() if abs(q.x-x)+abs(q.y-y)<=2}
        case["nearby_ownership"]={}
        case["first_6turns"]={}
        for role,(replay,states,history) in raw.items():
            case["nearby_ownership"][role]=[]
            for bid in sorted(tracked):
                info=before.buildings[bid];runs=[]
                for turn,state in enumerate(states):
                    owner=state.buildings[bid].owner
                    if not runs or runs[-1]["owner"]!=owner:runs.append(dict(start_turn=turn,end_turn=turn,owner=owner))
                    else:runs[-1]["end_turn"]=turn
                case["nearby_ownership"][role].append(dict(id=bid,type=info.btype,position=list(info.pos),runs=runs))
            case["first_6turns"][role]=[dict(turn=i,score=common.scores(states[i]),units={t:common.totals(states[i],t) for t in "YK"},
                                             production=history[i-1]["Y"]["production"],deaths=history[i-1]["Y"]["deaths"],
                                             flags=[line for line in replay["turns"][i-1]["commands"]["Y"] if line.startswith("MOVE ") and line.split()[3]=="F"])
                                       for i in range(first,min(first+6,len(states)))]
        # Each pair differs in exactly one F command. Replacing the whole own action is
        # therefore a one-command, legal, fixed-opponent comparison already checked above.
        for role in raw:
            case["first_turn_production"]=case.get("first_turn_production",{})
            case["first_turn_production"][role]=raw[role][2][first-1]["Y"]["production"]
        cases.append(case)
    root=arena.parent.parent
    manifest=json.loads((root/"manifest.json").read_text())
    return dict(schema=1,experiment_source_commit=manifest["source_commit"],results_path=f"{CANONICAL}/results.jsonl",
                results_sha256=common.sha(arena/"results.jsonl"),results_rows=len(rows),
                source_sha256={name:common.sha(root/"snapshot/candidates"/name/"main.cpp") for name in (CANDIDATE,"v3",OPPONENT)},
                scripts_sha256={str(Path(__file__).relative_to(common.ROOT)):common.sha(Path(__file__)),
                                str(Path(common.__file__).relative_to(common.ROOT)):common.sha(Path(common.__file__))},
                selection_rule="Fixed candidate/opponent/Y; one strict win-to-loss pair and one strict loss-to-win pair, each with smallest map_seed, then opponent/team. Chosen before inspecting actions.",
                scope="Locked-candidate remaining-weakness audit for future research; no new selection, promotion condition, code change or match.",
                paired_summary=dict(maps=128,candidate_wins=sum(r["win"] for r,b in pairs),baseline_wins=sum(b["win"] for r,b in pairs),
                                    win_to_loss=counts["regression"],loss_to_win=counts["gain"]),cases=cases)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arena",type=Path,default=common.ROOT/CANONICAL)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    d=analyze(args.arena)
    args.output.write_text(json.dumps(d,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps(dict(summary=d["paired_summary"],verified_frames=sum(p["verified_frames"] for c in d["cases"] for p in c["provenance"].values()))))


if __name__=="__main__":main()
