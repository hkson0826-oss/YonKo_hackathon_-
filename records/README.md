# 실험 기록

현재 제출은 [v4 검증 기록](submissions/v4/README.md)을 따른다. 이전 제출과 실험 원본은 각 실행 폴더에 보존한다.

| 폴더 | 내용 |
|---|---|
| [official/opponent-intel-20260928](official/opponent-intel-20260928/) | 상대 15팀·18경기 분석, 104팀 성적표, 추가 화면 관측, 독립 상대 사양 |
| [research/opponent-intel-20260928](research/opponent-intel-20260928/README.md) | 도착 기한 배정·종반 동시 행동·상대 모델·공략형 확장 연구 |
| [official/round2](official/round2/) | 최신 v3 공식 13경기 분석·실제 제출 연결·4패의 턴별 근거 |
| [benchmarks/v1](benchmarks/v1/) | 초기 예제·정책별 대전, 공격형 검사, 응답 시간 검사 |
| [benchmarks/teammate-v1](benchmarks/teammate-v1/) | 팀원 봇 원본 정보·제출 검사, 기존 v1과의 대전 |
| [benchmarks/v2](benchmarks/v2/) | 동일한 새 맵에서 실행한 v1·v2의 팀원 봇 상대 성적 |
| [replays](replays/) | 초기 실패 사례와 최종 평가의 패배 리플레이 |
| [submissions](submissions/) | 제출 ZIP별 검사 결과와 SHA-256·파일 목록 |
| [tuning](tuning/) | 후보 10개의 소스, 변경 설정, 개발 대전, 직접 대전 |
| [official/round1](official/round1/) | 사용자 제공 공식 5경기의 원본 해시·턴별 분석·사이트 관찰 |
| [research/round2](research/round2/) | Firecrawl 원응답, 논문·원 구현 출처와 확인 수준 |
| [research/gpu-allocation](research/gpu-allocation/) | Sample Factory·PBT·ASHA의 자원 배분 근거와 본문 확인 |
| [teammates/round2](teammates/round2/) | 최신 팀원·main ZIP 비교와 고정 소스 스냅샷 |
| [compute/round2](compute/round2/) | 로컬 환경과 CPU 작업자 1/2/4 처리량·로그·패배 리플레이 |
| [compute/code-search-pilot](compute/code-search-pilot/) | 실제 v2 판단 병목, 동일 대전의 CPU 병렬도 비교, CPU/CUDA 평가함수 정합성·실행 상태 |
| [research/compute-choice](research/compute-choice/) | CUDA·Python·irace·SMAC 공식 문서와 코드 탐색 적용 근거 |
| [research/local-league-search](research/local-league-search/) | Firecrawl 논문 확인과 실제 탐색 후보의 적용 범위·약점 |
| [league/campaign-001](league/campaign-001/README.md) | 43개 설정·2,674경기, 최종 비교·동결 소스·전체 결과·저장 리플레이·서버 복구 |
| [league/checkpoints-001](league/checkpoints-001/) | 완료 단계별 중간 결과·수비 후보 리플레이 분석·서버 자원 관측 |
| [league/loop2-design](league/loop2-design/) | 공식·내부 패배 및 개선 반사실, 신규 24개와 재수정 12개의 자체 비판·연구·검사·잠금 후보 검토 |
| [league/loop2-iteration1](league/loop2-iteration1/README.md) | 첫 반복 2,058경기·전 경기 리플레이·동결 소스·출력량·해시·TMP 정리 검증 |
| [league/loop2-iteration2](league/loop2-iteration2/README.md) | 실제 재수정 후 4,892경기·선택 잠금·64개 미사용 맵 검증·수정 효과와 회귀 |
| [league/loop2-cross-family](league/loop2-cross-family/README.md) | 새 상대 계열 6종·32맵·768경기, 384MiB 주소공간 제한과 추가 감사 |
| [league/loop2-checkpoints](league/loop2-checkpoints/) | 각 반복의 완료 배치만 회수한 중간 기록·원인 분석 표본·주 후보 잠금 |
| [submissions/v3](submissions/v3/README.md) | 추천 v3 ZIP·소스 해시·실제 ZIP 빌드·SDK 및 CPU 실행 검사 |
| [league/loop3-design](league/loop3-design/) | v3 후속 21개 후보, 새 연구 원문·실패와 개선 사례·규칙 검사·동결 해시 |
| [league/loop3-checkpoints](league/loop3-checkpoints/) | v3 후속 리그에서 완료된 단계만 회수한 중간 기록 |

공식 원본은 [artifacts/firstround_results](../artifacts/firstround_results/)에 그대로 보존했다. [분석 도구](../experiments/analyze_official_round1.py)는 합법 관측으로 알 수 있는 점수와 사후 복원 점수를 구분한다. [처리량 측정 도구](../experiments/profile_throughput.py)는 고정한 봇 소스·새 임시 빌드로 같은 맵을 반복하며, 기존 출력 경로 덮어쓰기를 거부한다.

최초 v2 튜닝의 선택 후보는 `tuning/portfolio-assets/`다. 당시 후보의 소스 해시와 결과 파일은 [tuning/index.json](tuning/index.json)에 기록했다. 해당 폴더의 `losses-*`에는 후보 평가 중 저장한 패배·무승부 리플레이가 있다. [campaign-001](league/campaign-001/README.md)은 v2 유지를 결정한 이전 리그다. 이후 36개 신규 후보·7,718경기의 반복 개선으로 v3를 채택했다. [최신 판단과 한계](../docs/19-반복개선검증결과.md).

최초 v2의 새 맵 검증은 시드 3000~3019의 양 진영 40경기다. [v2 결과](benchmarks/v2/benchmark-v2-team-holdout.json)는 38승 2패, [동일 조건의 v1 결과](benchmarks/v2/benchmark-v1-team-holdout.json)는 33승 7패다. v2의 두 패배는 [3012/Y](replays/v2-team-holdout/seed-3012-Y.json), [3019/K](replays/v2-team-holdout/seed-3019-K.json)에 저장했다.

`.json` 결과에는 시드·진영·승패·점수·종료 사유·턴 수·응답 시간이 있으며, 짝이 있는 `.log`에는 경기 완료 순서대로 출력된 결과가 있다. 응답 시간의 상대 봇 항목과 진영별 집계는 도구를 확장한 이후 결과부터 기록된다. 초기 대전은 저장 옵션을 켠 패배·무승부 중심이며, `loop2` 반복은 승리를 포함한 **전 경기 리플레이**를 저장하고 논리 전이 해시를 검증한다.

폴더 정리에서는 저장 파일의 연결 경로만 갱신했다. 승패·시드·점수·시간, 봇 소스와 제출 ZIP 내용은 변경하지 않았다. 과거 실행 명령과 환경 정보에는 당시 절대 경로가 남아 있으며, 현재 환경의 재실행 방법은 [프로젝트 안내](../README.md)에 있다. [path-map.json](path-map.json)은 정리 전후 파일 위치를 연결한다.

제출 ZIP은 기존 다운로드 경로를 유지해 [v1](../artifacts/submission-v1.zip), [v2](../artifacts/submission-v2.zip), [추천 v3](../artifacts/submission-v3.zip)에 보관했다. 실행 바이너리와 캐시는 포함하지 않는다.
