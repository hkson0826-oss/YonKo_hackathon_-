"""Run paired matches with the supplied engine and real bot subprocesses."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import shlex
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "yk-development-tools"))
from engine.config import load_config
from runner.bots import SubprocessBot
from runner.match import run_match


def play(seed, team, candidate, opponent, replay_dir=None):
    bot = SubprocessBot(candidate)
    other = SubprocessBot(opponent)
    y, k = (bot, other) if team == "Y" else (other, bot)
    replay, result = run_match(seed, load_config(), y, k)
    row = {"seed": seed, "team": team, "result": result,
           "win": result["winner"] == team,
           "draw": result["winner"] == "DRAW",
           "score_margin": result["score"][team] - result["score"]["K" if team == "Y" else "Y"],
           "max_turn_ms": bot.max_turn_ms,
           "opponent_max_turn_ms": other.max_turn_ms}
    if replay_dir is not None and not row["win"]:
        path = Path(replay_dir) / f"seed-{seed}-{team}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(replay, ensure_ascii=False), encoding="utf-8")
        row["replay"] = str(path)
    return row


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", default=str(ROOT / "artifacts/first_bot"))
    parser.add_argument("--opponent", default=f"{shlex.quote(sys.executable)} {ROOT / 'yk-python-sample/example_lv2.py'}")
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--seeds", type=int, default=10)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--output", default=str(ROOT / "records/benchmarks/local/benchmark.json"))
    parser.add_argument("--save-losses", metavar="DIR", help="Save loss and draw replays in this run's directory")
    args = parser.parse_args()
    rows = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        jobs = [pool.submit(play, seed, team, args.candidate, args.opponent, args.save_losses)
                for seed in range(args.start, args.start + args.seeds) for team in ("Y", "K")]
        for job in as_completed(jobs):
            row = job.result()
            rows.append(row)
            print(json.dumps(row), flush=True)
    rows.sort(key=lambda r: (r["seed"], r["team"]))
    summary = {"matches": len(rows), "wins": sum(r["win"] for r in rows),
               "draws": sum(r["draw"] for r in rows),
               "losses": sum(not r["win"] and not r["draw"] for r in rows),
               "forfeits": sum(r["result"]["reason"] == "forfeit" for r in rows),
               "max_turn_ms": max(r["max_turn_ms"] for r in rows),
               "opponent_max_turn_ms": max(r["opponent_max_turn_ms"] for r in rows),
               "mean_score_margin": sum(r["score_margin"] for r in rows) / len(rows),
               "full_length_matches": sum(r["result"]["turns"] == 160 for r in rows),
               "by_team": {team: {"wins": sum(r["win"] for r in rows if r["team"] == team),
                                  "draws": sum(r["draw"] for r in rows if r["team"] == team),
                                  "matches": sum(r["team"] == team for r in rows)} for team in ("Y", "K")}}
    output = {"candidate": args.candidate, "opponent": args.opponent, "summary": summary, "matches": rows}
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
