"""Measure v2 decision stages on fixed participant observations, without replaying games."""
import argparse
from datetime import datetime, timezone
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import platform
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def load_analysis():
    spec = importlib.util.spec_from_file_location("official_analysis", ROOT / "experiments/analyze_official_round1.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def protocol_input(replay, infer_bases):
    side = replay["side"]
    enemy = "K" if side == "Y" else "Y"
    first = replay["turns"][0]["observation"]
    bases = infer_bases(replay)
    buildings = sorted(first["buildings"], key=lambda b: b["id"])
    lines = ["INIT 15 15", f"TEAM {side}"]
    lines.extend("MAP " + row for row in first["map"])
    lines.append(f"BUILDINGS {len(buildings)}")
    lines.extend(f"{b['id']} {b['x']} {b['y']} {b['type']}" for b in buildings)
    lines.extend(f"BASE {team} {bases[team][0]} {bases[team][1]}" for team in ("Y", "K"))
    lines.append("END")
    for frame in replay["turns"][:-1]:
        obs = frame["observation"]
        lines.extend([f"TURN {obs['turn'] + 1}", f"RESOURCE {obs['resources'][side]} {obs['resources'][enemy]}",
                      f"UNITS {len(obs['units'])}"])
        lines.extend(" ".join(map(str, unit)) for unit in obs["units"])
        current = sorted(obs["buildings"], key=lambda b: b["id"])
        lines.append(f"BUILDINGS {len(current)}")
        for b in current:
            score = b.get("score")
            lines.append(f"{b['id']} {b['x']} {b['y']} {b['type']} {b['owner']} {b['stage']} {score if score is not None else -1}")
        lines.append("END")
    return "\n".join(lines) + "\n"


INSTRUMENT = r'''
struct ProbeMetric { long long calls=0; double seconds=0; };
ProbeMetric probe_metric[4];
int probe_fallback=0;
struct ProbeScope {
    int kind;
    chrono::steady_clock::time_point start;
    ProbeScope(int k):kind(k),start(chrono::steady_clock::now()){}
    ~ProbeScope(){++probe_metric[kind].calls;probe_metric[kind].seconds+=chrono::duration<double>(chrono::steady_clock::now()-start).count();}
};
void probe_report(){
    const char* names[]={"policy","advance","evaluation","decide"};
    cerr<<"{\"fallback_count\":"<<probe_fallback<<",\"stages\":{";
    for(int i=0;i<4;++i){if(i)cerr<<",";cerr<<"\""<<names[i]<<"\":{\"calls\":"<<probe_metric[i].calls<<",\"seconds\":"<<probe_metric[i].seconds<<"}";}
    cerr<<"}}\n";
}
'''


def instrument(source):
    replacements = [
        ("using namespace std;", "using namespace std;\n" + INSTRUMENT),
        ("State advance(State s, const Action& ay, const Action& ak) {", "State advance(State s, const Action& ay, const Action& ak) { ProbeScope ps(1);"),
        ("Action policy(const State& s, int t, int style) {", "Action policy(const State& s, int t, int style) { ProbeScope ps(0);"),
        ("double evaluation(const State& s, int t) {", "double evaluation(const State& s, int t) { ProbeScope ps(2);"),
        ("vector<string> decide(const p::View& v, const p::Init& in) {", "vector<string> decide(const p::View& v, const p::Init& in) { ProbeScope ps(3);"),
        ("        chosen=0;\n        if (complete)", "        chosen=0;\n        if (!complete) ++probe_fallback;\n        if (complete)"),
        ("    return p::run(decide);", "    int rc=p::run(decide); probe_report(); return rc;"),
    ]
    for old, new in replacements:
        if source.count(old) != 1:
            raise ValueError(f"Source anchor changed: {old}")
        source = source.replace(old, new)
    return source


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--replays", type=Path, default=ROOT / "artifacts/firstround_results")
    args = parser.parse_args()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    source_dir = ROOT / "submissions/tuned"
    original = (source_dir / "main.cpp").read_text()
    measured = instrument(original)
    (output / "instrumented.cpp").write_text(measured)
    result = {"status": "running", "started_utc": datetime.now(timezone.utc).isoformat(),
              "purpose": "Decision-stage profile on fixed legal observations; not a game replay or win-rate experiment",
              "script_sha256": digest(Path(__file__)),
              "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
              "source_sha256": {p.name: digest(p) for p in sorted(source_dir.iterdir()) if p.suffix in {".cpp", ".hpp"}},
              "instrumented_sha256": digest(output / "instrumented.cpp"),
              "host": {"platform": platform.platform(), "compiler": subprocess.check_output(["g++", "--version"], text=True).splitlines()[0]},
              "runs": [],
              "limitations": ["Instrumentation adds timing calls", "Recorded observations remain fixed even when regenerated commands differ",
                              "Official replay commands are not used as action labels", "Source internal 160ms fallback remains enabled",
                              "Single local shared host; no remote server inference"]}
    report_path = output / "result.json"

    def save():
        report_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")

    save()
    try:
        analysis = load_analysis()
        with tempfile.TemporaryDirectory(prefix="yk-stage-profile-") as temp:
            temp = Path(temp)
            for name in ("protocol.hpp", "generated.hpp"):
                (temp / name).write_bytes((source_dir / name).read_bytes())
            build_started = time.perf_counter()
            for name, code in (("plain", original), ("profiled", measured)):
                src = temp / (name + ".cpp")
                src.write_text(code)
                subprocess.run(["g++", "-std=c++20", "-O2", str(src), "-o", str(temp / name)], check=True, capture_output=True, text=True)
            result["build_wall_seconds"] = time.perf_counter() - build_started
            for replay_path in sorted(args.replays.glob("*.json")):
                replay = json.loads(replay_path.read_text())
                feed = protocol_input(replay, analysis.infer_bases)
                runs = {}
                for name in ("plain", "profiled"):
                    started = time.perf_counter()
                    completed = subprocess.run([str(temp / name)], input=feed, capture_output=True, text=True, timeout=180, check=True)
                    runs[name] = {"wall_seconds": time.perf_counter()-started,
                                  "output_sha256": sha256(completed.stdout.encode()).hexdigest(),
                                  "response_blocks": completed.stdout.splitlines().count("END")}
                    if name == "profiled":
                        runs[name]["profile"] = json.loads(completed.stderr)
                result["runs"].append({"replay": str(replay_path), "source_sha256": digest(replay_path),
                                       "protocol_input_sha256": sha256(feed.encode()).hexdigest(),
                                       "decisions": len(replay["turns"])-1, "plain": runs["plain"], "profiled": runs["profiled"],
                                       "instrumentation_preserved_commands": runs["plain"]["output_sha256"] == runs["profiled"]["output_sha256"]})
                save()
            totals = {kind: {"calls": sum(r["profiled"]["profile"]["stages"][kind]["calls"] for r in result["runs"]),
                             "seconds": sum(r["profiled"]["profile"]["stages"][kind]["seconds"] for r in result["runs"])}
                      for kind in ("policy", "advance", "evaluation", "decide")}
            result["totals"] = totals
            result["fallback_count"] = sum(r["profiled"]["profile"]["fallback_count"] for r in result["runs"])
            result["all_commands_preserved"] = all(r["instrumentation_preserved_commands"] for r in result["runs"])
            result["all_response_counts_correct"] = all(r["decisions"] == r["plain"]["response_blocks"] == r["profiled"]["response_blocks"] for r in result["runs"])
            fraction = totals["evaluation"]["seconds"] / totals["decide"]["seconds"]
            result["evaluation_fraction_of_decision_time"] = fraction
            result["evaluation_only_infinite_speed_upper_bound"] = 1 / (1-fraction)
            result["status"] = "complete"
    except Exception as error:
        result["status"] = "failed"
        result["error"] = repr(error)
        raise
    finally:
        result["finished_utc"] = datetime.now(timezone.utc).isoformat()
        save()
    print(json.dumps({k: result[k] for k in ["status", "totals", "fallback_count", "all_commands_preserved", "evaluation_fraction_of_decision_time", "evaluation_only_infinite_speed_upper_bound"]}, indent=2))


if __name__ == "__main__":
    main()
