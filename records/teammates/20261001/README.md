# 2026-10-01 팀원 전략 비교 기록

결론과 해석은 [팀원 전략 비교 문서](../../../docs/29-팀원전략비교와대전.md)에 있다. v8과 `손형권_v1`의 소스를 바꾸지 않고 직접 64경기와 공통 상대 96경기를 실행했다. 총 40개 맵·160경기이며 오류·몰수·무승부는 0건이다.

| 파일 | 역할 |
|---|---|
| [plan.json](plan.json) | 경기 전 고정한 브랜치·소스/ZIP 해시·맵·실행 제한·가설 |
| [summary.json](summary.json) | 직접/공통 상대, 진영별 집계·불확실성·행동 지표·명령 감사 |
| [match-index.json](match-index.json) | 160개 고유 경기의 결과·진영·시드·리플레이 SHA256 |
| [decision.json](decision.json) | v8 유지, 팀원 전체 교체 보류, 후속 비교와 한계 |
| [v8-source-review.md](v8-source-review.md) | 경기 전 소스 비교, 활성/비활성 탐색 기능 |
| [direct-cases.md](direct-cases.md), [direct-cases.json](direct-cases.json) | 패배 4건·대표 승리 3건의 턴별 명령·소유권·해시 |
| [분석기 검증](analysis/analyzer-validation.json), [독립 검토](analysis/independent-review.md) | 결과 집계·생산/손실·최종 상태·해석 경계 확인 |

`jisang`에는 `runs/` 아래 전 경기 원본·계획·실행 세션·명령 감사, `analysis/` 아래 전체 선수 관점과 턴별 궤적, `teammate-source-audit/` 아래 팀원 추적 파일 전체 목록과 관련 소스·문서 스냅샷을 보존했다. 원본 스냅샷은 줄바꿈 공백도 바꾸지 않았다. 원문 일부의 Markdown hard break 두 곳은 일반 `git diff --check` 예외로 보존했다.

`main`에는 위 공유 파일과 대표 경기 7개의 원본 리플레이만 선별했다. 전체 기록은 [jisang의 날짜별 폴더](https://github.com/hkson0826-oss/YonKo_hackathon_-/tree/jisang/records/teammates/20261001)에서 확인한다. 팀원 브랜치의 가상환경·바이너리나 실험 후보 전체를 병합하지 않았다.

## 실행과 검증

경기 전 계획을 커밋한 뒤 공식 배포 SDK를 `/tmp/yk-team-arena-20261001`에 고정했다. 6개 로컬 작업자, 보통 턴 300ms/첫 턴 3,000ms, 상속되는 주소 공간 384MiB 제한이다. 정책 난수 시드는 `20260927`, 맵은 직접전 `18000..18031`, 공통 상대전 `18100..18107`이다. 소스는 수정하지 않았다.

직접전은 8경기 pilot 후 같은 계획의 나머지 56경기를 완료했다. 공통 상대전은 72경기 저장 뒤 프로세스가 exit 143으로 종료되어 동일 계획과 소스 확인 후 `--resume`으로 24경기를 완료했다. 종료 원인은 미확정이다. 재개 전 완료 경기의 ID/원본은 유지됐으며 최종 160개 ID는 중복이 없다.

명령 감사는 8+56+96개 리플레이의 1,101+7,523+14,036 = **22,660개 턴 프레임**을 확인했다. 잘못된 명령·초과 수량 절단을 발견하지 못했다. 분석기는 공식 `step_spawn`으로 실제 생산을 복원하고, 전 경기의 최종 점수·생산−손실=잔존 병력·기존 실행기 diagnostics를 대조했다. 과거 32경기에서도 지표 일치를 확인했지만 이 경기는 이번 성적에 합산하지 않았다.

기존 제출 소스나 ZIP을 변경하지 않았으므로 새 ZIP 검증이나 사이트 재제출은 수행하지 않았다. 현재 서버 상태·리더보드 점수는 확인하지 않았으며 로컬 승률로 추정하지 않는다.

## 분석 재실행

전체 원본이 있는 `jisang` 체크아웃에서 실행한다. SDK 파일 해시는 각 명령 감사의 `sdk_reference_sha256`, 전체 봇/엔진 출처는 각 실행의 `manifest.json`에 기록했다. 아래 출력은 보관된 완료 기록과 분리한다.

```bash
python3 -B experiments/analyze_team_strategy_comparison.py \
  --sdk yk-development-tools \
  --run-dir records/teammates/20261001/runs/direct-pilot/run \
  --run-dir records/teammates/20261001/runs/direct-main/run \
  --focus v8,teammate --output /tmp/yk-team-direct-reanalysis.json

python3 -B experiments/analyze_team_strategy_comparison.py \
  --sdk yk-development-tools \
  --run-dir records/teammates/20261001/runs/common-opponents/run \
  --focus v8,teammate --output /tmp/yk-team-common-reanalysis.json
```

동일 소스 대전을 다시 실행하는 방법은 기존 `experiments/deadline_20260929.py prepare/run`과 고정 `plan.json`을 따른다. 기존 실행 ID를 새 실험에 재사용하지 않는다. v8은 시간 예산에 따라 후보 평가 수가 달라져 정책 난수를 고정해도 매번 동일 궤적이 보장되지는 않는다.

## 지표 해석과 도구 범위

- 경기 수와 선수 관점 수를 구분한다. 직접 64경기는 128개 선수 관점이고, 공통 96경기는 192개 선수 관점이다.
- bootstrap은 맵 단위 4,000회 재표집이다. 같은 맵의 진영·상대 경기는 독립 표본처럼 취급하지 않는다. 지도 특징별 구간은 사후 탐색이며 인과효과가 아니다.
- 건물 소유는 턴 처리 후 상태다. `building_turns`는 소유 건물 수의 합이며, 생산 전 할인 가능 여부를 세는 기존 `engineering_turns`와 다르다. 정확한 자원 수입으로 변환하지 않는다.
- 구간별 생산·손실은 해당 구간에 진입한 경기의 합계 평균이며 턴당 속도가 아니다. 후반 checkpoint는 이미 끝난 경기를 제외한다. 직접전 80턴은 61경기, 120턴은 46경기, 실제 최종 상태는 64경기다.
- 이 분석기는 이번 균형 설계와 matchup당 1회 실행을 대상으로 썼다. 다른 정책 시드의 동일 matchup 반복이나 불균형·미완료 배치를 합치기 전에는 pairing 키와 추정량을 다시 정해야 한다. 현재 입력에는 해당 문제가 없다.
- 원본 실행 경로는 `/tmp`로 기록되어 있다. 보관 경로는 `match-index.json`과 경기 ID, 원본 SHA256으로 대응한다. 임시 경로를 재현에 필요한 영구 저장 위치로 간주하지 않는다.
