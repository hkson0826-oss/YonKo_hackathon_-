"""Exercise the candidate through its public protocol and the official engine.

Tactical assertions are explicit minimum behavior contracts, not a claim that a
stationary opponent predicts tournament play. No candidate helpers are imported.
"""
from pathlib import Path
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'yk-development-tools'))
sys.path.insert(0, str(ROOT / 'tests'))
from engine.commands import DIRECTIONS, Move, Move2, Priority, Spawn, Tele
from engine.pipeline import run_turn, step_combat, step_move, step_spawn, unit_cost
from mapgen import generate, to_state
from engine.config import load_config
from engine.state import new_game
from runner.bots import SubprocessBot
from runner.protocol import parse_commands, serialize_init, serialize_turn
from mission_scheduler_cases import (HALL_REPLAY, OFFICIAL_REPLAY, RENDEZVOUS_REPLAY,
                                     hall_history_before, official_history_before,
                                     rendezvous_history_before, state_from_observation, tactical_state)

SOURCE = Path(os.environ.get('MISSION_SCHEDULER_SOURCE', ROOT / 'experiments/mission_scheduler_20261001/main.cpp')).resolve()


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


def flags(state, side):
    return sum(count for (_, _, team, kind), count in state.units.items() if team == side and kind == 'F')


class MissionSchedulerProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not SOURCE.is_file():
            raise unittest.SkipTest(f'Candidate not written yet: {SOURCE}')
        cls.folder = tempfile.TemporaryDirectory(prefix='yk-mission-tests-')
        cls.binary = Path(cls.folder.name) / 'candidate'
        compiler = os.environ.get('CXX', 'g++')
        build = subprocess.run([compiler, '-std=c++20', '-O2', str(SOURCE), '-o', str(cls.binary)],
                               capture_output=True, text=True, timeout=120)
        if build.returncode:
            cls.folder.cleanup()
            raise AssertionError(f'Candidate failed compilation:\n{build.stderr}')
        cls.audit = {'source_sha256': hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
                     'compiler': compiler, 'observations': [], 'limitations': [
                         'Handcrafted and forced historical observations are development cases, not fresh maps.',
                         'A stationary-opponent counterfactual is not full match replay.',
                         'No candidate-private implementation helpers are used.']}

    @classmethod
    def tearDownClass(cls):
        destination = os.environ.get('MISSION_SCHEDULER_AUDIT')
        if destination:
            Path(destination).write_text(json.dumps(cls.audit, ensure_ascii=False, indent=2) + '\n')
        cls.folder.cleanup()

    def bot(self, state, side='Y'):
        command = shlex.quote(str(self.binary))
        if shutil.which('prlimit'):
            command = 'prlimit --as=402653184 -- ' + command
        bot = SubprocessBot(command)
        self.addCleanup(bot.close)
        bot.send_init(serialize_init(state, side))
        return bot

    def ask(self, bot, state, side='Y'):
        first = bot._first_turn
        raw, status = bot.play_turn(serialize_turn(state, side, state.turn + 1), 3.0 if first else .3)
        self.assertEqual(status, 'ok', f'Protocol failure on input TURN {state.turn + 1}')
        commands = audit_commands(state, side, raw)
        self.audit['observations'].append({'test': self.id(), 'turn': state.turn + 1, 'side': side,
                                          'raw': raw, 'max_response_ms_so_far': bot.max_turn_ms})
        return commands

    def test_opening_production_moves_in_its_birth_turn_on_both_sides(self):
        for side in 'YK':
            with self.subTest(side=side):
                state = to_state(generate(22110, load_config()))
                commands = self.ask(self.bot(state, side), state, side)
                spawned_flags = sum(c.count for c in commands if isinstance(c, Spawn) and c.kind == 'F')
                self.assertGreater(spawned_flags, 0)
                moved = state.clone()
                step_spawn(moved, {t: [c for c in commands if isinstance(c, Spawn)] if t == side else [] for t in 'YK'})
                step_move(moved, {t: [c for c in commands if isinstance(c, (Move, Move2, Tele))] if t == side else [] for t in 'YK'})
                bx, by = state.bases[side]
                self.assertLess(moved.get_unit(bx, by, side, 'F'), spawned_flags,
                                'Opening flags should use their legal production-turn move')

    def test_unescorted_flag_does_not_walk_into_visible_stationary_army(self):
        state = tactical_state()
        state.add_unit(6, 5, 'Y', 'F', 1)
        state.add_unit(7, 5, 'K', 'W', 100)
        commands = self.ask(self.bot(state), state)
        after, _ = run_turn(state, commands, [])
        self.assertEqual(flags(after, 'Y'), 1, 'Holding or another safe square is available')

    def test_equal_warrior_escort_keeps_flag_alive(self):
        state = tactical_state()
        state.add_unit(6, 5, 'Y', 'F', 1)
        state.add_unit(6, 5, 'Y', 'W', 3)
        state.add_unit(7, 5, 'K', 'F', 1)
        state.add_unit(7, 5, 'K', 'W', 3)
        commands = self.ask(self.bot(state), state)
        after, _ = run_turn(state, commands, [])
        self.assertEqual(flags(after, 'Y'), 1)

    def test_surplus_warrior_clears_defending_flag_in_one_turn(self):
        state = tactical_state(turn=160)
        state.add_unit(6, 5, 'Y', 'F', 1)
        state.add_unit(6, 5, 'Y', 'W', 4)
        state.add_unit(7, 5, 'K', 'F', 1)
        state.add_unit(7, 5, 'K', 'W', 3)
        commands = self.ask(self.bot(state), state)
        after, result = run_turn(state, commands, [])
        self.assertEqual(after.buildings[13].owner, 'Y',
                         'A final-turn +1 escort can take the defended 4-point building immediately')
        self.assertEqual(after.get_unit(7, 5, 'K', 'F'), 0)
        self.assertEqual(result['winner'], 'Y')

    def test_last_turn_neutralization_is_enough_to_win(self):
        state = tactical_state(turn=160)
        state.add_unit(6, 5, 'Y', 'F', 1)
        commands = self.ask(self.bot(state), state)
        after, result = run_turn(state, commands, [])
        self.assertEqual(after.buildings[13].owner, 'N')
        self.assertEqual(result['score'], {'Y': 3, 'K': 2})
        self.assertEqual(result['winner'], 'Y')

    def test_last_turn_new_flag_can_neutralize_adjacent_enemy_building(self):
        template = tactical_state(turn=160, resource=5)
        template.buildings[13].owner, template.buildings[13].stage = 'N', 0
        template.buildings[1].owner, template.buildings[1].stage = 'K', 2
        state = new_game(load_config(), buildings=template.sorted_buildings(),
                         bases={'Y': (0, 1), 'K': (14, 13)}, resources={'Y': 5, 'K': 0})
        state.turn = 159
        state.revealed = {side: set(state.buildings) for side in 'YK'}
        commands = self.ask(self.bot(state), state)
        after, result = run_turn(state, commands, [])
        self.assertEqual(after.buildings[1].owner, 'N',
                         'A final-turn F birth can move immediately and remove the enemy 2-point lead')
        self.assertEqual(result['score'], {'Y': 3, 'K': 2})
        self.assertEqual(result['winner'], 'Y')

    def test_shared_budget_and_departure_pools_with_two_hospitals_and_stations(self):
        state = tactical_state(resource=40)
        for building in state.sorted_buildings():
            if building.btype in ('ENG', 'HOSPITAL', 'STATION'):
                building.owner, building.stage = 'Y', 2
        for bid in (9, 11):
            building = state.buildings[bid]
            state.add_unit(building.x, building.y, 'Y', 'W', 8)
            state.add_unit(building.x, building.y, 'Y', 'F', 2)
        state.add_unit(6, 5, 'Y', 'F', 3)
        bot = self.bot(state)
        for _ in range(8):
            commands = self.ask(bot, state)
            state, result = run_turn(state, commands, [])
            if result:
                break

    def test_merged_flags_can_all_die_then_new_observation_has_no_stale_departures(self):
        state = tactical_state()
        state.add_unit(6, 5, 'Y', 'F', 3)
        for x, y in [(5, 5), (7, 5), (6, 4), (6, 6)]:
            state.add_unit(x, y, 'K', 'W', 100)
        bot = self.bot(state)
        commands = self.ask(bot, state)
        moved = state.clone()
        step_spawn(moved, {'Y': [c for c in commands if isinstance(c, Spawn)], 'K': []})
        step_move(moved, {'Y': [c for c in commands if isinstance(c, (Move, Move2, Tele))], 'K': []})
        # If any flags hold, one of four adjacent armies moves in. Departed flags
        # meet the other stationary armies. This is a legal adversarial response.
        destinations = []
        for c in commands:
            if isinstance(c, Move) and c.kind == 'F':
                dx, dy = DIRECTIONS[c.direction]
                destinations.append((c.x + dx, c.y + dy))
        enemy = []
        if moved.get_unit(6, 5, 'Y', 'F'):
            for x, y, direction in [(5, 5, 'R'), (7, 5, 'L'), (6, 4, 'D'), (6, 6, 'U')]:
                if (x, y) not in destinations:
                    enemy = [Move(x, y, 'W', 100, direction)]
                    break
        state, _ = run_turn(state, commands, enemy)
        self.assertEqual(flags(state, 'Y'), 0)
        for _ in range(4):
            commands = self.ask(bot, state)
            state, result = run_turn(state, commands, [])
            if result:
                break

    @unittest.skipUnless(RENDEZVOUS_REPLAY.is_file(), 'Archived rendezvous development replay is unavailable')
    def test_stationary_hospital_guard_is_cleared_after_delayed_escort_arrives(self):
        history, replay = rendezvous_history_before(13)
        state = history[0]
        bot = self.bot(state)
        matched = 0
        for index, state in enumerate(history[:-1]):
            commands = self.ask(bot, state)
            raw = self.audit['observations'][-1]['raw']
            matched += raw == replay['turns'][index]['commands']['Y']
        state = history[-1]
        self.assertEqual(state.get_unit(9, 3, 'Y', 'F'), 1)
        self.assertEqual(state.get_unit(7, 4, 'Y', 'W'), 3)
        self.assertEqual(state.get_unit(10, 3, 'K', 'W'), 1)
        target = state.building_at(10, 3)
        self.assertEqual(target.btype, 'HOSPITAL')
        self.assertNotIn(target.id, state.revealed['Y'])
        serialized = serialize_turn(state, 'Y', 13)
        self.assertIn(f'{target.id} 10 3 HOSPITAL N 0 -1', serialized)
        trace = {'source_replay_sha256': hashlib.sha256(RENDEZVOUS_REPLAY.read_bytes()).hexdigest(),
                 'branch_input_turn': 13, 'original_history_outputs_matched': matched,
                 'original_history_outputs_compared': len(history) - 1,
                 'opponent_assumption': 'No movement or production after original turn 12',
                 'information': 'Official serialize_turn filters all hidden building scores',
                 'turns': [], 'captured_turn': None}
        self.audit['rendezvous_case'] = trace
        for _ in range(6):
            commands = self.ask(bot, state)
            initial_flags = flags(state, 'Y')
            births = sum(c.count for c in commands if isinstance(c, Spawn) and c.kind == 'F')
            after, result = run_turn(state, commands, [])
            trace['turns'].append({'turn': after.turn, 'commands': self.audit['observations'][-1]['raw'],
                                   'target_owner': after.buildings[target.id].owner,
                                   'flags_before': initial_flags, 'flag_births': births,
                                   'flags_after': flags(after, 'Y'),
                                   'units_after': [[team, kind, x, y, count]
                                                   for (x, y, team, kind), count in sorted(after.units.items())]})
            self.assertEqual(flags(after, 'Y'), initial_flags + births,
                             'The escort repair must preserve existing flags against the stationary opponent')
            if after.buildings[target.id].owner == 'Y':
                trace['captured_turn'] = after.turn
                self.assertGreater(after.get_unit(10, 3, 'Y', 'F'), 0)
                break
            state = after
            self.assertIsNone(result, 'The counterfactual ended before the hospital mission could be checked')
        self.assertIsNotNone(trace['captured_turn'],
                             'The adjacent flag and nearby W3 should coordinate to take the W1-guarded hospital within six turns')

    @unittest.skipUnless(HALL_REPLAY.is_file(), 'Archived HALL defense development replay is unavailable')
    def test_visible_flag_raid_is_stopped_before_home_hall_is_lost(self):
        history, replay = hall_history_before(14)
        bot = self.bot(history[0], 'K')
        matched = 0
        for index, previous in enumerate(history[:-1]):
            self.ask(bot, previous, 'K')
            matched += self.audit['observations'][-1]['raw'] == replay['turns'][index]['commands']['K']
        state = history[-1]
        hall = state.building_at(12, 9)
        self.assertEqual((state.turn, hall.btype, hall.owner), (13, 'HALL', 'K'))
        self.assertEqual(state.get_unit(11, 7, 'Y', 'F'), 1)
        raid_position = (11, 7)
        route = [(11, 8), (11, 9), (12, 9)]
        trace = {'source_replay_sha256': hashlib.sha256(HALL_REPLAY.read_bytes()).hexdigest(),
                 'branch_input_turn': 14, 'enemy_flag_input_position': [11, 7],
                 'original_history_outputs_matched': matched,
                 'original_history_outputs_compared': len(history) - 1,
                 'opponent_assumption': 'Only the F at (11,7) follows D,D,R; no other movement or production. Dead F receives no later orders.',
                 'information': 'Forced historical states are serialized through the official hidden-score filter',
                 'turns': [], 'intercepted_turn': None}
        self.audit['hall_defense_case'] = trace
        for offset in range(5):
            commands = self.ask(bot, state, 'K')
            enemy_lines = []
            if offset < len(route) and state.get_unit(*raid_position, 'Y', 'F'):
                destination = route[offset]
                dx, dy = destination[0] - raid_position[0], destination[1] - raid_position[1]
                direction = next(name for name, vector in DIRECTIONS.items() if vector == (dx, dy))
                enemy_lines = [f'MOVE {raid_position[0]} {raid_position[1]} F 1 {direction}']
                raid_position = destination
            enemy = audit_commands(state, 'Y', enemy_lines)
            after, result = run_turn(state, enemy, commands)
            alive = after.get_unit(*raid_position, 'Y', 'F') > 0
            if not alive and trace['intercepted_turn'] is None:
                trace['intercepted_turn'] = after.turn
            trace['turns'].append({'turn': after.turn,
                                   'own_commands': self.audit['observations'][-1]['raw'],
                                   'enemy_commands': enemy_lines,
                                   'hall_owner': after.buildings[hall.id].owner,
                                   'raider_alive': alive,
                                   'units_after': [[team, kind, x, y, count]
                                                   for (x, y, team, kind), count in sorted(after.units.items())]})
            self.assertEqual(after.buildings[hall.id].owner, 'K',
                             f'Turn {after.turn}: a visible three-step unescorted raid must not neutralize the owned HALL')
            state = after
            self.assertIsNone(result, 'The counterfactual ended before the five-turn defense check')
        self.assertIsNotNone(trace['intercepted_turn'], 'The scripted attacker must be intercepted')
        self.assertLessEqual(trace['intercepted_turn'], 16,
                             'The raider reaches the HALL on turn 16 unless removed earlier')

    @unittest.skipUnless(OFFICIAL_REPLAY.is_file(), 'Latest official development replay is unavailable')
    def test_official_turn_29_has_no_flag_suicide_against_stationary_enemy(self):
        side, observations = official_history_before(29)
        state = state_from_observation(observations[0])
        bot = self.bot(state, side)
        commands = None
        for observation in observations:
            state = state_from_observation(observation)
            commands = self.ask(bot, state, side)
        self.assertEqual(state.turn + 1, 29)
        spawned = state.clone()
        step_spawn(spawned, {t: [c for c in commands if isinstance(c, Spawn)] if t == side else [] for t in 'YK'})
        before_combat = flags(spawned, side)
        after, _ = run_turn(state, commands if side == 'Y' else [], commands if side == 'K' else [])
        self.assertEqual(flags(after, side), before_combat,
                         'Counterfactual safety check: enemy does not move or produce; this is not full game replay')


if __name__ == '__main__':
    unittest.main(verbosity=2)
