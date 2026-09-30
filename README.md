# 연고전 AI 해커톤 — 제출 봇과 전략 조사

**대회 사용 코드: 사이트 v8 — [submission-20260929-guard3.zip](artifacts/submission-20260929-guard3.zip)**

9/30 01:30에 v8 선택과 새로고침 후 유지를 확인했다. 중급·상급 모의 전투는 각각 10전 10승, 실행 오류 0이다. 요청한 9/29 20:00 마감은 놓쳤으며 실제 업로드는 9/30 01:19였다. [제출 이력과 남은 한계](docs/27-20260929-guard3제출.md) · [최종 소스](submissions/deadline-20260929-guard3/) · [검증 기록](records/submissions/deadline-20260929/README.md)

개발·선택·최종 리그 1,016경기 중 독립 최종 10맵에서 guard3는 Y 45/50승, K 44/50승이었다. 기준선 로컬 v4는 각각 31/50승, 38/50승이며, 사이트 v7 소스는 없어 직접 비교하지 못했다. 아래 v1~v4 안내와 마감 시각은 과거 기록이다.

**이전 추천 제출 파일: [artifacts/submission-v4.zip](artifacts/submission-v4.zip)**

v3 이후 33개 신규 후보·18,804리그 경기를 진행했다. 그중 마지막으로 고정한 후보는 새 128맵에서 v3 대비 Y **+10.07%p**, K **+7.12%p**, 별도 48맵에서 Y **+5.56%p**, K **+5.09%p**로 사전 조건을 모두 통과했다. 두 독립 확인은 smoke·교차 대전을 포함해 **6,416경기·179고유맵**, 오류·몰수 0이다.

실제 v4 ZIP도 TMP GCC12.2 빌드·SDK 기본 실행·새 CPU 4경기를 통과했다. 최대 후보 응답은 **130.73ms**였다. **[공유 요약·남은 약점](docs/24-s3독립검증결과.md)** · **[최종 소스](submissions/iterative-v4/)** · **[검사·해시·재현](records/submissions/v4/README.md)**

먼저 선택했던 방어 강화 후보는 추가 검증에서 기각했다. 그 판정은 [이전 실패 기록](docs/22-v3후속검증결과.md)에 보존하며, 이후 s3를 새 맵으로 독립 확인했다. 기존 v3 ZIP과 [당시 공유 기록](docs/21-v3공유요약.md)도 유지한다.

오늘(2026-09-28) 마감은 한국시간 오전 8시다. `main`은 검증된 제출·공유 자료를 제공하며, 진행 중인 개선 실험과 전체 리플레이는 `jisang`에 있다. 공식 GCC 12.2.0 환경의 사이트 빌드·검사는 업로드 후 확인해야 한다.

아래 v2·v1 성적은 이전 버전의 이력이다.

v2는 팀원 봇 상대 개발 맵 40전 38승, 별도 새 맵 40전 38승이었다. 기존 v1과 직접 대전에서는 20전 12승이며 제출 형식·컴파일·실행 검사를 통과했다. [튜닝 결과와 로그](docs/06-v2튜닝결과.md)

ZIP 자체를 업로드한다. 압축을 풀어 다시 감싸지 않는다. 업로드와 제출 코드 선택은 사용자가 직접 한다. 서버에서 빌드·검사가 통과하면 중·상 난도 연습 결과를 확인한다.

폴더 구성:

```text
artifacts/                 제출용 v1·v2·v3·v4 ZIP
submissions/first/         v1 C++ 소스
submissions/tuned/         v2 C++ 소스
submissions/iterative-v3/  이전 v3 C++ 소스
submissions/iterative-v4/  현재 추천 v4 C++ 소스
submissions/delineate-v1.zip  팀원 봇 원본
docs/                      규칙·조사·전략·검증 문서
tests/                     공식 엔진 대조 검사와 대전 도구
experiments/               튜닝 후보 생성·비교 스크립트
records/
  benchmarks/              v1·v2·팀원 대전 결과와 실행 로그
  replays/                 저장한 실패 경기의 턴별 상태·명령
  submissions/             제출 형식 검사와 ZIP 해시
  tuning/                  후보별 소스·설정·결과·리플레이
```

[기록 폴더 안내](records/README.md). 제공된 `yk-*` SDK와 안내 자료는 원래 위치에 보존했다. 로컬에서 생성하는 실행 파일과 압축 해제 캐시는 Git에서 제외한다.

| 문서 | 내용 |
|---|---|
| [현재 v4 독립 검증](docs/24-s3독립검증결과.md) | 제출 ZIP·새 128+48맵 성적·GCC12 실제 실행·남은 약점 |
| [이전 v3 공유 요약](docs/21-v3공유요약.md) | 이전 v3 제출물·검증·한계·원본 기록 |
| [규칙과 제출](docs/01-대회규칙과제출.md) | 전체 규칙, 판정 순서, 자원·전투·점령, 제출 제약, 운영 정보 |
| [Firecrawl 조사](docs/02-Firecrawl조사.md) | 실제 Lux 우승 회고, 동시 행동 탐색·정책 포트폴리오·상대 집단 연구와 원문 링크 |
| [알고리즘과 약점](docs/03-알고리즘과약점분석.md) | 폐기한 접근, 실제 1차 알고리즘, 대전 결과, 패배 분석, 최종 우승 후보 설계 |
| [상급 전승 이후 벤치마크](docs/04-벤치마크운영.md) | 서버 결과 확인, 기존 평가 도구, 새로운 실패 맵, 상대 집단과 실행 방법 |
| [팀원 봇 대전](docs/05-팀원봇대전.md) | 손형권 v1 브랜치 수신, 양 진영 40경기 결과와 패배 리플레이 |
| [v2 튜닝과 검증](docs/06-v2튜닝결과.md) | 채택한 개선, 개발·새 맵·직접 대전 결과, 로그와 제출 파일 추적 |

이전 v3를 빌드해 v2와 소규모로 비교하려면 프로젝트 루트에서 실행한다. 이 간단한 도구는 패배·무승부 리플레이만 저장하며, 위 최종 검증을 대체하지 않는다. 임시 파일은 종료 시 삭제하고 결과만 고유 경로에 보존한다. 전체 패키지 재검사는 [제출 기록](records/submissions/v3/README.md)의 명령을 따른다.

```bash
(
  set -eu
  run_tmp=$(mktemp -d /tmp/yk-recheck-XXXXXXXX)
  trap 'rm -rf -- "$run_tmp"' EXIT
  export TMPDIR="$run_tmp" PYTHONDONTWRITEBYTECODE=1
  run_id=${run_tmp##*/}
  g++ -std=c++20 -O2 submissions/iterative-v3/main.cpp -o "$run_tmp/v3"
  g++ -std=c++20 -O2 submissions/tuned/main.cpp -o "$run_tmp/v2"
  python3 tests/benchmark.py \
    --candidate "$run_tmp/v3" --opponent "$run_tmp/v2" \
    --start 7600 --seeds 2 --workers 2 \
    --save-losses "records/replays/reproduction/$run_id" \
    --output "records/benchmarks/reproduction/$run_id.json"
)
```

과거 실험 스크립트는 후보 소스·결과를 다시 생성할 수 있다. 동결 기록을 직접 덮어쓰지 않고 별도 TMP checkout과 새 결과 경로로 실행한다.

아래는 보존한 v1의 구성과 검증 이력이다. v1은 C++20으로 작성한 정책 3종, 최대 4턴의 동시 시뮬레이션, 3×3 후보 행렬의 혼합 선택을 사용한다. 신경망·학습 가중치·외부 패키지가 없다. [소스](submissions/first/main.cpp)

로컬 검증 결과:

- 제공 ZIP 검사 통과: 컴파일·실행·명령 검사 문제와 출력 경고 없음.
- 예제 lv2 상대 30개 맵, 양 진영 60전 60승.
- 자체 고정 정책 3종 상대 48전 47승 1패.
- 위 108경기 몰수 0회, 관측 최대 응답 약 37ms.
- 규칙 반례 18개 통과, 공식 엔진과 무작위 상태 전이 300개 일치.

후속 확인에서 서버 상급 상대 10전 10승(모두 Y)을 확인했다. 추가 로컬 검사에서는 공격형 정책 상대 새 맵 20개·양 진영 40전 중 38승 2패였고, 시드 1017에서는 양쪽 진영 모두 패했다. [결과와 벤치마크 운영](docs/04-벤치마크운영.md)

팀원 `손형권_v1`의 별도 Python 봇과는 같은 20개 맵·양 진영 40전에서 **25승 15패**, 몰수 0회였다. [결과와 재실행 방법](docs/05-팀원봇대전.md)

실제 대회 참가자 전반의 성능은 아직 확인하지 않았다. 내부 정책 상대는 코드 구조를 공유하므로 해당 승률을 실전 승률로 해석하지 않는다. 초기 검사에서 발견한 시드 0/Y의 패배는 중반 22:10 우세 후 최종 7:24로 역전된 경기이며 [리플레이](records/replays/v1-initial/v1-loss-seed0.json)를 보관했다.

실제 제출 환경은 GCC 12.2.0/CPU/300ms이며 로컬 환경과 다르다. 정확한 제한은 [배포 제한](yk-development-tools/bots/dist/starter/limits.json)을 따른다. 개발 과정에서는 CPU·GPU를 활용할 수 있으며, 현재 v4는 신경망 가중치 없는 C++ 코드다.
