"""Normalize the 24 rendered official match-detail extracts; no browser/network calls."""
from pathlib import Path
from collections import Counter
import hashlib
import json

HERE = Path(__file__).resolve().parent
ROUND = '10월 1일 17:00 리더보드'
SOURCE = 'Authenticated Chrome /matches public-round filter, each official detail page, 끝으로 control, rendered DOM snapshot'
END = {'instant': '즉시 승리', 'score': '점수 판정', 'bot_error': '봇 오류로 종료'}

def write_json(name, data):
    (HERE / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')

rows = json.loads((HERE / 'ui-extract.json').read_text())
canonical = json.dumps(rows, ensure_ascii=False, separators=(',', ':'))
fnv = 2166136261
for char in canonical:
    fnv = ((fnv ^ ord(char)) * 16777619) & 0xffffffff
assert len(rows) == 24 and len({r[0] for r in rows}) == 24
assert fnv == 0xe6cbb5f4 and len(canonical) == 3467, 'Rendered-DOM transfer checksum mismatch'

details = []
for game, opponent, result, timestamp, turn, reason, sy, sk, y, k in rows:
    game_id = 'rolling-game-' + game
    phase = '명령 처리 전' if reason == 'bot_error' else '처리 완료'
    winner = 'Y' if result == '승리' else 'K'
    status = f'{winner} · {"강릉" if winner == "Y" else opponent} 승리 · {END[reason]}'
    details.append({
        'game_id': game_id, 'round_label': ROUND, 'submission': 11,
        'opponent': opponent, 'side': 'Y', 'result': result,
        'timestamp_ui': timestamp, 'terminal_turn': turn, 'terminal_phase': phase,
        'end_reason': reason, 'status_ui': status,
        'public_score_y': sy, 'public_score_k': sk,
        'final_y': dict(zip(['resources', 'buildings', 'unit_value', 'occupation_turns'], y)) | {'capacity': 40},
        'final_k': dict(zip(['resources', 'buildings', 'unit_value'], k)) | {'capacity': 40, 'occupation_turns': None},
        'official_url': 'https://yonsei-vs-korea-hackathon.kr/matches/' + game_id,
        'evidence_kind': 'rendered_official_ui',
        'runtime_error_cause': None,
    })
write_json('details.json', details)

counts = Counter((d['end_reason'], d['result']) for d in details)
assert counts == {('instant', '승리'): 8, ('instant', '패배'): 8, ('score', '승리'): 3, ('score', '패배'): 4, ('bot_error', '승리'): 1}
summary = {
    'round_label': ROUND, 'submission': 11, 'side': 'Y',
    'checked_at_utc': '2026-10-01T09:27:36Z',
    'games': 24, 'wins': 12, 'losses': 12, 'draws': 0,
    'normal_games': 23, 'normal_wins': 11, 'normal_losses': 12,
    'normal_win_rate': 11 / 23, 'all_game_win_rate': 12 / 24,
    'bot_error_wins': 1, 'bot_error_losses': 0,
    'end_reason_counts': {reason: {'wins': counts[(reason, '승리')], 'losses': counts[(reason, '패배')]} for reason in END},
    'opponent_public_score_unknown': sum(d['public_score_k'] is None for d in details),
    'own_public_score_unknown': sum(d['public_score_y'] is None for d in details),
    'forfeit_opponents': ['Re:verse'],
    'observed_submission_values': [11], 'observed_side_values': ['Y'],
    'unique_game_ids': 24, 'missing_details': 0, 'browser_canonical_fnv1a32': 'e6cbb5f4',
    'copy_checksum_match': True,
    'source': SOURCE,
    'limitations': [
        'Scores are the final public scores displayed to our team. Missing opponent scores remain null; full final score differences cannot be calculated.',
        'Bot-error termination is visible for Re:verse. The detail UI does not establish the specific error or timeout cause.',
        'All 24 games were played as Y. This round cannot estimate K-side performance.',
        'The public round is 17:00; per-match detail timestamps span 14:40–15:22. These are distinct UI fields.',
        'Each detail explicitly says v11. The source-to-upload identity is maintained in separate submission/package records, not proved by this UI collection alone.',
        'No replay JSON was preserved during this collection. A Re:verse replay-file click returned a download event without a documented file path; chrome://downloads/ was then blocked by Browser Use URL policy. No workaround was attempted.',
        'Normal termination confirms the displayed result classification, not an independent per-command runtime or semantic audit.',
    ],
}
write_json('summary.json', summary)

lines = [
    '# 10월 1일 17:00 공식 회차 상세 확인', '',
    '공식 상세 24개를 모두 열어 최종 이벤트를 확인했다. 전부 제출 **#11**, 우리 진영 **Y**다. 목록과 상세의 승패가 24/24 일치하며 중복·누락은 없다.', '',
    '**12승 12패** 중 Re:verse전 1승은 `봇 오류로 종료`다. 이를 분리하면 정상 종료 **11승 12패, 47.83%**다. 즉시 승리는 8승 8패, 160턴 점수 판정은 3승 4패다.', '',
    'Re:verse전은 19턴 **명령 처리 전**에 끝났다. UI에서 구체적인 오류나 시간 초과 원인은 확인되지 않는다. 나머지 23개는 모두 처리 완료 후 정상 즉시/점수 종료이며, 우리 오류 패배는 표시되지 않았다.', '',
    '우리 최종 공개 점수는 24개 모두 확인했지만 상대 점수는 16개가 미공개다. 아래 `미공개`를 0이나 추정 점수로 바꾸지 않았다. 병력 가치는 W 인원수가 아니다.', '',
    '| 상대 | 결과 | 종료 | 턴 | 우리 공개점수 | 상대 공개점수 |',
    '|---|---|---|---:|---:|---:|',
]
for d in details:
    lines.append(f'| [{d["opponent"]}]({d["official_url"]}) | {d["result"]} | {END[d["end_reason"]]} | {d["terminal_turn"]} | {d["public_score_y"]} | {"미공개" if d["public_score_k"] is None else d["public_score_k"]} |')
lines += [
    '', '## 출처와 한계', '',
    '`ui-extract.json`은 각 공식 상세 화면의 표시값을 축약한 원시 추출이다. `details.json`은 키를 붙인 정규화 결과이고 `build_summary.py`로 요약을 재생성한다. 공식 리플레이 JSON 원본이나 전체 DOM 스냅샷으로 표시하지 않는다.', '',
    '인증 Chrome의 별도 탭에서 공개 회차 필터를 적용한 뒤 24개 경기 상세의 `끝으로`를 눌렀다. root 작업 탭, 제출 선택, 게임 실행, 소스 및 Git은 조작하지 않았다. 계정 이메일·인증정보·서명된 다운로드 주소는 저장하지 않았다.', '',
    'Re:verse 리플레이 파일 클릭의 download 이벤트는 관측했지만 파일 경로를 확보하지 못했다. 이후 `chrome://downloads/` 접근은 Browser Use URL 보안 정책이 거부해 중단했다. 우회하지 않았으며, 이번 수집은 공식 UI 증거로 한정한다.', '',
    '공개 회차 이름 17:00과 개별 경기 상세 시각 14:40–15:22는 다른 필드다. v11 표시는 24개 상세에서 직접 확인했다. v11과 v8 소스 ZIP의 관계는 별도 제출 이력·해시 근거를 인용해야 한다.', '',
    '이전 제출 #9(10:00 회차)의 오류 승리는 원본 JSON상 **신촌도 우리땅**과 **개우진보러갈까**다. 우트와윤트와 200OK가 아니다. 그 회차 정상 경기만의 성적은 10승 12패(45.45%)다. 상대 구성과 맵·상대 버전 차이를 통제하지 않은 두 비율 차이를 정책 개선의 인과효과로 해석하지 않는다.', '',
    '전송 검증: 브라우저에서 생성한 정규 JSON은 3,467자이며 UTF-16 FNV-1a32 `e6cbb5f4`; 로컬 재계산과 일치한다. 저장 파일별 SHA-256은 `manifest.json`에 있다.',
]
(HERE / 'summary.md').write_text('\n'.join(lines) + '\n')

manifest = {'source': SOURCE, 'files': []}
for name in ['ui-extract.json', 'details.json', 'summary.json', 'summary.md', 'build_summary.py']:
    data = (HERE / name).read_bytes()
    manifest['files'].append({'path': name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
manifest['ui_record_checksums'] = [{'game_id': d['game_id'], 'sha256': hashlib.sha256(json.dumps(d, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()} for d in details]
write_json('manifest.json', manifest)
print(json.dumps(summary, ensure_ascii=False, indent=2))
