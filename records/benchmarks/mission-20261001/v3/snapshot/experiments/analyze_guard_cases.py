"""Audit two selected guard gains with fixed recorded opponent commands."""
import argparse
import json
from pathlib import Path

import analyze_gain_cases as gain
from engine.pipeline import run_turn
from mapgen import generate, to_state
from runner.protocol import parse_commands
from runner.replay import snapshot

FOLDER = gain.ROOT / "records/league/loop2-checkpoints/iteration2/guard-cases"


def audit():
    manifest = json.loads((FOLDER / "manifest.json").read_text())
    gain.REPLAYS = FOLDER
    cases, raw = [], {}
    for row in manifest["rows"]:
        checked, replay, initial = gain.check_case(row["map_seed"], row["candidate"], row["job_id"],
                                                   manifest["sha256"][row["job_id"]])
        checked["opponent"] = row["opponent"]
        cases.append(checked)
        raw[row["map_seed"], row["candidate"]] = replay, initial
    pairs = []
    for seed in (7102, 7100):
        guard, initial = raw[seed, "q_v2_window_guard"]
        window, _ = raw[seed, "q_threat_window"]
        pair = gain.first_divergence(guard, window, initial)
        divergence = pair["first_own_command_difference"]
        if not divergence["preceding_snapshot_equal"] or not divergence["opponent_commands_equal"]:
            raise ValueError("The first-divergence experiment needs identical initial state and opponent action")
        turn = divergence["turn"]
        state = to_state(generate(seed, window["config"]))
        for frame in window["turns"][:turn - 1]:
            state, _ = run_turn(state, parse_commands(frame["commands"]["Y"]),
                                parse_commands(frame["commands"]["K"]))
        actual = window["turns"][turn - 1]
        original = actual["commands"]["Y"]
        scenarios = {"original_window": original, "recorded_guard": guard["turns"][turn - 1]["commands"]["Y"]}
        if seed == 7102:
            flag_move = "MOVE 7 7 F 1 L"
            warrior_move = "MOVE 6 7 W 1 U"
            if original.count(flag_move) != 1 or original.count(warrior_move) != 1:
                raise ValueError("7102 counterfactual command anchor changed")
            scenarios["F_hold_only"] = [c for c in original if c != flag_move]
            scenarios["W_arrival_only"] = [c for c in original if c != warrior_move] + ["MOVE 6 7 W 1 R"]
            scenarios["F_hold_and_W_arrival"] = [c for c in original if c not in (flag_move, warrior_move)] + ["MOVE 6 7 W 1 R"]
            bid = 0
        else:
            flag_move = "MOVE 3 3 F 1 U"
            if original.count(flag_move) != 1:
                raise ValueError("7100 counterfactual command anchor changed")
            scenarios["F_hold_only"] = [c for c in original if c != flag_move]
            bid = 5
        building = state.buildings[bid]
        pair["counterfactual_scope"] = "One turn from the identical observed state; all recorded K commands fixed. No claim about subsequent responses or full-match causality."
        pair["local_before"] = {
            "building": {"id": bid, "position": [building.x, building.y], "type": building.btype,
                         "owner": building.owner, "score": building.score, "known_to_Y": bid in state.revealed["Y"]},
            "units_within_one_manhattan_step": [u for u in snapshot(state)["units"]
                                                if abs(u[2] - building.x) + abs(u[3] - building.y) <= 1],
        }
        counterfactuals = {}
        for label, lines in scenarios.items():
            after, result = run_turn(state, parse_commands(lines), parse_commands(actual["commands"]["K"]))
            if label == "original_window" and snapshot(after) != actual["state"]:
                raise ValueError("Original transition mismatch")
            if label == "recorded_guard" and snapshot(after) != guard["turns"][turn - 1]["state"]:
                raise ValueError("Guard transition mismatch")
            counterfactuals[label] = {
                "score": gain.scores(after), "building_owner": after.buildings[bid].owner,
                "local_units": [u for u in snapshot(after)["units"] if (u[2], u[3]) == building.pos],
                "matches_recorded_guard_snapshot": snapshot(after) == guard["turns"][turn - 1]["state"],
                "result": result,
            }
        pair["counterfactuals"] = counterfactuals
        if seed == 7102:
            hypothetical = [line for line in actual["commands"]["K"]
                            if not (line.startswith("MOVE 8 7 W ") or line.startswith("MOVE 8 7 F "))]
            hypothetical.extend(["MOVE 8 7 W 1 L", "MOVE 8 7 F 1 L"])
        else:
            hypothetical = [line for line in actual["commands"]["K"] if not line.startswith("MOVE 3 2 F ")]
            hypothetical.append("MOVE 3 2 F 1 D")
        pair["hypothetical_attack_scope"] = "A legal alternative K attack from existing adjacent units, NOT the recorded K action. It demonstrates protection against a possible attack, not a realized save."
        pair["hypothetical_K_commands"] = hypothetical
        pair["hypothetical_attack_results"] = {}
        for label, lines in scenarios.items():
            after, _ = run_turn(state, parse_commands(lines), parse_commands(hypothetical))
            pair["hypothetical_attack_results"][label] = {
                "building_owner": after.buildings[bid].owner, "score": gain.scores(after),
                "local_units": [u for u in snapshot(after)["units"] if (u[2], u[3]) == building.pos],
            }
        pairs.append(pair)
    return {"schema": 1, "source_manifest_sha256": gain.sha(FOLDER / "manifest.json"),
            "script_sha256": gain.sha(Path(__file__)), "shared_audit_script_sha256": gain.sha(Path(gain.__file__)),
            "verified_frames": sum(case["verified_frames"] for case in cases),
            "selection": "Two hand-selected development gains after completed results; no population inference from these cases.",
            "cases": cases, "pairs": pairs}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(f"Verified {result['verified_frames']} transitions and {len(result['pairs'])} paired first-divergence cases.")


if __name__ == "__main__":
    main()
