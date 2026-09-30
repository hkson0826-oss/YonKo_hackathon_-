"""Summarize a completed v3 campaign and retain same-map outcome-change evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
from cpu_sweep import aggregate
from league_campaign import load_rows, point, crossplay_table
from v3_campaign import BASELINE, FIXED_OPPONENTS, SOURCE_SHA, paired, league


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(ok, message):
    if not ok:
        raise ValueError(message)


def key(row):
    return row['candidate'], row['map_seed'], row['team'], row['opponent']


def replay_path(arena, stage, row):
    relative = Path('runs') / stage / row['replay']
    path = (arena / relative).resolve()
    require(path.is_relative_to((arena / 'runs' / stage).resolve()) and path.is_file(),
            f'Missing or escaped replay: {relative}')
    return relative.as_posix()


def health(rows):
    errors = [r for r in rows if r['status'] != 'complete']
    forfeits = [r for r in rows if r.get('forfeit') or r.get('result', {}).get('reason') == 'forfeit']
    mutual = [r for r in forfeits if r.get('result', {}).get('forfeit', {}).get('team') == 'both']
    return {'errors': len(errors), 'forfeits': len(forfeits), 'mutual_forfeits': len(mutual),
            'runtime_gate_passed': not errors and not forfeits,
            'events': [{'job_id': r['job_id'], 'candidate': r['candidate'], 'opponent': r['opponent'],
                        'map_seed': r['map_seed'], 'team': r['team'], 'status': r['status'],
                        'result': r.get('result'), 'error': r.get('error'), 'replay': r.get('replay')}
                       for r in rows if r in errors or r in forfeits]}


def validate_stage(arena, stage, manifest, declared_matches):
    directory = arena / 'runs' / stage
    summary, plan, jobs = (read(directory / name) for name in ('summary.json', 'plan.json', 'jobs.json'))
    require(plan == read(arena / 'plans' / (stage + '.json')), f'{stage}: plan copies differ')
    expected = league.make_jobs(plan, manifest['bots'])
    require(bool(expected), f'{stage}: empty stage schedule')
    require({r['job_id']: key(r) for r in jobs} == {r['job_id']: key(r) for r in expected}
            and len(jobs) == len(expected), f'{stage}: job schedule differs from plan')
    rows = load_rows(directory)
    require(len(rows) == len(expected) == len({r['job_id'] for r in rows}), f'{stage}: incomplete or duplicate jobs')
    require({r['job_id']: key(r) for r in rows} == {r['job_id']: key(r) for r in expected}, f'{stage}: unexpected jobs')
    require(all(r['status'] in ('complete', 'error') for r in rows), f'{stage}: unfinished status')
    finished = sum(r['status'] == 'complete' for r in rows)
    require(summary['expected_jobs'] == summary['finished_jobs'] == len(rows), f'{stage}: incomplete summary')
    require(summary['overall']['matches'] == declared_matches == finished
            and summary['overall']['errors'] == len(rows) - finished, f'{stage}: summary/result count mismatch')
    require(summary['overall']['forfeits'] == health(rows)['forfeits'], f'{stage}: forfeit count mismatch')
    for row in rows:
        if row['status'] == 'complete':
            replay_path(arena, stage, row)
    return rows, plan


def evidence(arena, stage, old, new):
    side = new['team']
    return {'map_seed': new['map_seed'], 'opponent': new['opponent'], 'team': side,
            'baseline': BASELINE, 'candidate': new['candidate'],
            'baseline_points': point(old), 'candidate_points': point(new),
            'old_result': old['result'], 'new_result': new['result'],
            'old_replay': replay_path(arena, stage, old), 'new_replay': replay_path(arena, stage, new),
            'old_job_id': old['job_id'], 'new_job_id': new['job_id'],
            'old_diagnostics': old.get('diagnostics', {}).get(side),
            'new_diagnostics': new.get('diagnostics', {}).get(side),
            'old_trace_sha256': old.get('logical_trace_sha256'), 'new_trace_sha256': new.get('logical_trace_sha256'),
            'contains_forfeit': bool(old.get('forfeit') or new.get('forfeit'))}


def candidate_analysis(arena, stage, rows, name, bot, fixed, challenge):
    own = [r for r in rows if r['candidate'] == name]
    pool_stats = {}
    for pool, members in (('fixed', fixed), ('challenge', challenge)):
        selected = [r for r in own if r['opponent'] in members]
        pool_stats[pool] = {'all': aggregate(selected),
                            **{side: aggregate([r for r in selected if r['team'] == side]) for side in 'YK'}}
    comparisons = {pool: {side: paired(rows, name, side, opponents=opponents)
                          for side in 'YK'}
                   for pool, opponents in (('all', None), ('fixed', fixed), ('challenge', challenge))}
    opponents = {}
    for op in sorted({r['opponent'] for r in own}):
        matches = [r for r in own if r['opponent'] == op]
        opponents[op] = {'pool': 'fixed' if op in fixed else 'challenge', 'all': aggregate(matches),
                         **{side: aggregate([r for r in matches if r['team'] == side]) for side in 'YK'},
                         'comparisons': {side: paired(rows, name, side, opponents={op}) for side in 'YK'}}
    indexed = {key(r): r for r in rows if r['status'] == 'complete'}
    changes = {'improvements': [], 'regressions': [], 'loss_to_win': [], 'win_to_loss': []}
    if name != BASELINE:
        for row in sorted(own, key=lambda r: (r['map_seed'], r['opponent'], r['team'])):
            if row['status'] != 'complete':
                continue
            old = indexed.get((BASELINE, row['map_seed'], row['team'], row['opponent']))
            if old is None or point(old) == point(row):
                continue
            item = evidence(arena, stage, old, row)
            changes['improvements' if point(row) > point(old) else 'regressions'].append(item)
            if point(old) == 0 and point(row) == 1:
                changes['loss_to_win'].append(item)
            if point(old) == 1 and point(row) == 0:
                changes['win_to_loss'].append(item)
    involved = [r for r in rows if name in (r['candidate'], r['opponent'])]
    return {'source_sha256': bot['source_sha256'], 'family': bot.get('family'), 'parameters': bot.get('parameters', {}),
            'stats': {'all': aggregate(own), **{side: aggregate([r for r in own if r['team'] == side]) for side in 'YK'}},
            'comparisons': comparisons, 'pool_stats': pool_stats, 'per_opponent': opponents, 'outcome_changes': changes,
            'runtime_health_in_either_role': health(involved),
            'comparison_scope': 'Against v3 only; parent parameter is provenance, not an ablation or causal contribution estimate'}


def interval(value):
    if value is None:
        return '대응 경기 없음'
    low, high = value['map_cluster_bootstrap_95pct']
    return f"{100 * value['point_rate_difference']:+.1f}pp [{100 * low:+.1f}, {100 * high:+.1f}]"


def record(stats):
    return '/'.join(str(stats[k]) for k in ('wins', 'draws', 'losses'))


def analyze(arena):
    arena = arena.resolve()
    result, manifest, policy = (read(arena / name) for name in ('campaign-result.json', 'manifest.json', 'campaign-policy.json'))
    require(result['status'] == 'complete', 'Campaign is incomplete')
    require(result['baseline'] == policy['baseline'] == BASELINE, 'Expected a v3 campaign')
    require(manifest['bots'][BASELINE]['source_sha256'] == SOURCE_SHA, 'Submitted v3 source hash differs')
    require(result['phase'] in ('explore', 'final'), 'Unknown campaign phase')
    stages = ['smoke', 'development'] + (['selection', 'holdout', 'crossplay'] if result['phase'] == 'final' else [])
    require(set(result['stage_match_counts']) == set(stages), 'Missing or unexpected campaign stages')
    fixed, opponents = set(policy['fixed_opponents']), set(policy['opponents'])
    require(fixed == set(FIXED_OPPONENTS) and len(policy['fixed_opponents']) == 6, 'Fixed opponent pool changed')
    require(fixed <= opponents and len(opponents) == len(policy['opponents']), 'Opponent pool is duplicated or incomplete')
    challenge = opponents - fixed
    require(len(challenge) in (0, 2), 'Expected zero or two locked challenge opponents')
    if result['phase'] == 'final':
        require(len(challenge) == 2, 'Final validation requires the additional opponent pool')
    loaded = {stage: validate_stage(arena, stage, manifest, result['stage_match_counts'][stage]) for stage in stages}
    require(sum(result['stage_match_counts'].values()) == result['total_matches'], 'Campaign match total differs')
    all_rows = [row for rows, _ in loaded.values() for row in rows]
    overall_health = health(all_rows)
    require(result['errors'] == overall_health['errors'] and result['forfeits'] == overall_health['forfeits'], 'Campaign health counts differ')
    promotion = {'scope': 'Development only; no submission promotion', 'primary': None}
    if result['phase'] == 'final':
        lock = read(arena / 'locked-finalists.json')
        primary = lock['primary_candidate']
        require(lock['baseline'] == BASELINE and lock['finalists'][0] == primary == result['primary_candidate'], 'First locked primary differs')
        require(lock['finalists'] == result['finalists'], 'Locked finalist list differs')
        require(set(loaded['holdout'][1]['candidates']) == {BASELINE, *lock['finalists']}, 'Holdout plan differs from locked finalists')
        decisions = result['promotion_decisions']
        require(set(decisions) == set(lock['finalists']), 'Promotion decisions differ from locked finalists')
        for name in [BASELINE, *lock['finalists']]:
            require(lock['source_sha256'][name] == manifest['bots'][name]['source_sha256'], 'Locked finalist source changed')
        for name, decision in decisions.items():
            require(decision['baseline'] == BASELINE and decision['promoted'] == all(decision['gates'].values()), 'Promotion decision/gates disagree')
        require(result['recommended'] == (primary if decisions[primary]['promoted'] else BASELINE), 'Recommendation reselects or bypasses the primary gate')
        promotion = {'scope': 'Only the first finalist locked before holdout can promote; packaging and additional audit remain separate',
                     'primary': primary, 'lock_sha256': sha(arena / 'locked-finalists.json'), 'decisions': decisions,
                     'recommended': result['recommended']}
    output = {'campaign': result, 'baseline': BASELINE, 'fixed_opponents': sorted(fixed), 'challenge_opponents': sorted(challenge),
              'stages': {}, 'promotion_review': promotion, 'overall_health': overall_health,
              'analyzer_sha256': sha(Path(__file__)),
              'dependency_sha256': {name: sha(Path(__file__).parent / name) for name in
                                    ('v3_campaign.py', 'cpu_sweep.py', 'league_campaign.py', 'local_league.py')},
              'input_sha256': {name: sha(arena / name) for name in ('campaign-result.json', 'manifest.json', 'campaign-policy.json')},
              'inference_limits': ['Development/selection confidence intervals do not correct multiple-candidate selection bias.',
                                   'Map-cluster uncertainty is not leaderboard adjusted score or unseen-opponent win probability.',
                                   'Forfeit draws are runtime failures, not successful draws; paired scores including them are descriptive only.',
                                   'No parent contribution estimate is made; all contrasts use v3.']}
    lines = ['# v3 기준 반복 대전 분석', '',
             f"단계 `{result['phase']}` · 완료 {result['total_matches']:,}경기 · 추천 `{result['recommended']}`.", '',
             f"고정 상대 {len(fixed)}종과 추가 상대 {len(challenge)}종을 분리했다. 내부 대전 성적이며 리더보드 보정 점수가 아니다.", '',
             f"오류 {overall_health['errors']}, 몰수 {overall_health['forfeits']}, 양쪽 동시 몰수 {overall_health['mutual_forfeits']}. "
             '상호 몰수 무승부도 실행 건강성 실패로 센다.']
    for stage, (rows, plan) in loaded.items():
        stage_health = health(rows)
        section = {'plan': plan, 'health': stage_health, 'stats': aggregate(rows),
                   'results_sha256': sha(arena / 'runs' / stage / 'results.jsonl')}
        output['stages'][stage] = section
        if stage not in ('development', 'selection', 'holdout'):
            if stage == 'crossplay':
                section['crossplay'] = crossplay_table(rows)
            continue
        require(set(plan['opponents']) == opponents and BASELINE in plan['candidates'], f'{stage}: wrong comparison pool or missing baseline')
        names = sorted(set(r['candidate'] for r in rows))
        section['candidates'] = {name: candidate_analysis(arena, stage, rows, name, manifest['bots'][name], fixed, challenge) for name in names}
        names.sort(key=lambda name: (-(section['candidates'][name]['stats']['Y']['point_rate'] or 0), name))
        lines += ['', f'## {stage}', '',
                  '| 후보 | Y 승/무/패 | K 승/무/패 | Y 차이·95% 구간 | 고정 Y 차이 | 추가 Y 차이 | p95 / 최대 | 오류/몰수 |',
                  '|---|---|---|---|---|---|---:|---:|']
        for name in names:
            entry = section['candidates'][name]
            stats, cmp = entry['stats'], entry['comparisons']
            latency = stats['all']
            ms = lambda value: '—' if value is None else f'{value:.1f}ms'
            lines.append(f"| {name} | {record(stats['Y'])} | {record(stats['K'])} | {interval(cmp['all']['Y'])} | "
                         f"{interval(cmp['fixed']['Y'])} | {interval(cmp['challenge']['Y'])} | "
                         f"{ms(latency['p95_turn_ms'])} / {ms(latency['max_turn_ms'])} | {latency['errors']}/{latency['forfeits']} |")
        lines += ['', '후보별 K 차이, 상대·진영별 승무패와 응답 시간, 양 진영의 패→승·승→패 리플레이 경로는 [analysis.json](analysis.json)에 있다.', '',
                  '개발·선택 구간은 후보 다중 비교의 선택 편향을 보정하지 않는다. 수정에 사용한 맵은 이후 독립 검증에 재사용하지 않는다.']
    lines += ['', '## 채택 해석', '', promotion['scope']]
    if promotion['primary'] is not None:
        lines += ['', f"먼저 고정한 주 후보: `{promotion['primary']}`. 두 번째 후보의 holdout 성적으로 주 후보를 바꾸지 않는다.", '',
                  '| 주 후보 게이트 | 통과 |', '|---|---|']
        for name, passed in promotion['decisions'][promotion['primary']]['gates'].items():
            lines.append(f'| {name} | {passed} |')
    lines += ['', '[고정 소스](manifest.json) · [사전 계획](campaign-policy.json) · [기계 판독 분석](analysis.json)', '',
              '상세 로그의 차이는 관찰이며 인과 설명은 아니다. 다음 수정은 합법 관측·공식 전이의 반사실 검증으로 확인한다.']
    (arena / 'analysis.json').write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n')
    (arena / 'README.md').write_text('\n'.join(lines) + '\n')
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('arena', type=Path)
    analyze(parser.parse_args().arena)
