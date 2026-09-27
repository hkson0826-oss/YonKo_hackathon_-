"""Analyze participant-view replays without inventing opponent commands.

Score reconstruction is retrospective; per-turn legal knowledge is kept separate.
Only our spawn/movement stages are replayed through the official engine. The
opponent's W production follows from one-for-one W combat, not command recovery.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
SDK = ROOT / "yk-development-tools"
sys.path.insert(0, str(SDK))

from engine.commands import Move, Move2, Spawn, Tele
from engine.pipeline import run_turn, step_move, step_spawn, unit_cost
from engine.state import Building, GameState
from runner.protocol import parse_commands


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def mirrored_scores(buildings, known):
    """Infer only from supplied knowledge, never a later observation."""
    result = dict(known)
    for b in buildings:
        if b.get("type") == "PLAZA":
            result.setdefault(b["id"], 3)
    positions = {(b["x"], b["y"]): b["id"] for b in buildings}
    for b in buildings:
        mate = positions.get((14 - b["x"], 14 - b["y"]))
        if b["id"] not in result and mate in known:
            result[b["id"]] = known[mate]
    return result


def score_totals(buildings, scores):
    result = {}
    for team in ("Y", "K", "N"):
        owned = [b for b in buildings if b["owner"] == team]
        result[team] = (
            sum(scores[b["id"]] for b in owned)
            if all(b["id"] in scores for b in owned) else None
        )
    return result


def unit_totals(units):
    return {t: {k: sum(u[4] for u in units if u[:2] == [t, k])
                for k in ("F", "W", "S")} for t in ("Y", "K")}


def infer_bases(replay):
    first = replay["turns"][0]["observation"]
    homes = [(x, y) for y, line in enumerate(first["map"])
             for x, c in enumerate(line) if c == "H"]
    own = set()
    for cmd in parse_commands(replay["turns"][1]["command"]["lines"]):
        if isinstance(cmd, (Move, Move2, Tele)) and (cmd.x, cmd.y) in homes:
            own.add((cmd.x, cmd.y))
    if len(homes) != 2 or len(own) != 1:
        raise ValueError("Cannot infer unique own base from first-turn command")
    side = replay["side"]
    ours = own.pop()
    return {side: ours, "K" if side == "Y" else "Y": next(h for h in homes if h != ours)}


def state_from_observation(obs, bases, config):
    # Hidden scores, past depot claims and enemy reveal history do not affect
    # spawn/movement. They are deliberately not reconstructed here.
    return GameState(
        config=config, terrain=[list(row) for row in obs["map"]],
        buildings={b["id"]: Building(b["id"], b["x"], b["y"], b["type"],
                                     b.get("score", 0), b["owner"], b["stage"])
                   for b in obs["buildings"]},
        bases=bases, resources=dict(obs["resources"]), turn=obs["turn"],
        units={(x, y, team, kind): count for team, kind, x, y, count in obs["units"]},
    )


def own_transition(previous, current, bases, config, side):
    before = previous["observation"]
    after = current["observation"]
    state = state_from_observation(before, bases, config)
    commands = parse_commands(current["command"]["lines"])
    spawn = {t: [] for t in ("Y", "K")}
    moves = {t: [] for t in ("Y", "K")}
    spawn[side] = [c for c in commands if isinstance(c, Spawn)]
    moves[side] = [c for c in commands if isinstance(c, (Move, Move2, Tele))]
    old_totals = unit_totals(before["units"])
    new_totals = unit_totals(after["units"])
    costs = {k: unit_cost(state, side, k) for k in ("F", "W", "S")}
    step_spawn(state, spawn)
    production = {k: sum(n for (_x, _y, t, kind), n in state.units.items()
                          if t == side and kind == k) - old_totals[side][k]
                  for k in costs}
    step_move(state, moves)
    actual = {(x, y, t, k): n for t, k, x, y, n in after["units"] if t == side}
    projected = {key: n for key, n in state.units.items() if key[2] == side}
    keys = projected.keys() | actual.keys()
    losses = []
    for key in sorted(keys):
        difference = projected.get(key, 0) - actual.get(key, 0)
        if difference < 0:
            raise ValueError(f"Own stage mismatch turn {after['turn']}: {key}")
        if difference:
            x, y, _t, kind = key
            losses.append({"kind": kind, "x": x, "y": y, "count": difference})
    casualties = {k: sum(v["count"] for v in losses if v["kind"] == k) for k in costs}
    enemy = "K" if side == "Y" else "Y"
    enemy_w_production = new_totals[enemy]["W"] - old_totals[enemy]["W"] + casualties["W"]
    if enemy_w_production < 0:
        raise ValueError("Inconsistent one-for-one W combat")
    # Adding the same W casualties to each side is exact for this ruleset.
    enemy_w_cost = unit_cost(state_from_observation(before, bases, config), enemy, "W")
    return {
        "production": production, "production_resource_cost": sum(production[k] * costs[k] for k in costs),
        "unit_costs": costs, "casualties": casualties, "casualty_cells": losses,
        "enemy_w_production_inferred": enemy_w_production,
        "enemy_w_unit_cost": enemy_w_cost,
    }


def analyze(path):
    replay = json.loads(path.read_text())
    turns = replay["turns"]
    side = replay["side"]
    enemy = "K" if side == "Y" else "Y"
    config = json.loads((SDK / "config/balance.json").read_text())
    bases = infer_bases(replay)
    retrospective = {b["id"]: b["score"] for turn in turns
                     for b in turn["observation"]["buildings"] if "score" in b}
    retrospective = mirrored_scores(turns[0]["observation"]["buildings"], retrospective)
    if len(retrospective) != len(turns[0]["observation"]["buildings"]):
        raise ValueError("Final scores are not fully reconstructible")
    records = []
    occupation = {t: 0 for t in ("Y", "K")}
    previous_owners = {b["id"]: b["owner"] for b in turns[0]["observation"]["buildings"]}
    production = Counter()
    losses = Counter()
    total_enemy_w = 0
    total_spending = 0
    economic = {t: Counter() for t in ("Y", "K")}
    transition_checks = 0
    for i, turn in enumerate(turns):
        obs = turn["observation"]
        assert turn["turn"] == obs["turn"] == turn["turnIndex"] == i
        buildings = obs["buildings"]
        observed_known = {b["id"]: b["score"] for b in buildings if "score" in b}
        legal_known = mirrored_scores(buildings, observed_known)
        retrospective_totals = score_totals(buildings, retrospective)
        changes = []
        for b in buildings:
            old = previous_owners[b["id"]]
            if old != b["owner"]:
                changes.append({"id": b["id"], "type": b["type"], "x": b["x"], "y": b["y"],
                                "from": old, "to": b["owner"], "score_retrospective": retrospective[b["id"]]})
            previous_owners[b["id"]] = b["owner"]
        if i:
            for t in occupation:
                occupation[t] += retrospective_totals[t]
            assert obs["scores"][side] == retrospective_totals[side]
            assert obs["occTurns"][side] == occupation[side]
        row = {
            "turn": i, "observed_scores": obs["scores"],
            "legal_scores_as_of_turn": score_totals(buildings, legal_known),
            "retrospective_scores": retrospective_totals,
            "units": unit_totals(obs["units"]), "resources": obs["resources"],
            "building_counts": {t: dict(Counter(b["type"] for b in buildings if b["owner"] == t))
                                for t in ("Y", "K")},
            "ownership_changes": changes, "events": obs["events"],
            "response_ms": obs.get("myResponseMs"),
        }
        if i:
            derived = own_transition(turns[i - 1], turn, bases, config, side)
            row["own_transition"] = derived
            transition_checks += 1
            production.update(derived["production"])
            losses.update(derived["casualties"])
            total_enemy_w += derived["enemy_w_production_inferred"]
            total_spending += derived["production_resource_cost"]
            before = turns[i - 1]["observation"]["buildings"]
            for t in (side, enemy):
                economic[t]["turns_with_eng_at_production"] += any(b["type"] == "ENG" and b["owner"] == t for b in before)
                economic[t]["turns_with_hospital_at_production"] += any(b["type"] == "HOSPITAL" and b["owner"] == t for b in before)
                economic[t]["hall_count_sum_at_turn_start"] += sum(b["type"] == "HALL" and b["owner"] == t for b in before)
        records.append(row)
    final = records[-1]
    responses = sorted(r["response_ms"] for r in records if r["response_ms"] is not None)
    first_full_information_turn = next((r["turn"] for r in records
        if all(r["legal_scores_as_of_turn"][t] is not None for t in ("Y", "K", "N"))), None)
    our_leads = [r["turn"] for r in records if r["retrospective_scores"][side] > r["retrospective_scores"][enemy]]
    summary = {
        "source": str(path.relative_to(ROOT)), "sha256": digest(path),
        **{k: replay[k] for k in ("evaluationId", "gameId", "seriesId", "teamId", "side", "rulesetVersion", "protocolVersion", "schemaVersion", "result")},
        "turn_count": final["turn"], "our_result": "win" if replay["result"]["winner"] == side else "loss",
        "final_observed_scores": final["observed_scores"],
        "final_scores_reconstructed": final["retrospective_scores"],
        "final_occupation_reconstructed": occupation,
        "final_units": final["units"],
        "first_turn_with_all_building_scores_legally_inferable": first_full_information_turn,
        "last_turn_our_score_strictly_led": max(our_leads, default=None),
        "response_ms": {"max": max(responses), "mean": sum(responses) / len(responses),
                        "p95_nearest_rank": responses[(95 * len(responses) + 99) // 100 - 1],
                        "at_least_160ms_count": sum(v >= 160 for v in responses)},
        "command_status_counts": dict(Counter(t["command"]["status"] for t in turns if "command" in t)),
        "our_production": dict(production), "our_casualties": dict(losses),
        "our_production_resource_spend": total_spending,
        "enemy_w_production_inferred_from_equal_w_losses": total_enemy_w,
        "economy": economic, "own_spawn_move_transitions_checked": transition_checks,
        "submission_link": {"status": "not_present_in_replay", "zip_hash": None},
        "opponent_identity": None,
    }
    assert production["W"] - total_enemy_w == final["units"][side]["W"] - final["units"][enemy]["W"]
    return {"summary": summary, "turns": records}


def watch_defense_probe(path):
    """A local 160th-turn probe, not a reconstruction of unknown enemy orders."""
    replay = json.loads(path.read_text())
    before = replay["turns"][159]["observation"]
    after = replay["turns"][160]["observation"]
    config = json.loads((SDK / "config/balance.json").read_text())
    state = state_from_observation(before, infer_bases(replay), config)
    watch = next(b for b in state.buildings.values() if b.pos == (7, 11))
    assert (watch.id, watch.owner, watch.score) == (13, "Y", 4)
    local_units = {(6, 11, "Y", "F"): 1, (7, 11, "Y", "W"): 3,
                   (7, 12, "K", "F"): 1, (8, 11, "K", "W"): 3}
    assert all(state.units.get(key) == n for key, n in local_units.items())
    state.units = local_units
    enemy = ["MOVE 8 11 W 3 L", "MOVE 7 12 F 1 U"]
    cases = {
        "recorded_local_own_action": ["MOVE 7 11 W 1 D", "MOVE 7 11 W 2 D"],
        "hold_three_warriors_only": [],
        "hold_warriors_and_contest_with_adjacent_flag": ["MOVE 6 11 F 1 R"],
    }
    outcomes = {}
    for name, commands in cases.items():
        result, _ = run_turn(state, parse_commands(commands), parse_commands(enemy))
        outcomes[name] = {"own_commands": commands, "watch_owner": result.buildings[13].owner,
                          "watch_units": [[t, k, n] for (x, y, t, k), n in sorted(result.units.items())
                                          if (x, y) == (7, 11)]}
    baseline = outcomes["recorded_local_own_action"]
    actual_watch = [[t, k, n] for t, k, x, y, n in after["units"] if (x, y) == (7, 11)]
    assert sorted(baseline["watch_units"]) == sorted(actual_watch)
    assert baseline["watch_owner"] == after["buildings"][13]["owner"]
    return {
        "source": str(path.relative_to(ROOT)), "turn": 160, "building_id": 13,
        "building_score": 4, "opponent_local_commands_assumed": enemy,
        "scope": "Isolated local actors from the actual turn-159 observation, with a legal opponent move consistent with actual turn-160 units at this building. Other units/commands are omitted. Only this building's outcome is asserted; no full-game counterfactual or win is claimed.",
        "outcomes": outcomes,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=ROOT / "artifacts/firstround_results")
    parser.add_argument("--output", type=Path, default=ROOT / "records/official/round1/analysis.json")
    args = parser.parse_args()
    paths = sorted(args.input.resolve().glob("*.json"))
    matches = [analyze(p) for p in paths]
    files = [Path(__file__), SDK / "engine/pipeline.py", SDK / "engine/state.py",
             SDK / "runner/protocol.py", SDK / "config/balance.json", SDK / "docs/rulebook.md"]
    result = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "analysis_sources": {str(p.relative_to(ROOT)): digest(p) for p in files},
        "engine_game_commit": json.loads((SDK / "docs/platform-sdk-provenance.json").read_text())["gameCommit"],
        "command": "python3 experiments/analyze_official_round1.py",
        "scope": {
            "match_count": len(matches), "complete_round": "unverified_from_files_alone",
            "observations": "own participant view; public units/resources/ownership; hidden opponent score fields may be null",
            "score_reconstruction": "retrospective building scores plus exact 180-degree symmetric pairs; legal per-turn estimates stored separately",
            "transition_verification": "own spawn/move stages only; opponent commands absent; not full official game reproduction",
            "counterfactual": "no fixed-opponent-command one-turn counterfactual claimed",
        },
        "matches": matches,
        "local_counterfactuals": [watch_defense_probe(p) for p in paths
            if json.loads(p.read_text())["gameId"] == "rolling-game-805c50c9a490f1c11b69ad06d37d8a66ff8a012f4ede324c829038c68ea5fb4e"],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    for match in matches:
        s = match["summary"]
        print(Path(s["source"]).name, s["our_result"], s["turn_count"], s["final_scores_reconstructed"],
              "production", s["our_production"], "enemy W", s["enemy_w_production_inferred_from_equal_w_losses"],
              "casualties", s["our_casualties"], "economy", s["economy"])


if __name__ == "__main__":
    main()
