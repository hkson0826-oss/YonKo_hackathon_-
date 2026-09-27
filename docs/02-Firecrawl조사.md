# Firecrawl 조사: 관련 알고리즘과 실제 대회 사례

조사일: 2026-09-27. 사용자가 지정한 **Firecrawl MCP 서버**의 웹 검색, 원문 수집, 논문 검색, 관련 논문 확장, 본문 질의 도구를 사용했다. CLI나 일반 검색 결과만으로 대체하지 않았다. 원문 응답은 프로젝트의 `.firecrawl/`에 보관했다.

모든 관련 정보를 망라했다고 주장할 수는 없다. 아래는 이 게임의 제약과 직접 연결되는 방법군과 1차 자료를 조사한 결과다. 검색에서 나온 관련성이 낮은 항공 전투·분자 설계·일반 밴딧 논문은 핵심 근거에서 제외했다. 다른 게임의 논문 실험 수치를 이 게임의 예상 승률로 옮기지 않았다.

## 1. 실제 대회 우승 사례에서 가져올 것

| 자료 | 확인한 내용 | 이 대회에 적용 | 그대로 옮기면 안 되는 부분 |
|---|---|---|---|
| Lux AI Season 2 1위 Ryan Anderson | 역할과 목표를 유지하며 여러 턴을 전방 시뮬레이션. 경제와 공격을 결합하고 역할 중복을 관리 | 생산·이동·점령을 따로 최적화하지 말고 하나의 계획으로 평가. 유닛별 목표 예약 | Lux의 전력·채굴·아군 충돌 규칙은 여기 없음. 그 대회의 탐색 시간도 여기보다 김 |
| Lux AI Season 2 2위 Tigga | 상태를 유지하는 규칙 기반 봇, 역할 배분, 안전 검사, 자가 대전. 후기에서 늦은 공격 대응과 잦은 이동을 약점으로 명시 | 안전성 검사와 역할 변경 비용, 종반 별도 계획, 패배 원인 분류 | “규칙 기반이면 충분하다”는 일반적 보장은 아님 |

출처: [1위 작성자의 회고](https://www.kaggle.com/competitions/lux-ai-season-2/writeups/ry-andy-1st-place-solution), [2위 작성자의 회고](https://www.kaggle.com/competitions/lux-ai-season-2/writeups/tigga-yet-another-logic-bot). 두 글은 Firecrawl로 본문을 직접 읽었다. 1위의 성공뿐 아니라 특정 상대에게 약했던 부분까지 확인했다.

이 사례에서 내린 판단은 **경제·전술·역할 배분·전방 시뮬레이션을 잘 구현한 봇이 강력한 후보가 될 수 있다**는 것이다. “규칙 기반이 항상 강화학습보다 낫다”는 결론은 아니다.

## 2. 탐색 공간을 줄이는 방법

### Asymmetric Action Abstractions for Multi-Unit Control in Adversarial Real-Time Games

일부 유닛은 스크립트가 제안한 행동만 고려하고, 중요한 일부 유닛에는 더 다양한 행동을 허용한다. PGS와 SSS 계열을 확장한다. 논문 본문에서 원래 방식의 상대 행동 고정 가정과 세밀한 제어가 필요한 유닛에 계산을 더 배분하는 이유를 확인했다. [논문](https://arxiv.org/abs/1711.08101)

적용: 후방 W 이동은 가벼운 경로 정책에 맡기고, 경합 건물·위험한 F·병원 앞 전투에 탐색을 집중한다. 여기에는 체력이 없으므로 원문의 “체력이 낮은 유닛 우선” 기준 대신 **점유를 바꿀 수 있는 유닛 우선**으로 바꿔야 한다.

### Combinatorial Multi-armed Bandits for Real-Time Strategy Games

여러 유닛의 행동 조합으로 분기 수가 커지는 문제에 대해 naive sampling을 제안하고 RTS에서 평가한다. [논문](https://arxiv.org/abs/1710.04805)

적용: W 한 명씩 모든 조합을 열거하지 않고 부대·역할 단위 후보를 뽑는다. 다만 F와 호위 W의 동시 도착, TELE 한 번, 공동 생산 예산처럼 상호작용하는 제약을 독립 행동처럼 다루면 잘못된 계획을 만든다. 이 게임에서는 결합 행동을 만든 뒤 전체 자원·도착 결과를 다시 검사해야 한다.

### Portfolio Search and Optimization for General Strategy Game-Playing

포트폴리오와 Rolling Horizon Evolutionary Algorithm을 결합하고, 포트폴리오 및 파라미터 최적화에 NTBEA를 사용한다. [논문](https://arxiv.org/abs/2104.10429)

적용: 경제, 확장, 호위, 공격, 방어, 종반 뒤집기 등 서로 다른 계획을 생성하고 비교한다. 같은 휴리스틱의 가중치만 조금 바꾼 후보들보다 행동 자체가 다른 후보가 중요하다. 이것은 원문을 이 게임에 맞춰 해석한 설계 판단이다.

### Combining Strategic Learning and Tactical Search in Real-Time Strategy Games

상위 전략 선택과 하위 전술 탐색을 결합한 연구다. 원문 방식에는 학습된 CNN이 포함된다. [논문](https://arxiv.org/abs/1709.03480)

적용: 계층 분리는 채택하되, 현재 제출 규정 아래에서는 CNN 가중치를 제출하지 않는다. 상위 계층은 소스에 구현된 경제·역할 정책, 하위 계층은 짧은 정확 시뮬레이션으로 구성한다.

### The N-Tuple Bandit Evolutionary Algorithm for Game Agent Optimisation

평가 비용이 비싸고 노이즈가 있는 조합적 파라미터 최적화를 다룬다. [논문](https://arxiv.org/abs/1802.05991)

적용: F 목표 수, 역할 우선순위, 탐색 깊이 등의 후보 설정을 여러 시드와 여러 상대에 대해 비교하는 오프라인 실험 방법 후보. 1차 버전에는 자동 튜닝을 실행하지 않았으며 현재 수치는 수작업 초기값이다. 학습 모델을 상수 배열로 위장하여 제출하는 우회는 제안하지 않는다.

## 3. 동시 턴 게임에서 필요한 이론

### Convergence of Monte Carlo Tree Search in Simultaneous Move Games

동시 행동 게임에서 탐색과 행동 선택을 분석하고, 추가 조건 아래 후회 최소화 계열 선택 방법의 수렴을 다룬다. [논문](https://arxiv.org/abs/1310.8613)

적용: 내 행동을 고른 다음 적이 이를 보고 대응하는 순차 미니맥스로 바꾸지 않는다. 각 후보의 동시 조합을 payoff matrix로 계산하고 혼합 전략을 고려한다.

### Analysis of Hannan Consistent Selection for Monte Carlo Tree Search in Simultaneous Move Games

중요한 반례다. 개별 선택기가 no-regret라고 해서 표준 SM-MCTS가 자동으로 균형에 수렴하지 않는다. 평균 보상을 쓰는 수정과 탐색 조건, 추가적인 UPO 가정 등을 구분한다. 이 부분은 초록뿐 아니라 Firecrawl의 본문 질의로 확인했다. [논문](https://arxiv.org/abs/1804.09045)

적용: “regret matching을 넣었으니 전체 게임에서 최적”이라고 말하지 않는다. 1차 봇은 **3×3의 제한된 후보 행렬에서 짧은 시뮬레이션 값을 사용**한다. 원래 게임 전체의 내시 균형을 구한 것이 아니다.

### Tree Search for Simultaneous Move Games via Equilibrium Approximation

동시 행동 환경에서 트리 탐색 내부에 근사 균형 계산을 넣는 방법을 다룬다. [논문](https://arxiv.org/abs/2406.10411)

적용: 동시 행동을 명시적으로 모델링하는 설계 근거다. 논문의 학습 구조 전체를 구현하거나 검증한 것은 아니다.

### Computing Approximate Nash Equilibria and Robust Best-Responses Using Sampling

균형 전략과 특정 상대를 더 잘 공략하는 반응의 차이, 상대 공략과 강건성의 결합을 다룬다. [논문](https://arxiv.org/abs/1401.4591)

적용: 상대가 수비형임이 관측되면 이를 공략하되, 한 모델에 완전히 의존하지 않는다. 적의 정책을 틀리게 추정할 때도 크게 지지 않는 후보를 유지한다.

## 4. 과적합을 막는 상대 집단

### A Unified Game-Theoretic Approach to Multiagent Reinforcement Learning

독립 학습 정책이 훈련 상대에 과적합할 수 있음을 다루고, 상대 정책의 혼합에 대한 근사 최적 반응과 메타 전략을 사용한다. PSRO 계열의 핵심 자료다. [논문](https://arxiv.org/abs/1711.00832)

적용: 최신 봇 하나와만 자가 대전하지 않는다. 과거 버전, 확장형, 전투 집중형, 방어형, 병원 압박형, 종반 공격형을 남긴다. 여기서는 학습 가중치 대신 직접 구현한 정책들의 대전 행렬에도 이 운영 아이디어를 적용할 수 있다.

### Choosing Well Your Opponents: How to Guide the Synthesis of Programmatic Strategies

프로그램 형태의 전략을 개선할 때 어떤 참조 상대를 선택할지를 다룬다. MicroRTS 등의 실험을 제시한다. [논문](https://arxiv.org/abs/2307.04893)

적용: 모든 실험을 예제 봇에 쓰지 말고, 현재 버전이 실제로 지는 전략을 적극적으로 상대 집합에 추가한다. 1차 봇의 실패 맵과 공격형 정책을 회귀 검사에 남기는 이유다.

### Neural Fictitious Self-Play on ELF Mini-RTS

단순 자가 대전과 게임 이론적 학습을 Mini-RTS에서 연구한다. [논문](https://arxiv.org/abs/1902.02004)

적용: 자가 대전 정책 집단 연구의 참고 자료. 현재 규정과 1차 제출 목적에서는 학습 모델의 직접 배포를 선택하지 않았다.

## 5. 역할 배분·경로 계획의 인접 연구

### Optimal Target Assignment and Path Finding for Teams of Agents

목표 배정과 경로 계획을 결합하고 최소비용 흐름을 활용한다. [논문](https://arxiv.org/abs/1612.05693)

적용: 깃발병들이 같은 건물로 몰리는 것을 막기 위해 목표별 수요를 두고 배정한다. 이 게임은 아군끼리 겹칠 수 있으므로 원문의 충돌 회피 제약을 그대로 넣으면 불필요한 제약이 생긴다. 적과의 동시 도착과 전투만 별도로 모델링한다.

### Flow-Based Task Assignment for Large-Scale Online Multi-Agent Pickup and Delivery

온라인 임무 배정을 환경 그래프의 최소비용 흐름으로 다루는 인접 연구다. [논문](https://arxiv.org/abs/2508.05890)

적용: 병력 공급 위치와 임무 수요를 함께 생각하는 참고 자료다. 적대적 전투와 W 우세 문턱이 없는 운송 문제이므로 해법의 최적성을 이 게임으로 이전할 수 없다.

## 6. 추가로 조사했지만 최종 중심 방법에서 제외한 것

| 자료 | 배제 또는 보류 이유 |
|---|---|
| [Centralized control for multi-agent RL in a complex RTS game](https://arxiv.org/abs/2304.13004) | Lux의 RL 구현 사례. 데이터·규칙·출력 공간이 다르고 현재 가중치 제출 제약과 맞지 않음 |
| [StarCraft Micromanagement with RL and Curriculum Transfer Learning](https://arxiv.org/abs/1804.00810) | 교과 과정 학습은 참고 가능하나 체력·공격 구조가 다른 전술 문제 |
| [Approximation Models of Combat in StarCraft 2](https://arxiv.org/abs/1403.1521) | 이 게임은 전투가 정확한 정수 상쇄라 전투 근사 모델을 새로 학습할 이유가 작음 |
| [The Design of Stratega](https://arxiv.org/abs/2009.05643) | 전방 모델을 사용하는 전략 게임 연구 도구. 이미 제공된 정확 엔진을 우선 활용 |
| [Simultaneous AlphaZero](https://arxiv.org/abs/2512.12486) | 동시 행동 학습·탐색의 인접 연구이나 가중치 제출 금지와 1차 구현 비용 때문에 보류 |

2026년 논문도 검색에 나타났지만, 최근이라는 이유만으로 검증된 기존 방법보다 우선하지 않았다. 이번 설계는 제공 엔진을 재현할 수 있고 실제 로컬 검증을 할 수 있다는 장점을 우선 사용한다.

## 7. 조사에서 도출한 선택

**우선순위는 정확한 규칙 처리 → 경제와 역할 배분 → 짧은 동시 행동 탐색 → 다양한 상대에 대한 검증이다.**

추천 구조는 소스 코드로 실행되는 C++ 정책 포트폴리오에 정확한 상태 전이, 중요한 유닛에 집중한 전술 탐색, 제한된 행동 행렬의 혼합 전략을 결합하는 방식이다. 이 조합은 위 연구와 대회 사례를 이 게임의 300ms·CPU·소스 제출 제약에 맞춰 적용한 제안이며, 기존 논문 이름을 바꾼 새로운 학술 알고리즘이라고 주장하지 않는다.

연구 요약과 구현의 구분:

- **구현됨:** 3가지 정책, 4턴 전방 시뮬레이션, 3×3 동시 행동 행렬, 후회 최소화에 의한 혼합 선택.
- **아직 제안 단계:** 서로 다른 8개 이상의 행동 정책, 중요 부대별 국소 탐색, 점수의 여러 가능한 조합 평가, 상대 정책 추정, 적응형 종반 탐색, 상대 집단을 이용한 자동 튜닝.
- **검증하지 않음:** 공개 논문에 실린 다른 게임의 성능 재현, 실제 대회 상위 참가자 상대 승률, GPU 학습의 이 대회 효용.

## 8. 재현 가능한 조사 기록

`.firecrawl/`에 저장한 주요 응답:

- `event.json`, `round2_2.json`: 대회 공지 검색·본문.
- `round2_0.json`, `round2_1.json`: RTS 탐색·동시 행동 논문 검색.
- `rel_abstraction.json`: 관련 논문 그래프 확장.
- `read_asym.json`, `read_hannan.json`: 핵심 가정에 대한 본문 질의.
- `research_bandit.json`, `research_psro.json`, `mapf_paper.json`: 방법군 보완 조사.
- `lux_winner.json`, `lux_second.json`: 참가자가 직접 쓴 우승·준우승 회고 원문.

검색 결과 원문에는 관련성이 낮은 자료도 함께 들어 있다. 보고서의 결론은 위에서 명시한 자료와 로컬 엔진 검증에 근거한다.
