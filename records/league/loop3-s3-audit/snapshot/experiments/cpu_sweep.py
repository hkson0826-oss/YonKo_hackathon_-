"""Evaluate frozen C++ parameter candidates with a process pool; no GPU or training.

Example: python3 experiments/cpu_sweep.py --config experiments/cpu_sweep_example.json \
    --output-dir records/benchmarks/cpu-sweep/example --workers 4
Use a new output directory for a new run. --resume accepts only matching inputs and
snapshots, rejects duplicate rows, and archives an unfinished final JSONL line.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import itertools
import json
import math
import multiprocessing
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import subprocess
import sys
import time
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
VERSION = 1
POLICY_SEED = 20260927
PARAMETERS = {
    "eng_bonus": (110, "if (has(s,team,ENG)) bonus += 110;", "if (has(s,team,ENG)) bonus += {value};"),
    "income_bonus": (35, "bonus += (income(s,team)-10)*35;", "bonus += (income(s,team)-10)*{value};"),
    "army_weight": (1.3, "result += 1.3*future*", "result += {value}*future*"),
    "resource_weight": (0.35, "+ .35*future*(s.res[t]-s.res[1-t]);", "+ {value}*future*(s.res[t]-s.res[1-t]);"),
}


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def json_hash(value):
    return digest(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def render_candidate(source, params):
    if set(params) - PARAMETERS.keys():
        raise ValueError(f"Unknown parameters: {sorted(set(params) - PARAMETERS.keys())}")
    for name, (default, needle, replacement) in PARAMETERS.items():
        if source.count(needle) != 1:
            raise ValueError(f"Source guard failed for {name}: expected exactly one occurrence")
        value = params.get(name, default)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError(f"{name} must be a finite nonnegative number")
        if value != default:
            source = source.replace(needle, replacement.format(value=format(value, ".17g")), 1)
    return source


def normalize_config(raw):
    allowed = {"candidates", "map_seeds", "teams", "opponents", "save_replays"}
    if set(raw) - allowed:
        raise ValueError(f"Unknown config keys: {sorted(set(raw) - allowed)}")
    candidates = raw.get("candidates", [])
    if not candidates:
        raise ValueError("At least one candidate is required")
    normalized = []
    for candidate in candidates:
        if set(candidate) - {"id", "parameters"}:
            raise ValueError("Candidate accepts only id and parameters")
        name = candidate.get("id", "")
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", name):
            raise ValueError("Candidate id must contain letters, digits, underscores or hyphens")
        params = candidate.get("parameters", {})
        if set(params) - PARAMETERS.keys():
            raise ValueError(f"Unknown parameters for {name}")
        normalized.append({"id": name, "parameters": {
            key: params.get(key, value[0]) for key, value in PARAMETERS.items()}})
    seeds = raw.get("map_seeds", [])
    teams = raw.get("teams", ["Y", "K"])
    opponents = raw.get("opponents", ["teammate"])
    if not seeds or any(isinstance(seed, bool) or not isinstance(seed, int) or seed < 0 for seed in seeds):
        raise ValueError("map_seeds must be nonnegative integers")
    if not teams or set(teams) - {"Y", "K"}:
        raise ValueError("teams must be Y and/or K")
    if not opponents or set(opponents) - {"v1", "v2", "teammate"}:
        raise ValueError("opponents must be v1, v2 and/or teammate")
    for label, values in (("candidate ids", [c["id"] for c in normalized]), ("map seeds", seeds),
                          ("teams", teams), ("opponents", opponents)):
        if len(values) != len(set(values)):
            raise ValueError(f"Duplicate {label}")
    save = raw.get("save_replays", "losses_and_first_win")
    if save not in {"all", "losses_and_first_win", "none"}:
        raise ValueError("save_replays must be all, losses_and_first_win or none")
    return {"candidates": normalized, "map_seeds": seeds, "teams": teams,
            "opponents": opponents, "save_replays": save}


def make_jobs(config):
    jobs = []
    for candidate, seed, team, opponent in itertools.product(
            config["candidates"], config["map_seeds"], config["teams"], config["opponents"]):
        job = {"candidate": candidate["id"], "map_seed": seed, "team": team, "opponent": opponent}
        job["job_id"] = json_hash(job)[:24]
        jobs.append(job)
    return jobs


def source_inputs(config):
    paths = {Path("experiments/cpu_sweep.py"), Path("submissions/tuned/main.cpp")}
    paths.update(path.relative_to(ROOT) for path in (ROOT / "submissions/tuned").glob("*.hpp"))
    for folder in ("engine", "runner", "mapgen", "config", "bots/dist/starter/python"):
        paths.update(path.relative_to(ROOT) for path in (ROOT / "yk-development-tools" / folder).rglob("*")
                     if path.is_file() and path.suffix in {".py", ".json"})
    if "v1" in config["opponents"]:
        paths.add(Path("submissions/first/main.cpp"))
        paths.update(path.relative_to(ROOT) for path in (ROOT / "submissions/first").glob("*.hpp"))
    if "teammate" in config["opponents"]:
        paths.add(Path("submissions/delineate-v1.zip"))
    return {str(path): digest((ROOT / path).read_bytes()) for path in sorted(paths)}


def identity(config, inputs):
    return {"version": VERSION, "config": config, "source_inputs": inputs,
            "policy_rng_seed": POLICY_SEED, "python_version": platform.python_version()}


def check_resume_identity(manifest, expected):
    if manifest["identity"] != expected or manifest["identity_sha256"] != json_hash(expected):
        raise ValueError("Resume refused: configuration, source hashes or Python version changed")


def load_completed(path, jobs):
    """Only newline-terminated rows are committed. Archive and remove an incomplete tail."""
    if not path.exists():
        return []
    data = path.read_bytes()
    end = data.rfind(b"\n") + 1
    if end < len(data):
        tail_path = path.with_name(f"{path.name}.unfinished-{time.time_ns()}")
        tail_path.write_bytes(data[end:])
        with path.open("r+b") as handle:
            handle.truncate(end)
    expected = {job["job_id"]: job for job in jobs}
    rows, seen = [], set()
    for line in data[:end].splitlines():
        row = json.loads(line)
        key = row["job_id"]
        if key in seen:
            raise ValueError(f"Duplicate completed job: {key}")
        if key not in expected or any(row.get(k) != v for k, v in expected[key].items()):
            raise ValueError(f"Unrecognized or mismatched job: {key}")
        if row.get("status") not in {"complete", "error"}:
            raise ValueError(f"Unfinished row: {key}")
        seen.add(key)
        rows.append(row)
    return rows


def build_snapshot(output, config, inputs):
    snapshot = output / "snapshot"
    for relative in inputs:
        target = snapshot / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
        if digest(target.read_bytes()) != inputs[relative]:
            raise ValueError(f"Input changed while freezing snapshot: {relative}")
    source = (snapshot / "submissions/tuned/main.cpp").read_text()
    if render_candidate(source, {}) != source:
        raise ValueError("Default candidate changed original source")
    compiler = shutil.which("g++")
    if compiler is None:
        raise RuntimeError("g++ is required")
    commands, builds, candidate_sources = {}, [], {}
    (output / "bin").mkdir()
    (output / ".gitignore").write_text("bin/\n")
    for candidate in config["candidates"]:
        candidate_source = snapshot / "candidates" / candidate["id"] / "main.cpp"
        candidate_source.parent.mkdir(parents=True)
        candidate_source.write_text(render_candidate(source, candidate["parameters"]))
        candidate_sources[candidate["id"]] = digest(candidate_source.read_bytes())
        commands["candidate:" + candidate["id"]] = _compile(output, candidate_source,
            "candidate-" + candidate["id"], compiler, builds, snapshot / "submissions/tuned")
    for opponent in config["opponents"]:
        if opponent in {"v1", "v2"}:
            relative = "submissions/first/main.cpp" if opponent == "v1" else "submissions/tuned/main.cpp"
            commands["opponent:" + opponent] = _compile(output, snapshot / relative,
                "opponent-" + opponent, compiler, builds, (snapshot / relative).parent)
        else:
            target = snapshot / "opponents/teammate"
            target.mkdir(parents=True)
            with ZipFile(snapshot / "submissions/delineate-v1.zip") as archive:
                for name in archive.namelist():
                    if not re.fullmatch(r"[A-Za-z0-9_.-]+", name) or name in {".", ".."}:
                        raise ValueError(f"Unexpected teammate archive path: {name}")
                    (target / name).write_bytes(archive.read(name))
            commands["opponent:teammate"] = shlex.join([sys.executable, str(target / "main.py")])
    hashes = {str(path.relative_to(output)): digest(path.read_bytes())
              for folder in (snapshot, output / "bin") for path in sorted(folder.rglob("*")) if path.is_file()}
    return {"commands": commands, "builds": builds, "candidate_source_sha256": candidate_sources,
            "frozen_files": hashes, "compiler": subprocess.check_output([compiler, "--version"], text=True).splitlines()[0]}


def _compile(output, source, name, compiler, builds, include_dir):
    binary = output / "bin" / name
    command = [compiler, "-std=c++20", "-O2", "-DNDEBUG", "-I",
               str(include_dir), str(source), "-o", str(binary)]
    completed = subprocess.run(command, text=True, capture_output=True)
    builds.append({"command": command, "returncode": completed.returncode,
                   "stdout": completed.stdout, "stderr": completed.stderr})
    if completed.returncode:
        write_json(output / "build-error.json", builds)
        raise RuntimeError(f"Build failed: {source}; see build-error.json")
    return shlex.join([str(binary)])


def initialize_worker(snapshot):
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(Path(snapshot) / "yk-development-tools"))


def play_job(job, commands, replay_dir, replay_policy, first_seed):
    from engine.config import load_config
    from runner.bots import SubprocessBot
    from runner.match import run_match

    class ObservedBot(SubprocessBot):
        def __init__(self, command):
            super().__init__(command)
            self.response_ms = []

        def collect_turn(self):
            previous_max = self.max_turn_ms
            self.max_turn_ms = 0.0
            try:
                response = super().collect_turn()
                if response[1] == "ok":
                    self.response_ms.append(self.max_turn_ms)
                return response
            finally:
                self.max_turn_ms = max(previous_max, self.max_turn_ms)

    started = time.perf_counter()
    row = {**job, "started_utc": now(), "policy_rng_seed": POLICY_SEED}
    bot = other = None
    try:
        bot = ObservedBot(commands["candidate:" + job["candidate"]])
        other = ObservedBot(commands["opponent:" + job["opponent"]])
        y, k = (bot, other) if job["team"] == "Y" else (other, bot)
        replay, result = run_match(job["map_seed"], load_config(), y, k)
        enemy = "K" if job["team"] == "Y" else "Y"
        row.update(status="complete", result=result, win=result["winner"] == job["team"],
                   draw=result["winner"] == "DRAW", forfeit=result["reason"] == "forfeit",
                   score_margin=result["score"][job["team"]] - result["score"][enemy],
                   max_turn_ms=bot.max_turn_ms, opponent_max_turn_ms=other.max_turn_ms,
                   response_ms=bot.response_ms, opponent_response_ms=other.response_ms,
                   p95_turn_ms=percentile95(bot.response_ms),
                   opponent_p95_turn_ms=percentile95(other.response_ms),
                   logical_trace_sha256=json_hash({"turns": replay["turns"], "result": result}))
        if replay_policy == "all" or (replay_policy != "none" and (not row["win"] or job["map_seed"] == first_seed)):
            path = Path(replay_dir) / (job["job_id"] + ".json")
            write_json(path, replay)
            row["replay"] = "replays/" + path.name
    except Exception as error:
        row.update(status="error", error=f"{type(error).__name__}: {error}")
        for active in (bot, other):
            if active is not None:
                try:
                    active.close()
                except Exception:
                    pass
    row.update(finished_utc=now(), elapsed_seconds=time.perf_counter() - started)
    return row


def percentile95(values):
    return sorted(values)[math.ceil(len(values) * 0.95) - 1] if values else None


def aggregate(rows):
    complete = [row for row in rows if row["status"] == "complete"]
    count = len(complete)
    wins = sum(row["win"] for row in complete)
    draws = sum(row["draw"] for row in complete)
    return {"jobs": len(rows), "matches": count, "errors": len(rows) - count,
            "distinct_map_count": len({row["map_seed"] for row in complete}),
            "wins": wins, "draws": draws, "losses": count - wins - draws,
            "point_rate": (wins + 0.5 * draws) / count if count else None,
            "forfeits": sum(row["forfeit"] for row in complete),
            "max_turn_ms": max((row["max_turn_ms"] for row in complete), default=None),
            "opponent_max_turn_ms": max((row["opponent_max_turn_ms"] for row in complete), default=None),
            "p95_turn_ms": percentile95([value for row in complete for value in row.get("response_ms", [])]),
            "opponent_p95_turn_ms": percentile95([value for row in complete for value in row.get("opponent_response_ms", [])]),
            "mean_score_margin": sum(row["score_margin"] for row in complete) / count if count else None}


def summarize(rows, expected_jobs):
    result = {"expected_jobs": len(expected_jobs), "finished_jobs": len(rows), "overall": aggregate(rows)}
    for key in ("candidate", "team", "opponent"):
        result["by_" + key] = {value: aggregate([row for row in rows if row[key] == value])
                              for value in sorted({job[key] for job in expected_jobs})}
    result["by_candidate_team_opponent"] = [
        {"candidate": candidate, "team": team, "opponent": opponent,
         **aggregate([row for row in rows if (row["candidate"], row["team"], row["opponent"]) == (candidate, team, opponent)])}
        for candidate, team, opponent in sorted({(job["candidate"], job["team"], job["opponent"]) for job in expected_jobs})]
    return result


def main():
    overall_started = time.perf_counter()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--executor", choices=("process", "thread"), default="process")
    parser.add_argument("--replays", choices=("all", "losses", "none"),
                        help="Override replay policy; losses also saves first-map wins")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers must be positive")
    config = normalize_config(json.loads(args.config.read_text()))
    if args.replays is not None:
        config["save_replays"] = "losses_and_first_win" if args.replays == "losses" else args.replays
    # Validate replacement values and source guards before creating the output directory.
    for candidate in config["candidates"]:
        render_candidate((ROOT / "submissions/tuned/main.cpp").read_text(), candidate["parameters"])
    output = args.output_dir.resolve()
    jobs = make_jobs(config)
    expected = identity(config, source_inputs(config))
    if args.resume:
        manifest = json.loads((output / "manifest.json").read_text())
        check_resume_identity(manifest, expected)
        if manifest["output_dir"] != str(output):
            raise ValueError("Resume requires the original output path")
        for relative, expected_hash in manifest["frozen_files"].items():
            if digest((output / relative).read_bytes()) != expected_hash:
                raise ValueError(f"Frozen file changed: {relative}")
    else:
        output.mkdir(parents=True, exist_ok=False)
        try:
            commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        except subprocess.CalledProcessError:
            commit = None
        manifest = {"run_id": output.name, "output_dir": str(output), "created_utc": now(),
                    "identity": expected, "identity_sha256": json_hash(expected),
                    "source_commit": commit, "source_hashes_authoritative": True,
                    "environment": {"platform": platform.platform(), "python": sys.version,
                                    "python_executable": sys.executable, "cpu_count": os.cpu_count()},
                    "rules": {"turn_timeout_ms": 300, "engine": "frozen official development tools"},
                    "replay_policy": "All losses/draws and first-map wins per candidate/team/opponent; all if requested.",
                    "resume_policy": "Worker count/executor may change; source/config/replay policy may not. Completed/error rows are terminal; malformed terminated rows fail; unfinished final line is archived.",
                    "timing_policy": "END receipt minus runner start, including process startup on first turn; successful responses only. P95 is nearest-rank. Deadlines are unchanged.",
                    "trace_policy": "SHA256 of canonical sorted JSON {turns, result}; bot command paths excluded.",
                    **build_snapshot(output, config, expected["source_inputs"])}
        write_json(output / "manifest.json", manifest)
        write_json(output / "jobs.json", jobs)
    (output / "replays").mkdir(exist_ok=True)
    rows = load_completed(output / "results.jsonl", jobs)
    done = {row["job_id"] for row in rows}
    pending = [job for job in jobs if job["job_id"] not in done]
    session = {"started_utc": now(), "workers": args.workers, "executor": args.executor, "resumed_jobs": len(rows),
               "scheduled_jobs": len(pending), "command": [sys.executable, *sys.argv], "status": "running"}
    session_path = output / f"session-{time.time_ns()}.json"
    write_json(session_path, session)
    started = time.perf_counter()
    pool_type = ProcessPoolExecutor if args.executor == "process" else ThreadPoolExecutor
    pool_options = {"max_workers": args.workers, "initializer": initialize_worker,
                    "initargs": (str(output / "snapshot"),)}
    if args.executor == "process":
        pool_options["mp_context"] = multiprocessing.get_context("spawn")
    try:
        with (output / "results.jsonl").open("a", encoding="utf-8") as handle:
            with pool_type(**pool_options) as pool:
                futures = {pool.submit(play_job, job, manifest["commands"], str(output / "replays"),
                    config["save_replays"], config["map_seeds"][0]): job for job in pending}
                for future in as_completed(futures):
                    job = futures[future]
                    try:
                        row = future.result()
                    except Exception as error:
                        row = {**job, "status": "error", "error": f"Worker failure: {error}", "finished_utc": now()}
                    handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                    rows.append(row)
                    print(json.dumps({"finished": len(rows), "total": len(jobs),
                                      "job_id": row["job_id"], "status": row["status"]}), flush=True)
        session["status"] = "complete_with_errors" if any(row["status"] == "error" for row in rows) else "complete"
    except BaseException:
        session["status"] = "interrupted"
        raise
    finally:
        session.update(finished_utc=now(), wall_seconds=time.perf_counter() - started,
                       total_wall_seconds=time.perf_counter() - overall_started,
                       finished_new_jobs=len(rows) - session["resumed_jobs"])
        write_json(session_path, session)
        write_json(output / "summary.json", summarize(rows, jobs))
    print(json.dumps({"session": session, "summary": summarize(rows, jobs)}, ensure_ascii=False), flush=True)
    if session["status"] == "complete_with_errors":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
