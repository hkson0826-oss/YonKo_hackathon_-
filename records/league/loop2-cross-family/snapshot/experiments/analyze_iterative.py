"""Preserve paired outcome changes for a completed iteration."""
import argparse
import hashlib
import json
from pathlib import Path

from league_campaign import paired_interval, ranking, load_rows, point


def analyze(arena):
    result = json.loads((arena / 'campaign-result.json').read_text())
    manifest = json.loads((arena / 'manifest.json').read_text())
    output = {'campaign': result, 'stages': {},
              'analyzer_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    lines = ['# 반복 개선 대전 결과', '',
             f"단계 `{result['phase']}`, 완료 {result['total_matches']:,}경기. 추천: **{result['recommended']}**.",
             '', result['recommendation_scope'], '',
             '모든 승리·패배의 전체 리플레이를 보존했다. 내부 고정 상대 성적이며 리더보드 보정 점수나 외부 참가자 전체 승률이 아니다.']
    for stage in ['development', 'selection', 'holdout']:
        directory = arena / 'runs' / stage
        if not directory.exists():
            continue
        rows = load_rows(directory)
        summary = json.loads((directory / 'summary.json').read_text())
        names = ranking(summary, summary['by_candidate'])
        indexed = {(r['candidate'], r['opponent'], r['map_seed'], r['team']): r
                   for r in rows if r['status'] == 'complete'}
        analysis = {}
        lines += ['', f'## {stage}', '',
                  '| 후보 | Y 승/무/패 | K 승/무/패 | Y 차이·맵 95% 구간 | 최대 응답 |',
                  '|---|---|---|---|---:|']
        for name in names:
            stats = summary['by_candidate'][name]
            cmp = None if name == 'v2' else paired_interval(rows, name)
            ci = '기준선' if cmp is None else (
                f"{100*cmp['point_rate_difference']:+.1f}%p "
                f"[{100*cmp['map_cluster_bootstrap_95pct'][0]:+.1f}, {100*cmp['map_cluster_bootstrap_95pct'][1]:+.1f}]")
            record = lambda side: '/'.join(str(stats[side][key]) for key in ['wins', 'draws', 'losses'])
            lines.append(f"| {name} | {record('Y')} | {record('K')} | {ci} | {stats['max_turn_ms']:.1f}ms |")
            regressions, improvements = [], []
            opponents = {}
            for row in rows:
                if row['candidate'] != name or row['status'] != 'complete' or row['team'] != 'Y':
                    continue
                op = row['opponent']
                old = indexed.get(('v2', op, row['map_seed'], 'Y'))
                if old is None:
                    continue
                entry = opponents.setdefault(op, {'games': 0, 'candidate_points': 0, 'baseline_points': 0})
                entry['games'] += 1
                entry['candidate_points'] += point(row)
                entry['baseline_points'] += point(old)
                if point(row) == point(old):
                    continue
                evidence = {'map_seed': row['map_seed'], 'opponent': op, 'team': 'Y',
                            'old_result': old['result'], 'new_result': row['result'],
                            'old_replay': f"runs/{stage}/{old['replay']}",
                            'new_replay': f"runs/{stage}/{row['replay']}",
                            'old_diagnostics': old['diagnostics']['Y'],
                            'new_diagnostics': row['diagnostics']['Y']}
                (regressions if point(row) < point(old) else improvements).append(evidence)
            analysis[name] = {'Y_comparison': cmp, 'per_opponent_Y': opponents,
                              'regressions': regressions, 'improvements': improvements,
                              'stats': stats, 'source_sha256': manifest['bots'][name]['source_sha256']}
        output['stages'][stage] = analysis
        lines += ['', '개발·선택 단계의 구간은 다수 후보를 비교해 고른 데 따른 선택 편향을 보정하지 않는다. 최종 채택에는 사전 고정한 주 후보의 미사용 맵 검증을 쓴다.']
    lines += ['', '## 원본과 복구', '',
              '[후보·소스 해시](manifest.json), [실행 계획](campaign-policy.json), '
              '[대응 승패·진단](analysis.json), [전송·TMP 삭제](transport_receipt.json).', '',
              '생산량·병력 집중도는 관찰 지표다. 집중 공격과 움직이지 못하는 정체를 구분하려면 명령·거점 변화를 함께 읽어야 한다.']
    (arena / 'analysis.json').write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n')
    (arena / 'README.md').write_text('\n'.join(lines) + '\n')
    return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('arena', type=Path)
    args = parser.parse_args()
    analyze(args.arena.resolve())
