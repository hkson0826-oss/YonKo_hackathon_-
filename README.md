# 연고전 AI 해커톤 — 제출 봇과 전략 조사

**현재 추천 제출 파일: [artifacts/submission-v2.zip](artifacts/submission-v2.zip)**

v2는 팀원 봇 상대 개발 맵 40전 38승, 별도 새 맵 40전 38승이었다. 기존 v1과 직접 대전에서는 20전 12승이며 제출 형식·컴파일·실행 검사를 통과했다. [튜닝 결과와 로그](docs/06-v2튜닝결과.md)

공식 1차는 **4승 1패, 참고 12위·보정 61.0%**다(9/27 22:00 공개). 사이트 v3가 로컬 `submission-v2.zip`에 해당한다. [공식 경기 분석](docs/07-공식1차경기분석.md), [사이트 운영·최종 평가](docs/10-사이트운영과보정점수.md), [다음 전략과 검증 순서](docs/12-후속개발우선순위.md)를 함께 읽는다. 후속 연구 단계에서 새 제출 ZIP을 만들지는 않았다.

ZIP 자체를 업로드한다. 압축을 풀어 다시 감싸지 않는다. 업로드와 제출 코드 선택은 사용자가 직접 한다. 서버에서 빌드·검사가 통과하면 중·상 난도 연습 결과를 확인한다.

폴더 구성:

```text
artifacts/                 제출용 v1·v2 ZIP
submissions/first/         v1 C++ 소스
submissions/tuned/         v2 C++ 소스
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
| [규칙과 제출](docs/01-대회규칙과제출.md) | 전체 규칙, 판정 순서, 자원·전투·점령, 제출 제약, 운영 정보 |
| [Firecrawl 조사](docs/02-Firecrawl조사.md) | 실제 Lux 우승 회고, 동시 행동 탐색·정책 포트폴리오·상대 집단 연구와 원문 링크 |
| [알고리즘과 약점](docs/03-알고리즘과약점분석.md) | 폐기한 접근, 실제 1차 알고리즘, 대전 결과, 패배 분석, 최종 우승 후보 설계 |
| [상급 전승 이후 벤치마크](docs/04-벤치마크운영.md) | 서버 결과 확인, 기존 평가 도구, 새로운 실패 맵, 상대 집단과 실행 방법 |
| [팀원 봇 대전](docs/05-팀원봇대전.md) | 손형권 v1 브랜치 수신, 양 진영 40경기 결과와 패배 리플레이 |
| [v2 튜닝과 검증](docs/06-v2튜닝결과.md) | 채택한 개선, 개발·새 맵·직접 대전 결과, 로그와 제출 파일 추적 |
| [공식 1차 분석](docs/07-공식1차경기분석.md) | 5경기·생산 격차·종반 경합 반례와 재현 도구 |
| [후속 알고리즘 연구](docs/08-다양한접근과근거.md) | 접근 8계열의 적용 범위·약점·원문 및 채택 기준 |
| [팀원 최신 변경](docs/09-팀원변경검토.md) | 새 커밋·ZIP 실제 차이, 동일 소스 해시 및 채택 판단 |
| [사이트·보정 점수](docs/10-사이트운영과보정점수.md) | 상대·제출물 연결, 최종 순위·마감·보고서·최신 제한 |
| [GPU 계획](docs/11-GPU실험계획.md) | RTX 3090 8개 활용, CPU 처리량, 학습·확대·중단 조건 |
| [GPU 자원 배분 보완](docs/13-GPU자원배분보완.md) | 공용 작업 큐·다중 후보·배치 추론·성과에 따른 자원 재배분 |
| [후속 개발 순서](docs/12-후속개발우선순위.md) | 제안 알고리즘, 자체 약점 검토, 구현·벤치마크 명세 |
| [CPU·GPU 선택 근거](docs/14-CPU와GPU선택근거.md) | 코드·파라미터 경쟁, CPU 전체 대전과 GPU 배치 계산의 역할 |
| [CPU·GPU 실측과 실행법](docs/15-CPU와GPU실측결과.md) | 판단 병목, 병렬 대전 비교, CUDA 실행 상태, 재개 가능한 탐색 도구 |
| [다양한 후보 리그](docs/16-다양한후보리그계획.md) | 43개 후보·최대 2,674경기, 미사용 맵 검증, 공용 서버 TMP 실행·복구 |

v2를 빌드하고 팀원 봇과 대전하려면 프로젝트 루트에서 실행한다. 상세 리플레이는 패배·무승부만 저장한다. 다음 명령은 별도 결과 파일을 만들어 기존 검증 기록을 보존한다.

```bash
g++ -std=c++20 -O2 submissions/tuned/main.cpp -o artifacts/tuned_bot
python3 -m zipfile -e submissions/delineate-v1.zip artifacts/opponents/delineate-v1
python3 tests/benchmark.py \
  --candidate './artifacts/tuned_bot' \
  --opponent 'python3 artifacts/opponents/delineate-v1/main.py' \
  --start 3000 --seeds 20 \
  --save-losses records/replays/reproduction/v2-team \
  --output records/benchmarks/reproduction/v2-team.json
python3 yk-development-tools/bots/dist/starter/run_tests.py --zip artifacts/submission-v2.zip
```

`experiments/tune_presubmit*.py`도 위 명령으로 팀원 ZIP을 푼 뒤 실행할 수 있다. 실험 스크립트는 해당 후보의 소스·결과를 다시 생성하므로 보관된 기록을 재현할 때는 별도 checkout을 권장한다.

아래는 보존한 v1의 구성과 검증 이력이다. v1은 C++20으로 작성한 정책 3종, 최대 4턴의 동시 시뮬레이션, 3×3 후보 행렬의 혼합 선택을 사용한다. 신경망·학습 가중치·외부 패키지가 없다. [소스](submissions/first/main.cpp)

로컬 검증 결과:

- 제공 ZIP 검사 통과: 컴파일·실행·명령 검사 문제와 출력 경고 없음.
- 예제 lv2 상대 30개 맵, 양 진영 60전 60승.
- 자체 고정 정책 3종 상대 48전 47승 1패.
- 위 108경기 몰수 0회, 관측 최대 응답 약 37ms.
- 규칙 반례 18개 통과, 공식 엔진과 무작위 상태 전이 300개 일치.

후속 확인에서 서버 상급 상대 10전 10승(모두 Y)을 확인했다. 추가 로컬 검사에서는 공격형 정책 상대 새 맵 20개·양 진영 40전 중 38승 2패였고, 시드 1017에서는 양쪽 진영 모두 패했다. [결과와 벤치마크 운영](docs/04-벤치마크운영.md)

팀원 `손형권_v1`의 별도 Python 봇과는 같은 20개 맵·양 진영 40전에서 **25승 15패**, 몰수 0회였다. [결과와 재실행 방법](docs/05-팀원봇대전.md)

공식 1차의 참가자 5팀 상대 결과를 추가했지만 전체 참가자 상대 성능은 아직 알 수 없다. 내부 정책 상대는 코드 구조를 공유하므로 해당 승률을 실전 승률로 해석하지 않는다. 초기 검사에서 발견한 시드 0/Y의 패배는 중반 22:10 우세 후 최종 7:24로 역전된 경기이며 [리플레이](records/replays/v1-initial/v1-loss-seed0.json)를 보관했다.

재빌드·테스트:

```bash
g++ -std=c++20 -O2 submissions/first/main.cpp -o artifacts/first_bot
g++ -std=c++20 -O2 tests/simulator_bridge.cpp -o artifacts/simulator_bridge
python3 tests/test_rules.py
python3 tests/test_simulator.py
python3 tests/benchmark.py --seeds 10
python3 yk-development-tools/bots/dist/starter/run_tests.py --zip artifacts/submission-v1.zip
```

실제 제출 환경은 GCC 12.2.0/CPU/300ms이며 로컬 환경과 다르다. 정확한 제한은 [배포 제한](yk-development-tools/bots/dist/starter/limits.json)을 따른다. 개발에서는 AI·CPU·GPU를 활용해 코드 후보를 만들고 검증하며, 최종 실행 코드의 성능으로 선택한다.
