"""Audit the fixed reclaim-relay opponent in the completed warrior-reserve audit."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import audit_warrior_reserve_development as audit

CANONICAL = "records/league/loop3-audit/runs/audit"
OPPONENT = "j_v2_reclaim_relay"


def window(history, start, end):
    return {t: audit.economy(history[start-1:end], t, end-start+1) for t in "YK"}


def analyze(arena):
    rows = [json.loads(line) for line in (arena/"results.jsonl").read_text().splitlines()]
    assert len(rows) == 1024 and len({r["job_id"] for r in rows}) == 1024
    assert all(r["status"] == "complete" and not r["forfeit"] for r in rows)
    relevant = [r for r in rows if r["opponent"] == OPPONENT and r["team"] == "Y"]
    old = {audit.key(r):r for r in relevant if r["candidate"] == "v3"}
    pairs = [(r,old[audit.key(r)],r["score_margin"]-old[audit.key(r)]["score_margin"])
             for r in relevant if r["candidate"] == audit.CANDIDATE]
    assert len(pairs) == 32 and len(old) == 32
    regressions = sorted((p for p in pairs if not p[0]["win"] and p[1]["win"]),key=lambda p:(p[2],*audit.key(p[0])))
    gains = sorted((p for p in pairs if p[0]["win"] and not p[1]["win"]),key=lambda p:(-p[2],*audit.key(p[0])))
    improved = sorted((p for p in pairs if p[2] > 0),key=lambda p:(-p[2],*audit.key(p[0])))
    selected = [("regression",p,len(regressions)) for p in regressions[:2]]
    selected += [("margin_improvement",improved[0],len(improved))]
    audit.CANONICAL = CANONICAL
    cases = []
    for kind,(candidate,baseline,delta),eligible in selected:
        choice = dict(kind=kind,candidate=candidate,baseline=baseline,delta_margin=delta,eligible_pairs=eligible)
        case = audit.analyze_pair(arena,choice)
        first = case["first_physical_difference_turn"]
        raw = {role:audit.replay_case(arena/choice[role]["replay"],choice[role]) for role in ("candidate","baseline")}
        if len(case["changed_origins"]) <= 2:
            before=raw["candidate"][1][first-1]
            commands={r:audit.parse_commands(case["commands"][r]["Y"]) for r in raw}
            fixed=audit.parse_commands(case["commands"]["candidate"]["K"])
            changes=[]
            for entry in case["changed_origins"]:
                x,y=entry["position"]
                is_origin=lambda c:isinstance(c,(audit.Move,audit.Move2,audit.Tele)) and (c.x,c.y)==(x,y)
                replacement=[c for c in commands["candidate"] if not is_origin(c)] + [c for c in commands["baseline"] if is_origin(c)]
                spawned,_,_,_=audit.phases(before,{"Y":replacement,"K":fixed})
                for kind in "FWS":
                    moving=sum(c.count for c in replacement if is_origin(c) and c.kind==kind)
                    assert moving<=spawned.get_unit(x,y,"Y",kind)
                after,_=audit.run_turn(before,replacement,fixed)
                changes.append(dict(changed_own_origin=[x,y],scope="Replace only this origin's own moves with baseline moves; other own commands and actual opponent unchanged.",
                                    scores=audit.scores(after),resources=after.resources,own_units=audit.totals(after,"Y"),
                                    equals_baseline_snapshot=audit.snapshot(after)==raw["baseline"][0]["turns"][first-1]["state"],
                                    ownership_change_from_candidate=[dict(id=b.id,type=b.btype,position=list(b.pos),
                                                                         candidate_owner=raw["candidate"][1][first].buildings[b.id].owner,replaced_owner=b.owner)
                                                                    for b in after.buildings.values() if b.owner!=raw["candidate"][1][first].buildings[b.id].owner]))
            case["single_origin_counterfactuals"]=changes
        common = min(len(raw[role][2]) for role in raw)
        windows = [(1,first-1),(first,min(first+39,common)),(max(first,common-39),common)]
        case["economic_windows"] = [dict(start_turn=a,end_turn=b,values={role:window(raw[role][2],a,b) for role in raw}) for a,b in windows if a<=b]
        case["largest_post_divergence_w_losses"] = {}
        for role,(_,states,history) in raw.items():
            ranked = sorted(range(first-1,len(history)),key=lambda i:(-history[i]["Y"]["deaths"]["W"],i))[:3]
            case["largest_post_divergence_w_losses"][role] = []
            for i in ranked:
                frame=raw[role][0]["turns"][i]
                commands={t:audit.parse_commands(frame["commands"][t]) for t in "YK"}
                _,landed,_,_=audit.phases(states[i],commands)
                sites=[]
                for (x,y,t,k),count in landed.units.items():
                    if t != "Y" or k != "W": continue
                    loss=min(count,landed.get_unit(x,y,"K","W"))
                    if not loss: continue
                    building=states[i].building_at(x,y)
                    sites.append(dict(position=[x,y],Y_W=count,K_W=landed.get_unit(x,y,"K","W"),loss_each=loss,
                                      building=None if building is None else dict(id=building.id,type=building.btype,owner_before=building.owner,owner_after=states[i+1].buildings[building.id].owner)))
                sites.sort(key=lambda x:(-x["loss_each"],x["position"]))
                case["largest_post_divergence_w_losses"][role].append(dict(turn=i+1,own_W_loss=history[i]["Y"]["deaths"]["W"],
                       score_before=audit.scores(states[i]),score_after=audit.scores(states[i+1]),largest_combat_sites=sites[:3]))
        cases.append(case)
    snapshot=arena.parent.parent/"snapshot/candidates"
    manifest=json.loads((arena.parent.parent/"manifest.json").read_text())
    return dict(schema=1,scope="Completed audit, two largest loss reversals and largest margin improvement against one fixed opponent; selected diagnosis, no candidate changes or promotion.",
                experiment_source_commit=manifest["source_commit"],
                analysis_base_commit="6e36cb5bfab7ff874fbb48a3c3b82308e41bdcf2",
                results_path=f"{CANONICAL}/results.jsonl",results_sha256=audit.sha(arena/"results.jsonl"),results_rows=1024,
                source_sha256={name:audit.sha(snapshot/name/"main.cpp") for name in (audit.CANDIDATE,"v3",OPPONENT)},
                scripts_sha256={str(Path(__file__).relative_to(audit.ROOT)):audit.sha(Path(__file__)),
                                str(Path(audit.__file__).relative_to(audit.ROOT)):audit.sha(Path(audit.__file__))},
                selection_rule="Y and reclaim-relay only; top two strict win-to-loss pairs by margin decline then map/opponent/team; no strict loss-to-win exists, so largest positive margin change is the improvement comparator.",
                paired_summary=dict(maps=32,candidate_wins=sum(p[0]["win"] for p in pairs),baseline_wins=sum(p[1]["win"] for p in pairs),
                                    win_to_loss=len(regressions),loss_to_win=len(gains),positive_margin_pairs=len(improved)),
                cases=cases)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arena",type=Path,default=audit.ROOT/CANONICAL)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    evidence=analyze(args.arena)
    args.output.write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({"summary":evidence["paired_summary"],"verified_frames":sum(p["verified_frames"] for c in evidence["cases"] for p in c["provenance"].values()),
                      "cases":[dict(kind=c["kind"],map=c["provenance"]["candidate"]["map_seed"],turn=c["first_physical_difference_turn"]) for c in evidence["cases"]]}))


if __name__ == "__main__":
    main()
