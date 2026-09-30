"""Profile observed opponents; never recover or invent their hidden commands."""
from __future__ import annotations

import argparse
import hashlib
from collections import Counter, deque
from datetime import datetime, timezone
import json
from pathlib import Path
import statistics
import subprocess

from analyze_official_round1 import ROOT, SDK, analyze, digest, infer_bases

PHASES = ((1, 30), (31, 80), (81, 130), (131, 160))


def bfs(terrain, start, stations=()):
    height, width = len(terrain), len(terrain[0])
    seen, queue = {tuple(start): 0}, deque([tuple(start)])
    stations = set(stations)
    while queue:
        x, y = queue.popleft()
        destinations = [(x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)]
        if (x, y) in stations and len(stations) >= 2:
            destinations += list(stations)
        for nx, ny in destinations:
            if (0 <= nx < width and 0 <= ny < height and terrain[ny][nx] != '#'
                    and (nx, ny) not in seen):
                seen[nx, ny] = seen[x, y] + 1
                queue.append((nx, ny))
    return seen


def future_threat_allowed(turn, final_observation_turn, travel_steps):
    # Before termination, use the rules horizon, not hindsight about an early win.
    return (0 <= turn < min(final_observation_turn, 160)
            and 0 <= travel_steps <= min(3, 160 - turn))


def self_check():
    terrain = ['.....', '.###.', '.....']
    assert bfs(terrain, (0, 1))[(4, 1)] == 6
    assert bfs(terrain, (0, 1), [(0, 1), (4, 1)])[(4, 1)] == 1
    assert bfs(terrain, (0, 1), [(0, 1)])[(4, 1)] == 6
    assert (2, 1) not in bfs(terrain, (0, 1))
    assert not future_threat_allowed(107, 107, 0)
    assert not future_threat_allowed(92, 92, 1)
    assert future_threat_allowed(106, 107, 3)
    assert not future_threat_allowed(160, 160, 0)
    assert future_threat_allowed(159, 160, 1)
    assert not future_threat_allowed(159, 160, 2)
    return {'obstacle_detour': True, 'station_edge': True, 'one_station_no_tele': True,
            'blocked_cell_unreachable': True, 'early_terminal_observations_excluded': True,
            'earlier_observations_keep_rules_horizon': True,
            'normal_terminal_and_last_turn_horizon': True}


def mean(values):
    return statistics.mean(values) if values else None


def owned_intervals(rows, predicate):
    result, start = [], None
    for i, row in enumerate(rows):
        yes = predicate(row)
        if yes and start is None:
            start = row['turn']
        if start is not None and (not yes or i == len(rows) - 1):
            result.append([start, row['turn'] if yes else rows[i - 1]['turn']])
            start = None
    return result


def source_entries(extra):
    entries = []
    for round_id, filename, version, submission in (
        ('round1', 'records/official/round1/site-observations.json', 'v2', 3),
        ('round2', 'records/official/round2/site-observations.json', 'v3', 4),
    ):
        site = json.loads((ROOT / filename).read_text())
        for m in site['matches']:
            entries.append({**m, 'path': m.get('path', m.get('source_path')),
                            'round': round_id, 'local_version': version,
                            'site_submission': submission, 'identity_source': filename,
                            'identity_source_sha256': digest(ROOT / filename)})
    if extra:
        metadata = json.loads(extra.read_text())
        for m in metadata['matches']:
            for key in ('path', 'game_id', 'opponent', 'side', 'outcome', 'round',
                        'site_submission', 'local_version'):
                assert key in m, (key, m)
            entries.append({**m, 'identity_source': str(extra.relative_to(ROOT)),
                            'identity_source_sha256': digest(extra)})
    assert len(entries) == len({m['game_id'] for m in entries})
    return entries


def profile(entry):
    path = ROOT / entry['path']
    raw = json.loads(path.read_text())
    derived = analyze(path)
    summary = derived['summary']
    side, enemy = raw['side'], 'K' if raw['side'] == 'Y' else 'Y'
    assert (entry['game_id'], entry['side'], entry['outcome']) == (
        raw['gameId'], side, summary['our_result'])
    bases = infer_bases(raw)
    terrain = raw['turns'][0]['observation']['map']
    home = (lambda x: x <= 4) if bases[side][0] <= 4 else (lambda x: x >= 10)
    layout = {'terrain': terrain, 'buildings': sorted(
        [(b['id'], b['type'], b['x'], b['y']) for b in raw['turns'][0]['observation']['buildings']])}
    layout_hash = hashlib.sha256(json.dumps(layout, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    distance_cache = {}

    def distances(start, stations=()):
        key = (tuple(start), tuple(sorted(stations)))
        if key not in distance_cache:
            distance_cache[key] = bfs(terrain, start, stations)
        return distance_cache[key]

    rows = []
    threats = []
    own_losses = []
    enemy_home_events = []
    for raw_turn, source in zip(raw['turns'], derived['turns'], strict=True):
        obs = raw_turn['observation']
        turn = obs['turn']
        units = obs['units']
        buildings = obs['buildings']
        stations = {t: [(b['x'], b['y']) for b in buildings
                        if b['type'] == 'STATION' and b['owner'] == t] for t in (side, enemy)}
        warriors = [u for u in units if u[:2] == [enemy, 'W']]
        flags = [u for u in units if u[:2] == [enemy, 'F']]
        ours_w = [u for u in units if u[:2] == [side, 'W']]
        wcount = sum(u[4] for u in warriors)
        eng = any(b['type'] == 'ENG' and b['owner'] == side for b in buildings)
        spawn_origins = [bases[side]] + [(b['x'], b['y']) for b in buildings
                                       if b['type'] == 'HOSPITAL' and b['owner'] == side]
        can_spawn_w = obs['resources'][side] >= (2 if eng else 3)
        home_flags = [{'x': u[2], 'y': u[3], 'count': u[4]} for u in flags if home(u[2])]
        row = {
            'turn': turn, 'enemy_units_observed': source['units'][enemy],
            'enemy_resource_end_turn': obs['resources'][enemy],
            'enemy_w_stacks': len(warriors),
            'enemy_largest_w_stack': max((u[4] for u in warriors), default=0),
            'enemy_w_largest_stack_fraction': max((u[4] for u in warriors), default=0) / wcount if wcount else None,
            'enemy_w_concentration_hhi': sum((u[4] / wcount) ** 2 for u in warriors) if wcount else None,
            'enemy_w_in_our_home': sum(u[4] for u in warriors if home(u[2])),
            'enemy_w_in_center': sum(u[4] for u in warriors if 5 <= u[2] <= 9),
            'enemy_f_in_our_home': home_flags,
            'enemy_f_with_no_w_within_one_walk_step': sum(u[4] for u in flags
                if not any(distances((u[2], u[3])).get((w[2], w[3]), 999) <= 1 for w in warriors)),
            'enemy_owned_building_counts': source['building_counts'][enemy],
            'enemy_owned_center_buildings': sum(b['owner'] == enemy and 5 <= b['x'] <= 9 for b in buildings),
            'plaza_owner': next(b['owner'] for b in buildings if b['type'] == 'PLAZA'),
            'enemy_has_two_stations': len(stations[enemy]) >= 2,
            'retrospective_score_our_minus_enemy': source['retrospective_scores'][side] - source['retrospective_scores'][enemy],
            'ownership_changes': source['ownership_changes'],
        }
        if turn:
            transition = source['own_transition']
            row['enemy_w_produced_inferred'] = transition['enemy_w_production_inferred']
            row['enemy_w_unit_cost'] = transition['enemy_w_unit_cost']
            row['our_w_produced'] = transition['production']['W']
            row['equal_w_combat_deaths_each_side'] = transition['casualties']['W']
        for change in source['ownership_changes']:
            event = {'turn': turn, **change}
            if change['from'] == side:
                own_losses.append(event)
            if home(change['x']) and (change['to'] == enemy or
                    any(e.get('team') == enemy and e.get('buildingId') == change['id']
                        and e.get('kind') == 'neutral' for e in obs['events'])):
                enemy_home_events.append(event)
        for flag in flags:
            pos = (flag[2], flag[3])
            walk = distances(pos)
            transport = distances(pos, stations[enemy])
            unescorted = not any(walk.get((w[2], w[3]), 999) <= 1 for w in warriors)
            for building in buildings:
                if (building['owner'] != side or building['type'] not in ('ENG', 'HALL')
                        or not home(building['x'])):
                    continue
                target = (building['x'], building['y'])
                eta = transport.get(target, 999)
                if not future_threat_allowed(turn, raw['turns'][-1]['turn'], eta):
                    continue
                existing = min((distances((u[2], u[3]), stations[side]).get(target, 999)
                                for u in ours_w), default=999)
                spawn = min((max(1, distances(p, stations[side]).get(target, 999))
                             for p in spawn_origins), default=999) if can_spawn_w else 999
                threats.append({'observation_turn': turn, 'command_turn_starting_from_this_observation': turn + 1,
                    'target_id': building['id'], 'target_type': building['type'], 'target_xy': list(target),
                    'remaining_turns': 160 - turn, 'target_stage': building['stage'], 'enemy_f_xy': list(pos), 'enemy_f_count': flag[4],
                    'enemy_w_absent_within_one_walk_step': unescorted,
                    'enemy_f_walk_steps': walk.get(target), 'enemy_f_static_transport_steps': eta,
                    'our_existing_w_static_transport_steps': existing if existing < 999 else None,
                    'our_spawned_w_geometric_arrival_turns': spawn if spawn < 999 else None,
                    'our_resource_now_allows_one_w_spawn': can_spawn_w,
                    'geometric_enemy_arrives_before_any_current_or_immediate_spawn_w': eta < min(existing, spawn),
                    'enemy_w_on_target': sum(u[4] for u in warriors if (u[2], u[3]) == target),
                    'our_w_on_target': sum(u[4] for u in ours_w if (u[2], u[3]) == target)})
        rows.append(row)
    phases = []
    for start, end in PHASES:
        selected = [r for r in rows if start <= r['turn'] <= end]
        if not selected:
            continue
        total_w = sum(r['enemy_units_observed']['W'] for r in selected)
        phases.append({
            'turn_start': start, 'turn_end': selected[-1]['turn'], 'observations': len(selected),
            'enemy_w_production_exact_inferred': sum(r['enemy_w_produced_inferred'] for r in selected),
            'our_w_production': sum(r['our_w_produced'] for r in selected),
            'enemy_mean_f_observed': mean([r['enemy_units_observed']['F'] for r in selected]),
            'enemy_peak_f_observed': max(r['enemy_units_observed']['F'] for r in selected),
            'enemy_peak_s_observed': max(r['enemy_units_observed']['S'] for r in selected),
            'enemy_mean_largest_w_stack_fraction_nonempty': mean([r['enemy_w_largest_stack_fraction'] for r in selected if r['enemy_w_largest_stack_fraction'] is not None]),
            'enemy_mean_w_hhi_nonempty': mean([r['enemy_w_concentration_hhi'] for r in selected if r['enemy_w_concentration_hhi'] is not None]),
            'enemy_center_w_unit_turn_share': sum(r['enemy_w_in_center'] for r in selected) / total_w if total_w else None,
            'enemy_our_home_w_unit_turn_share': sum(r['enemy_w_in_our_home'] for r in selected) / total_w if total_w else None,
            'enemy_plaza_owned_end_observations': sum(r['plaza_owner'] == enemy for r in selected),
            'enemy_mean_resource_end_observation': mean([r['enemy_resource_end_turn'] for r in selected]),
        })
    first_home = next(({'turn': r['turn'], 'cells': r['enemy_f_in_our_home']} for r in rows if r['enemy_f_in_our_home']), None)
    enemy_w_cost = sum(r.get('enemy_w_produced_inferred', 0) * r.get('enemy_w_unit_cost', 0) for r in rows)
    threat_first = next((t for t in threats if t['enemy_w_absent_within_one_walk_step']), None)
    late_losses = [c for c in own_losses if c['turn'] >= 145]
    behavioral_tags = []
    if first_home and first_home['turn'] <= 30:
        behavioral_tags.append('관측: 30턴 이내 상대 F가 우리 홈 영역에 진입')
    if threat_first and threat_first['observation_turn'] <= 30:
        behavioral_tags.append('관측: 30턴 이내 주변 1칸에 W 없는 F가 우리 ENG/HALL 3이동 이내 접근')
    if late_losses:
        behavioral_tags.append('관측: 145턴 이후 우리 소유 거점의 소유권 상실 발생')
    if any(p['enemy_mean_largest_w_stack_fraction_nonempty'] is not None and p['enemy_mean_largest_w_stack_fraction_nonempty'] >= .6 for p in phases):
        behavioral_tags.append('관측: 한 구간에서 상대 최대 W 덩어리가 평균 병력 60% 이상')
    if not behavioral_tags:
        behavioral_tags.append('판정 보류: 설정한 대표 행동 지표가 뚜렷하지 않음')
    return {
        'identity': {k: entry.get(k) for k in ('opponent', 'round', 'local_version', 'site_submission',
                     'identity_source', 'identity_source_sha256', 'opponent_reference_rank', 'url')},
        'source': {'path': entry['path'], 'sha256': digest(path), 'game_id': raw['gameId'],
                   'evaluation_id': raw['evaluationId'], 'series_id': raw['seriesId'],
                   'ruleset': raw['rulesetVersion'], 'protocol': raw['protocolVersion']},
        'initial_visible_layout_sha256': layout_hash,
        'layout_hash_excludes_hidden_scores_and_policy': True,
        'opponent_code_version': 'unknown; never pooled as one fixed policy across rounds',
        'our_side': side, 'our_result': summary['our_result'], 'turns': summary['turn_count'],
        'final_score_our_enemy': [summary['final_scores_reconstructed'][side], summary['final_scores_reconstructed'][enemy]],
        'our_w_production': summary['our_production']['W'],
        'enemy_w_production_exact_inferred': summary['enemy_w_production_inferred_from_equal_w_losses'],
        'enemy_w_resource_spend_exact_inferred': enemy_w_cost,
        'enemy_f_s_production': 'unidentifiable; counts are observations, not total production',
        'enemy_peak_units_observed': {k: max(r['enemy_units_observed'][k] for r in rows) for k in ('F', 'W', 'S')},
        'economy_control_at_production': summary['economy'],
        'enemy_resource_at_cap_end_observation_count': sum(r['enemy_resource_end_turn'] == 40 for r in rows[1:]),
        'enemy_two_owned_stations_observations': sum(r['enemy_has_two_stations'] for r in rows[1:]),
        'enemy_plaza_owned_intervals': owned_intervals(rows, lambda r: r['plaza_owner'] == enemy),
        'first_enemy_f_in_our_home': first_home,
        'first_unescorted_f_economic_threat': threat_first,
        'our_home_enemy_capture_or_neutral_events': enemy_home_events,
        'our_all_building_losses': own_losses,
        'our_late_building_losses_from_turn145': late_losses,
        'behavioral_observations': behavioral_tags,
        'phases': phases, 'economic_threat_snapshots': threats, 'observed_turns': rows,
        'checks': {'own_spawn_move_transitions_checked': summary['own_spawn_move_transitions_checked'],
                   'own_score_and_occupation_reconstruction': True,
                   'enemy_w_nonnegative_each_turn': True, 'site_identity_result_side_match': True},
    }


def markdown(result):
    lines = ['# 공식 상대 행동 전수 조사', '',
        f"{result['coverage']['games']}경기, 상대 {result['coverage']['distinct_opponents']}팀, 관측 지형·거점 배치 {result['coverage']['distinct_initial_visible_layouts']}개. 숨은 점수와 정책이 같은 맵이라는 뜻은 아니다. 상대 코드는 제공되지 않았고 상대 버전도 미확인이다. 경기별로 분리하여 비교했다.", '',
        '## 읽는 방법', '',
        '- W 생산은 우리 실제 생산·이동을 공식 엔진으로 계산한 W 손실과 양측 동일 W 전투 손실 규칙으로 복원했다. F/S 생산은 알 수 없어 관측 최대치만 기록한다.',
        '- 명령 t는 관측 t−1에서 선택된 명령이다. 접근 지표는 관측 시점의 정보만 사용한다.',
        '- 홈은 우리 본진 쪽 x=0..4 또는 10..14, 중앙은 x=5..9이다. 경로는 장애물을 반영한다.',
        '- 경제 위협은 우리 소유 ENG/HALL에 상대 F가 현재 역 연결 포함 3이동 이내인 장면이다. 주변 1도보 칸의 상대 W 부재를 무호위 지표로 쓴다.',
        '- 조기종료를 포함한 최종 관측은 이후 명령이 없으므로 미래 위협에서 제외한다. 종료 전 관측은 규칙상 160턴 한도를 사용하며 사후에 알게 된 조기종료 시각으로 경로를 자르지 않는다.',
        '- 도착 시간은 현재 소유 역 및 즉시 생산 가능한 병원을 포함한 기하학적 하한이다. 전투·향후 생산·자원 경쟁·거점 소유 변화·상대 선택을 예측하지 않으며 실제 차단 성공을 뜻하지 않는다.',
        '- 자원 상한 관측 횟수, HALL 소유 관측 합계는 자원 손실 또는 실제 총수입이 아니다. 역 2개 소유도 실제 순간이동 사용의 증거가 아니다.',
        '- 점수는 사후 전체 공개 정보를 이용한 분석 값이다. 상대 명령이나 숨은 점수를 봇 입력으로 제공하지 않는다.', '',
        '## 전 경기 비교', '',
        '| 상대 | 우리 버전/결과 | 최종 우리:상대 | W 생산 우리/상대 | 상대 F/S 최대 관측 | 상대 F 홈 첫 진입 | 경제 위협 첫 무호위 F |',
        '|---|---|---:|---:|---:|---:|---:|']
    for p in result['profiles']:
        first, threat = p['first_enemy_f_in_our_home'], p['first_unescorted_f_economic_threat']
        units = p['enemy_peak_units_observed']
        lines.append(f"| {p['identity']['opponent']} | {p['identity']['local_version']}/{p['our_result']} | {p['final_score_our_enemy'][0]}:{p['final_score_our_enemy'][1]} | {p['our_w_production']}/{p['enemy_w_production_exact_inferred']} | {units['F']}/{units['S']} | {first['turn'] if first else '없음'} | {str(threat['observation_turn'])+'t '+threat['target_type'] if threat else '없음'} |")
    lines += ['', '## 상대별 관측과 검증할 가설', '']
    for p in result['profiles']:
        identity = p['identity']
        lines += [f"### {identity['opponent']} / {identity['round']} / 우리 {identity['local_version']}", '',
                  f"- 원본: `{p['source']['path']}`; 경기 `{p['source']['game_id']}`.",
                  '- ' + '; '.join(p['behavioral_observations']) + '.',
                  f"- 중앙광장 상대 소유 구간(양끝 포함): {p['enemy_plaza_owned_intervals'] or '없음'}."]
        events = p['our_home_enemy_capture_or_neutral_events']
        lines.append('- 우리 홈 상대 점령/중립화 이벤트: ' + (', '.join(f"{e['turn']}t {e['type']}#{e['id']} {e['from']}→{e['to']}" for e in events[:14]) if events else '없음') + (f" 외 {len(events)-14}건(JSON 참조)." if len(events) > 14 else '.'))
        phase_text = []
        for ph in p['phases']:
            concentration = ph['enemy_mean_largest_w_stack_fraction_nonempty']
            phase_text.append(f"{ph['turn_start']}–{ph['turn_end']}t W생산 {ph['enemy_w_production_exact_inferred']}, 최대덩어리 평균 {concentration:.1%}" if concentration is not None else f"{ph['turn_start']}–{ph['turn_end']}t W 없음")
        lines.append('- 구간별 상대 W: ' + '; '.join(phase_text) + '.')
        lines.append('- 가설: ' + ('우회 F 경로와 도착 우선 수비를 독립 공략형으로 검증한다.' if p['first_unescorted_f_economic_threat'] else '이 한 경기만으로 고정 전략을 단정하지 않고 전선 집중·점령 유지 지표를 개발 상대 설계에 활용한다.'))
        lines.append('')
    lines += ['## 검증 범위와 다음 실험', '',
        '- 모든 원본 SHA256을 실행 전후 비교하고 경기 ID·진영·결과를 사이트 관측과 대조했다. 기존 분석과 W 생산·최종 점수·턴 수도 재대조했다.',
        '- 동일 상대의 라운드별 차이는 우리 버전, 맵, 상대 버전이 함께 달라질 수 있으므로 인과적 개선이나 상대 업데이트로 단정할 수 없다.',
        '- 강릉이 이긴 상대 경기에도 후방 침투·종반 거점 상실이 있는지 함께 수집했다. 패배만 학습하면 쉽게 이겼던 상대에 대한 회귀를 놓칠 수 있다.',
        '- 이 자료는 1:1 승리 보장이 아니라 재현할 공격 유형과 실패 조건을 정하는 근거다. 후방 우회 F, 분산 양방향 압박, 집중 W, 막판 점령을 우리 팀 코드로 독립 구현하여 고정 상대 목록을 넓힌다.',
        '- 상대별 표본이 작고 아직 만나지 않은 팀의 행동 리플레이가 없다. 공개 순위·승패만으로 그 팀의 생산·명령을 역추정하지 않는다.', '']
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=ROOT / 'records/official/opponent-intel-20260928')
    parser.add_argument('--extra-metadata', type=Path)
    args = parser.parse_args()
    started = datetime.now(timezone.utc).isoformat()
    entries = source_entries(args.extra_metadata)
    original_hashes = {e['path']: digest(ROOT / e['path']) for e in entries}
    self_checks = self_check()
    profiles = [profile(e) for e in entries]
    prior = {}
    for filename in ('records/official/round1/analysis.json', 'records/official/round2/replay-analysis.json'):
        for match in json.loads((ROOT / filename).read_text())['matches']:
            prior[match['summary']['gameId']] = match['summary']
    crosschecks = []
    for p in profiles:
        game = p['source']['game_id']
        if game in prior:
            old = prior[game]
            assert p['enemy_w_production_exact_inferred'] == old['enemy_w_production_inferred_from_equal_w_losses']
            assert p['our_w_production'] == old['our_production']['W']
            assert p['turns'] == old['turn_count']
            assert p['final_score_our_enemy'] == [old['final_scores_reconstructed'][p['our_side']], old['final_scores_reconstructed']['K' if p['our_side'] == 'Y' else 'Y']]
            crosschecks.append(game)
    assert original_hashes == {e['path']: digest(ROOT / e['path']) for e in entries}
    source_paths = ['experiments/build_opponent_census.py', 'experiments/analyze_official_round1.py',
                    'yk-development-tools/engine/pipeline.py', 'yk-development-tools/config/balance.json',
                    'records/official/round1/site-observations.json', 'records/official/round2/site-observations.json']
    result = {
        'created_at_utc': datetime.now(timezone.utc).isoformat(), 'started_at_utc': started,
        'source_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'source_hashes': {p: digest(ROOT / p) for p in source_paths},
        'scope': 'participant-visible opponent behavior, per-game/version-separated, no hidden command recovery',
        'future_threat_filter': 'exclude final observation; nonterminal observations use rules horizon 160',
        'coverage': {'games': len(profiles), 'distinct_opponents': len({p['identity']['opponent'] for p in profiles}),
                     'by_round': dict(Counter(p['identity']['round'] for p in profiles)),
                     'our_results': dict(Counter(p['our_result'] for p in profiles)),
                     'observed_transitions': sum(p['turns'] for p in profiles),
                     'distinct_initial_visible_layouts': len({p['initial_visible_layout_sha256'] for p in profiles}),
                     'repeated_opponents_by_round': {name: [{'round': p['identity']['round'], 'our_version': p['identity']['local_version'], 'game_id': p['source']['game_id'], 'layout': p['initial_visible_layout_sha256']} for p in profiles if p['identity']['opponent'] == name]
                         for name in sorted({p['identity']['opponent'] for p in profiles}) if sum(p['identity']['opponent'] == name for p in profiles) > 1}},
        'profiles': profiles,
    }
    verification = {'status': 'passed', 'source_commit': result['source_commit'], 'source_hashes': result['source_hashes'],
        'self_checks': self_checks, 'original_hashes_unchanged': original_hashes,
        'existing_analysis_crosschecked_games': crosschecks,
        'all_site_game_identity_side_result_checks': len(profiles),
        'own_official_spawn_move_transitions_checked': result['coverage']['observed_transitions'],
        'enemy_orders_reconstructed': False, 'extra_metadata': str(args.extra_metadata) if args.extra_metadata else None,
        'started_at_utc': started, 'finished_at_utc': datetime.now(timezone.utc).isoformat()}
    args.output.mkdir(parents=True, exist_ok=True)
    for name in ('census.json', 'census.md', 'census-verification.json'):
        if (args.output / name).exists():
            raise FileExistsError(args.output / name)
    (args.output / 'census.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    (args.output / 'census.md').write_text(markdown(result))
    verification['output_sha256'] = {p: digest(args.output / p) for p in ('census.json', 'census.md')}
    (args.output / 'census-verification.json').write_text(json.dumps(verification, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'status': 'passed', 'coverage': result['coverage'], 'output': str(args.output)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
