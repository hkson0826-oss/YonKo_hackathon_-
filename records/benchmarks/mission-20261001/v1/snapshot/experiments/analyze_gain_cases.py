"""Replay the four fixed q_threat_window gain cases and audit their economy."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
SDK = ROOT / "yk-development-tools"
sys.path.insert(0, str(SDK))

from engine.commands import Move, Move2, Spawn, Tele
from engine.pipeline import run_turn, step_combat, step_income, step_move, step_spawn, unit_cost
from mapgen import generate, to_state
from runner.protocol import parse_commands
from runner.replay import snapshot

REPLAYS = ROOT / "records/league/loop2-iteration1/runs/development/replays"
CASES = (
    (7001, "q_threat_window", "79215d6bf9cdda4968121d7e", "1bef5cfad7932de52f7a3dd25fc9467edd8340329ad74d42ad4a0c7a36c71794"),
    (7001, "v2", "cfcbb116d2922a3b8f3fdfef", "9a480f5db3015aa70460e771898590c5818f8e46c0358f1f3cb73f29ff23215b"),
    (7000, "q_threat_window", "0d8be0871fafd2be313ef48d", "bb722a0245fe9a731e1a89b8869d5bbea89e25beb46a5c36490e437bfb92c5fe"),
    (7000, "v2", "8b43974e924bfb9b33edd4dc", "bb9ab84658956c29c317070717e8f94f15449693fb0d82e6966eaa941a868afc"),
)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def totals(state, team):
    return {kind: sum(count for (_, _, side, unit), count in state.units.items()
                      if side == team and unit == kind) for kind in "FWS"}


def scores(state):
    return {team: sum(b.score for b in state.buildings.values() if b.owner == team) for team in "YK"}


def check_case(seed, candidate, job_id, expected_hash):
    path = REPLAYS / (job_id + ".json.gz")
    if sha(path) != expected_hash:
        raise ValueError(f"Input hash changed: {path}")
    with gzip.open(path, "rt") as stream:
        replay = json.load(stream)
    if replay["seed"] != seed:
        raise ValueError(f"Unexpected map seed in {job_id}")
    state = to_state(generate(seed, replay["config"]))
    initial = snapshot(state)
    economy = {team: {"eng_discount_turns_at_spawn": 0, "hall_count_sum_at_income": 0,
                      "effective_income": 0, "nominal_hall_income": 0,
                      "production": {kind: 0 for kind in "FWS"}, "production_spending": 0,
                      "deaths": {kind: 0 for kind in "FWS"}}
               for team in "YK"}
    timeline = []
    last_result = None
    for number, frame in enumerate(replay["turns"], 1):
        if frame["turn"] != number:
            raise ValueError(f"Non-contiguous frame {job_id}:{number}")
        commands = {team: parse_commands(frame["commands"][team]) for team in "YK"}
        before_units = {team: totals(state, team) for team in "YK"}
        phase = state.clone()
        phase.turn += 1
        for building in phase.buildings.values():
            if building.owner == "N" and building.stage == 1:
                building.stage = 0
        for team in "YK":
            economy[team]["eng_discount_turns_at_spawn"] += unit_cost(phase, team, "W") < phase.config["units"]["W"]["cost"]
        before_resource = dict(phase.resources)
        step_spawn(phase, {team: [cmd for cmd in commands[team] if isinstance(cmd, Spawn)] for team in "YK"})
        spawned_units = {team: totals(phase, team) for team in "YK"}
        for team in "YK":
            economy[team]["production_spending"] += before_resource[team] - phase.resources[team]
            for kind in "FWS":
                economy[team]["production"][kind] += spawned_units[team][kind] - before_units[team][kind]
        step_move(phase, {team: [cmd for cmd in commands[team] if isinstance(cmd, (Move, Move2, Tele))] for team in "YK"})
        step_combat(phase)
        for team in "YK":
            hall_count = sum(b.owner == team and b.btype == "HALL" for b in phase.buildings.values())
            economy[team]["hall_count_sum_at_income"] += hall_count
            economy[team]["nominal_hall_income"] += hall_count * phase.config["resource"]["hall_bonus"]
        before_income = dict(phase.resources)
        step_income(phase)
        for team in "YK":
            economy[team]["effective_income"] += phase.resources[team] - before_income[team]

        state, last_result = run_turn(state, commands["Y"], commands["K"])
        if snapshot(state) != frame["state"]:
            raise ValueError(f"Official snapshot mismatch {job_id}:{number}")
        for team in "YK":
            remaining = totals(state, team)
            for kind in "FWS":
                economy[team]["deaths"][kind] += spawned_units[team][kind] - remaining[kind]
        if number in (20, 40, 80, 120, 140, 160):
            timeline.append({"turn": number, "score": scores(state), "Y_units": totals(state, "Y")})
    for key in ("winner", "reason", "score", "turns"):
        if last_result is None or last_result[key] != replay["result"][key]:
            raise ValueError(f"Final result mismatch {job_id}: {key}")
    return {
        "map_seed": seed, "candidate": candidate, "opponent": "v2", "team": "Y",
        "job_id": job_id, "path": str(path.relative_to(ROOT)), "sha256": expected_hash,
        "verified_frames": len(replay["turns"]), "result": replay["result"],
        "economy": economy, "timeline": timeline,
    }, replay, initial


def first_divergence(candidate, baseline, initial):
    first = None
    first_ownership = None
    for index, (own, old) in enumerate(zip(candidate["turns"], baseline["turns"])):
        if first is None and own["commands"]["Y"] != old["commands"]["Y"]:
            preceding_own = candidate["turns"][index - 1]["state"] if index else initial
            preceding_old = baseline["turns"][index - 1]["state"] if index else initial
            first = {"turn": own["turn"], "preceding_snapshot_equal": preceding_own == preceding_old,
                     "opponent_commands_equal": own["commands"]["K"] == old["commands"]["K"],
                     "candidate_commands": own["commands"]["Y"], "baseline_commands": old["commands"]["Y"]}
        if first_ownership is None:
            changes = [{"id": info["id"], "position": [info["x"], info["y"]], "type": info["type"],
                        "score_retrospective": info["score"], "candidate_owner": a["owner"], "baseline_owner": b["owner"]}
                       for info, a, b in zip(candidate["map"]["buildings"], own["state"]["buildings"], old["state"]["buildings"])
                       if a["owner"] != b["owner"]]
            if changes:
                first_ownership = {"turn": own["turn"], "changes": changes}
    return {"map_seed": candidate["seed"], "first_own_command_difference": first,
            "first_ownership_difference": first_ownership}


def analyze():
    cases, raw = [], {}
    for spec in CASES:
        checked, replay, initial = check_case(*spec)
        cases.append(checked)
        raw[spec[0], spec[1]] = replay, initial
    pairs = [first_divergence(raw[seed, "q_threat_window"][0], raw[seed, "v2"][0],
                              raw[seed, "q_threat_window"][1]) for seed in (7001, 7000)]
    files = ("engine/pipeline.py", "engine/state.py", "engine/commands.py", "mapgen/generator.py",
             "runner/protocol.py", "runner/replay.py")
    return {"schema": 1, "script_sha256": sha(Path(__file__)),
            "engine_file_sha256": {name: sha(SDK / name) for name in files},
            "verified_frames": sum(case["verified_frames"] for case in cases),
            "scope": "Retrospective fixed gain-case audit, not an unbiased evaluation or a new match. C++ instrumentation is not rerun.",
            "income_definition": "Resource increase at step_income after resource-cap clipping; excludes depot bonuses and capture spending.",
            "cases": cases, "pairs": pairs}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = analyze()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(f"Verified {result['verified_frames']} official transitions across {len(result['cases'])} replays.")


if __name__ == "__main__":
    main()
