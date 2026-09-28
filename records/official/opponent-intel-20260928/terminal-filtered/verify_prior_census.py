"""Check that removing terminal future threats leaves all other evidence unchanged."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
PRIOR = HERE.parent
ROOT = HERE.parents[3]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def binary_counts(profiles):
    scopes = {'all': profiles, 'round2': [p for p in profiles if p['identity']['round'] == 'round2']}
    result = {}
    for name, rows in scopes.items():
        result[name] = {}
        for outcome in ('win', 'loss'):
            selected = [p for p in rows if p['our_result'] == outcome]
            result[name][outcome] = {
                'games': len(selected),
                'enemy_f_home_incursion': sum(p['first_enemy_f_in_our_home'] is not None for p in selected),
                'unescorted_economic_threat_any': sum(p['first_unescorted_f_economic_threat'] is not None for p in selected),
                'unescorted_economic_threat_by30': sum(p['first_unescorted_f_economic_threat'] is not None and p['first_unescorted_f_economic_threat']['observation_turn'] <= 30 for p in selected),
                'our_home_enemy_capture_neutral_event': sum(bool(p['our_home_enemy_capture_or_neutral_events']) for p in selected),
                'our_late_losses145onward': sum(bool(p['our_late_building_losses_from_turn145']) for p in selected),
            }
    return result


old = json.loads((PRIOR / 'census.json').read_text())
new = json.loads((HERE / 'census.json').read_text())
old_checks = json.loads((PRIOR / 'census-output-checks.json').read_text())
old_verification = json.loads((PRIOR / 'census-verification.json').read_text())
new_verification = json.loads((HERE / 'census-verification.json').read_text())
assert digest(PRIOR / 'census.json') == old_checks['census_sha256']
for parent, verification in ((PRIOR, old_verification), (HERE, new_verification)):
    for filename, expected in verification['output_sha256'].items():
        assert digest(parent / filename) == expected
assert old['coverage'] == new['coverage']
assert old_verification['original_hashes_unchanged'] == new_verification['original_hashes_unchanged']
for path, expected in new_verification['original_hashes_unchanged'].items():
    assert digest(ROOT / path) == expected
removed = []
unchanged_profiles = 0
for before, after in zip(old['profiles'], new['profiles'], strict=True):
    assert before['source']['game_id'] == after['source']['game_id']
    old_remaining = {k: v for k, v in before.items() if k != 'economic_threat_snapshots'}
    new_remaining = {k: v for k, v in after.items() if k != 'economic_threat_snapshots'}
    assert old_remaining == new_remaining
    terminal = before['turns']
    retained = [t for t in before['economic_threat_snapshots'] if t['observation_turn'] < terminal]
    assert retained == after['economic_threat_snapshots']
    assert all(t['observation_turn'] < terminal for t in after['economic_threat_snapshots'])
    for row in before['economic_threat_snapshots']:
        if row['observation_turn'] >= terminal:
            assert row['observation_turn'] == terminal < 160
            removed.append({'opponent': before['identity']['opponent'],
                            'round': before['identity']['round'],
                            'game_id': before['source']['game_id'], 'terminal_turn': terminal,
                            'removed_future_threat': row})
    unchanged_profiles += 1
assert len(removed) == 3
assert Counter((r['opponent'], r['round'], r['terminal_turn']) for r in removed) == {
    ('뚜띠태하소불고기와멸치두명', 'round2', 107): 2,
    ('신촌도 우리땅', 'round2', 92): 1,
}
new_counts = binary_counts(new['profiles'])
assert new_counts == old_checks['game_weighted_binary_observation_counts']
assert new_counts == binary_counts(old['profiles'])
result = {
    'status': 'passed', 'checked_at_utc': datetime.now(timezone.utc).isoformat(),
    'source_commit': new['source_commit'],
    'verification_script_sha256': digest(Path(__file__)),
    'command': 'PYTHONDONTWRITEBYTECODE=1 python -B records/official/opponent-intel-20260928/terminal-filtered/verify_prior_census.py',
    'old_census_sha256': digest(PRIOR / 'census.json'),
    'new_census_sha256': digest(HERE / 'census.json'),
    'old_output_hashes_still_match_original_verification': True,
    'new_output_hashes_match_verification': True,
    'all_18_original_replay_hashes_still_match': True,
    'coverage_exactly_unchanged': True,
    'all_profile_fields_except_threat_snapshot_list_exactly_unchanged': unchanged_profiles,
    'first_threats_scores_production_outcomes_observed_turn_rows_unchanged': True,
    'removed_terminal_future_threat_count': len(removed),
    'removed_terminal_future_threats': removed,
    'retained_future_threat_count_before': sum(len(p['economic_threat_snapshots']) for p in old['profiles']),
    'retained_future_threat_count_after': sum(len(p['economic_threat_snapshots']) for p in new['profiles']),
    'all_nonterminal_threat_rows_preserved_in_order': True,
    'game_weighted_binary_observation_counts': new_counts,
    'binary_counts_exactly_unchanged': True,
    'interpretation': 'Only post-termination hypothetical action threats removed; full terminal observations are preserved. No new behavioral or performance evidence added.',
}
output = HERE / 'comparison-verification.json'
if output.exists():
    raise FileExistsError(output)
output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({'status': 'passed', 'unchanged_profiles': unchanged_profiles,
                  'removed_rows': len(removed), 'threats_before': result['retained_future_threat_count_before'],
                  'threats_after': result['retained_future_threat_count_after']}, ensure_ascii=False))
