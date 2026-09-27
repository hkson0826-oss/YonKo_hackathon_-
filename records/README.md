# 실험 기록

현재 추천 v3의 [제출 검사·해시](submissions/v3/README.md), [평가 요약 근거](submissions/v3/evidence/source-manifest.json), [팀 공유 요약](../docs/21-v3공유요약.md)을 먼저 참고한다. 전체 후보·리플레이는 `jisang`에 보존했다.

| 폴더 | 내용 |
|---|---|
| [benchmarks/v1](benchmarks/v1/) | 초기 예제·정책별 대전, 공격형 검사, 응답 시간 검사 |
| [benchmarks/teammate-v1](benchmarks/teammate-v1/) | 팀원 봇 원본 정보·제출 검사, 기존 v1과의 대전 |
| [benchmarks/v2](benchmarks/v2/) | 동일한 새 맵에서 실행한 v1·v2의 팀원 봇 상대 성적 |
| [replays](replays/) | 초기 실패 사례와 최종 평가의 패배 리플레이 |
| [submissions](submissions/) | 제출 ZIP별 검사 결과와 SHA-256·파일 목록 |
| [tuning](tuning/) | 후보 10개의 소스, 변경 설정, 개발 대전, 직접 대전 |

최종 선택 후보는 `tuning/portfolio-assets/`다. 전체 후보의 소스 해시와 결과 파일은 [tuning/index.json](tuning/index.json)에 기록했다. 해당 폴더의 `losses-*`에는 후보 평가 중 저장한 패배·무승부 리플레이가 있다.

최종 새 맵 검증은 시드 3000~3019의 양 진영 40경기다. [v2 결과](benchmarks/v2/benchmark-v2-team-holdout.json)는 38승 2패, [동일 조건의 v1 결과](benchmarks/v2/benchmark-v1-team-holdout.json)는 33승 7패다. v2의 두 패배는 [3012/Y](replays/v2-team-holdout/seed-3012-Y.json), [3019/K](replays/v2-team-holdout/seed-3019-K.json)에 저장했다.

`.json` 결과에는 시드·진영·승패·점수·종료 사유·턴 수·응답 시간이 있으며, 짝이 있는 `.log`에는 경기 완료 순서대로 출력된 결과가 있다. 응답 시간의 상대 봇 항목과 진영별 집계는 도구를 확장한 이후 결과부터 기록된다. 상세 리플레이는 저장 옵션을 켠 패배·무승부 경기만 포함한다.

폴더 정리에서는 저장 파일의 연결 경로만 갱신했다. 승패·시드·점수·시간, 봇 소스와 제출 ZIP 내용은 변경하지 않았다. 과거 실행 명령과 환경 정보에는 당시 절대 경로가 남아 있으며, 현재 환경의 재실행 방법은 [프로젝트 안내](../README.md)에 있다. [path-map.json](path-map.json)은 정리 전후 파일 위치를 연결한다.

제출 ZIP은 기존 다운로드 경로를 유지해 [v1](../artifacts/submission-v1.zip), [v2](../artifacts/submission-v2.zip)에 보관했다. 실행 바이너리와 캐시는 포함하지 않는다.
