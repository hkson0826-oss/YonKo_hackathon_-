# v3 방어 수정의 근거와 검증 보존본

v1의 seed19013 K/j_balanced 경기에서 HALL 방어가 빠진 이유를 계측한 기록이다. `task-audit/`는 방어 후보·예약, `allocation-detail/`은 생산 이후 예약 초기화와 W 목표 배분을 추적한다. 두 실행 모두 원본 123턴의 K 명령을 전부 재현했다. 원본 소스·manifest·JSON을 바이트 그대로 보존했고, 복사 출처·해시는 `archive-manifest.json`에 있다. 컴파일된 `allocation-detail/trace`는 제외했다.

- [확정 원인 및 한계](task-audit/summary.json): 적 F당 한 건물만 선택해 HALL 후보가 누락됨, 실제 방어 예약이 초기화됨, 방어의 남은 수요보다 큰 W 묶음 전체가 배분됨.
- [방어 후보·예약 원본 trace](task-audit/audit.json), [W 배분 상세 trace](allocation-detail/audit.json).
- v1 SDK 국소 반사실과 clipping 보정은 [v1 diagnosis](../../../benchmarks/mission-20261001/v1/diagnosis/README.md)에 있다.
- v2 대전 비교 및 v3 HALL 계약 on/off 통과는 [v2 diagnosis](../../../benchmarks/mission-20261001/v2/diagnosis/README.md)에 있다.

14턴 **입력**의 적 F는 `(11,7)`이고 14턴 종료 위치는 `(11,8)`이다. HALL ETA3/rank12.6보다 ENG ETA4/rank15.6이 높아 HALL이 후보에서 빠졌다. 관측된 국소 결함과 수정 후 전체 대전 승률은 별도로 판단한다.

## 프로토콜 증거 구분

| 실행 | 범위 | 결과 |
|---|---|---|
| v3 합류 on | 기존 10개 + 새 HALL 계약 | 11개 통과 (`v2/diagnosis/all-contracts-v3-rally.json`) |
| v3 합류 off | 새 HALL 계약 단독 | 통과, 15턴 침입 차단 (`v2/diagnosis/hall-contract-v3-no-rally.json`) |
| v3 합류 off 전체 실행 | HALL 추가 전 기존 10개 | 9통과, 병원 합류 계약 1실패 (`protocol/`의 JSON·log) |

합류 off의 전체 실행 JSON은 소스 해시 `14263049e51f07632404637698b7d6a7783d23a14f7858e9a202e2462066be78`를 기록한다. HALL 단독 on/off 검사는 기본 소스 `5cff84e533234f02fa8665de009ec7b2d10641c5baf5a33ac3fcc7edddb434e1`를 각각 기본 옵션 또는 `-DMISSION_RENDEZVOUS=0`으로 컴파일했다. 서로 다른 파일 해시와 실행 범위를 섞지 않는다.

## 원래 경로와 재현

원래 두 폴더는 `/tmp/yk-mission-defense-audit-20261001` 및 `/tmp/yk-mission-defense-detail-20261001`였다. `task-audit/README.md`에 남은 “sibling directory”는 현재 `allocation-detail/`을 가리킨다. 분석 코드의 원래 `/tmp` 경로는 출처 기록으로 보존했다.

새 체크아웃에서 재현하려면 해당 폴더를 임시 작업 디렉터리에 복사하고, `analyze.py`의 SDK 경로를 `records/benchmarks/mission-20261001/v1/snapshot/yk-development-tools`, 리플레이 경로를 `records/benchmarks/mission-20261001/v1/runs/development-common/replays/ca61304a881abc2d17a4d2c8.json.gz`로 맞춘다. 임시 복사본 안에서 `g++ -O2 -std=c++20 trace.cpp -o trace`와 `python3 -B analyze.py`를 실행한다. 저장소의 보존 JSON과 manifest를 덮어쓰지 않는다.
