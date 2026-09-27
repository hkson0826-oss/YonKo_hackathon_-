"""Freeze a diverse code population and run resumable official-engine leagues."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
import gzip
import hashlib
import importlib.util
import itertools
import json
import math
import multiprocessing
import os
from pathlib import Path
import random
import shlex
import shutil
import subprocess
import sys
import time
from zipfile import ZipFile

import cpu_sweep as sweep

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    sweep.write_json(path, value)


def stamp():
    return datetime.now(timezone.utc).isoformat()


def parameter_variants(source):
    settings = [
        {"eng_bonus": 70}, {"eng_bonus": 160}, {"eng_bonus": 220},
        {"army_weight": .8}, {"army_weight": 2.0}, {"income_bonus": 20},
        {"income_bonus": 55}, {"eng_bonus": 180, "army_weight": 1.8},
    ]
    rng = random.Random(927603)
    for _ in range(8):
        settings.append({"eng_bonus": rng.choice([70, 110, 150, 190]),
                         "income_bonus": rng.choice([20, 35, 50]),
                         "army_weight": rng.choice([.8, 1.3, 1.8]),
                         "resource_weight": rng.choice([.15, .35, .65])})
    return [{"id": f"p_{i:02}", "family": "parameter", "parameters": values,
             "hypothesis": "경제·병력 가치의 다른 조합을 같은 맵에서 비교한다.",
             "weakness": "행동 후보 공간 자체는 v2와 같으며 계수만으로 방어 누락을 고칠 수 없다.",
             "source": sweep.render_candidate(source, values)} for i, values in enumerate(settings)]


def filter_population(population, spec):
    ids = [item['id'] for item in population]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate bot ids')
    requested = spec.get('include_ids')
    if requested is not None:
        unknown = set(requested) - set(ids)
        if unknown:
            raise ValueError(f'Unknown requested candidates: {sorted(unknown)}')
        prefixes = tuple(spec.get('include_prefixes', []))
        population = [item for item in population if item['id'] in requested or item['id'].startswith(prefixes)]
    aliases, unique, hashes = {}, [], {}
    for item in population:
        digest = hashlib.sha256(item['source'].encode()).hexdigest()
        if spec.get('deduplicate') and digest in hashes:
            aliases[item['id']] = hashes[digest]
        else:
            unique.append(item)
            hashes[digest] = item['id']
    return unique, aliases


def prepare(output, population_spec=None):
    output.mkdir(parents=True, exist_ok=False)
    (output / ".gitignore").write_text("bin/\n")
    snapshot = output / "snapshot"
    inputs = {path.relative_to(ROOT) for path in (ROOT / 'experiments').glob('*.py')}
    inputs.update(path.relative_to(ROOT) for path in (ROOT / "experiments/local_league").glob("*.py"))
    for folder in ("submissions/tuned", "submissions/first", "yk-development-tools/engine",
                   "yk-development-tools/runner", "yk-development-tools/mapgen", "yk-development-tools/config",
                   "yk-development-tools/bots/dist/starter/python"):
        inputs.update(path.relative_to(ROOT) for path in (ROOT / folder).rglob("*")
                      if path.is_file() and path.suffix in {".cpp", ".hpp", ".py", ".json"})
    inputs.add(Path("submissions/delineate-v1.zip"))
    for relative in sorted(inputs):
        dest = snapshot / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, dest)
    source = (snapshot / "submissions/tuned/main.cpp").read_text()
    population = [{"id": "v2", "family": "baseline", "parameters": {},
                   "hypothesis": "현재 제출 기준선", "weakness": "공식 1차 경제·종반 패배", "source": source}]
    spec_config = population_spec or {}
    if spec_config.get('include_parameters', True):
        population += parameter_variants(source)
    for module in spec_config.get('modules', ("repairs", "search_families", "challengers")):
        # Import the copied generator so every produced candidate is attributable.
        path = snapshot / f"experiments/local_league/{module}.py"
        spec = importlib.util.spec_from_file_location("league_" + module, path)
        loaded = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(loaded)
        population += loaded.variants(source)
    population.append({"id": "v1", "family": "reference", "parameters": {},
                       "hypothesis": "과거 제출 회귀 검사", "weakness": "이전 후보", "source": (snapshot / "submissions/first/main.cpp").read_text()})
    population, aliases = filter_population(population, spec_config)
    bots = {}
    (output / "bin").mkdir()
    compiler = shutil.which("g++")
    manifest = {"status": "building", "created_utc": stamp(), "root": str(output),
                "source_commit": os.environ.get("YK_SOURCE_COMMIT") or subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                "input_sha256": {str(p): sha(snapshot / p) for p in sorted(inputs)},
                "compiler": subprocess.check_output([compiler, "--version"], text=True).splitlines()[0],
                "python": sys.version, "policy_rng_seed": 20260927, "bots": bots,
                "population_spec": spec_config, "duplicate_source_aliases": aliases}
    write(output / "manifest.json", manifest)
    compiled = {}
    for candidate in population:
        name = candidate["id"]
        folder = snapshot / "candidates" / name
        folder.mkdir(parents=True)
        (folder / "main.cpp").write_text(candidate["source"])
        header_dir = snapshot / ("submissions/first" if name == "v1" else "submissions/tuned")
        for header in header_dir.glob("*.hpp"):
            shutil.copyfile(header, folder / header.name)
        digest = sha(folder / "main.cpp")
        builds = []
        if digest in compiled:
            command = compiled[digest]
        else:
            command = sweep._compile(output, folder / "main.cpp", name, compiler, builds, folder)
            compiled[digest] = command
        bots[name] = {key: value for key, value in candidate.items() if key != "source"}
        bots[name].update(command=command, source=str((folder / "main.cpp").relative_to(output)),
                          source_sha256=digest, builds=builds, binary_sha256=sha(shlex.split(command)[0]))
        write(output / "manifest.json", manifest)
        print(json.dumps({"built": name, "count": len(bots), "total": len(population)}), flush=True)
    teammate = snapshot / "opponents/teammate"
    teammate.mkdir(parents=True)
    with ZipFile(snapshot / "submissions/delineate-v1.zip") as archive:
        for name in archive.namelist():
            if Path(name).name != name or name in {".", ".."}:
                raise ValueError("Unexpected teammate ZIP path")
            (teammate / name).write_bytes(archive.read(name))
    bots["teammate"] = {"id": "teammate", "family": "reference", "command": shlex.join([sys.executable, str(teammate / "main.py")]),
                        "source_sha256": sha(snapshot / "submissions/delineate-v1.zip")}
    manifest["frozen_sha256"] = {str(path.relative_to(output)): sha(path)
                               for folder in (snapshot, output / "bin") for path in sorted(folder.rglob("*")) if path.is_file()}
    manifest.update(status="ready", finished_utc=stamp())
    write(output / "manifest.json", manifest)


def diagnostics(replay):
    from engine.commands import Spawn
    from engine.config import load_config
    from engine.pipeline import step_spawn
    from mapgen import generate, to_state
    state = to_state(generate(replay["seed"], load_config()))
    result = {t: {"engineering_turns": 0, "late_engineering_turns": 0,
                  "production": {k: 0 for k in "FWS"}, "deaths": {k: 0 for k in "FWS"},
                  "score_turn_120": None, "max_score_lead": 0, "biggest_score_drop": 0,
                  "biggest_drop_turn": None, "flag_contest_turns": 0,
                  "late_frames": 0, "late_w_concentration_mean": 0.0,
                  "late_largest_w_stack": 0} for t in "YK"}
    previous_scores = {t: 0 for t in "YK"}
    for frame in replay["turns"]:
        before = {t: {k: sum(n for (x,y,side,kind),n in state.units.items() if side==t and kind==k) for k in "FWS"} for t in "YK"}
        for t in "YK":
            eng = any(b.owner == t and b.btype == "ENG" for b in state.buildings.values())
            result[t]["engineering_turns"] += eng
            result[t]["late_engineering_turns"] += eng and frame["turn"] >= 121
        spawns = {t: [Spawn(**{k:v for k,v in cmd.items() if k != "cmd"})
                       for cmd in frame["applied"][t] if cmd["cmd"] == "Spawn"] for t in "YK"}
        step_spawn(state, spawns)
        after_spawn = {t: {k: sum(n for (x,y,side,kind),n in state.units.items() if side==t and kind==k) for k in "FWS"} for t in "YK"}
        snap = frame["state"]
        state.units = {(x,y,t,k): n for t,k,x,y,n in snap["units"]}
        state.resources = dict(snap["resources"])
        for b in snap["buildings"]:
            state.buildings[b["id"]].owner = b["owner"]
            state.buildings[b["id"]].stage = b["stage"]
        score = {t: sum(b.score for b in state.buildings.values() if b.owner==t) for t in "YK"}
        for t in "YK":
            enemy = "K" if t == "Y" else "Y"
            for k in "FWS":
                remaining = sum(n for (x,y,side,kind),n in state.units.items() if side==t and kind==k)
                result[t]["production"][k] += after_spawn[t][k] - before[t][k]
                result[t]["deaths"][k] += after_spawn[t][k] - remaining
            if frame["turn"] == 120:
                result[t]["score_turn_120"] = score[t]
            result[t]["max_score_lead"] = max(result[t]["max_score_lead"], score[t]-score[enemy])
            drop = previous_scores[t] - score[t]
            if drop > result[t]["biggest_score_drop"]:
                result[t]["biggest_score_drop"], result[t]["biggest_drop_turn"] = drop, frame["turn"]
            result[t]["flag_contest_turns"] += sum(state.get_unit(b.x,b.y,t,"F") > 0 and state.get_unit(b.x,b.y,enemy,"F") > 0 for b in state.buildings.values())
            if frame['turn'] >= 121:
                warriors = [n for (x,y,side,kind),n in state.units.items() if side == t and kind == 'W']
                largest = max(warriors, default=0)
                result[t]['late_frames'] += 1
                result[t]['late_w_concentration_mean'] += largest / max(1, sum(warriors))
                result[t]['late_largest_w_stack'] = max(result[t]['late_largest_w_stack'], largest)
        previous_scores = score
    for stats in result.values():
        stats['late_w_concentration_mean'] /= max(1, stats['late_frames'])
    return result


def worker(job, commands, replay_dir, first_seed, replay_mode):
    from engine.config import load_config
    from runner.bots import SubprocessBot
    from runner.match import run_match

    class TimedBot(SubprocessBot):
        def __init__(self, command):
            super().__init__(command)
            self.times = []

        def collect_turn(self):
            previous = self.max_turn_ms
            self.max_turn_ms = 0.0
            try:
                response = super().collect_turn()
                if response[1] == "ok":
                    self.times.append(self.max_turn_ms)
                return response
            finally:
                self.max_turn_ms = max(previous, self.max_turn_ms)

    start = time.perf_counter()
    row = {**job, "started_utc": stamp()}
    own = enemy = None
    try:
        own, enemy = TimedBot(commands[job["candidate"]]), TimedBot(commands[job["opponent"]])
        y, k = (own, enemy) if job["team"] == "Y" else (enemy, own)
        replay, result = run_match(job["map_seed"], load_config(), y, k,
                                   names={job["team"]:job["candidate"], "K" if job["team"]=="Y" else "Y":job["opponent"]})
        other = "K" if job["team"] == "Y" else "Y"
        row.update(status="complete", result=result, win=result["winner"]==job["team"],
                   draw=result["winner"]=="DRAW", forfeit=result["reason"]=="forfeit",
                   score_margin=result["score"][job["team"]]-result["score"][other],
                   max_turn_ms=own.max_turn_ms, opponent_max_turn_ms=enemy.max_turn_ms,
                   response_ms=own.times, opponent_response_ms=enemy.times,
                   p95_turn_ms=sweep.percentile95(own.times), diagnostics=diagnostics(replay),
                   logical_trace_sha256=sweep.json_hash({"turns":replay["turns"], "result":result}))
        save = replay_mode == "all" or (replay_mode == "losses" and (not row["win"] or job["map_seed"]==first_seed))
        if save:
            name = job["job_id"] + ".json.gz"
            Path(replay_dir, name).write_bytes(gzip.compress(json.dumps(replay,ensure_ascii=False,separators=(",", ":")).encode(),mtime=0))
            row["replay"] = "replays/" + name
    except Exception as error:
        row.update(status="error", error=f"{type(error).__name__}: {error}")
        for bot in (own, enemy):
            if bot is not None:
                try:
                    bot.close()
                except Exception:
                    pass
    row.update(finished_utc=stamp(), elapsed_seconds=time.perf_counter()-start)
    return row


def make_jobs(plan, bots):
    jobs = []
    if "pairs" in plan:
        pairs = plan["pairs"]
    else:
        pairs = itertools.product(plan["candidates"], plan["opponents"])
    for candidate, opponent in pairs:
        if candidate not in bots or opponent not in bots:
            raise ValueError(f"Unknown bot: {candidate}/{opponent}")
        for seed, team in itertools.product(plan["map_seeds"], ["Y", "K"]):
            item = {"candidate":candidate,"opponent":opponent,"map_seed":seed,"team":team}
            item["job_id"] = sweep.json_hash(item)[:24]
            jobs.append(item)
    if len({j["job_id"] for j in jobs}) != len(jobs):
        raise ValueError("Duplicate games in plan")
    random.Random(plan.get("order_seed", 927604)).shuffle(jobs)
    return jobs


def summarize(rows, jobs):
    summary = sweep.summarize(rows, jobs)
    for key, aggregate in summary["by_candidate"].items():
        selected = [r for r in rows if r["candidate"]==key and r["status"]=="complete"]
        aggregate["Y"] = sweep.aggregate([r for r in selected if r["team"]=="Y"])
        aggregate["K"] = sweep.aggregate([r for r in selected if r["team"]=="K"])
        aggregate["opponents"] = {op: sweep.aggregate([r for r in selected if r["opponent"]==op])
                                   for op in sorted({r["opponent"] for r in selected})}
        for field in ("engineering_turns", "late_engineering_turns", "flag_contest_turns"):
            aggregate["mean_"+field] = sum(r["diagnostics"][r["team"]][field] for r in selected)/len(selected) if selected else None
        aggregate["mean_w_production"] = sum(r["diagnostics"][r["team"]]["production"]["W"] for r in selected)/len(selected) if selected else None
    return summary


def run(arena, plan_path, run_id, workers, resume):
    manifest = json.loads((arena / "manifest.json").read_text())
    if manifest["status"] != "ready":
        raise ValueError("Arena is not ready")
    if manifest["python"] != sys.version:
        raise ValueError("Python version changed after freezing")
    for relative, expected in manifest["frozen_sha256"].items():
        if sha(arena / relative) != expected:
            raise ValueError(f"Frozen input changed: {relative}")
    if sha(arena / "snapshot/experiments/local_league.py") != sha(Path(__file__)) or sha(arena / "snapshot/experiments/cpu_sweep.py") != sha(ROOT / "experiments/cpu_sweep.py"):
        raise ValueError("Runner changed after freezing; run the frozen script instead")
    plan = json.loads(plan_path.read_text())
    jobs = make_jobs(plan, manifest["bots"])
    output = arena / "runs" / run_id
    if resume:
        if json.loads((output / "plan.json").read_text()) != plan:
            raise ValueError("Resume plan mismatch")
    else:
        output.mkdir(parents=True, exist_ok=False)
        write(output / "plan.json", plan)
        write(output / "jobs.json", jobs)
    (output / "replays").mkdir(exist_ok=True)
    rows = sweep.load_completed(output / "results.jsonl", jobs)
    done = {row["job_id"] for row in rows}
    pending = [job for job in jobs if job["job_id"] not in done]
    commands = {key:bot["command"] for key,bot in manifest["bots"].items()}
    session = {"status":"running","started_utc":stamp(),"workers":workers,"resumed_jobs":len(rows),
               "scheduled_jobs":len(pending),"command":[sys.executable,*sys.argv],"plan_sha256":sha(plan_path),
               "python":sys.version,"python_executable":sys.executable}
    session_path = output / f"session-{time.time_ns()}.json"
    write(session_path,session)
    start = time.perf_counter()
    try:
        with (output / "results.jsonl").open("a") as handle:
            with ProcessPoolExecutor(max_workers=workers,mp_context=multiprocessing.get_context("spawn"),
                    initializer=sweep.initialize_worker,initargs=(str(arena / "snapshot"),)) as pool:
                futures = {pool.submit(worker, job, commands, str(output/"replays"),min(plan["map_seeds"]),plan.get("replays","losses")):job for job in pending}
                for future in as_completed(futures):
                    job = futures[future]
                    try:
                        row = future.result()
                    except Exception as error:
                        row = {**job,"status":"error","error":repr(error),"finished_utc":stamp()}
                    handle.write(json.dumps(row,ensure_ascii=False)+"\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                    rows.append(row)
                    if len(rows)%16==0 or len(rows)==len(jobs):
                        write(output/"summary.json",summarize(rows,jobs))
                        print(json.dumps({"finished":len(rows),"total":len(jobs),"elapsed_seconds":round(time.perf_counter()-start,1),"errors":sum(r['status']=='error' for r in rows),"forfeits":sum(r.get('forfeit',False) for r in rows)}),flush=True)
        session["status"] = "complete_with_errors" if any(r["status"]=="error" for r in rows) else "complete"
    except BaseException:
        session["status"] = "interrupted"
        raise
    finally:
        session.update(finished_utc=stamp(),wall_seconds=time.perf_counter()-start,finished_new_jobs=len(rows)-session["resumed_jobs"])
        write(session_path,session)
        write(output/"summary.json",summarize(rows,jobs))
    if session["status"] != "complete":
        raise SystemExit(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--arena",type=Path,required=True)
    play = sub.add_parser("run")
    play.add_argument("--arena",type=Path,required=True)
    play.add_argument("--plan",type=Path,required=True)
    play.add_argument("--run-id",required=True)
    play.add_argument("--workers",type=int,default=8)
    play.add_argument("--resume",action="store_true")
    args = parser.parse_args()
    if args.action=="prepare":
        prepare(args.arena.resolve())
    else:
        if args.workers<1 or not args.run_id.replace('-','').replace('_','').isalnum():
            parser.error("Invalid worker count or run id")
        run(args.arena.resolve(),args.plan.resolve(),args.run_id,args.workers,args.resume)


if __name__ == "__main__":
    main()
