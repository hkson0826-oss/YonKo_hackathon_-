"""Run identical complete games under different CPU executor configurations."""
import argparse
import json
from pathlib import Path
import random
import statistics
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--workers", default="1,2,4,8")
    parser.add_argument("--executors", default="process,thread")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--order-seed", type=int, default=927)
    args = parser.parse_args()
    workers = [int(value) for value in args.workers.split(",")]
    executors = args.executors.split(",")
    if args.repeats < 1 or any(n < 1 for n in workers) or not set(executors) <= {"process", "thread"}:
        parser.error("Invalid workers, executors or repeats")
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    schedule = [(executor, n, repeat) for executor in executors for n in workers
                for repeat in range(args.repeats)]
    random.Random(args.order_seed).shuffle(schedule)
    report = {"status": "running", "command": [sys.executable, *sys.argv],
              "scope": "Repeated identical jobs measure throughput, not additional independent strength evidence.",
              "schedule": schedule, "runs": []}
    reference_traces = None
    for executor, n, repeat in schedule:
        name = f"{executor}-{n}-repeat-{repeat}"
        command = [sys.executable, str(ROOT / "experiments/cpu_sweep.py"),
                   "--config", str(args.config.resolve()), "--output-dir", str(output / name),
                   "--workers", str(n), "--executor", executor, "--replays", "none"]
        print(f"Starting {name}", flush=True)
        with (output / f"{name}.log").open("w") as log:
            done = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, cwd=ROOT)
        if done.returncode:
            report.update(status="failed", failed_run=name, returncode=done.returncode)
            (output / "comparison.json").write_text(json.dumps(report, indent=2) + "\n")
            raise SystemExit(done.returncode)
        session = json.loads(next((output / name).glob("session-*.json")).read_text())
        summary = json.loads((output / name / "summary.json").read_text())
        results = [json.loads(line) for line in (output / name / "results.jsonl").read_text().splitlines()]
        traces = {row["job_id"]: row.get("logical_trace_sha256") for row in results}
        if reference_traces is None:
            reference_traces = traces
        changed = sorted(key for key in set(reference_traces) | set(traces)
                         if reference_traces.get(key) != traces.get(key))
        row = {"run": name, "executor": executor, "workers": n, "repeat": repeat,
               "wall_seconds": session["wall_seconds"], "total_wall_seconds": session["total_wall_seconds"],
               "games_per_second": summary["overall"]["matches"] / session["wall_seconds"],
               "changed_trace_jobs_vs_first": changed, "summary": summary["overall"],
               "by_candidate": summary["by_candidate"]}
        report["runs"].append(row)
        (output / "comparison.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(row), flush=True)
    report["groups"] = [
        {"executor": executor, "workers": n,
         "median_games_per_second": statistics.median(
             row["games_per_second"] for row in report["runs"] if (row["executor"], row["workers"]) == (executor, n))}
        for executor, n in sorted({(row["executor"], row["workers"]) for row in report["runs"]})]
    report["status"] = "complete"
    report["all_traces_preserved"] = all(not row["changed_trace_jobs_vs_first"] for row in report["runs"])
    (output / "comparison.json").write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
