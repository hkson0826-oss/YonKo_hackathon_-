"""Measure the existing thread runner on frozen bot snapshots, one batch at a time."""
import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import platform
import resource
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def source_tree_digest(folder):
    files = sorted(p for p in folder.rglob("*") if p.suffix == ".py")
    return {str(p.relative_to(ROOT)): digest(p) for p in files}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--workers", type=int, nargs="+", default=[1, 2, 4])
    parser.add_argument("--start", type=int, default=4000)
    parser.add_argument("--seeds", type=int, default=2)
    args = parser.parse_args()
    if args.seeds < 1 or any(w < 1 for w in args.workers):
        parser.error("seeds and workers must be positive")
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    profile_file = output / "runtime-profile.json"
    outputs = [profile_file]
    for w in args.workers:
        outputs.extend([output / f"throughput-{w}.json", output / f"throughput-{w}.log",
                        output / f"replays-workers-{w}"])
    if any(p.exists() for p in outputs):
        parser.error("Output already exists; use a new directory")
    opponent_zip = ROOT / "submissions/delineate-v1.zip"
    source = ROOT / "submissions/tuned"
    source_files = sorted(p for p in source.iterdir() if p.suffix in {".cpp", ".hpp"})
    expected = {p.name: digest(p) for p in source_files}
    profile = {
        "started_at_utc": now(), "status": "running",
        "purpose": "CPU runner throughput smoke profile, not independent strategy evaluation",
        "script_sha256": digest(Path(__file__)),
        "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "candidate_source_sha256": expected,
        "opponent_zip_sha256": digest(opponent_zip),
        "benchmark_script_sha256": digest(ROOT / "tests/benchmark.py"),
        "engine_source_sha256": source_tree_digest(ROOT / "yk-development-tools/engine"),
        "runner_source_sha256": source_tree_digest(ROOT / "yk-development-tools/runner"),
        "balance_sha256": digest(ROOT / "yk-development-tools/config/balance.json"),
        "limits_sha256": digest(ROOT / "yk-development-tools/bots/dist/starter/limits.json"),
        "host": {"platform": platform.platform(), "python": sys.version,
                 "cpu_count": os.cpu_count(), "cpu_affinity": sorted(os.sched_getaffinity(0)),
                 "initial_load_average": os.getloadavg(),
                 "compiler": subprocess.check_output(["g++", "--version"], text=True).splitlines()[0]},
        "maps": list(range(args.start, args.start + args.seeds)),
        "teams": ["Y", "K"], "workers_order": args.workers,
        "batches": [],
        "replay_retention": "all loss/draw replays per batch; repeated same maps; no independent samples added",
        "limitations": ["One batch per worker count, fixed order and only two maps by default",
                        "Existing ThreadPoolExecutor runner and Python engine retain GIL contention",
                        "Bot subprocesses can run in parallel; CPU scheduling also affects response latency",
                        "No CPU pinning or isolation; shared host background load is recorded",
                        "GPU not used; this profile does not estimate GPU training performance"]
    }

    def save():
        profile_file.write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    save()
    try:
        with tempfile.TemporaryDirectory(prefix="yk-throughput-") as temp:
            work = Path(temp)
            candidate_source = work / "candidate"
            candidate_source.mkdir()
            for p in source_files:
                shutil.copyfile(p, candidate_source / p.name)
                assert digest(candidate_source / p.name) == expected[p.name]
            opponent = work / "opponent"
            opponent.mkdir()
            with zipfile.ZipFile(opponent_zip) as archive:
                for name in archive.namelist():
                    path = Path(name)
                    if path.name != name or path.suffix not in {".py", ".json"}:
                        raise ValueError(f"Unexpected opponent ZIP member: {name}")
                    (opponent / name).write_bytes(archive.read(name))
            profile["opponent_source_sha256"] = {p.name: digest(p) for p in sorted(opponent.iterdir())}
            binary = work / "candidate_bot"
            compile_command = ["g++", "-std=c++20", "-O2", str(candidate_source / "main.cpp"), "-o", str(binary)]
            built = subprocess.run(compile_command, capture_output=True, text=True, check=True)
            profile["build"] = {"command": compile_command, "stdout": built.stdout,
                                "stderr": built.stderr, "executable_sha256": digest(binary)}
            save()
            for workers in args.workers:
                result_path = output / f"throughput-{workers}.json"
                log_path = output / f"throughput-{workers}.log"
                command = [sys.executable, str(ROOT / "tests/benchmark.py"),
                           "--candidate", shlex.join([str(binary)]),
                           "--opponent", shlex.join([sys.executable, str(opponent / "main.py")]),
                           "--start", str(args.start), "--seeds", str(args.seeds),
                           "--workers", str(workers), "--output", str(result_path),
                           "--save-losses", str(output / f"replays-workers-{workers}")]
                batch = {"workers": workers, "command": command, "started_at_utc": now(),
                         "load_average_before": os.getloadavg()}
                print(json.dumps({"event": "batch_start", "workers": workers}), flush=True)
                before = resource.getrusage(resource.RUSAGE_CHILDREN)
                start = time.perf_counter()
                with log_path.open("x", encoding="utf-8") as log:
                    completed = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
                wall = time.perf_counter() - start
                after = resource.getrusage(resource.RUSAGE_CHILDREN)
                cpu = after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime
                batch.update({"finished_at_utc": now(), "exit_code": completed.returncode,
                              "wall_seconds": wall, "children_cpu_seconds": cpu,
                              "average_cpu_cores": cpu / wall,
                              "load_average_after": os.getloadavg(),
                              "result_path": str(result_path.relative_to(ROOT)) if result_path.is_relative_to(ROOT) else str(result_path),
                              "log_path": str(log_path.relative_to(ROOT)) if log_path.is_relative_to(ROOT) else str(log_path)})
                if completed.returncode == 0:
                    results = json.loads(result_path.read_text())
                    batch["summary"] = results["summary"]
                    batch["games_per_second"] = results["summary"]["matches"] / wall
                    batch["turns_per_second"] = sum(r["result"]["turns"] for r in results["matches"]) / wall
                    batch["seconds_per_game_amortized"] = wall / results["summary"]["matches"]
                profile["batches"].append(batch)
                save()
                print(json.dumps({"event": "batch_done", **batch}, ensure_ascii=False), flush=True)
                if completed.returncode != 0:
                    raise RuntimeError(f"workers={workers} failed; inspect {log_path}")
            signatures = []
            for workers in args.workers:
                results = json.loads((output / f"throughput-{workers}.json").read_text())
                signatures.append([(r["seed"], r["team"], r["result"]) for r in results["matches"]])
            profile["same_game_results_across_workers"] = all(s == signatures[0] for s in signatures[1:])
            baseline = profile["batches"][0]["wall_seconds"]
            for batch in profile["batches"]:
                batch["speedup_vs_first_batch"] = baseline / batch["wall_seconds"]
            profile["status"] = "complete"
    except Exception as error:
        profile["status"] = "failed"
        profile["error"] = repr(error)
        raise
    finally:
        profile["finished_at_utc"] = now()
        profile["temporary_bot_snapshot_removed"] = True
        save()


if __name__ == "__main__":
    main()
