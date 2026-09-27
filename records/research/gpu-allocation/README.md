# GPU 자원 배분 보완 근거

2026-09-27 Firecrawl MCP research index로 검색하고 세 논문의 관련 본문을 조회했다. JSON은 MCP 응답의 `structuredContent`를 보존한 것으로 검색 결과와 질문에 해당하는 본문 발췌다. 논문 전체를 수집했다는 뜻은 아니다.

| 출처 | 확인한 내용 | 원응답 |
|---|---|---|
| [Sample Factory, 2006.11751](https://arxiv.org/abs/2006.11751) | CPU 환경, GPU 배치 추론, learner 분리; 한 GPU에 복수 learner 배치; 통신·정책 지연 | [read-sample-factory.json](read-sample-factory.json) |
| [Population Based Training, 1711.09846](https://arxiv.org/abs/1711.09846) | 최소 학습 후 exploit/explore, checkpoint 복제·하이퍼파라미터 변경 | [read-pbt.json](read-pbt.json) |
| [ASHA, 1810.05934](https://arxiv.org/abs/1810.05934) | 최소·최대 자원, 비동기 승급, 잘못된 초기 승급 가능성 | [read-asha.json](read-asha.json) |

검색은 [샘플링·자원 효율](search-sampling.json), [자원 배분·PBT·ASHA](search-allocation.json)에 보존했다. 검색에서 나온 3D 배치 시뮬레이션·VLA·대형 데이터셋 HPO의 속도 수치는 이 게임에 적용하지 않았다. 후보 큐 크기·비율·측정 범위는 논문의 권장값이 아니라 프로젝트의 미실행 제안이다.

최종 설계: [GPU 자원 배분 보완](../../../docs/13-GPU자원배분보완.md).
