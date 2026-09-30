"""Legal observations and engine fixtures for the independent mission-bot audit."""
from pathlib import Path
import json
import gzip
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'yk-development-tools'))
from engine.config import load_config
from engine.state import Building, new_game

OFFICIAL_REPLAY = ROOT / 'records/official/latest-20261001/raw/rolling-game-f8600dcbb568c94c1bf2715e2bae9e00fd16abc8333520f22a5fd05a1c25362c.json'


def tactical_state(turn=80, resource=0):
    pairs = [
        ('HALL', (1, 1), 2), ('LIBRARY', (1, 3), 1),
        ('ENG', (1, 5), 1), ('HOSPITAL', (2, 2), 2),
        ('STATION', (2, 10), 2), ('STATION', (5, 2), 3),
        ('WATCH', (7, 5), 4), ('DEPOT', (5, 11), 4),
    ]
    buildings = [Building(0, 7, 7, 'PLAZA', 3, 'Y', 2)]
    for kind, (x, y), points in pairs:
        for px, py in [(x, y), (14 - x, 14 - y)]:
            buildings.append(Building(len(buildings), px, py, kind, points))
    for bid in (2, 13):
        buildings[bid].owner = 'K'
        buildings[bid].stage = 2
    state = new_game(load_config(), buildings=buildings, resources={'Y': resource, 'K': 0})
    state.turn = turn - 1
    state.revealed = {side: set(state.buildings) for side in 'YK'}
    return state


def state_from_observation(observation):
    """Retain hidden point masks; fill engine-only scores by observed symmetry or a range value."""
    by_position = {(b['x'], b['y']): b for b in observation['buildings']}
    buildings = []
    seen = set()
    for b in observation['buildings']:
        score = b.get('score')
        if score is not None:
            seen.add(b['id'])
        else:
            mate = by_position[(14 - b['x'], 14 - b['y'])]
            score = mate.get('score')
            if score is None:
                score = 3 if b['type'] == 'PLAZA' else (2 if 5 <= b['x'] <= 9 else 1)
        buildings.append(Building(b['id'], b['x'], b['y'], b['type'], score,
                                  b['owner'], b['stage']))
    terrain = [list(row) for row in observation['map']]
    homes = sorted((x, y) for y, row in enumerate(terrain) for x, cell in enumerate(row) if cell == 'H')
    state = new_game(load_config(), terrain=terrain, buildings=buildings,
                     bases={'Y': homes[0], 'K': homes[1]}, resources=observation['resources'])
    state.turn = observation['turn']
    side = observation['side']
    state.revealed[side] = seen
    for team, kind, x, y, count in observation['units']:
        state.add_unit(x, y, team, kind, count)
    for team in 'YK':
        state.occupation_score_turns[team] = observation.get('occTurns', {}).get(team) or 0
    return state


def official_history_before(turn):
    replay = json.loads(OFFICIAL_REPLAY.read_text())
    observations = [row['observation'] for row in replay['turns']
                    if row['observation']['turn'] < turn]
    return replay['side'], sorted(observations, key=lambda row: row['turn'])


RENDEZVOUS_REPLAY = ROOT / 'records/benchmarks/mission-20261001/v1/runs/development-common/replays/81b32c6a7c4aa249159323da.json.gz'


def rendezvous_history_before(turn=13):
    """Reconstruct original states, preserving reveal masks before protocol serialization."""
    from engine.pipeline import run_turn
    from runner.protocol import parse_commands
    from runner.replay import snapshot

    replay = json.loads(gzip.open(RENDEZVOUS_REPLAY, 'rt').read())
    game_map = replay['map']
    buildings = [Building(b['id'], b['x'], b['y'], b['type'], b['score'])
                 for b in game_map['buildings']]
    state = new_game(replay['config'], terrain=[list(row) for row in game_map['terrain']],
                     buildings=buildings, bases=game_map['bases'])
    history = [state]
    for frame in replay['turns']:
        if frame['turn'] >= turn:
            break
        state, _ = run_turn(state, parse_commands(frame['commands']['Y']),
                           parse_commands(frame['commands']['K']))
        if snapshot(state) != frame['state']:
            raise AssertionError(f"Official engine does not reproduce source frame {frame['turn']}")
        history.append(state)
    if history[-1].turn != turn - 1:
        raise AssertionError('Source replay does not reach requested observation')
    return history, replay
