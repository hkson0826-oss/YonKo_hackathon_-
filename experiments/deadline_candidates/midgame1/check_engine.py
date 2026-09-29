"""Verify the joint hold/reinforcement counterexample with the official engine."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "yk-development-tools"))
from engine.config import load_config
from engine.pipeline import run_turn
from engine.state import Building, new_game
from runner.protocol import parse_commands

state = new_game(load_config(), buildings=[
    Building(0, 7, 7, "ENG", 2, "Y", 2),
    Building(1, 6, 7, "HOSPITAL", 2, "Y", 2),
    Building(2, 0, 0, "WATCH", 2, "Y", 2),
    Building(3, 14, 14, "WATCH", 2, "K", 2),
], resources={"Y": 0, "K": 0})
for team, kind, x, y, count in [
    ("Y", "F", 7, 7, 1), ("Y", "W", 6, 7, 3), ("Y", "W", 8, 7, 3),
    ("K", "F", 7, 6, 1), ("K", "W", 7, 8, 5),
]:
    state.add_unit(x, y, team, kind, count)
enemy = parse_commands(["MOVE 7 6 F 1 D", "MOVE 7 8 W 5 U"])
cases = {
    "joint": (["MOVE 6 7 W 3 R", "MOVE 8 7 W 2 L", "MOVE 8 7 W 1 R"], "Y"),
    "only_flag": (["MOVE 6 7 W 3 L", "MOVE 8 7 W 3 R"], "K"),
    "only_w": (["MOVE 7 7 F 1 U", "MOVE 6 7 W 3 R", "MOVE 8 7 W 2 L", "MOVE 8 7 W 1 R"], "N"),
}
for name, (commands, expected) in cases.items():
    after, _ = run_turn(state, parse_commands(commands), enemy)
    assert after.buildings[0].owner == expected, (name, after.buildings[0].owner)
    print(name, expected)
