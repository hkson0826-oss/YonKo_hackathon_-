"""Compare actual revisions with their parents on identical development games."""
import argparse
import hashlib
import json
from pathlib import Path

from league_campaign import load_rows, paired_interval, point

CONTRASTS = [
    ('q_v2_window_guard', 'q_threat_window'),
    ('q_v2_tactical_mean', 'q_threat_window'),
    ('q_v2_tactical_worst', 'q_threat_window'),
    ('q_v2_guard_tactical', 'q_v2_window_guard'),
    ('q_v2_guard_tactical', 'q_v2_tactical_mean'),
    ('j_v2_defensive_delayed', 'j_defensive_portfolio'),
    ('j_v2_reclaim_flags7', 'j_reclaim_portfolio'),
    ('j_v2_reclaim_relay', 'j_reclaim_portfolio'),
    ('j_v2_reclaim_relay_delayed', 'j_v2_reclaim_relay'),
    ('a_v2_terminal_local', 'a_local_unabstracted'),
    ('a_v2_tactical_local', 'a_v2_terminal_local'),
    ('a_v2_tactical_fit', 'a_v2_tactical_local'),
    ('a_v2_continuous_mix', 'a_opponent_fit'),
]


def analyze(arena):
    run = arena / 'runs/development'
    rows = load_rows(run)
    summary = json.loads((run / 'summary.json').read_text())
    if len(rows) != summary['overall']['jobs']:
        raise ValueError('Development stage is still incomplete')
    contrasts = []
    lines = ['# 실제 코드 재수정의 대응 비교', '',
             '같은 개발 맵·상대·진영에서 수정 전후를 비교한다. 여러 비교를 탐색한 8개 개발 맵 결과이므로 독립적인 최종 검증이나 단일 원인의 일반화 증명은 아니다.', '',
             '| 수정 후보 | 대조 부모 | Y 승점/경기 | 부모 Y 승점/경기 | 차이와 맵 95% 구간 |',
             '|---|---|---|---|---|']
    for candidate, parent in CONTRASTS:
        own = [row for row in rows if row['candidate'] == candidate and row['status'] == 'complete']
        old = [row for row in rows if row['candidate'] == parent and row['status'] == 'complete']
        if not own or not old:
            continue
        paired = [*own, *[{**row, 'candidate': 'v2'} for row in old]]
        comparisons = {side: paired_interval(paired, candidate, side) for side in 'YK'}
        counts = {}
        for name, source in [(candidate, own), (parent, old)]:
            games = [row for row in source if row['team'] == 'Y']
            counts[name] = {'games': len(games), 'points': sum(map(point, games))}
        contrasts.append({'candidate': candidate, 'parent': parent, 'comparisons': comparisons,
                          'Y_counts': counts})
        gain = comparisons['Y']; low, high = gain['map_cluster_bootstrap_95pct']
        record = lambda name: f"{counts[name]['points']:g}/{counts[name]['games']}"
        lines.append(f"| {candidate} | {parent} | {record(candidate)} | {record(parent)} | "
                     f"{gain['point_rate_difference']*100:+.1f}%p [{low*100:+.1f}, {high*100:+.1f}] |")
    result = {'stage': 'development', 'contrasts': contrasts,
              'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'limitation': 'Exploratory paired development comparisons, not corrected for multiple comparisons.'}
    (arena / 'revision-effects.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    (arena / 'revision-effects.md').write_text('\n'.join(lines) + '\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('arena', type=Path)
    analyze(parser.parse_args().arena.resolve())
