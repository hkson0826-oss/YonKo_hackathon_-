"""Prove every score used in the one downloaded game's retrospective total."""
from pathlib import Path
import argparse
import hashlib
import json

folder = Path(__file__).resolve().parent
parser = argparse.ArgumentParser()
parser.add_argument('--source', type=Path, default=folder.parent / 'raw/rolling-game-f8600dcbb568c94c1bf2715e2bae9e00fd16abc8333520f22a5fd05a1c25362c.json')
parser.add_argument('--output', type=Path, default=folder / 'score-reconstruction-evidence.json')
args = parser.parse_args()
raw = json.loads(args.source.read_text())
known, first = {}, {}
for turn in raw['turns']:
    for b in turn['observation']['buildings']:
        if 'score' not in b:
            continue
        assert isinstance(b['score'], (int, float)) and b['score'] >= 0, b
        assert b['id'] not in known or known[b['id']] == b['score'], b
        known[b['id']] = b['score']
        first.setdefault(b['id'], turn['turn'])
buildings = raw['turns'][-1]['observation']['buildings']
at = {(b['x'], b['y']): b for b in buildings}
rows = []
for b in buildings:
    mirror = at[(14-b['x'], 14-b['y'])]
    bid, mid = b['id'], mirror['id']
    assert bid in known or mid in known, ('unresolved score', b)
    if bid in known and mid in known:
        assert known[bid] == known[mid], ('symmetry mismatch', b, mirror)
    if bid in known:
        score = known[bid]
        evidence = {'kind': 'direct_observation', 'building_id': bid, 'first_turn': first[bid]}
    else:
        score = known[mid]
        evidence = {'kind': '180_degree_symmetric_pair', 'observed_building_id': mid,
                    'observed_xy': [mirror['x'], mirror['y']], 'first_turn': first[mid]}
    rows.append({'id': bid, 'type': b['type'], 'xy': [b['x'], b['y']],
                 'final_owner': b['owner'], 'score': score, 'evidence': evidence})
scores = {team: sum(b['score'] for b in rows if b['final_owner'] == team) for team in 'YKN'}
result = {
    'source': str(args.source), 'source_sha256': hashlib.sha256(args.source.read_bytes()).hexdigest(),
    'verifier_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    'game_id': raw['gameId'], 'raw_final_scores': raw['turns'][-1]['observation']['scores'],
    'retrospective_exact_scores': scores, 'total_map_score': sum(b['score'] for b in rows),
    'invalid_or_negative_score_observations': [], 'all17_resolved': len(rows) == 17,
    'building_scores': rows,
    'interpretation': 'K=35 is an exact retrospective sum from directly observed building scores and their rule-defined 180-degree symmetric mates. Raw final K total is null. No imputation, unknown=-1 replacement, or midpoint estimate used.',
}
assert scores[raw['side']] == raw['turns'][-1]['observation']['scores'][raw['side']]
args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({'exact_scores': scores, 'all17_resolved': result['all17_resolved']}))
