"""Read participant-view official replays; never reconstruct hidden enemy orders."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import statistics
import sys

DEFAULT_REPO = next((p for p in Path(__file__).resolve().parents
    if (p / 'experiments/analyze_official_round1.py').exists()), Path('/home/dlwltkd/YonKo_hackathon_-'))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def interval(rows, predicate):
    output, start = [], None
    for i, row in enumerate(rows):
        yes = predicate(row)
        if yes and start is None:
            start = row['turn']
        if start is not None and (not yes or i == len(rows) - 1):
            output.append([start, row['turn'] if yes else rows[i - 1]['turn']])
            start = None
    return output


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--repo', type=Path, default=DEFAULT_REPO)
    ap.add_argument('--input-root', type=Path, default=DEFAULT_REPO)
    ap.add_argument('--raw', type=Path, default=Path('records/official/latest-20261001/raw'))
    ap.add_argument('--identity', type=Path)
    ap.add_argument('--expected-games', type=int)
    ap.add_argument('--output', type=Path, default=Path(__file__).resolve().parent)
    args = ap.parse_args()
    sys.path.insert(0, str(args.repo / 'experiments'))
    import analyze_official_round1 as base
    base.ROOT = args.input_root
    paths = sorted((args.input_root / args.raw).glob('*.json'))
    identities = {}
    if args.identity:
        identity = json.loads(args.identity.read_text())
        for row in identity if isinstance(identity, list) else identity['matches']:
            identities[row.get('game_id', row.get('gameId'))] = row
    games = []
    for path in paths:
        raw = json.loads(path.read_text())
        if 'turns' not in raw:
            continue
        assert all(isinstance(b['score'], (int, float)) and b['score'] >= 0
                   for row in raw['turns'] for b in row['observation']['buildings'] if 'score' in b), path
        derived = base.analyze(path)
        summary = derived['summary']
        side = raw['side']
        enemy = 'K' if side == 'Y' else 'Y'
        summary['our_result'] = ('draw' if raw['result']['winner'] not in ('Y', 'K') else
                                 'win' if raw['result']['winner'] == side else 'loss')
        identity = identities.get(raw['gameId'])
        if identity:
            for key, expected in [('side', side), ('outcome', summary['our_result'])]:
                if key in identity:
                    assert identity[key] == expected, (raw['gameId'], key, identity[key], expected)
        summary['site_identity'] = identity
        if identity and identity.get('opponent'):
            summary['opponent_name'] = identity['opponent']
        elif raw['gameId'].startswith('rolling-game-f8600d'):
            summary['opponent_name'] = '붉은 산호초'
            summary['opponent_name_source'] = 'collector task message, pending saved site manifest'
        else:
            summary['opponent_name'] = None
        summary['first_response_ms'] = raw['turns'][1]['observation'].get('myResponseMs')
        response = sorted(t['observation']['myResponseMs'] for t in raw['turns'][2:]
                          if t['observation'].get('myResponseMs') is not None)
        summary['normal_response_ms'] = {'count': len(response), 'max': max(response, default=None),
            'median': statistics.median(response) if response else None,
            'p95': response[(95 * len(response) + 99) // 100 - 1] if response else None,
            'over_300ms': sum(x > 300 for x in response)}
        summary['economic_ownership_intervals'] = []
        for building in raw['turns'][0]['observation']['buildings']:
            if building['type'] not in ('ENG', 'HALL', 'HOSPITAL'):
                continue
            bid = building['id']
            summary['economic_ownership_intervals'].append({**building,
                'intervals': {t: interval(raw['turns'], lambda row, t=t:
                    next(b['owner'] for b in row['observation']['buildings'] if b['id'] == bid) == t)
                    for t in ('Y', 'K', 'N')}})
        summary['economic_first_capture'] = {
            team: {kind: next((r['turn'] for r in derived['turns']
                if r['building_counts'][team].get(kind, 0)), None)
                for kind in ('ENG', 'HALL', 'HOSPITAL')}
            for team in ('Y', 'K')}
        summary['phases'] = []
        for start, end in [(1, 20), (21, 40), (41, 80), (81, 120), (121, 140), (141, 160)]:
            rows = [r for r in derived['turns'] if start <= r['turn'] <= end]
            if not rows:
                continue
            born, dead = Counter(), Counter()
            for row in rows:
                born.update(row['own_transition']['production'])
                dead.update(row['own_transition']['casualties'])
            summary['phases'].append({'start': start, 'end': rows[-1]['turn'],
                'own_production': dict(born), 'own_casualties': dict(dead),
                'enemy_w_produced': sum(r['own_transition']['enemy_w_production_inferred'] for r in rows),
                'end_scores': rows[-1]['retrospective_scores'], 'end_units': rows[-1]['units']})
        summary['checkpoints'] = [{key: row[key] for key in ('turn', 'retrospective_scores', 'units', 'building_counts')}
            for row in derived['turns'] if row['turn'] in {5, 10, 15, 20, 30, 40, 60, 80, 100, 120, 140, 150, 158, 159, 160, summary['turn_count']}]
        our_losses, economic_losses, flag_losses, home_events = [], [], [], []
        bases = base.infer_bases(raw)
        home = (lambda x: x <= 4) if bases[side][0] <= 4 else (lambda x: x >= 10)
        summary['first_enemy_flag_in_home'] = None
        summary['enemy_maximum_observed_f'] = 0
        summary['own_tele_command_count'] = sum(line.startswith('TELE ')
            for row in raw['turns'] for line in row.get('command', {}).get('lines', []))
        for i, row in enumerate(derived['turns']):
            obs = raw['turns'][i]['observation']
            summary['enemy_maximum_observed_f'] = max(summary['enemy_maximum_observed_f'], row['units'][enemy]['F'])
            home_flags = [u for u in obs['units'] if u[:2] == [enemy, 'F'] and home(u[2])]
            if home_flags and summary['first_enemy_flag_in_home'] is None:
                summary['first_enemy_flag_in_home'] = {'turn': i, 'units': home_flags}
            for ev in row['ownership_changes']:
                if ev['from'] == side:
                    item = {'turn': i, **ev,
                        'first_recovery': next((r['turn'] for r in derived['turns'][i + 1:]
                            if any(c['id'] == ev['id'] and c['to'] == side for c in r['ownership_changes'])), None),
                        'own_casualties_on_cell': [c for c in row.get('own_transition', {}).get('casualty_cells', [])
                            if (c['x'], c['y']) == (ev['x'], ev['y'])],
                        'post_cell_units': [u for u in obs['units'] if u[2:4] == [ev['x'], ev['y']]],
                        'scores': row['retrospective_scores']}
                    our_losses.append(item)
                    if ev['type'] in ('ENG', 'HALL', 'HOSPITAL'):
                        economic_losses.append(item)
                if home(ev['x']) and (ev['to'] == enemy or any(e.get('kind') == 'neutral'
                      and e.get('team') == enemy and e.get('buildingId') == ev['id'] for e in obs['events'])):
                    home_events.append({'turn': i, **ev})
            for c in row.get('own_transition', {}).get('casualty_cells', []):
                if c['kind'] != 'F':
                    continue
                previous = raw['turns'][i - 1]['observation']
                x, y = c['x'], c['y']
                flag_losses.append({'turn': i, **c,
                    'building': next((b for b in previous['buildings'] if (b['x'], b['y']) == (x, y)), None),
                    'before_units_manhattan_2': [u for u in previous['units'] if abs(u[2]-x)+abs(u[3]-y) <= 2],
                    'after_units_manhattan_2': [u for u in obs['units'] if abs(u[2]-x)+abs(u[3]-y) <= 2],
                    'own_commands': raw['turns'][i]['command']['lines']})
        summary['first_economic_loss'] = economic_losses[0] if economic_losses else None
        summary['home_intrusion_ownership_event_count'] = len(home_events)
        hold_probes = []
        config = json.loads((base.SDK / 'config/balance.json').read_text())
        for loss_turn in sorted({e['turn'] for e in flag_losses}):
            previous = raw['turns'][loss_turn - 1]['observation']
            probe_state = base.state_from_observation(previous, bases, config)
            own_commands = base.parse_commands(raw['turns'][loss_turn]['command']['lines'])
            after_hold, _ = base.run_turn(probe_state, own_commands if side == 'Y' else [],
                                         own_commands if side == 'K' else [])
            ours_before = sum(u[4] for u in previous['units'] if u[:2] == [side, 'F'])
            ours_born = derived['turns'][loss_turn]['own_transition']['production']['F']
            ours_after = sum(n for (x, y, t, k), n in after_hold.units.items() if (t, k) == (side, 'F'))
            if ours_before + ours_born > ours_after:
                hold_probes.append({'turn': loss_turn,
                    'own_f_loss_with_actual_own_action_and_enemy_hold': ours_before + ours_born - ours_after,
                    'actual_own_f_loss': derived['turns'][loss_turn]['own_transition']['casualties']['F'],
                    'scope': 'One-turn legal opponent response: no enemy spawn or move. Combat probe only; not a full-game counterfactual or opponent reconstruction.'})
        summary['enemy_hold_counterexample_turns'] = hold_probes
        summary['late_score_margin'] = {str(row['turn']): row['retrospective_scores'][side]-row['retrospective_scores'][enemy]
            for row in derived['turns'] if row['turn'] in (120, 140, 150, 158, 159, 160)}
        summary['largest_our_score_lead'] = max(({'turn': row['turn'],
            'margin': row['retrospective_scores'][side] - row['retrospective_scores'][enemy]}
            for row in derived['turns']), key=lambda x: (x['margin'], -x['turn']))
        for k in ('F', 'W', 'S'):
            assert summary['our_production'][k] - summary['our_casualties'][k] == summary['final_units'][side][k]
        assert summary['sha256'] == digest(path)
        games.append({'summary': summary, 'economic_losses': economic_losses,
            'all_ownership_losses': our_losses, 'flag_loss_events': flag_losses,
            'home_intrusion_events': home_events, 'turns': derived['turns']})
    assert len(games) == len({g['summary']['gameId'] for g in games})
    args.output.mkdir(parents=True, exist_ok=True)
    metadata = {'created_at_utc': datetime.now(timezone.utc).isoformat(),
        'raw_scope': str(args.input_root / args.raw), 'complete_expected_set': len(games) == args.expected_games and
            (not identities or set(identities) == {g['summary']['gameId'] for g in games})
            if args.expected_games is not None else None,
        'expected_games': args.expected_games, 'analyzed_games': len(games),
        'missing_collector_game_ids': sorted(set(identities) - {g['summary']['gameId'] for g in games}),
        'outcomes': dict(Counter(g['summary']['our_result'] for g in games)),
        'own_spawn_move_transitions_checked': sum(g['summary']['own_spawn_move_transitions_checked'] for g in games),
        'dependency_hashes': {str(p): digest(p) for p in [Path(__file__), args.repo/'experiments/analyze_official_round1.py',
            base.SDK/'engine/pipeline.py', base.SDK/'engine/state.py', base.SDK/'config/balance.json', base.SDK/'runner/protocol.py']},
        'schema': 'Official participant-view schemaVersion 2. Our command, public units and ownership; no opponent orders. Retrospective scores inferred only for analysis, never injected into bot observations.',
        'limits': ['Only own spawn/move stages checked with official SDK; no full-game opponent-order reproduction.',
                   'Enemy W production follows exact equal W combat losses; enemy F production is not reconstructed.',
                   'No causal victory counterfactual from replay observations.',
                   'Current site code version and opponent names require separate collector identity records.'],
        'identity_source': str(args.identity) if args.identity else None,
        'identity_sha256': digest(args.identity) if args.identity else None}
    (args.output/'analysis.json').write_text(json.dumps({'metadata': metadata, 'matches': games}, ensure_ascii=False, indent=2)+'\n')
    (args.output/'summary.json').write_text(json.dumps({'metadata': metadata, 'matches': [g['summary'] for g in games]}, ensure_ascii=False, indent=2)+'\n')
    lines = ['# 최신 공식 리플레이 관측 분석', '',
        f"실제 수집·분석 {len(games)}경기. 결과 {metadata['outcomes']}. 예정 전체 경기 수 {args.expected_games}; 완전 수집 여부 {metadata['complete_expected_set']}.", '',
        '상대 명령은 포함되지 않는다. 우리 생산·이동을 공식 엔진으로 대조하고 상대 W 생산은 동일 W 상쇄로 역산했다. 점수는 이후 공개값·대칭을 이용한 사후 재구성이며 당시 합법 관측과 구분한다.', '',
        '| 상대 / ID | 결과 | 종료 턴 | 점수 Y:K | W 생산 우리:상대 | F 생산/사망 우리 | ENG 생산혜택 Y:K | 첫 경제 손실 |',
        '|---|---|---:|---:|---:|---:|---:|---|']
    for g in games:
        s=g['summary'];sc=s['final_scores_reconstructed'];loss=s['first_economic_loss'];e=s['economy']
        lines.append(f"| {s['opponent_name'] or s['gameId'][13:21]} | {s['our_result']} | {s['turn_count']} | {sc['Y']}:{sc['K']} | {s['our_production']['W']}:{s['enemy_w_production_inferred_from_equal_w_losses']} | {s['our_production']['F']}/{s['our_casualties']['F']} | {e['Y']['turns_with_eng_at_production']}:{e['K']['turns_with_eng_at_production']} | {str(loss['turn'])+'턴 '+loss['type'] if loss else '없음'} |")
    lines += ['', f"대조 전이 {metadata['own_spawn_move_transitions_checked']}개. 원본 파일을 변경하지 않았으며 각 경기 SHA256을 보존했다.", '',
        '원본별 전체 수치·전 턴 파생값·소유 상실·F 전사 전후 주변 병력·실제 우리 명령은 analysis.json에 저장했다. 결과를 보고 선정한 사례는 개발 자료다.']
    (args.output/'summary.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps(metadata, ensure_ascii=False))


if __name__ == '__main__':
    main()
