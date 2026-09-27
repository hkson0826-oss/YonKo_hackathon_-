"""Additional fixed-opponent nonregression audit of the first locked finalist."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
from pathlib import Path
import resource
import time

import local_league as league
from league_campaign import paired_interval

OPPONENTS = (
    "j_balanced_portfolio", "a_local_unabstracted", "q_threat_window",
    "a_v2_tactical_local", "j_v2_reclaim_relay", "teammate",
)
MODULES = ("repairs", "causal_repairs", "joint_allocator", "adaptive_search")
MAP_SEEDS = tuple(range(7500, 7532))
ADDRESS_SPACE_BYTES = 384 * 1024 * 1024


def make_plan(candidate, map_seeds=MAP_SEEDS):
    if not candidate or candidate in {"v2", "v1", "teammate"}:
        raise ValueError("Candidate must be the first locked non-baseline finalist")
    seeds = list(map_seeds)
    if not seeds or len(set(seeds)) != len(seeds) or any(seed < 0 for seed in seeds):
        raise ValueError("Map seeds must be distinct nonnegative integers")
    return {"candidates": ["v2", candidate], "opponents": list(OPPONENTS),
            "map_seeds": seeds, "replays": "all", "order_seed": 927607}


def population_spec(candidate):
    return {"modules": list(MODULES), "revision": 2, "include_parameters": False,
            "deduplicate": False,
            "include_ids": list(dict.fromkeys(["v2", candidate, *[op for op in OPPONENTS if op != "teammate"]])),
            "include_prefixes": []}


@contextmanager
def submission_address_space():
    """Apply the submission address-space cap after compilation, then restore it."""
    previous = resource.getrlimit(resource.RLIMIT_AS)
    limits = [ADDRESS_SPACE_BYTES, *[value for value in previous if value != resource.RLIM_INFINITY]]
    effective = min(limits)
    resource.setrlimit(resource.RLIMIT_AS, (effective, previous[1]))
    try:
        yield {"resource": "RLIMIT_AS", "requested_soft_bytes": ADDRESS_SPACE_BYTES,
               "effective_soft_bytes": effective, "hard_bytes": previous[1],
               "previous_soft_bytes": previous[0], "inherited_by": "workers and bot processes",
               "scope": "Per-process virtual address space; not total RSS or a replica of the submission container"}
    finally:
        resource.setrlimit(resource.RLIMIT_AS, previous)


def audit_result(rows, candidate, map_seeds=MAP_SEEDS):
    plan = make_plan(candidate, map_seeds)
    bots = dict.fromkeys([*plan["candidates"], *OPPONENTS])
    jobs = league.make_jobs(plan, bots)
    expected = {job["job_id"] for job in jobs}
    identifiers = [row.get("job_id") for row in rows]
    actual = set(identifiers)
    complete = len(identifiers) == len(actual) == len(expected) and actual == expected
    health = {}
    for name in plan["candidates"]:
        selected = [row for row in rows if row["candidate"] == name]
        health[name] = {"rows": len(selected),
                        "errors": sum(row["status"] != "complete" for row in selected),
                        "forfeits": sum(bool(row.get("forfeit", False)) for row in selected)}
    comparisons = {side: paired_interval(rows, candidate, side) for side in "YK"}
    opponents = {op: paired_interval([row for row in rows if row["opponent"] == op], candidate)
                 for op in OPPONENTS}
    primary = comparisons["Y"]
    gates = {
        "complete_schedule_without_duplicates": complete,
        "no_baseline_or_candidate_errors_or_forfeits": all(not value["errors"] and not value["forfeits"] for value in health.values()),
        "no_overall_Y_regression": primary is not None and primary["point_rate_difference"] >= -1e-12,
        "no_opponent_Y_regression_worse_than_12_5pp": all(
            value is not None and value["point_rate_difference"] >= -.125 - 1e-12 for value in opponents.values()),
    }
    return {"status": "complete" if complete and gates["no_baseline_or_candidate_errors_or_forfeits"] else "incomplete_or_failed",
            "candidate": candidate, "baseline": "v2", "planned_matches": len(jobs),
            "observed_rows": len(rows), "missing_job_ids": sorted(expected - actual),
            "unexpected_job_ids": sorted(str(value) for value in actual - expected),
            "duplicate_row_count": len(identifiers) - len(actual), "health": health,
            "comparisons": comparisons, "opponent_Y_comparisons": opponents,
            "gates": gates, "passes_additional_gate": all(gates.values()),
            "interpretation": "Additional fixed cross-family audit only. Passing cannot replace a failed original holdout or select another candidate."}


def campaign(args):
    started = time.perf_counter()
    arena = args.arena.resolve()
    plan = make_plan(args.candidate)
    lock = None
    lock_path = getattr(args, "selection_lock", None)
    lock_json = getattr(args, "selection_lock_json", None)
    if lock_path is not None and lock_json is not None:
        raise ValueError("Provide only one selection lock input")
    if lock_path is not None or lock_json is not None:
        lock = json.loads(lock_path.read_text() if lock_path is not None else lock_json)
        if not isinstance(lock, dict) or lock.get("primary_candidate") != args.candidate:
            raise ValueError("Candidate differs from the first locked selection finalist")
    policy = {
        "declared_utc": league.stamp(), "candidate": args.candidate,
        "candidate_rule": "Only the first locked selection finalist; never reselect using audit or holdout outcomes",
        "selection_lock": lock,
        "selection_lock_verification": ("file verified" if lock_path is not None else "inline JSON verified") if lock else "Caller must verify against the existing locked-finalists.json",
        "opponents": list(OPPONENTS), "map_seeds": list(MAP_SEEDS),
        "planned_matches": 768, "primary_metric": "paired Y point-rate difference",
        "gates": {"candidate_and_baseline_errors": 0, "candidate_and_baseline_forfeits": 0,
                  "minimum_overall_Y_difference": 0.0, "minimum_opponent_Y_difference": -.125},
        "self_play": "Keep candidate-versus-identical-opponent games on both sides and all maps",
        "replays": "all", "population_revision": 2, "workers": args.workers,
        "requested_RLIMIT_AS_soft_bytes": ADDRESS_SPACE_BYTES,
        "address_space_policy": "Apply only after prepare/compilation and before workers/bots; lower preexisting caps remain lower",
        "relationship_to_holdout": "Additional gate; cannot replace the original holdout or authorize another candidate",
        "sampling_limit": "Opponents include new action/search families but remain largely v2-derived; unknown contestants are not represented",
    }
    league.prepare(arena, population_spec(args.candidate))
    manifest = json.loads((arena / "manifest.json").read_text())
    league.make_jobs(plan, manifest["bots"])
    policy["source_sha256"] = {name: manifest["bots"][name]["source_sha256"]
                               for name in dict.fromkeys(["v2", args.candidate, *OPPONENTS])}
    policy["source_commit"] = manifest["source_commit"]
    league.write(arena / "audit-policy.json", policy)
    if lock is not None:
        league.write(arena / "selection-lock.json", lock)
    plan_path = arena / "plans/audit.json"
    plan_path.parent.mkdir()
    league.write(plan_path, plan)
    print(json.dumps({"event": "audit_start", "candidate": args.candidate, "jobs": 768}), flush=True)
    with submission_address_space() as cap:
        league.write(arena / "audit-resource-limit.json", cap)
        try:
            league.run(arena, plan_path, "audit", args.workers, False)
        finally:
            results_path = arena / "runs/audit/results.jsonl"
            rows = [json.loads(line) for line in results_path.read_text().splitlines()] if results_path.exists() else []
            result = audit_result(rows, args.candidate)
            result.update(elapsed_seconds=time.perf_counter() - started, finished_utc=league.stamp(),
                          resource_limit=cap, selection_lock_verification=policy["selection_lock_verification"])
            league.write(arena / "audit-result.json", result)
            completed = sum(row["status"] == "complete" for row in rows)
            compatibility = {
                "phase": "audit", "status": result["status"],
                "candidate_count": 2, "primary_candidate": args.candidate,
                "stage_match_counts": {"audit": completed}, "total_matches": completed,
                "errors": sum(value["errors"] for value in result["health"].values()),
                "forfeits": sum(value["forfeits"] for value in result["health"].values()),
                "elapsed_seconds": result["elapsed_seconds"],
                "recommended": args.candidate if result["passes_additional_gate"] else "v2",
                "recommendation_scope": "Additional cross-family gate only; this is not submission promotion and cannot replace the original holdout.",
            }
            league.write(arena / "campaign-result.json", compatibility)
            print(json.dumps({"event": "audit_complete", **result}, ensure_ascii=False), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arena", type=Path, required=True)
    parser.add_argument("--candidate", required=True, help="First primary_candidate from the existing locked-finalists.json")
    lock_input = parser.add_mutually_exclusive_group()
    lock_input.add_argument("--selection-lock", type=Path, help="Optional copy of the locked-finalists JSON; mismatch is rejected before building")
    lock_input.add_argument("--selection-lock-json", help="Inline locked-finalists JSON; mutually exclusive with --selection-lock")
    parser.add_argument("--workers", type=int, default=16)
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("workers must be positive")
    campaign(args)


if __name__ == "__main__":
    main()
