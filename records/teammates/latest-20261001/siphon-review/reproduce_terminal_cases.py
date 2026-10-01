"""Compare unmodified siphon with two legal one-turn stationary-opponent witnesses."""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys

sys.dont_write_bytecode = True
ROOT = Path(os.environ.get('YK_REPO', '/tmp/yk-new-bot-20261001'))
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT/'tests'))
sys.path.insert(0, str(ROOT/'yk-development-tools'))
from test_mission_scheduler import audit_commands
from mission_scheduler_cases import tactical_state
from engine.config import load_config
from engine.pipeline import run_turn
from engine.state import new_game
from runner.protocol import serialize_init, serialize_turn
from runner.replay import snapshot


def run_case(name, state, witness):
    payload = serialize_init(state, 'Y') + serialize_turn(state, 'Y', state.turn+1)
    original = subprocess.run([str(HERE/'siphon')], input=payload, text=True,
                              capture_output=True, timeout=3, check=True)
    probe = subprocess.run([str(HERE/'probe')], input=payload, text=True,
                           capture_output=True, timeout=3, check=True)
    assert original.stdout == probe.stdout, 'Instrumentation changed output'
    lines = [x for x in original.stdout.splitlines() if x != 'END']
    actual = audit_commands(state, 'Y', lines)
    alternative = audit_commands(state, 'Y', witness)
    after_actual, result_actual = run_turn(state, actual, [])
    after_witness, result_witness = run_turn(state, alternative, [])
    return {'case': name, 'input': payload, 'initial': snapshot(state),
            'candidate_commands': lines, 'candidate_result': result_actual,
            'candidate_after': snapshot(after_actual),
            'witness_commands': witness, 'witness_result': result_witness,
            'witness_after': snapshot(after_witness),
            'probe_matches_original': True, 'probe_stderr': probe.stderr,
            'strict_audit': {'candidate': 'pass', 'witness': 'pass', 'enemy': 'stationary empty'},
            'limitations': ['Handcrafted fully revealed legal SDK state, not a generated full match.',
                            'Opponent holds for one turn; this is not an adaptive opponent or a win-rate estimate.']}

state = tactical_state(turn=160)
state.add_unit(6, 5, 'Y', 'F', 1)
rows = [run_case('existing_flag_free_neutralization', state, ['MOVE 6 5 F 1 R'])]
template = tactical_state(turn=160, resource=5)
template.buildings[13].owner, template.buildings[13].stage = 'N', 0
template.buildings[1].owner, template.buildings[1].stage = 'K', 2
state = new_game(load_config(), buildings=template.sorted_buildings(),
                 bases={'Y': (0,1), 'K': (14,13)}, resources={'Y':5, 'K':0})
state.turn = 159
state.revealed = {side: set(state.buildings) for side in 'YK'}
rows.append(run_case('new_flag_free_neutralization', state, ['SPAWN F 1','MOVE 0 1 F 1 R']))
report = {'source_sha256': hashlib.sha256((HERE/'submissions/siphon/main.cpp').read_bytes()).hexdigest(),
          'repository_commit_at_reproduction': subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
          'cases': rows}
(HERE/'terminal-witnesses.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
for row in rows:
    print(row['case'], row['candidate_result'], '=>', row['witness_result'])
    print(row['probe_stderr'].strip())
