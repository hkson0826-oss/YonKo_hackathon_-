# 후속 알고리즘 연구 기록

2026-09-27, `jisang`에서 [v2](../../../submissions/tuned/main.cpp)를 기준으로 조사했다. 결론·8개 접근 비교·실험안은 [연구 문서](../../../docs/08-다양한접근과근거.md), 출처와 적용 한계는 [sources.json](sources.json)에 있다.

## 수집 방법

- 사용 도구: 설정된 `mcp__firecrawl` MCP 서버의 논문 검색, 관련 논문 확장, 본문 질의, 원문 페이지 수집.
- `firecrawl-research-index`와 `firecrawl-scrape` 스킬을 읽고 적용했다. CLI 인증을 MCP 연결 여부로 해석하지 않았다.
- 3개 초기 주제 검색 후 RHEA·프로그램 전략 상대 선택의 관련 논문을 확장했다. 배정·CMA-ES·SMAC3·CEM을 추가 검색했다.
- 핵심 12개 논문은 본문을 확인했다. 보조자료 2개는 본문, CEM 변형 1개는 초록까지만 확인해 근거 수준을 구분했다.
- `read_program_sketch.json`은 서버 500 오류다. 같은 논문의 HTML을 Firecrawl scrape로 가져온 `read_sketch_fallback.json`으로 대체했다.
- 원 구현 2개는 저자/개발 프로젝트의 저장소 README를 읽었다. 설치·실행하지 않았으며 관찰한 커밋만 색인에 기록했다.

`raw/`의 28개 JSON에는 검색 결과와 직접 읽은 본문 응답, 오류가 들어 있다. 검색 결과에는 채택하지 않은 인접 자료도 포함된다. 검색 순위와 유사도는 방법의 우수성이나 이 게임 성능을 뜻하지 않는다. 수집 시각은 해당 연구 배치의 기록 시각이며 각 개별 네트워크 요청의 정확한 완료 타임스탬프가 아니다.

## 핵심 원문

| ID | 원문 | 확인한 쟁점 |
|---|---|---|
| R1 | [Target Assignment and Path Finding](https://arxiv.org/abs/1612.05693) | 충돌 회피·최소 완료시간 목적의 범위 |
| R2 | [Asymmetric Action Abstractions](https://arxiv.org/abs/1711.08101) | 일부 유닛만 추상화 해제, 상대 행동 고정 |
| R3 | [Combinatorial Multi-armed Bandits for RTS](https://arxiv.org/abs/1710.04805) | 개별/공동 통계, 작은 표본의 한계 |
| R4 | [Hannan Consistent Selection in SM-MCTS](https://arxiv.org/abs/1804.09045) | 수렴 반례와 추가 조건 |
| R5 | [Portfolio Search and Optimization](https://arxiv.org/abs/2104.10429) | 긴 계획의 역할 흔들림과 sparse 변경 |
| R6 | [Opponent Modelling in an RTS Game](https://arxiv.org/abs/2006.08659) | 부정확한 모델에 대한 RHEA 민감도 |
| R7 | [NTBEA](https://arxiv.org/abs/1802.05991) | 이산 노이즈 설정 탐색 |
| R8 | [CMA-ES Tutorial](https://arxiv.org/abs/1604.00772) | 연속 블랙박스 최적화 |
| R9 | [SMAC3](https://arxiv.org/abs/2109.09831) | 조건부 설정과 인스턴스별 racing |
| R10 | [PSRO](https://arxiv.org/abs/1711.00832) | 경험 payoff, 상대 혼합, 집단 과적합 |
| R11 | [Choosing Well Your Opponents](https://arxiv.org/abs/2307.04893) | 프로그램 합성에 유용한 참조 상대 선택 |
| R12 | [Imitating an Oracle Planner](https://arxiv.org/abs/2012.12186) | 교사 특권 정보와 학생 관측 구분 |

원 구현: [SMAC3](https://github.com/automl/SMAC3), [pycma](https://github.com/CMA-ES/pycma). 보조 연구: [양측 공진화](https://arxiv.org/abs/1607.01730), [프로그램 sketch 학습](https://arxiv.org/abs/2203.11912), [CEM 변형](https://arxiv.org/abs/2009.09043).

## 재현과 완료 범위

이 하위 작업은 연구와 실험 설계만 완료했다. 봇 소스 변경, 경기 실행, 논문 결과 재현, GPU 학습은 수행하지 않았다. 사용자 추가 공식 경기 원본은 읽거나 수정하지 않았다. 이 연구 자료만으로 후보 채택을 확정하지 않는다.

소스 기준 커밋과 SHA-256은 `sources.json`에 있다. 논문 인덱스가 반환한 HTML/PDF 텍스트에는 수식 변환 흔적이 있으므로 구현 시 식을 원문과 다시 확인해야 한다. 출처 전체를 빠짐없이 찾았다고 주장하지 않는다.
