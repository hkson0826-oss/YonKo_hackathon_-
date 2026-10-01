"""Generate bounded diagnoses from the participant-view analysis, without policy-mode inference."""
from pathlib import Path
from collections import deque, Counter
import json

OUT = Path(__file__).resolve().parent
analysis = json.loads((OUT / 'analysis.json').read_text())
games = analysis['matches']
by_name = {g['summary']['identity']['opponent']: g for g in games}

def raw(game):
    source = OUT / game['summary']['source_relative_to_archive']
    if not source.is_file():
        source = Path(game['summary']['source'])
    return json.loads(source.read_text())

def evidence(name, command_turn):
    game = by_name[name]
    source = raw(game)
    return {'gameId': source['gameId'], 'source': game['summary']['source'],
            'source_relative_to_archive': game['summary']['source_relative_to_archive'],
            'source_sha256': game['summary']['sha256'], 'command_turn': command_turn,
            'legal_input_observation_turn': command_turn - 1,
            'legal_input_observation': source['turns'][command_turn - 1]['observation'],
            'actual_own_commands': source['turns'][command_turn]['command'],
            'actual_output_observation': source['turns'][command_turn]['observation']}

items = []
for game in games:
    summary = game['summary']
    side, enemy = summary['side'], 'K' if summary['side'] == 'Y' else 'Y'
    rows = game['turns']
    trailing = next((r['turn'] for i, r in enumerate(rows)
                     if i + 10 <= len(rows) and all(
                         q['public_scores'].get(side) is not None and
                         q['public_scores'][side] < q['legal_score_bounds'][enemy][0]
                         for q in rows[i:i + 10])), None)
    leads = [r['turn'] for r in rows if r['public_scores'].get(side) is not None
             and r['public_scores'][side] > r['legal_score_bounds'][enemy][1]]
    positive = [p for p in summary['stationary_enemy_F_probes']
                if p['F_casualties_enemy_no_spawn_no_move'] > 0]
    items.append({'gameId': summary['gameId'], 'opponent': summary['identity']['opponent'],
                  'result': summary['our_result'], 'reason': summary['result']['reason'],
                  'turn_count': summary['turn_count'],
                  'first_at_least10_observations_of_guaranteed_score_deficit': trailing,
                  'last_observation_of_guaranteed_score_lead': max(leads, default=None),
                  'F_production_deaths': [summary['production']['F'], summary['casualties']['F']],
                  'early_stationary_counterexample': positive[0] if positive else None,
                  'stationary_positive_turns': len(positive),
                  'had_pre120_ten_observation_deficit': summary['turn_count'] > 140 and
                      trailing is not None and trailing < 120})

opening_raw = raw(by_name['박박이'])
obs = opening_raw['turns'][2]['observation']
start, goal = (4, 6), (4, 11)
queue, seen, route = deque([(start, [])]), {start}, None
while queue:
    (x, y), moves = queue.popleft()
    if (x, y) == goal:
        route = moves
        break
    for dx, dy, direction in [(0,-1,'U'),(1,0,'R'),(0,1,'D'),(-1,0,'L')]:
        destination = x + dx, y + dy
        if (0 <= destination[0] < 15 and 0 <= destination[1] < 15 and
                obs['map'][destination[1]][destination[0]] != '#' and destination not in seen):
            seen.add(destination)
            queue.append((destination, moves + [(x, y, direction, destination)]))
opening = {'evidence': evidence('박박이', 3), 'hospital': goal,
           'traversable_route_without_opponent_interference': route,
           'earliest_geometric_arrival_turn_from_T2': 2 + len(route),
           'actual_enemy_hospital_capture_turn': 9, 'actual_our_hospital_capture': None,
           'scope': 'Geometry from actual T2 public map and units only. Not an adversarial safety or alternate whole-game win proof.'}

stationary_game = by_name['2325']
stationary = {'evidence': evidence('2325', 16),
              'official_sdk_stationary_enemy_probe': next(p for p in stationary_game['summary']['stationary_enemy_F_probes'] if p['turn'] == 16),
              'actual_F_loss': [f for f in stationary_game['summary']['F_loss_events'] if f['turn'] == 16]}
late_game = by_name['占쏙옙']
late = {'gameId': late_game['summary']['gameId'],
        'checkpoints': [r for r in late_game['turns'] if r['turn'] in [120,140,150,153,154,155,156,157,158,159,160]],
        'redistribution_evidence': evidence('占쏙옙', 155),
        'stationary_F_loss_evidence': evidence('占쏙옙', 159),
        'stationary_F_loss_probe': next(p for p in late_game['summary']['stationary_enemy_F_probes'] if p['turn'] == 159),
        'internal_mode': None,
        'interpretation': 'Observed troop redistribution after trailing, followed by loss of three formerly owned sites. Internal policy mode and alternate full-game outcome unverified.'}

strata = {}
for key, group in [
        ('loss', [g for g in games if g['summary']['our_result'] == 'loss']),
        ('ordinary_win', [g for g in games if g['summary']['our_result'] == 'win' and not g['summary']['forfeit']]),
        ('forfeit_win', [g for g in games if g['summary']['our_win_forfeit']])]:
    strata[key] = {'games': len(group),
        'F_produced': sum(g['summary']['production']['F'] for g in group),
        'F_dead': sum(g['summary']['casualties']['F'] for g in group),
        'W_produced': sum(g['summary']['production']['W'] for g in group),
        'enemy_W_produced_inferred': sum(g['summary']['enemy_W_production_inferred'] for g in group),
        'W_production_advantage_games': sum(g['summary']['production']['W'] > g['summary']['enemy_W_production_inferred'] for g in group),
        'positive_stationary_F_loss_probe_turns': sum(p['F_casualties_enemy_no_spawn_no_move'] > 0 for g in group for p in g['summary']['stationary_enemy_F_probes'])}
strata['scope'] = 'Descriptive totals across unequal opponents, maps and game durations; not matched treatment effects or normalized unit-loss rates.'

classification = {
    'before140_instant_losses': [x['opponent'] for x in items if x['result']=='loss' and x['turn_count']<140],
    'late_instant_losses': [x['opponent'] for x in items if x['result']=='loss' and x['turn_count']>=140 and x['reason']=='instant'],
    'final_score_losses': [x['opponent'] for x in items if x['result']=='loss' and x['reason']=='score'],
    'scope': 'Exhaustive termination categories. These are not exclusive causal mechanisms; late termination alone is not proof of a newly appearing late-game defect.'}
result = {'matches': items, 'termination_classification': classification, 'outcome_strata': strata,
          'opening_geometry': opening, 'stationary_safety': stationary, 'late_reversal': late,
          'method': 'All decisions evaluated using previous observation only; no future scores, opponent commands, or source-mode inference.'}
(OUT / 'diagnosis-cases.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')

lines = [
'# 10월 1일 10:00 공식 회차 — 실패 유형과 대조 사례', '',
'전체 24경기 원본·공식 목록을 대조했습니다. 서버 제출 #9의 12승 12패이며, 승리 중 2건은 상대 기권입니다. 현재 선택 #10의 결과나 제출 ZIP 해시가 확인된 로컬 소스 결과로 해석하지 않습니다.', '',
'패배는 140턴 전 instant 4건, 141~160턴 instant 5건, 160턴 점수패 3건입니다. 관측과 실제 명령에서 문제를 특정할 수 있지만, 적 명령이 없으므로 첫 잘못된 결정을 모든 경기에서 인과적으로 확정하거나 전체 경기 승리 반사실을 만들지는 않습니다.', '',
'## 박박이: 경제 확장 누락이 첫 F 사망보다 먼저 발생', '',
'- T2 공개 관측의 F(4,6)에서 병원(4,11)까지 장애물 없는 5칸 경로가 있습니다. 실제 T3에는 오른쪽(5,6)으로 이동합니다. 북쪽 F(4,2)도 오른쪽으로 이동해 T4 방송국(6,2)을 점령합니다. 내부 목표선택 이유는 미확인입니다.',
'- 병원 직행의 기하학적 최초 도착은 T7입니다. 실제 적은 T9에 이 병원을, T11에 양쪽 병원을 점령합니다. 직행 경로는 적 반응을 포함한 안전·승리 보장이 아닙니다.',
'- 적은 T12에 HALL 두 개를 모두 점령합니다. 우리는 43턴 내내 HALL·병원을 한 번도 보유하지 못합니다. ENG 첫 점령은 우리 T10, 적 T8입니다.',
'- F는 8명 생산해 1명만 죽고 7명이 생존합니다. 첫 F 사망 T37, 첫 경제거점 상실 T38보다 경제 확보 실패가 먼저입니다. 최종 W 생산 171:229, 생존 62:120입니다.',
'- 최종 공개점수는 Y0/K미공개입니다. 당시 합법 정보로 K26–28까지만 알 수 있습니다. 숨은 HALL 점수를 정확값으로 만들지 않습니다.', '',
'## 2325: 경제 보존과 F 생존은 별개', '',
'- ENG/HALL/병원을 160턴 동안 한 번도 빼앗기지 않았고, 최초 경제 점령도 양쪽이 ENG T1/HALL T7/병원 T8로 같습니다. 그러나 F28명 생산 중 27명이 죽고 7:26으로 패배했습니다. K26은 공개 점수 필드가 아니라 당시 공개 건물 점수·대칭으로 확정한 값입니다.',
'- T16 입력인 T15 관측에 적 W2가 이미 (10,2)에 있습니다. 실제 명령 `MOVE 10 1 F 1 D`는 호위 없이 F를 그 셀로 보냅니다. 실제 사망과 함께, 공식 SDK에 우리 실제 명령·적 정지/무생산을 적용해도 F1 사망을 확인했습니다.',
'- 이는 상대가 특별한 움직임을 해야만 발생하는 위험이 아닙니다. 이 한 턴 반례를 고치면 전체 경기를 이긴다는 주장은 하지 않습니다.', '',
'## 占쏙옙: 큰 병력 우위에서도 발생한 종반 역전', '',
'- T120 공개점수 35:4, W413:102에서 T140 22:15, T150 19:16으로 줄었습니다. T153까지 19:16으로 앞서다가 T154 적이 중립 DEPOT(5,10) 4점을 얻어 19:20이 됩니다.',
'- T155의 실제 입력인 T154 관측에는 병원(2,2)의 W58, ENG(1,7)의 W17이 있습니다. 실제 명령은 병원에 W7을 추가 생산한 뒤 W65 전부를 오른쪽으로 보내고, ENG의 W17도 전부 오른쪽으로 보냅니다. 적 F/W가 (2,0)에 1/14, (2,6)에 1/16 보이는 상태입니다.',
'- 이후 ENG는 T157 중립화·T158 적 점령, 병원과 STATION(8,12)은 T158 중립화·T159 적 점령됩니다. 관측된 병력 재배치와 방어거점 상실의 연속은 확인되지만, 내부 LOCK/ALLIN 모드나 전환 조건은 추정하지 않습니다.',
'- T160에는 W548:94인데 최종 공개점수는 15:17입니다. 우리 W214는 STATION(6,2), W237은 PLAZA(7,7), W81은 DEPOT(5,10)에 있습니다. 전체 W의 532/548명이 세 셀에 집중되어 있고, 마지막 DEPOT은 아직 중립입니다.',
'- 별도로 T159의 `MOVE 13 12 F 1 L`은 입력에 적 W1이 보이는 병원(12,12)에 무호위 진입합니다. 실제 F1 사망 및 정지적 SDK 반례도 확인했습니다. 종반 점수 계획과 당턴 F 안전 모두 관찰됩니다.', '',
'## 승리와 접전 대조', '',
'- 200OK전은 ENG를 우리 T6/적 T18, 병원을 우리 T5/적 T18에 확보하고 T39에 35:0으로 끝납니다. 공주전도 경제 첫 점령이 전반적으로 앞서고 W 생산 312:57, T51에 34:0입니다. 경제 선점이 잘 된 승리 사례지만 맵·상대가 달라 인과 효과의 크기로 비교할 수 없습니다.',
'- 조선김전은 18:15, 인공저능전은 17:16으로 이겼습니다. 둘 다 초반 10개 관측 연속 확정 열세가 있었으므로 첫 장기 열세가 곧 회복불능은 아닙니다. 인공저능전은 W 생산 869:905로 뒤져도 이겼습니다. W 생산 총량만으로 결과를 설명할 수 없습니다.',
'- 일반 승리 10건의 F 생산/사망은 104/45, 패배 12건은 255/195입니다. W 생산 우위는 일반 승리 9/10건, 패배 1/12건입니다. 경기 길이·맵·상대가 다르므로 이 합계는 기술 통계이며 정규화한 정책 효과가 아닙니다.',
'- 신촌도 우리땅 T24와 개우진보러갈까 T17은 상대 기권 승리입니다. 마지막 프레임은 BEFORE_COMMANDS이며 실제 전이는 각각 23·16회입니다. 우리 응답 status가 ok여도 마지막 생산·이동은 실행되지 않았습니다. 기권 원인은 원본에 없습니다.', '',
'## 종료 턴과 열세 시작', '',
'아래 열세 시작은 그 시점까지의 합법 점수 하한으로 우리 열세가 10개 연속 관측에서 확실한 첫 턴입니다. 회복불가능 판정이나 최초 인과적 오류를 뜻하지 않습니다.', '',
'| 상대 | 결과·종료 | 10관측 연속 확정열세 시작 | 마지막 확정우세 | F생산/사망 | 첫 정지적 F손실 반례 |',
'|---|---|---:|---:|---:|---|']
for item in sorted(items, key=lambda x: (x['result'], x['turn_count'], x['opponent'])):
    probe = item['early_stationary_counterexample']
    fmt = lambda value: '없음' if value is None else str(value)
    lines.append(f"| {item['opponent']} | {item['result']} T{item['turn_count']} {item['reason']} | {fmt(item['first_at_least10_observations_of_guaranteed_score_deficit'])} | {fmt(item['last_observation_of_guaranteed_score_lead'])} | {item['F_production_deaths'][0]}/{item['F_production_deaths'][1]} | {'T'+str(probe['turn'])+', F'+str(probe['F_casualties_enemy_no_spawn_no_move']) if probe else '없음'} |")
lines += ['', '생산·이동 장부 2,712턴을 공식 SDK로 검사했습니다. 상대 명령이 없어 전체 전이를 재현한 것은 아닙니다. 관측된 우리 응답 2,714개는 모두 status ok이며 일반 턴 최대 214ms, 첫 턴 최대 302ms입니다. 상대 실행 시간·메모리·기권 원인은 미확인입니다.', '',
          'Root가 확인한 [10/1 10:42 공식 FAQ](https://yonsei-vs-korea-hackathon.kr/announcements)는 봇별 0.25 vCPU, 일반 300ms/첫 3초의 실제 경과시간 제한을 명시합니다. 위 수치는 공식 리플레이 자체의 응답 기록이며, 별도 로컬 무제한 대전과 동일한 환경이라고 주장하지 않습니다.', '',
          '재현: `python3 -B analyze.py` 후 `python3 -B cases.py`. 출력은 스크립트 폴더에 저장되며, 보관 위치에서는 ../raw 원본과 저장소의 experiments/analyze_official_round1.py를 자동으로 찾습니다. /tmp 실행에는 고정 clone 경로를 사용합니다. summary.json은 전체 집계, analysis.json은 모든 턴 장부, diagnosis-cases.json은 공개 입력·실제 명령을 포함한 세 대표 사례입니다. 원본·소스·Git은 변경하지 않았습니다.']
(OUT / 'cases.md').write_text('\n'.join(lines) + '\n')
print(json.dumps({'termination_classification': classification, 'outcome_strata': strata}, ensure_ascii=False, indent=2))
