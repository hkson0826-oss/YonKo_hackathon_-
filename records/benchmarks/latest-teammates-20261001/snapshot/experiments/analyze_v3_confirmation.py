"""Check and summarize the one-shot s3 confirmation; never run or reselect bots."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
import v3_confirmation as confirmation
from analyze_v3_campaign import health, interval, read, record, require, sha, validate_stage
from cpu_sweep import aggregate
from league_campaign import crossplay_table
from v3_campaign import paired

BASELINE, PRIMARY = confirmation.BASELINE, confirmation.PRIMARY
STAGES = {'final': ('smoke', 'holdout', 'crossplay'), 'audit': ('audit',)}
COUNTS = {'smoke': 20, 'holdout': 4608, 'crossplay': 60, 'audit': 1728}


def normalized(value):
    return json.loads(json.dumps(value))


def outcome_check(row):
    if row['status'] != 'complete':
        return
    result = row['result']
    winner, side = result['winner'], row['team']
    require(winner in ('Y', 'K', 'DRAW'), 'Unknown raw winner')
    require(type(row['win']) is bool and type(row['draw']) is bool,
            'Outcome flags must be booleans')
    require(row['win'] == (winner == side) and row['draw'] == (winner == 'DRAW'),
            'Raw winner and outcome flags differ')
    other = 'K' if side == 'Y' else 'Y'
    require(row['score_margin'] == result['score'][side] - result['score'][other],
            'Raw score and margin differ')
    require(bool(row.get('forfeit')) == (result.get('reason') == 'forfeit'),
            'Raw result and forfeit flag differ')


def load_completed(arena, phase, original_lock=None):
    """Reject live, missing, duplicate or differently locked data before statistics."""
    arena = Path(arena).resolve()
    files = {name: arena / name for name in
             ('campaign-result.json', 'manifest.json', 'campaign-policy.json',
              'locked-finalists.json', 'progress.json')}
    result, manifest, policy, lock, progress = (read(path) for path in files.values())
    stages = STAGES[phase]
    require(result.get('phase') == phase and result.get('experiment') == confirmation.EXPERIMENT,
            'Wrong confirmation phase or experiment')
    allowed = ('complete',) if phase == 'final' else ('complete', 'incomplete_or_failed')
    require(result.get('status') in allowed, 'Confirmation is not closed')
    require(progress.get('completed') == list(stages), 'Progress does not mark every required stage completed')
    require(set(result['stage_match_counts']) == set(stages), 'Unexpected campaign stages')
    confirmation.validate_lock(lock, manifest)
    require(original_lock is None or lock == original_lock, 'Audit changed the original confirmation lock')
    require(result.get('baseline') == BASELINE and result.get('primary_candidate') == PRIMARY
            and result.get('finalists') == result.get('selection_ranking') == [PRIMARY],
            'Campaign changed the single locked primary')
    require(result.get('original_failed_audit') == confirmation.ORIGINAL_FAILED_AUDIT,
            'Prior failed f3 conclusion changed')
    expected_policy = {'experiment': confirmation.EXPERIMENT, 'phase': phase, 'baseline': BASELINE,
                       'primary_candidate': PRIMARY, 'candidate_ids': [BASELINE, PRIMARY],
                       'fixed_opponents': confirmation.campaign.FIXED_OPPONENTS,
                       'opponents': confirmation.OPPONENTS, 'map_sets': confirmation.FINAL_MAPS,
                       'reserved_audit_maps': confirmation.AUDIT_MAPS, 'selection_lock': lock,
                       'source_sha256': confirmation.PINNED, 'selection_scope': confirmation.SCOPE,
                       'original_failed_audit': confirmation.ORIGINAL_FAILED_AUDIT,
                       'primary_only_can_promote': True}
    for key, value in expected_policy.items():
        require(policy.get(key) == value, 'Confirmation policy differs: ' + key)
    if phase == 'audit':
        files['audit-policy.json'] = arena / 'audit-policy.json'
        files['selection-lock.json'] = arena / 'selection-lock.json'
        audit_policy = read(files['audit-policy.json'])
        require(read(files['selection-lock.json']) == lock, 'Audit selection-lock copy differs')
        for key, value in expected_policy.items():
            require(audit_policy.get(key) == value, 'Audit policy differs: ' + key)
        require(audit_policy.get('candidate') == PRIMARY and
                audit_policy.get('map_seeds') == confirmation.AUDIT_MAPS, 'Audit maps or candidate changed')
    rows_by_stage = {}
    for stage in stages:
        directory = arena / 'runs' / stage
        sessions = sorted(directory.glob('session-*.json'))
        require(bool(sessions), stage + ': missing session record')
        session = read(sessions[-1])
        require(session.get('status') in ('complete', 'complete_with_errors') and session.get('finished_utc'),
                stage + ': session is not closed')
        rows, plan = validate_stage(arena, stage, manifest, result['stage_match_counts'][stage])
        require(plan == normalized(confirmation.plans()[stage]), stage + ': predeclared plan changed')
        require(len(rows) == COUNTS[stage], stage + ': unexpected schedule size')
        for row in rows:
            outcome_check(row)
        actual = aggregate(rows)
        summary = read(directory / 'summary.json')['overall']
        for key in ('jobs', 'matches', 'errors', 'wins', 'draws', 'losses', 'point_rate', 'forfeits'):
            require(summary.get(key) == actual[key], stage + ': raw aggregate differs from summary: ' + key)
        rows_by_stage[stage] = rows
        for path in [sessions[-1], arena / 'plans' / (stage + '.json'),
                     *(directory / name for name in ('plan.json', 'jobs.json', 'summary.json', 'results.jsonl'))]:
            files[str(path.relative_to(arena))] = path
    all_rows = [row for rows in rows_by_stage.values() for row in rows]
    runtime = health(all_rows)
    require(result['total_matches'] == sum(r['status'] == 'complete' for r in all_rows)
            == sum(result['stage_match_counts'].values()), 'Campaign completed-match total differs')
    require(result['errors'] == runtime['errors'] and result['forfeits'] == runtime['forfeits'],
            'Campaign health totals differ')
    return {'arena': arena, 'result': result, 'manifest': manifest, 'policy': policy, 'lock': lock,
            'rows': rows_by_stage, 'health': runtime,
            'input_sha256': {name: sha(path) for name, path in files.items()}}


def verify_decision(run):
    if run['result']['phase'] == 'final':
        decision = confirmation.final_assessment(run['rows']['holdout'], run['rows']['crossplay'])
        stored = run['result']['promotion_decisions']
        require(set(stored) == {PRIMARY}, 'Unexpected promotion candidate')
        require(stored[PRIMARY] == normalized(decision), 'Stored final decision differs from raw results')
        passed = decision['promoted']
    else:
        decision = confirmation.audit_assessment(run['rows']['audit'])
        path = run['arena'] / 'audit-result.json'
        stored = read(path)
        for key, value in normalized(decision).items():
            require(stored.get(key) == value, 'Stored audit decision differs from raw results: ' + key)
        require(stored.get('original_failed_audit') == confirmation.ORIGINAL_FAILED_AUDIT,
                'Audit rewrites the prior failed conclusion')
        require(run['result']['status'] == decision['status'], 'Audit completion status differs')
        run['input_sha256']['audit-result.json'] = sha(path)
        passed = decision['passes_additional_gate']
    require(run['result']['recommended'] == (PRIMARY if passed else BASELINE),
            'Stored recommendation bypasses its raw gates')
    return {**decision, 'failed_gates': [key for key, value in decision['gates'].items() if not value],
            'stored_decision_matches_raw_results': True}


def stats(rows):
    value = aggregate(rows)
    value['points'] = value['wins'] + .5 * value['draws']
    value['win_rate'] = value['wins'] / value['matches'] if value['matches'] else None
    return value


def pool_analysis(rows, opponents):
    selected = [row for row in rows if row['opponent'] in opponents]
    return {side: {
        'baseline': stats([r for r in selected if r['candidate'] == BASELINE and r['team'] == side]),
        'candidate': stats([r for r in selected if r['candidate'] == PRIMARY and r['team'] == side]),
        'paired_point_rate_difference': paired(selected, PRIMARY, side),
    } for side in 'YK'}


def describe(run, decision):
    stage = 'holdout' if run['result']['phase'] == 'final' else 'audit'
    rows = run['rows'][stage]
    pools = {'overall': confirmation.OPPONENTS, 'fixed': confirmation.campaign.FIXED_OPPONENTS,
             'added': confirmation.ADDED}
    output = {'arena': str(run['arena']), 'campaign': run['result'], 'decision': decision,
              'health': run['health'], 'input_sha256': run['input_sha256'],
              'distinct_comparison_maps': len({r['map_seed'] for r in rows}),
              'pools': {name: pool_analysis(rows, members) for name, members in pools.items()},
              'per_opponent': {op: {'pool': 'fixed' if op in pools['fixed'] else 'added',
                                    **pool_analysis(rows, [op])} for op in confirmation.OPPONENTS},
              'stage_counts': {name: {'observed_jobs': len(values), **stats(values)}
                               for name, values in run['rows'].items()}}
    if stage == 'holdout':
        output['crossplay'] = crossplay_table(run['rows']['crossplay'])
    return output


def conclusion(final_passed, audit_passed, healthy=True):
    eligible = final_passed and audit_passed is True and healthy
    return {'recommended': PRIMARY if eligible else BASELINE,
            'confirmation_gates_passed': eligible,
            'audit_status': 'not_provided' if audit_passed is None else ('passed' if audit_passed else 'failed'),
            'scope': 'Statistical confirmation only; artifact verification and actual ZIP/compiler/runtime validation remain required.'}


def percent(value):
    return '—' if value is None else f'{100 * value:.2f}%'


def markdown(report):
    lines = ['# s3 독립 확인 실험 분석', '',
             f"고정 후보 `{PRIMARY}` · 기준선 `{BASELINE}` · 현재 결론 `{report['conclusion']['recommended']}`.", '',
             '이 문서는 새 독립 확인 실험만 요약한다. 기존 f3 추가 감사 실패와 v3 유지 결론은 그대로 보존한다. '
             '이전 80맵 holdout은 이번 후보를 고르는 데 사용했으므로 선택 자료이며 이번 독립 표본에 포함하지 않는다.', '',
             '고정 6종 + 추가 3종, 같은 초기 맵·상대·진영끼리 비교했다. CI는 맵 단위 5,000회 bootstrap한 '
             '후보−v3 승점률 차이의 95% 구간이다. 승률은 승/경기, 승점률은 (승+0.5×무)/경기다.']
    for phase in ('final', 'audit'):
        section = report.get(phase)
        if section is None:
            continue
        result, runtime, decision = section['campaign'], section['health'], section['decision']
        failed = ', '.join('`' + name + '`' for name in decision['failed_gates']) or '없음'
        lines += ['', f'## {phase}', '',
                  f"완료 {result['total_matches']:,}경기 · 비교 맵 {section['distinct_comparison_maps']}개 · "
                  f"오류 {runtime['errors']}, 몰수 {runtime['forfeits']}. 저장된 판정과 원본 재계산이 일치했다.", '',
                  '실패 게이트: ' + failed + '.', '',
                  '| 구간 | 진영 | 후보 승/무/패 | v3 승/무/패 | 후보/v3 승률 | 후보/v3 승점률 | 차이·95% CI |',
                  '|---|---|---:|---:|---:|---:|---|']
        entries = [*section['pools'].items(), *section['per_opponent'].items()]
        for name, values in entries:
            for side in 'YK':
                current = values[side]
                candidate, baseline = current['candidate'], current['baseline']
                lines.append(f"| {name} | {side} | {record(candidate)} | {record(baseline)} | "
                             f"{percent(candidate['win_rate'])}/{percent(baseline['win_rate'])} | "
                             f"{percent(candidate['point_rate'])}/{percent(baseline['point_rate'])} | "
                             f"{interval(current['paired_point_rate_difference'])} |")
    if report['audit'] is None:
        lines += ['', '추가 감사 결과는 아직 제공되지 않았다. final 통과만으로 새 제출을 추천하지 않는다.']
    lines += ['', '## 해석 범위', '',
              '전체·fixed·added 조건과 상대별 회귀 조건을 모두 유지했다. 감사 통과로 final 실패를 구제하거나 다른 후보를 다시 고르지 않는다. '
              '상대들은 대부분 v2/v3 공통 구조에서 파생되어 전체 참가자를 대표하지 않는다. 맵별 불확실성은 '
              '리더보드 보정 점수나 미지의 상대 승률을 뜻하지 않는다.', '',
              '완료된 몰수 결과도 성적표에는 포함하지만 실행 건강성 실패이며 채택 근거로 인정하지 않는다. '
              '응답 시간은 스케줄링·입출력도 포함하므로 내부 135ms 탐색 예산과 동일한 측정이 아니다. '
              '384MiB RLIMIT_AS는 RSS/cgroup 제한 또는 공식 컨테이너 재현과 같지 않다.', '',
              '이 분석은 원본 요약·일정·잠금·판정을 대조한다. 소스 바이트/전체 replay 검증과 실제 ZIP의 GCC·CPU 검사는 별도다. '
              '[수치·게이트·입력 해시](analysis.json)에 기록했다.']
    return '\n'.join(lines) + '\n'


def analyze(arena, audit=None, output_dir=None):
    final = load_completed(arena, 'final')
    final_decision = verify_decision(final)
    audit_run = load_completed(audit, 'audit', final['lock']) if audit is not None else None
    audit_decision = verify_decision(audit_run) if audit_run is not None else None
    output = Path(output_dir).resolve() if output_dir is not None else final['arena']
    targets = [output / 'analysis.json', output / 'README.md']
    require(not any(path.exists() for path in targets), 'Analysis output exists; choose a new --output-dir')
    report = {'baseline': BASELINE, 'candidate': PRIMARY, 'experiment': confirmation.EXPERIMENT,
              'original_failed_audit': confirmation.ORIGINAL_FAILED_AUDIT,
              'prior_80_map_holdout_role': 'Selection/development evidence for this new candidate choice; not independent confirmation data.',
              'source_sha256': final['lock']['source_sha256'],
              'final': describe(final, final_decision),
              'audit': describe(audit_run, audit_decision) if audit_run is not None else None,
              'conclusion': conclusion(final_decision['promoted'],
                                       audit_decision['passes_additional_gate'] if audit_decision else None,
                                       final['health']['runtime_gate_passed'] and
                                       (audit_run is None or audit_run['health']['runtime_gate_passed'])),
              'analyzer_sha256': sha(Path(__file__)),
              'dependency_sha256': {name: sha(Path(confirmation.__file__).parent / name) for name in
                                    ('v3_confirmation.py', 'v3_campaign.py', 'analyze_v3_campaign.py',
                                     'cpu_sweep.py', 'league_campaign.py', 'local_league.py')},
              'ci_scope': 'Paired point-rate difference, map-cluster bootstrap; rates include completed forfeits descriptively only.',
              'no_reselection': True, 'no_matches_executed': True}
    output.mkdir(parents=True, exist_ok=True)
    targets[0].write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    targets[1].write_text(markdown(report))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('arena', type=Path, help='Completed confirmation final arena')
    parser.add_argument('--audit', type=Path, help='Optional completed confirmation audit arena')
    parser.add_argument('--output-dir', type=Path, help='New output folder; default: final arena')
    args = parser.parse_args()
    report = analyze(args.arena, args.audit, args.output_dir)
    print(json.dumps(report['conclusion'], ensure_ascii=False))
