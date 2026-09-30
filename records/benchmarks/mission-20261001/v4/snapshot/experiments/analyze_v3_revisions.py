"""Compare complete revision-2 development runs to their declared parents."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze_v3_diversity import key, outcome, point, rate, validate_schedule
from league_campaign import paired_interval
from local_league import make_jobs
from v3_campaign import FIXED_OPPONENTS, NEW_MODULES

PARENTS = {
    'f3_v2_soft_matching': 'f3_matching',
    'f3_v2_movement_matching': 'f3_matching',
    'f3_v2_safe_econ_mission': 'f3_econ_mission',
    'f3_v2_warrior_reserve': 'v3',
    's3_v2_screen_paired_guard': 's3_screen_refine',
    's3_v2_screen_roundrobin': 's3_screen_refine',
    's3_v2_screen_continuation': 's3_screen_refine',
    's3_v2_screen_intact_base': 's3_screen_refine',
    'r3_v2_y_tail': 'r3_lower_tail',
    'r3_v2_pareto_local': 'r3_lower_tail',
    'r3_v2_tail_recheck': 'r3_lower_tail',
    'r3_v2_mean_control': 'v3',
}
NOTES = {
    'f3_v2_soft_matching': '평가 보정 강도를 바꾼다. 최적 강도나 전체 인과 효과의 증명은 아니다.',
    'f3_v2_movement_matching': '초기 선택 척도·국소 재평가 경계·소모 시간이 함께 달라진다.',
    'f3_v2_safe_econ_mission': '새 임무의 수용 조건을 바꾸며 원래 정책의 위험 행동 전체를 제거하지 않는다.',
    'f3_v2_warrior_reserve': '보유 거점 W 잔류 후보와 그 평가 비용을 함께 추가한다.',
    's3_v2_screen_paired_guard': '상대별 비악화 조건과 추가 평가 비용을 함께 바꾼다.',
    's3_v2_screen_roundrobin': '출발지 순서와 얕은 평가 마감 시간이 함께 달라진다.',
    's3_v2_screen_continuation': '다른 후속 정책 검사와 추가 평가 비용을 함께 바꾼다.',
    's3_v2_screen_intact_base': '기본 탐색의 65ms/135ms 분할과 확장에 남는 시간이 달라진다.',
    'r3_v2_y_tail': 'Y는 꼬리 목적, K는 원본 v3 함수다. 진영 특화 가설이며 벽시계 경계는 영향을 줄 수 있다.',
    'r3_v2_pareto_local': '초기 정책 선택과 국소 수용 조건을 함께 바꾼다.',
    'r3_v2_tail_recheck': '부모/꼬리 탐색 시간 분할과 완결 재검사 조건을 함께 바꾼다.',
    'r3_v2_mean_control': 'v3와 목적식은 같지만 상대 a_clean·deadline 처리도 다르므로 완전한 단일 요소 제거 실험이 아니다.',
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def health(rows):
    errors = [r for r in rows if r['status'] != 'complete']
    forfeits = [r for r in rows if r.get('forfeit') or r.get('result', {}).get('reason') == 'forfeit']
    return {'errors': len(errors), 'forfeits': len(forfeits),
            'mutual_forfeits': sum(r.get('result', {}).get('forfeit', {}).get('team') == 'both' for r in forfeits),
            'healthy': not errors and not forfeits,
            'problem_job_ids': sorted({r['job_id'] for r in errors + forfeits})}


def validate_inputs(manifest, policy, progress, plan, copied_plan, jobs, rows, summary, session):
    require('development' in progress.get('completed', []), 'progress.json does not mark development completed')
    require(manifest.get('status') == 'ready', 'Frozen arena is not ready')
    revisions = manifest.get('population_spec', {}).get('module_revisions', {})
    require(all(revisions.get(name) == 2 for name in NEW_MODULES), 'Expected revision-2 modules')
    require(plan == copied_plan, 'Development plan copies differ')
    require(plan['map_seeds'] and len(plan['map_seeds']) == len(set(plan['map_seeds'])), 'Empty or repeated maps')
    require(len(plan['candidates']) == len(set(plan['candidates'])), 'Repeated candidates')
    require(len(plan['opponents']) == len(set(plan['opponents'])), 'Repeated opponents')
    needed = set(PARENTS) | set(PARENTS.values())
    require(needed <= set(plan['candidates']), 'Development must contain all 12 revisions and their declared parents')
    require(policy.get('baseline') == 'v3', 'Expected v3 campaign baseline')
    require(plan['map_seeds'] == policy['map_sets']['development'], 'Development map policy differs')
    require(plan['opponents'] == policy['opponents'], 'Opponent policy differs')
    require(policy['fixed_opponents'] == FIXED_OPPONENTS, 'Expected the six frozen fixed opponents')
    lock = policy.get('challenge_lock') or {}
    added = lock.get('opponents', [])
    require(len(added) == len(set(added)) == 2 and not set(added) & set(FIXED_OPPONENTS), 'Expected two distinct locked added opponents')
    require(plan['opponents'] == [*FIXED_OPPONENTS, *added], 'Fixed/added pools do not cover the schedule exactly')
    for name in added:
        require(lock.get('source_sha256', {}).get(name) == manifest['bots'][name]['source_sha256'], 'Added opponent source lock mismatch')
    validate_schedule(plan, jobs, rows, summary, session)
    generated = make_jobs(plan, manifest['bots'])
    require({r['job_id']: (r['candidate'], *key(r)) for r in jobs} ==
            {r['job_id']: (r['candidate'], *key(r)) for r in generated}, 'Job IDs differ from frozen schedule conditions')
    complete = sum(r['status'] == 'complete' for r in rows)
    require(summary['overall']['matches'] == complete, 'Summary completed match count differs')
    require(summary['overall']['forfeits'] == health(rows)['forfeits'], 'Summary misses a forfeit result')
    for row in rows:
        if row['status'] != 'complete':
            continue
        require(type(row.get('win')) is bool and type(row.get('draw')) is bool, 'Outcome flags must be booleans')
        outcome(row)
        result = row.get('result')
        if result is not None:
            require(row['win'] == (result['winner'] == row['team']) and row['draw'] == (result['winner'] == 'DRAW'), 'Result and outcome flags differ')
            other = 'K' if row['team'] == 'Y' else 'Y'
            require(row['score_margin'] == result['score'][row['team']] - result['score'][other], 'Result score margin differs')
    return {'all': plan['opponents'], 'fixed': FIXED_OPPONENTS, 'added': added}


def paired_stats(new, old, candidate, parent, side):
    require({key(r) for r in new} == {key(r) for r in old}, 'Incomplete exact parent pairing')
    new_rate, old_rate = rate(new), rate(old)
    # Reuse the existing map-cluster bootstrap with its expected baseline ID.
    aliased = [{**r, 'candidate': 'revision'} for r in new] + [{**r, 'candidate': 'v2'} for r in old]
    interval = paired_interval(aliased, 'revision', side)
    require(interval is not None, 'No paired games for side')
    interval.update(candidate=candidate, baseline=parent, paired_games=len(new))
    return {'candidate': new_rate, 'parent': old_rate,
            'wdl_count_difference': {k: new_rate[k] - old_rate[k] for k in ('wins', 'draws', 'losses')},
            'point_rate_difference': new_rate['point_rate'] - old_rate['point_rate'],
            'mean_score_margin_difference': sum(r['score_margin'] for r in new) / len(new) - sum(r['score_margin'] for r in old) / len(old),
            'interval': interval}


def evidence(new, old):
    return {'map_seed': new['map_seed'], 'opponent': new['opponent'], 'team': new['team'],
            'candidate_job_id': new['job_id'], 'parent_job_id': old['job_id'],
            'candidate_outcome': outcome(new), 'parent_outcome': outcome(old),
            'point_difference': point(new) - point(old),
            'candidate_score_margin': new['score_margin'], 'parent_score_margin': old['score_margin'],
            'candidate_replay': str(Path('runs/development') / new['replay']) if new.get('replay') else None,
            'parent_replay': str(Path('runs/development') / old['replay']) if old.get('replay') else None}


def compare(rows, candidate, parent, pools):
    new = [r for r in rows if r['candidate'] == candidate]
    old = [r for r in rows if r['candidate'] == parent]
    require(new and old, 'Candidate or parent has no rows')
    require(len(new) == len({key(r) for r in new}) and len(old) == len({key(r) for r in old}), 'Duplicate paired condition')
    require({key(r) for r in new} == {key(r) for r in old}, 'Incomplete exact parent pairing')
    checked = health(new + old)
    report = {'candidate': candidate, 'parent': parent, 'interpretation': NOTES[candidate], 'health': checked}
    if not checked['healthy']:
        return {**report, 'status': 'excluded_unhealthy_pair', 'pools': {}, 'matched_cases': {},
                'exclusion': 'No partial healthy-subset scoring: an error or forfeit excludes this entire candidate-parent comparison'}
    report.update(status='paired_complete', pools={})
    for pool, opponents in pools.items():
        report['pools'][pool] = {side: paired_stats(
            [r for r in new if r['team'] == side and r['opponent'] in opponents],
            [r for r in old if r['team'] == side and r['opponent'] in opponents], candidate, parent, side)
            for side in 'YK'}
    indexed = {key(r): r for r in old}
    changes = [evidence(r, indexed[key(r)]) for r in sorted(new, key=key) if outcome(r) != outcome(indexed[key(r)])]
    report['matched_cases'] = {
        'loss_to_win': [r for r in changes if r['parent_outcome'] == 'L' and r['candidate_outcome'] == 'W'],
        'win_to_loss': [r for r in changes if r['parent_outcome'] == 'W' and r['candidate_outcome'] == 'L'],
        'all_outcome_changes': changes,
        'score_margin_sign_reversals': [evidence(r, indexed[key(r)]) for r in sorted(new, key=key)
                                        if r['score_margin'] * indexed[key(r)]['score_margin'] < 0]}
    return report


def markdown(report):
    lines = ['# v3 2차 수정과 보존 부모 비교', '',
             f"완료된 development {report['development_rows']}행, 서로 다른 맵 {report['maps']}개를 읽었다. 고정 상대 6종과 추가 상대 2종을 구분했다. 승점률은 승 1·무 0.5·패 0이며 리더보드 보정 점수가 아니다.", '',
             '같은 초기 맵·상대·진영 조건을 정확히 짝지었다. 경기 중간 상태가 같다는 의미나 단일 변경의 인과 증명은 아니다. 구간은 맵 단위 5,000회 bootstrap이며 상대별 경기를 독립 표본으로 늘려 세지 않는다.', '',
             '| 수정 후보 → 부모 | Y 후보/부모 승·무·패 | K 후보/부모 승·무·패 | 전체 Y 차이 [95% 구간] | 전체 K 차이 [95% 구간] | 고정 Y 차이 | 추가 Y 차이 |',
             '|---|---|---|---|---|---|---|']
    def wdl(r):
        return f"{r['wins']}·{r['draws']}·{r['losses']}"
    def delta(s, ci=True):
        value = f"{100*s['point_rate_difference']:+.1f}pp"
        if ci:
            low, high = s['interval']['map_cluster_bootstrap_95pct']
            value += f' [{100*low:+.1f}, {100*high:+.1f}]'
        return value
    for item in report['comparisons']:
        title = f"{item['candidate']} → {item['parent']}"
        if item['status'] != 'paired_complete':
            lines.append(f"| {title} | 건강성 실패로 전체 쌍 제외 | — | — | — | — | — |")
            continue
        pools = item['pools']; y, k = pools['all']['Y'], pools['all']['K']
        lines.append(f"| {title} | {wdl(y['candidate'])}/{wdl(y['parent'])} | {wdl(k['candidate'])}/{wdl(k['parent'])} | {delta(y)} | {delta(k)} | {delta(pools['fixed']['Y'],False)} | {delta(pools['added']['Y'],False)} |")
    lines += ['', '## 구현 차이와 해석', '']
    lines += [f"- `{name}` → `{parent}`: {NOTES[name]}" for name, parent in PARENTS.items()]
    lines += ['', 'fixed/added 각각의 Y/K 승무패·차이·95% 구간, 오류/몰수 job ID, 패→승·승→패 및 점수차 부호 반전의 두 경기 ID·리플레이 경로는 JSON에 있다.', '',
              '개발 자료로 후보를 여러 번 수정하고 부모를 선택했으므로 선택 편향과 다중 비교가 남는다. CI는 이를 보정하지 않으며 미지의 실제 참가자에 대한 승률 구간도 아니다. 비교에는 시간 분할·평가·수용 조건 등 구현 묶음의 차이가 포함된다. 이 진단은 기존 후보 선정·상대 잠금·승격 규칙을 변경하지 않으며 별도 선택/holdout 결과를 대체하지 않는다.', '',
              f"전체 개발 건강성: 오류 {report['health']['errors']}, 몰수 {report['health']['forfeits']}, 양쪽 동시 몰수 {report['health']['mutual_forfeits']}. 오류나 몰수가 포함된 후보-부모 쌍은 정상 경기 일부만 골라 계산하지 않았다."]
    return '\n'.join(lines) + '\n'


def analyze(arena, output=None):
    arena = Path(arena)
    progress_path = arena / 'progress.json'
    progress_bytes = progress_path.read_bytes()
    progress = json.loads(progress_bytes)
    require('development' in progress.get('completed', []), 'progress.json does not mark development completed')
    folder = arena / 'runs/development'
    sessions = sorted(folder.glob('session-*.json'))
    require(sessions, 'Missing development session')
    paths = {'manifest': arena/'manifest.json', 'policy': arena/'campaign-policy.json',
             'plan': folder/'plan.json', 'copied_plan': arena/'plans/development.json',
             'jobs': folder/'jobs.json', 'summary': folder/'summary.json', 'session': sessions[-1],
             'results': folder/'results.jsonl'}
    raw = {name: path.read_bytes() for name, path in paths.items()}
    parsed = {name: json.loads(data) for name, data in raw.items() if name != 'results'}
    rows = [json.loads(line) for line in raw['results'].decode().splitlines() if line.strip()]
    pools = validate_inputs(progress=progress, rows=rows, **parsed)
    manifest, plan = parsed['manifest'], parsed['plan']
    report = {'status': 'completed_development_parent_diagnostic', 'created_utc': datetime.now(timezone.utc).isoformat(),
              'scope': 'Development revision-parent comparison only; no candidate or opponent reselection',
              'source_commit': manifest.get('source_commit'), 'development_rows': len(rows),
              'maps': len(plan['map_seeds']), 'map_seeds': plan['map_seeds'], 'pools': pools,
              'parent_mapping': PARENTS, 'health': health(rows),
              'comparisons': [compare(rows, candidate, parent, pools) for candidate, parent in PARENTS.items()],
              'manifest_declared_source_sha256': {name: manifest['bots'][name]['source_sha256']
                                                  for name in set(PARENTS) | set(PARENTS.values())},
              'limitations': ['Development selection and repeated revision bias; intervals are not multiplicity-adjusted',
                             'Matched initial conditions, not matched intermediate states or isolated causal interventions',
                             'Implementation bundles and cooperative wall-clock boundaries can change together',
                             'Fixed and development-selected added opponents do not represent all actual participants'],
              'input_sha256': {name: hashlib.sha256(data).hexdigest() for name, data in {**raw, 'progress': progress_bytes}.items()}}
    require(all(path.read_bytes() == raw[name] for name, path in paths.items()), 'Development input changed during analysis')
    prefix = Path(output) if output else arena/'revision-comparison'
    targets = [prefix.with_suffix('.json'), prefix.with_suffix('.md')]
    if any(path.exists() for path in targets):
        raise FileExistsError('Revision comparison output exists; choose a new prefix')
    prefix.parent.mkdir(parents=True, exist_ok=True)
    targets[0].write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    targets[1].write_text(markdown(report))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('arena', type=Path)
    parser.add_argument('--output', type=Path, help='New .json/.md output prefix')
    args = parser.parse_args()
    report = analyze(args.arena, args.output)
    print(json.dumps({'status': report['status'], 'comparisons': len(report['comparisons']),
                      'healthy_comparisons': sum(r['status'] == 'paired_complete' for r in report['comparisons'])}, ensure_ascii=False))
