"""Audit deterministic win/loss reversals for the frozen warrior-reserve candidate."""
from __future__ import annotations

import argparse
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "yk-development-tools"))
from engine.commands import Move, Move2, Spawn, Tele
from engine.pipeline import run_turn, step_combat, step_income, step_move, step_spawn, unit_cost
from mapgen import generate, to_state
from runner.protocol import parse_commands, serialize_turn
from runner.replay import snapshot

CANONICAL = "records/league/loop3-iteration2/runs/development"
CANDIDATE = "f3_v2_warrior_reserve"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def key(row):
    return row["map_seed"], row["opponent"], row["team"]


def select(rows):
    assert len(rows) == 2560 and len({r["job_id"] for r in rows}) == 2560
    assert all(r["status"] == "complete" and not r["forfeit"] for r in rows)
    baseline = {key(r): r for r in rows if r["candidate"] == "v3"}
    choices = []
    for kind in ("gain", "regression"):
        pool = []
        for row in rows:
            if row["candidate"] != CANDIDATE:
                continue
            old = baseline[key(row)]
            gain = row["win"] and not old["win"] and not old["draw"]
            loss = old["win"] and not row["win"] and not row["draw"]
            if (kind == "gain" and gain) or (kind == "regression" and loss):
                pool.append((row, old, row["score_margin"] - old["score_margin"]))
        pool.sort(key=lambda pair: ((-pair[2] if kind == "gain" else pair[2]), *key(pair[0])))
        row, old, delta = pool[0]
        choices.append(dict(kind=kind, eligible_pairs=len(pool), delta_margin=delta,
                            candidate=row, baseline=old))
    return choices


def totals(state, team):
    return {k: sum(n for (_, _, t, u), n in state.units.items() if t == team and u == k) for k in "FWS"}


def scores(state):
    return {t: sum(b.score for b in state.buildings.values() if b.owner == t) for t in "YK"}


def phases(state, commands):
    phase = state.clone()
    phase.turn += 1
    for b in phase.buildings.values():
        if b.owner == "N" and b.stage == 1:
            b.stage = 0
    step_spawn(phase, {t: [c for c in commands[t] if isinstance(c, Spawn)] for t in "YK"})
    spawned = phase.clone()
    step_move(phase, {t: [c for c in commands[t] if isinstance(c, (Move, Move2, Tele))] for t in "YK"})
    landed = phase.clone()
    step_combat(phase)
    hall = {t: sum(b.owner == t and b.btype == "HALL" for b in phase.buildings.values()) for t in "YK"}
    before = dict(phase.resources)
    step_income(phase)
    return spawned, landed, hall, {t: phase.resources[t] - before[t] for t in "YK"}


def replay_case(path, row):
    replay = json.load(gzip.open(path, "rt"))
    assert replay["seed"] == row["map_seed"] and replay["result"] == row["result"]
    state = to_state(generate(replay["seed"], replay["config"]))
    states = [state]
    history = []
    for number, frame in enumerate(replay["turns"], 1):
        assert frame["turn"] == number
        commands = {t: parse_commands(frame["commands"][t]) for t in "YK"}
        assert all(len(commands[t]) == len(frame["commands"][t]) for t in "YK")
        spawned, _, hall, income = phases(state, commands)
        after, result = run_turn(state, commands["Y"], commands["K"])
        assert snapshot(after) == frame["state"]
        history.append({t: dict(
            eng=int(unit_cost(state, t, "W") < state.config["units"]["W"]["cost"]),
            hall=hall[t], income=income[t],
            production={k: totals(spawned, t)[k] - totals(state, t)[k] for k in "FWS"},
            deaths={k: totals(spawned, t)[k] - totals(after, t)[k] for k in "FWS"}) for t in "YK"})
        states.append(after)
        state = after
    assert all(result[k] == row["result"][k] for k in ("winner", "reason", "score", "turns"))
    return replay, states, history


def economy(history, team, limit):
    selected = [h[team] for h in history[:limit]]
    out = {k: sum(h[k] for h in selected) for k in ("eng", "hall", "income")}
    for metric in ("production", "deaths"):
        out[metric] = {k: sum(h[metric][k] for h in selected) for k in "FWS"}
    return out


def movement(lines):
    counts = Counter()
    for command in parse_commands(lines):
        if isinstance(command, Move):
            counts[(command.x, command.y, command.kind, command.direction)] += command.count
        elif isinstance(command, Tele):
            counts[(command.x, command.y, command.kind, f"TELE:{command.tx},{command.ty}")] += command.count
        elif isinstance(command, Move2):
            counts[(command.x, command.y, "S", command.dir1 + command.dir2)] += command.count
    return counts


def analyze_pair(arena, choice):
    replays, states, histories = {}, {}, {}
    provenance = {}
    for role in ("candidate", "baseline"):
        row = choice[role]
        path = arena / row["replay"]
        replays[role], states[role], histories[role] = replay_case(path, row)
        provenance[role] = {k: row[k] for k in ("candidate", "opponent", "map_seed", "team", "job_id", "result")}
        provenance[role].update(path=f"{CANONICAL}/{row['replay']}", sha256=sha(path), verified_frames=len(replays[role]["turns"]))
    own = choice["candidate"]["team"]
    enemy = "K" if own == "Y" else "Y"
    a, b = replays["candidate"], replays["baseline"]
    first_text = next(i + 1 for i, (x, y) in enumerate(zip(a["turns"], b["turns"])) if x["commands"][own] != y["commands"][own])
    turn = next(i + 1 for i, (x, y) in enumerate(zip(a["turns"], b["turns"])) if x["state"] != y["state"])
    before = states["candidate"][turn - 1]
    assert snapshot(before) == snapshot(states["baseline"][turn - 1])
    frames = {role: replays[role]["turns"][turn - 1] for role in replays}
    assert frames["candidate"]["commands"][enemy] == frames["baseline"]["commands"][enemy]
    moves = {role: movement(frames[role]["commands"][own]) for role in frames}
    changed = sorted({(x, y) for x, y, kind, direction in set(moves["candidate"]) | set(moves["baseline"])
                      if moves["candidate"][(x, y, kind, direction)] != moves["baseline"][(x, y, kind, direction)]})
    origins = []
    for x, y in changed:
        building = before.building_at(x, y)
        entry = dict(position=[x, y], building=None if building is None else dict(id=building.id, type=building.btype, owner=building.owner,
                     visible_score=building.score if building.id in before.revealed[own] else -1), before={t: {k: before.get_unit(x,y,t,k) for k in "FW"} for t in "YK"})
        for role, frame in frames.items():
            commands = {t: parse_commands(frame["commands"][t]) for t in "YK"}
            spawned, landed, _, _ = phases(before, commands)
            outgoing = {k: sum(c.count for c in commands[own] if isinstance(c, (Move, Move2, Tele)) and c.kind == k and (c.x,c.y) == (x,y)) for k in "FW"}
            stay = {k: spawned.get_unit(x,y,own,k)-outgoing[k] for k in "FW"}
            assert min(stay.values()) >= 0
            entry[role] = dict(outgoing=outgoing, stayed_at_origin=stay,
                               landed_before_combat={t:{k:landed.get_unit(x,y,t,k) for k in "FW"} for t in "YK"},
                               after_owner=None if building is None else states[role][turn].buildings[building.id].owner)
        origins.append(entry)
    # Replacing the own first action on the shared state reproduces both observed next states.
    fixed = parse_commands(frames["candidate"]["commands"][enemy])
    verified = {}
    for role, frame in frames.items():
        action = parse_commands(frame["commands"][own])
        after, _ = run_turn(before, action if own == "Y" else fixed, fixed if own == "Y" else action)
        verified[role] = snapshot(after) == frame["state"]
        assert verified[role]
    alternate_threat = []
    for entry in origins:
        if entry["candidate"]["stayed_at_origin"]["W"] <= entry["baseline"]["stayed_at_origin"]["W"]:
            continue
        x,y=entry["position"]
        for index,command in enumerate(fixed):
            if not isinstance(command,Move) or command.kind != "F" or abs(command.x-x)+abs(command.y-y) != 1:
                continue
            if before.get_unit(command.x,command.y,enemy,"F") < command.count:
                continue
            direction={(1,0):"R",(-1,0):"L",(0,1):"D",(0,-1):"U"}[(x-command.x,y-command.y)]
            if direction == command.direction:
                continue
            changed_enemy=list(fixed)
            changed_enemy[index]=Move(command.x,command.y,"F",command.count,direction)
            detail=dict(target=entry["position"],enemy_original_command=f"MOVE {command.x} {command.y} F {command.count} {command.direction}",
                        enemy_alternative_command=f"MOVE {command.x} {command.y} F {command.count} {direction}",results={})
            for role,frame in frames.items():
                action=parse_commands(frame["commands"][own])
                after,_=run_turn(before,action if own=="Y" else changed_enemy,changed_enemy if own=="Y" else action)
                detail["results"][role]=dict(score=scores(after),target_owner=after.building_at(x,y).owner,
                                              target_enemy_F=after.get_unit(x,y,enemy,"F"),own_units=totals(after,own))
            alternate_threat.append(detail)
            break
    tracked = sorted({e["building"]["id"] for e in origins if e["building"] is not None} |
                     {q.id for q in before.buildings.values() if q.btype in ("ENG", "HALL", "HOSPITAL")})
    owner_runs = {}
    for role in frames:
        owner_runs[role] = []
        for bid in tracked:
            info=before.buildings[bid]; runs=[]
            for i, state in enumerate(states[role]):
                owner=state.buildings[bid].owner
                if not runs or runs[-1]["owner"] != owner: runs.append(dict(start_turn=i,end_turn=i,owner=owner))
                else: runs[-1]["end_turn"]=i
            owner_runs[role].append(dict(id=bid,type=info.btype,position=list(info.pos),runs=runs))
    common=min(60,len(histories["candidate"]),len(histories["baseline"]))
    payload=serialize_turn(before,own,turn)
    return dict(kind=choice["kind"], eligible_pairs=choice["eligible_pairs"],delta_margin=choice["delta_margin"],provenance=provenance,
                first_text_difference_turn=first_text,first_physical_difference_turn=turn,legal_observation=payload,
                legal_observation_sha256=hashlib.sha256(payload.encode()).hexdigest(),prior_state_equal=True,opponent_commands_equal=True,
                commands={r:frames[r]["commands"] for r in frames},changed_origins=origins,
                first_after={r:dict(scores=scores(states[r][turn]),units={t:totals(states[r][turn],t) for t in "YK"},resources=states[r][turn].resources) for r in frames},
                fixed_opponent_one_step_reproduces_both=verified,
                hypothetical_adjacent_enemy_F_attack=alternate_threat,
                common_economy_through_turn=common,economy={r:{t:economy(histories[r],t,common) for t in "YK"} for r in frames},
                timeline={r:[dict(turn=i,score=scores(states[r][i]),own_units=totals(states[r][i],own)) for i in (20,40,60,80,100,120) if i<len(states[r])] for r in frames},
                building_ownership=owner_runs)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arena",type=Path,default=ROOT/CANONICAL)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    path=args.arena/"results.jsonl"
    rows=[json.loads(line) for line in path.read_text().splitlines()]
    selected=select(rows)
    result=dict(schema=1,results_path=f"{CANONICAL}/results.jsonl",results_sha256=sha(path),results_rows=len(rows),
                selection_rule="Within strict loss-to-win and win-to-loss pairs, maximize absolute candidate-minus-v3 final score-margin change; ties map_seed, opponent, team ascending.",
                retrieval_note="Completed development copied read-only before final canonical archive retrieval; canonical SHA comparison remains root's responsibility.",
                scope="Outcome-selected development diagnostics; official transitions and one-turn action effects, not first-action attribution of whole-match outcome.",
                script_sha256=sha(Path(__file__)),engine_sha256={str(p.relative_to(ROOT)):sha(p) for p in [ROOT/"yk-development-tools/engine/pipeline.py",ROOT/"yk-development-tools/runner/protocol.py"]},
                cases=[analyze_pair(args.arena,c) for c in selected])
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({"verified_frames":sum(p["verified_frames"] for c in result["cases"] for p in c["provenance"].values()),"cases":[{k:c[k] for k in ("kind","first_text_difference_turn","first_physical_difference_turn","delta_margin")} for c in result["cases"]]}))


if __name__ == "__main__":
    main()
