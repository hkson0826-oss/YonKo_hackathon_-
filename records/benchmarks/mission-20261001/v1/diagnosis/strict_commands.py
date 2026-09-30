"""Frozen audit_commands from tests/test_mission_scheduler.py.

Imports use the arena SDK already selected by counterfactuals.py. The function is
preserved verbatim so this diagnosis does not depend on later test edits.
"""
from engine.commands import DIRECTIONS, Move, Move2, Priority, Spawn, Tele
from engine.pipeline import step_spawn, unit_cost
from runner.protocol import parse_commands

AUDIT_SOURCE_SHA256 = "69627837d4d291277af5a6b1f993323698916d56dd1ab44cced0886ed01d8805"
AUDIT_FUNCTION_SHA256 = "2668d8ebfc3f884fe0a7dd0a653d6f83a59d03ae6a711d778dc8b9bdf52bf743"

def audit_commands(state, side, lines):
    """Check requested counts before the official engine could silently clip them."""
    commands = parse_commands(lines)
    nonempty = [line for line in lines if line.strip()]
    if len(commands) != len(nonempty):
        raise AssertionError(f'Parser rejected output: {lines}')
    output = '\n'.join([*lines, 'END', ''])
    if len(output.encode()) > 65536 or len(lines) + 1 > 4096:
        raise AssertionError('Output exceeds the per-turn limit')
    if any(len((line + '\n').encode()) > 1024 for line in [*lines, 'END']):
        raise AssertionError('Output exceeds the per-line limit')
    produced = state.clone()
    for command in commands:
        if not isinstance(command, Spawn):
            continue
        if command.x is not None:
            site = state.building_at(command.x, command.y)
            if not (site and site.btype == 'HOSPITAL' and site.owner == side):
                raise AssertionError(f'Invalid explicit spawn site: {command}')
        cost = unit_cost(produced, side, command.kind)
        if command.count * cost > produced.resources[side]:
            raise AssertionError(f'Spawn budget clipped: {command}')
        step_spawn(produced, {team: [command] if team == side else [] for team in 'YK'})
    stock = dict(produced.units)
    tele_used = 0
    for command in commands:
        if isinstance(command, (Spawn, Priority)):
            continue
        kind = 'S' if isinstance(command, Move2) else command.kind
        if isinstance(command, Move):
            dx, dy = DIRECTIONS[command.direction]
            if not state.is_passable(command.x + dx, command.y + dy):
                raise AssertionError(f'Blocked destination: {command}')
        elif isinstance(command, Move2):
            dx, dy = DIRECTIONS[command.dir1]
            mx, my = command.x + dx, command.y + dy
            dx, dy = DIRECTIONS[command.dir2]
            if not state.is_passable(mx, my) or not state.is_passable(mx + dx, my + dy):
                raise AssertionError(f'Blocked scout path: {command}')
        elif isinstance(command, Tele):
            src = state.building_at(command.x, command.y)
            dst = state.building_at(command.tx, command.ty)
            if not (src and dst and src.id != dst.id and src.btype == dst.btype == 'STATION'
                    and src.owner == dst.owner == side):
                raise AssertionError(f'Invalid TELE ownership: {command}')
            tele_used += 1
            if tele_used > state.config['tele']['per_turn'] or command.count > state.config['tele']['max_units']:
                raise AssertionError(f'TELE capacity exceeded: {command}')
        else:
            raise AssertionError(f'Unexpected command: {command}')
        key = command.x, command.y, side, kind
        if stock.get(key, 0) < command.count:
            raise AssertionError(f'Departure stock clipped: {command}, available={stock.get(key, 0)}')
        stock[key] -= command.count
    return commands
