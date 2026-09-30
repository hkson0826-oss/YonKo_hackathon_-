"""Predeclared screening, diverse selection, holdout and cross-play campaign."""
import argparse
import itertools
import json
from pathlib import Path
import random
import time

import local_league as league


def load_rows(folder):
    return [json.loads(line) for line in (folder / "results.jsonl").read_text().splitlines()]


def point(row):
    return float(row["win"]) + .5 * row["draw"]


def ranking(summary, candidates):
    def key(name):
        s = summary["by_candidate"][name]
        primary = s["Y"]["point_rate"]
        worst = min(v["point_rate"] for v in s["opponents"].values())
        return (-(primary if primary is not None else -1), -worst,
                -s["overall_point_rate"] if "overall_point_rate" in s else -s["point_rate"],
                -s["mean_score_margin"], name)
    eligible = [name for name in candidates if name in summary["by_candidate"]
                and summary["by_candidate"][name]["errors"] == 0
                and summary["by_candidate"][name]["forfeits"] == 0]
    return sorted(eligible, key=key)


def select_diverse(ordered, bots, count=8):
    chosen, families = [], set()
    # Six performance slots, with no more than two variants of one family.
    for name in ordered:
        if name == "v2":
            continue
        family = bots[name]["family"]
        if sum(bots[n]["family"] == family for n in chosen) >= 2:
            continue
        chosen.append(name)
        families.add(family)
        if len(chosen) == min(6, count):
            break
    for require_new_family in (True, False):
        for name in ordered:
            if len(chosen) >= count:
                break
            if name == "v2" or name in chosen:
                continue
            family = bots[name]["family"]
            if require_new_family and family in families:
                continue
            chosen.append(name)
            families.add(family)
    return ["v2", *chosen]


def paired_interval(rows, candidate, team="Y"):
    indexed = {(r["candidate"],r["map_seed"],r["team"],r["opponent"]):r for r in rows if r["status"]=="complete"}
    per_map = {}
    for (name,seed,side,opponent), row in indexed.items():
        key = ("v2",seed,side,opponent)
        if name == candidate and side == team and key in indexed:
            per_map.setdefault(seed, []).append(point(row)-point(indexed[key]))
    values = [sum(v)/len(v) for _,v in sorted(per_map.items())]
    if not values:
        return None
    rng = random.Random(927605)
    samples = sorted(sum(rng.choices(values,k=len(values)))/len(values) for _ in range(5000))
    return {"team":team,"maps":len(values),"point_rate_difference":sum(values)/len(values),
            "map_cluster_bootstrap_95pct":[samples[125],samples[4874]],
            "resamples":5000,"seed":927605,"per_map":per_map,
            "limitation":"Internal fixed opponent pool; map-cluster sampling uncertainty does not describe unknown real opponents."}


def crossplay_table(rows):
    pairs, totals = {}, {}
    for row in rows:
        if row["status"] != "complete":
            continue
        for name, opponent, side, earned in (
            (row["candidate"],row["opponent"],row["team"],point(row)),
            (row["opponent"],row["candidate"],"K" if row["team"]=="Y" else "Y",1-point(row))):
            for table, key in ((totals,name),(pairs,name+" vs "+opponent)):
                entry=table.setdefault(key,{"games":0,"points":0,"wins":0,"draws":0,"losses":0,"Y_games":0,"Y_points":0})
                entry["games"]+=1;entry["points"]+=earned
                entry["wins"]+=earned==1;entry["draws"]+=earned==.5;entry["losses"]+=earned==0
                entry["Y_games"]+=side=="Y";entry["Y_points"]+=earned if side=="Y" else 0
    return {"unique_matches":sum(r["status"]=="complete" for r in rows),"totals":totals,"directed_pairs":pairs}


def campaign(arena, workers, resume=False):
    started = time.perf_counter()
    if not resume:
        league.prepare(arena)
    manifest = json.loads((arena / "manifest.json").read_text())
    bots = manifest["bots"]
    candidates = [name for name in bots if name not in {"v1","teammate"}]
    plan_dir = arena / "plans"
    plan_dir.mkdir(exist_ok=resume)
    policy = {"candidate_count":len(candidates),"workers":workers,"primary_metric":"Y point rate",
              "ranking_ties":["worst opponent both-side point rate","both-side point rate","mean score margin","id"],
              "smoke_seeds":[5900],"screen_seeds":list(range(6000,6003)),
              "selection_seeds":list(range(6100,6108)),"holdout_seeds":list(range(6200,6224)),
              "crossplay_seeds":[6300,6301],"replays":"gzip: all losses/draws and first-map wins",
              "selection":"6 ranked slots with max 2 per family, then 2 diversity/rank slots; baseline always retained",
              "finalists":"Best two selection candidates excluding baseline, locked before holdout",
              "promotion":"First selection finalist only: Y paired gain >=0.03, map-cluster bootstrap lower bound >0, no baseline/candidate forfeit/error, no opponent Y regression worse than 0.10; otherwise keep v2",
              "source_edit_policy":"No candidate changes within this campaign",
              "crossplay":"Top 8 selection bots incl baseline, all unordered pairs, both sides on 2 maps"}
    league.write(arena / "campaign-policy.json", policy)
    reports = {}

    def stage(name, plan):
        existing=arena / "runs" / name
        if resume and existing.exists() and json.loads((existing/"plan.json").read_text())!=plan:
            raise ValueError("Resumed campaign changed a stage plan")
        league.write(plan_dir / (name+".json"), plan)
        print(json.dumps({"event":"stage_start","stage":name,"jobs":len(league.make_jobs(plan,bots))}),flush=True)
        league.run(arena,plan_dir/(name+".json"),name,workers,resume and existing.exists())
        report = json.loads((arena / "runs" / name / "summary.json").read_text())
        reports[name] = report
        league.write(arena / "progress.json", {"completed":list(reports),"elapsed_seconds":time.perf_counter()-started})
        print(json.dumps({"event":"stage_complete","stage":name,"overall":report["overall"]}),flush=True)
        return report

    smoke = stage("smoke",{"candidates":[*candidates,"v1","teammate"],"opponents":["v2"],"map_seeds":[5900],"replays":"losses"})
    broken = [name for name,record in smoke["by_candidate"].items() if record["errors"] or record["forfeits"]]
    if "v2" in broken:
        raise RuntimeError("Baseline failed smoke under this load; reduce workers before comparing strategy")
    candidates = [name for name in candidates if name not in broken]
    league.write(arena / "smoke-exclusions.json", {"excluded":broken,"reason":"Infrastructure error or match forfeit; inspect original result cause before attributing to strategy"})
    opponents = ["v2","teammate","c_economy_direct","c_territory_direct"]
    if any(name in broken for name in [*opponents,"c_spearhead_direct"]):
        raise RuntimeError("Required opponent failed smoke")
    screen = stage("screen",{"candidates":candidates,"opponents":opponents,"map_seeds":list(range(6000,6003)),"replays":"losses"})
    ordered = ranking(screen,candidates)
    chosen = select_diverse(ordered,bots)
    league.write(arena / "screen-selection.json",{"ranking":ordered,"selected":chosen})
    opponents += ["c_spearhead_direct"]
    selected = stage("selection",{"candidates":chosen,"opponents":opponents,"map_seeds":list(range(6100,6108)),"replays":"losses"})
    selection_rank = ranking(selected,chosen)
    finalists = [name for name in selection_rank if name != "v2"][:2]
    league.write(arena / "locked-finalists.json",{"ranking":selection_rank,"finalists":finalists,"primary_candidate":finalists[0] if finalists else None})
    holdout = stage("holdout",{"candidates":["v2",*finalists],"opponents":opponents,"map_seeds":list(range(6200,6224)),"replays":"losses"})
    cross = ["v2", *[n for n in selection_rank if n != "v2"][:7]]
    stage("crossplay",{"pairs":list(itertools.combinations(cross,2)),"map_seeds":[6300,6301],"replays":"losses"})
    league.write(arena/"crossplay-table.json",crossplay_table(load_rows(arena/"runs/crossplay")))
    rows = load_rows(arena / "runs/holdout")
    comparisons = {name:{team:paired_interval(rows,name,team) for team in "YK"} for name in finalists}
    opponent_comparisons = {name:{op:paired_interval([r for r in rows if r['opponent']==op],name) for op in opponents} for name in finalists}
    recommended = "v2"
    if finalists:
        name = finalists[0]
        stats = holdout["by_candidate"][name]
        cmp = comparisons[name]["Y"]
        baseline = holdout["by_candidate"]["v2"]
        no_regression = all(c is not None and c["point_rate_difference"] >= -.10 for c in opponent_comparisons[name].values())
        if cmp and cmp["point_rate_difference"] >= .03 and cmp["map_cluster_bootstrap_95pct"][0] > 0 and not stats["forfeits"] and not stats["errors"] and not baseline["forfeits"] and not baseline["errors"] and no_regression:
            recommended = name
    result = {"status":"complete","elapsed_seconds":time.perf_counter()-started,
              "candidate_count":len(candidates),"stage_match_counts":{k:v["overall"]["matches"] for k,v in reports.items()},
              "total_matches":sum(v["overall"]["matches"] for v in reports.values()),
              "screen_ranking":ordered,"selection_ranking":selection_rank,"finalists":finalists,
              "holdout_comparisons":comparisons,"opponent_Y_comparisons":opponent_comparisons,"recommended":recommended,
              "recommendation_scope":"Internal league evidence only; package and independent CPU validation required before changing submission."}
    league.write(arena / "campaign-result.json",result)
    print(json.dumps({"event":"campaign_complete",**result},ensure_ascii=False),flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arena",type=Path,required=True)
    parser.add_argument("--workers",type=int,default=8)
    parser.add_argument("--resume",action="store_true",help="Resume the same frozen arena at its original path")
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("workers must be positive")
    campaign(args.arena.resolve(),args.workers,args.resume)


if __name__ == "__main__":
    main()
