"""Diagnose completed development diversity without changing opponent selection."""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import itertools
import json
from pathlib import Path

BASELINE = 'v3'
CONDITION = ('map_seed', 'opponent', 'team')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_json(path):
    return json.loads(path.read_text())


def key(row):
    return tuple(row[field] for field in CONDITION)


def outcome(row):
    if row['win'] and row['draw']:
        raise ValueError('A result cannot be both a win and a draw')
    return 'W' if row['win'] else 'D' if row['draw'] else 'L'


def point(row):
    return {'W': 1.0, 'D': .5, 'L': 0.0}[outcome(row)]


def rate(rows):
    values = [outcome(row) for row in rows]
    return {'games': len(values), 'wins': values.count('W'), 'draws': values.count('D'),
            'losses': values.count('L'),
            'point_rate': sum(point(row) for row in rows) / len(rows) if rows else None}


def compare(first, second):
    a, b = {key(r): r for r in first}, {key(r): r for r in second}
    shared = sorted(a.keys() & b.keys())
    equal = sum(outcome(a[k]) == outcome(b[k]) for k in shared)
    traced = [k for k in shared if a[k].get('logical_trace_sha256') and b[k].get('logical_trace_sha256')]
    trace_equal = sum(a[k]['logical_trace_sha256'] == b[k]['logical_trace_sha256'] for k in traced)
    return {'matched_initial_conditions': len(shared), 'outcome_equal_games': equal,
            'outcome_agreement': equal / len(shared) if shared else None,
            'identical_full_outcome_vector': bool(shared) and len(shared) == len(a) == len(b) and equal == len(shared),
            'trace_comparable_games': len(traced), 'trace_equal_games': trace_equal,
            'trace_agreement': trace_equal / len(traced) if traced else None,
            'trace_coverage': len(traced) / len(shared) if shared else None,
            'score_margin_equal_games': sum(a[k]['score_margin'] == b[k]['score_margin'] for k in shared),
            'point_difference_first_minus_second': {
                side: sum(point(a[k]) - point(b[k]) for k in shared if k[2] == side) /
                sum(k[2] == side for k in shared) if any(k[2] == side for k in shared) else None
                for side in 'YK'}}


def validate_schedule(plan, jobs, rows, summary, session):
    if session.get('status') not in {'complete', 'complete_with_errors'}:
        raise ValueError('Development session is not closed')
    expected = {(name, seed, opponent, side) for name in plan['candidates']
                for seed in plan['map_seeds'] for opponent in plan['opponents'] for side in 'YK'}
    job_keys = [(r['candidate'], *key(r)) for r in jobs]
    row_keys = [(r['candidate'], *key(r)) for r in rows]
    for label, values in [('job', job_keys), ('result', row_keys)]:
        if len(values) != len(set(values)) or set(values) != expected:
            raise ValueError(f'Development {label} schedule is missing, duplicated or unexpected')
    if len({r['job_id'] for r in jobs}) != len(jobs) or len({r['job_id'] for r in rows}) != len(rows):
        raise ValueError('Duplicate job IDs')
    indexed = {r['job_id']: (r['candidate'], *key(r)) for r in jobs}
    for row in rows:
        if indexed.get(row['job_id']) != (row['candidate'], *key(row)):
            raise ValueError('Job identity does not match its condition')
        if row['status'] not in {'complete', 'error'}:
            raise ValueError('A development result is still incomplete')
    if summary['expected_jobs'] != len(jobs) or summary['finished_jobs'] != len(rows):
        raise ValueError('Development summary is partial or stale')
    if summary['overall']['errors'] != sum(r['status'] == 'error' for r in rows):
        raise ValueError('Summary error count differs from results')
    if summary['overall']['forfeits'] != sum(bool(r.get('forfeit')) for r in rows):
        raise ValueError('Summary forfeit count differs from results')


def diagnose(plan, rows, bots, lock):
    grouped = {name: [r for r in rows if r['candidate'] == name] for name in plan['candidates']}
    excluded = {name: {'errors': sum(r['status'] != 'complete' for r in data),
                       'forfeits': sum(bool(r.get('forfeit')) for r in data)}
                for name, data in grouped.items()
                if any(r['status'] != 'complete' or r.get('forfeit') for r in data)}
    healthy = {name: data for name, data in grouped.items() if name not in excluded}
    statistics = {}
    outcome_groups = defaultdict(list)
    trace_groups = defaultdict(list)
    for name, data in healthy.items():
        ordered = sorted(data, key=key)
        vector = [(key(r), outcome(r)) for r in ordered]
        vector_hash = digest(json.dumps(vector, separators=(',', ':')).encode())
        outcome_groups[vector_hash].append(name)
        trace_hash = None
        if all(r.get('logical_trace_sha256') for r in ordered):
            trace_hash = digest(json.dumps([(key(r), r['logical_trace_sha256']) for r in ordered], separators=(',', ':')).encode())
            trace_groups[trace_hash].append(name)
        matchups = {op: {'both': rate([r for r in data if r['opponent'] == op]),
                          **{side: rate([r for r in data if r['opponent'] == op and r['team'] == side]) for side in 'YK'}}
                    for op in plan['opponents']}
        worst = sorted(matchups, key=lambda op: (matchups[op]['both']['point_rate'], op))[:3]
        statistics[name] = {'source_sha256': bots[name]['source_sha256'],
                            'family': bots[name].get('family'), 'both': rate(data),
                            **{side: rate([r for r in data if r['team'] == side]) for side in 'YK'},
                            'direct_vs_v3': matchups.get(BASELINE), 'opponents': matchups,
                            'weakest_matchups': [{'opponent': op, **matchups[op]} for op in worst],
                            'outcome_vector_sha256': vector_hash, 'trace_vector_sha256': trace_hash,
                            'vs_v3_same_conditions': compare(data, healthy[BASELINE]) if BASELINE in healthy else None}
    comparisons = [{'first': a, 'second': b, **compare(healthy[a], healthy[b])}
                   for a, b in itertools.combinations(sorted(healthy), 2)]
    selected = lock.get('opponents', []) if lock else []
    if len(selected) != len(set(selected)):
        raise ValueError('Existing opponent lock has duplicate IDs')
    for name in selected:
        if name not in bots or lock['source_sha256'].get(name) != bots[name]['source_sha256']:
            raise ValueError(f'Locked opponent source mismatch: {name}')
    challenge = {'selection_rule_unchanged': True, 'existing_lock': lock,
                 'opponents': {name: {'health': excluded.get(name, {'errors': 0, 'forfeits': 0}),
                                     'measured_in_development': name in grouped,
                                     'statistics': statistics.get(name)} for name in selected},
                 'mutual_comparisons': [{'first': a, 'second': b, **compare(healthy[a], healthy[b])}
                                        for a, b in itertools.combinations(selected, 2) if a in healthy and b in healthy]}
    source_count = len({bots[name]['source_sha256'] for name in grouped})
    return {'status': 'completed_development_diagnostic', 'baseline': BASELINE,
            'scope': 'Development only; no ranking, opponent-lock or promotion changes',
            'scheduled_candidates': len(grouped), 'distinct_source_count': source_count,
            'healthy_candidates': len(healthy), 'excluded_candidates': excluded,
            'distinct_healthy_outcome_vectors': len(outcome_groups),
            'distinct_complete_trace_vectors': len(trace_groups),
            'candidates_with_complete_traces': sum(v['trace_vector_sha256'] is not None for v in statistics.values()),
            'identical_outcome_groups': [names for names in outcome_groups.values() if len(names) > 1],
            'identical_complete_trace_groups': [names for names in trace_groups.values() if len(names) > 1],
            'candidates': statistics, 'pairwise': comparisons, 'locked_challengers': challenge,
            'limitations': [
                'Matched initial map/opponent/side conditions, not identical intermediate game states.',
                'Outcome agreement is a coarse W/D/L statistic; equal results do not imply equal actions.',
                'Equal logical traces support strong equivalence for those games only. Different traces need not mean different strategy: command ordering or expression can differ even when resulting states agree.',
                'Candidates with any error or forfeit are excluded entirely from behavioral comparisons, not partially scored.',
                'Diversity counts are observed fingerprints on this fixed development distribution, not a count of distinct algorithms or proof of generalization.',
                'Locked exploiters were selected on these development games; their strength is selection-biased and must be validated on fresh maps.']}


def markdown(report):
    lines = ['# v3 개발 후보 다양성 진단', '',
             f"소스 {report['distinct_source_count']}종 중 건강한 후보 {report['healthy_candidates']}개에서 서로 다른 승무패 벡터 {report['distinct_healthy_outcome_vectors']}개를 관찰했다. 이 수는 실제 알고리즘 또는 행동 종류의 수가 아니다.", '',
             '같은 **초기 맵·상대·진영 조건**을 짝지었다. 경기 중간 상태가 같다는 뜻은 아니다. trace 동일은 해당 경기의 강한 동일성 근거지만, trace 차이는 명령 표현·순서 차이일 수도 있어 전략 차이를 보장하지 않는다.', '',
             '| 후보 | Y 승/무/패 | K 승/무/패 | v3 직접 양진영 승점률 | 최저 상대 승점률 | v3와 결과 일치 | v3와 trace 일치/비교 가능 |',
             '|---|---|---|---:|---|---:|---:|']
    for name, s in report['candidates'].items():
        y, k, direct, comparison = s['Y'], s['K'], s['direct_vs_v3'], s['vs_v3_same_conditions']
        d = f"{direct['both']['point_rate']:.1%}" if direct else '없음'
        worst = s['weakest_matchups'][0] if s['weakest_matchups'] else None
        w = f"{worst['opponent']} {worst['both']['point_rate']:.1%}" if worst else '없음'
        agreement = f"{comparison['outcome_agreement']:.1%}" if comparison else '제외'
        trace = f"{comparison['trace_equal_games']}/{comparison['trace_comparable_games']}" if comparison else '제외'
        lines.append(f"| {name} | {y['wins']}/{y['draws']}/{y['losses']} | {k['wins']}/{k['draws']}/{k['losses']} | {d} | {w} | {agreement} | {trace} |")
    locked = report['locked_challengers']
    names = list(locked['opponents'])
    lines += ['', '기존에 선정한 공략형: ' + (', '.join(f'`{n}`' for n in names) if names else '선정 기록 없음') + '. 선정 규칙과 lock을 그대로 보존했다.']
    for item in locked['mutual_comparisons']:
        lines.append(f"두 공략형 {item['first']} / {item['second']}: 결과 일치 {item['outcome_agreement']:.1%}, trace 동일 {item['trace_equal_games']}/{item['trace_comparable_games']}경기.")
    lines += ['', f"전체 제외 후보: {json.dumps(report['excluded_candidates'], ensure_ascii=False)}. 오류·몰수가 있는 후보는 일부 경기만 골라 집계하지 않았다.", '',
              '하위 상대 3종·상대별 양 진영 승무패·전체 후보 쌍의 비교·동일 벡터 그룹은 JSON에 있다. 개발 성적은 공략형 선정에 이미 사용됐으므로 새 맵에서 재검증해야 한다. 이 보고서는 사후 재선정이나 승격 기준 변경에 사용하지 않는다.']
    return '\n'.join(lines) + '\n'


def analyze(arena, output=None):
    arena = Path(arena)
    folder = arena / 'runs/development'
    sessions = sorted(folder.glob('session-*.json'))
    if not sessions:
        raise ValueError('No completed development session record')
    paths = {'manifest': arena/'manifest.json', 'plan': folder/'plan.json', 'jobs': folder/'jobs.json',
             'summary': folder/'summary.json', 'results': folder/'results.jsonl', 'session': sessions[-1]}
    inputs = {name: path.read_bytes() for name, path in paths.items()}
    manifest, plan, jobs, summary, session = (json.loads(inputs[n]) for n in ['manifest','plan','jobs','summary','session'])
    if manifest.get('status') != 'ready':
        raise ValueError('Frozen arena is not ready')
    rows = [json.loads(line) for line in inputs['results'].decode().splitlines() if line.strip()]
    validate_schedule(plan, jobs, rows, summary, session)
    lock_path = arena/'next-opponents.json'
    lock = None
    if lock_path.exists():
        inputs['next_opponents'] = lock_path.read_bytes()
        lock = json.loads(inputs['next_opponents'])
    report = diagnose(plan, rows, manifest['bots'], lock)
    report.update(created_utc=datetime.now(timezone.utc).isoformat(), source_commit=manifest.get('source_commit'),
                  development_games=len(rows), distinct_maps=len(set(plan['map_seeds'])),
                  input_sha256={name: digest(data) for name,data in inputs.items()})
    prefix = Path(output) if output else arena/'diversity-analysis'
    targets = [prefix.with_suffix('.json'), prefix.with_suffix('.md')]
    if any(path.exists() for path in targets):
        raise FileExistsError('Diversity analysis output already exists; use a new output prefix')
    prefix.parent.mkdir(parents=True, exist_ok=True)
    targets[0].write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    targets[1].write_text(markdown(report))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('arena', type=Path)
    parser.add_argument('--output', type=Path, help='New output prefix for .json and .md')
    args = parser.parse_args()
    report = analyze(args.arena, args.output)
    print(json.dumps({k: report[k] for k in ['status','scheduled_candidates','healthy_candidates','distinct_healthy_outcome_vectors']},ensure_ascii=False))
