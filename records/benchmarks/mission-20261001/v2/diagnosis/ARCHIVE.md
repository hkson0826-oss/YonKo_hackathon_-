# 보존 범위

`/tmp/yk-mission-v2-review-20261001`의 분석·소스·검증 JSON 9개를 그대로 복사했다. 파일별 원래 경로·바이트·SHA-256은 `archive-manifest.json`에 있다. `g++-no-rally`는 56바이트 셸 소스이며 컴파일 바이너리가 아니다.

- [분석 요약](README.md), [집계 및 대표 경기 원명령](evidence.json), [검증 실행 요약](hall-contract-summary.json).
- `hall-contract-v2.json`: HALL 계약 실패(16턴 중립화).
- `hall-contract-v3-rally.json`, `hall-contract-v3-no-rally.json`: 같은 v3 소스의 합류 on/off 모두 HALL 계약 통과(15턴 침입 차단).
- `all-contracts-v3-rally.json`: 합류 on의 전체 11개 SDK 계약 통과 실행. off의 전체 계약 결과와 구분한다.
- off 전체 기존 10개 계약 실행의 9통과·병원 합류 1실패 증거는 [defense-v3/protocol](../../../../research/new-bot-20261001/defense-v3/protocol/)에 별도로 보존했다.

원본 연구 스크립트의 `/tmp` 경로는 실행 당시 출처로 유지했다. `review.py`를 다른 체크아웃에서 재실행할 때 `--v1`은 `records/benchmarks/mission-20261001/v1`, `--v2`는 이 폴더의 상위 `v2`, `--output`은 별도 임시 디렉터리로 지정하고, 스크립트의 `flow_source` 및 v1 `summary.json` 경로를 해당 체크아웃의 `v1/diagnosis`로 맞춘다. 보존된 원본 결과를 덮어쓰지 않는다.

v3 테스트 당시 구현 해시는 `5cff84e533234f02fa8665de009ec7b2d10641c5baf5a33ac3fcc7edddb434e1`이다. 이 폴더의 회귀 계약 증거를 v2 전체 대전 성능 개선으로 해석하지 않는다.
