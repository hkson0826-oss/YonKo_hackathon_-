"""Compare the C++ lookahead transition with the unmodified Python engine."""
import json
from pathlib import Path
import random
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "yk-development-tools"))
from engine.config import load_config
from engine.commands import Move, Move2, Priority, Spawn, Tele, DIRECTIONS
from engine.pipeline import run_turn
from mapgen import generate, to_state
from runner.protocol import serialize_init


def encode(state, commands):
    lines = [serialize_init(state, "Y").rstrip(),
             f"{state.turn} {state.resources['Y']} {state.resources['K']} "
             f"{state.occupation_score_turns['Y']} {state.occupation_score_turns['K']}"]
    for b in state.sorted_buildings():
        claimed = state.depot_claimed.get(b.id, set())
        lines.append(" ".join(map(str, [(-1 if b.owner == "N" else "YK".index(b.owner)), b.stage, b.score,
                                       int("Y" in claimed), int("K" in claimed),
                                       int(b.id in state.revealed['Y']), int(b.id in state.revealed['K'])])))
    lines.append(str(len(state.units)))
    for (x, y, t, k), n in state.units.items():
        lines.append(f"{'YK'.index(t)} {'FWS'.index(k)} {x+15*y} {n}")
    ids = {b.id: i for i, b in enumerate(state.sorted_buildings())}
    for t in "YK":
        spawns, moves, priority = [], [], []
        for c in commands[t]:
            if isinstance(c, Spawn):
                x, y = state.bases[t] if c.x is None else (c.x, c.y)
                spawns.append(f"{'FWS'.index(c.kind)} {x+15*y} {c.count}")
            elif isinstance(c, Move):
                dx, dy = DIRECTIONS[c.direction]
                moves.append(f"{'FWS'.index(c.kind)} {c.x+15*c.y} {c.x+dx+15*(c.y+dy)} {c.count} 0")
            elif isinstance(c, Move2):
                dx1, dy1 = DIRECTIONS[c.dir1]
                dx2, dy2 = DIRECTIONS[c.dir2]
                moves.append(f"2 {c.x+15*c.y} {c.x+dx1+dx2+15*(c.y+dy1+dy2)} {c.count} 0")
            elif isinstance(c, Tele):
                moves.append(f"{'FWS'.index(c.kind)} {c.x+15*c.y} {c.tx+15*c.ty} {c.count} 1")
            elif isinstance(c, Priority):
                priority = [str(ids[state.building_at(x,y).id]) for x,y in c.coords if state.building_at(x,y)]
        lines.append(f"{len(spawns)} {len(moves)} {len(priority)}")
        lines.extend(spawns + moves)
        lines.append(" ".join(priority))
    return "\n".join(lines)+"\n"


def expected(state):
    lines = [[state.turn, state.resources['Y'], state.resources['K'],
              state.occupation_score_turns['Y'], state.occupation_score_turns['K']]]
    for b in state.sorted_buildings():
        claimed = state.depot_claimed.get(b.id, set())
        lines.append([(-1 if b.owner == "N" else "YK".index(b.owner)), b.stage,
                      int('Y' in claimed), int('K' in claimed),
                      int(b.id in state.revealed['Y']), int(b.id in state.revealed['K'])])
    units = [["YK".index(t), "FWS".index(k), x+15*y, n] for (x,y,t,k),n in state.units.items()]
    return lines + sorted(units)


class SimulatorTest(unittest.TestCase):
    def test_random_transitions(self):
        rng = random.Random(276091)
        for case in range(300):
            s = to_state(generate(case % 40, load_config()))
            s.turn = rng.randrange(160)
            for t in "YK":
                s.resources[t] = rng.randrange(41)
                s.occupation_score_turns[t] = rng.randrange(3000)
            for b in s.sorted_buildings():
                b.owner = rng.choice("NYK")
                b.stage = 2 if b.owner != "N" else rng.randrange(2)
                for t in "YK":
                    if rng.random() < .5: s.revealed[t].add(b.id)
                    if b.btype == "DEPOT" and rng.random() < .5: s.depot_claimed.setdefault(b.id,set()).add(t)
                    if rng.random() < .6:
                        s.add_unit(b.x,b.y,t,"F",rng.randrange(1,4))
                        s.add_unit(b.x,b.y,t,"W",rng.randrange(1,10))
            cells = [(x,y) for y in range(15) for x in range(15) if s.is_passable(x,y)]
            for _ in range(50):
                x,y = rng.choice(cells)
                s.add_unit(x,y,rng.choice("YK"),rng.choice("FWS"),rng.randrange(1,15))
            commands = {t: [] for t in "YK"}
            for t in "YK":
                sources = [None] + [b.pos for b in s.sorted_buildings() if b.btype == "HOSPITAL" and b.owner == t]
                for _ in range(3):
                    p = rng.choice(sources)
                    commands[t].append(Spawn(rng.choice("FWS"),rng.randrange(1,10),*(p or (None,None))))
                for (x,y,team,k),n in list(s.units.items()):
                    if team != t: continue
                    ds = [d for d,(dx,dy) in DIRECTIONS.items() if s.is_passable(x+dx,y+dy)]
                    for _ in range(rng.randrange(3)):
                        if ds: commands[t].append(Move(x,y,k,rng.randrange(1,n+5),rng.choice(ds)))
                    if k == "S" and ds:
                        d1 = rng.choice(ds); dx,dy = DIRECTIONS[d1]
                        d2s = [d for d,(a,b) in DIRECTIONS.items() if s.is_passable(x+dx+a,y+dy+b)]
                        if d2s: commands[t].append(Move2(x,y,n,d1,rng.choice(d2s)))
                stations = [b.pos for b in s.sorted_buildings() if b.btype == "STATION"]
                for _ in range(3):
                    x,y = rng.choice(stations); tx,ty = rng.choice(stations)
                    commands[t].append(Tele(x,y,rng.choice("FWS"),rng.randrange(1,10),tx,ty))
                order = s.sorted_buildings(); rng.shuffle(order)
                if rng.random() < .8: commands[t].append(Priority([b.pos for b in order[:rng.randrange(18)]]))
            result, _ = run_turn(s,commands['Y'],commands['K'])
            process = subprocess.run([str(ROOT/'artifacts/simulator_bridge')],input=encode(s,commands),
                                     text=True,capture_output=True,check=True)
            actual = [[int(v) for v in line.split()] for line in process.stdout.splitlines()]
            with self.subTest(case=case): self.assertEqual(expected(result),actual)


if __name__ == "__main__":
    unittest.main()
