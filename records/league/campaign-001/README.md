# 다양한 후보 리그 결과

완료 경기 **2,674전**, 후보 43개. 내부 승격 기준 추천은 **v2**다.

| 단계 | 경기 수 |
|---|---:|
| smoke | 90 |
| screen | 1,032 |
| selection | 720 |
| holdout | 720 |
| crossplay | 112 |

최종 후보는 선택 단계에서 고정했다. 아래 수치는 24개 새 맵과 고정 상대 5개에서의 검증이며 실제 참가자 전체에 대한 승률 추정은 아니다.

| 후보 | Y 승/무/패 | Y 승점률 | K 승점률 | v2 대비 Y 차이·맵 bootstrap 95% 구간 | 몰수 | 최대 응답 |
|---|---|---:|---:|---|---:|---:|
| v2 | 110/0/10 | 91.7% | 86.7% | 기준선 | 0 | 71.8ms |
| r_combined | 109/0/11 | 90.8% | 90.0% | -0.8%p [-6.7, +5.0] | 0 | 65.8ms |
| p_01 | 105/0/15 | 87.5% | 85.0% | -4.2%p [-7.5, -0.8] | 0 | 73.3ms |

승격 기준은 사전에 정했다: 주 후보의 Y 개선 3%p 이상·구간 하한 양수·양쪽 무오류/무몰수·상대별 Y 회귀 10%p 이내. 보조 후보가 더 좋아 보여도 그 결과를 보고 주 후보를 바꾸려면 새로운 검증 맵을 사용한다.

## r_combined

Combine joint defense, shared-arrival escort, engineering savings, and terminal ordering.

사전 약점: Interactions may overcommit scarce units; compare against individual repairs before adoption.

같은 Y 조건에서 결과가 개선된 경기는 6개, 회귀한 경기는 7개다. 공학관 할인 보유 비율의 평균 차이는 +2.4%p, 턴당 W 생산 차이는 +0.11명이다. 경기 길이·행동이 함께 달라지므로 원인 효과로 단정하지 않는다.

| 상대 | Y 승점률 차이 |
|---|---:|
| v2 | +8.3%p |
| teammate | -12.5%p |
| c_economy_direct | +0.0%p |
| c_territory_direct | +0.0%p |
| c_spearhead_direct | +0.0%p |

개선 사례: 맵 6216/Y, 상대 v2. v2 {'Y': 10, 'K': 27} → 후보 {'Y': 33, 'K': 4}. 상세 수치와 리플레이 경로는 [analysis.json](analysis.json)에 보존했다.

회귀 사례: 맵 6209/Y, 상대 v2. v2 {'Y': 31, 'K': 0} → 후보 {'Y': 13, 'K': 17}. 상세 수치와 리플레이 경로는 [analysis.json](analysis.json)에 보존했다.

## p_01

경제·병력 가치의 다른 조합을 같은 맵에서 비교한다.

사전 약점: 행동 후보 공간 자체는 v2와 같으며 계수만으로 방어 누락을 고칠 수 없다.

같은 Y 조건에서 결과가 개선된 경기는 0개, 회귀한 경기는 5개다. 공학관 할인 보유 비율의 평균 차이는 +0.5%p, 턴당 W 생산 차이는 +0.01명이다. 경기 길이·행동이 함께 달라지므로 원인 효과로 단정하지 않는다.

| 상대 | Y 승점률 차이 |
|---|---:|
| v2 | -16.7%p |
| teammate | -4.2%p |
| c_economy_direct | +0.0%p |
| c_territory_direct | +0.0%p |
| c_spearhead_direct | +0.0%p |

회귀 사례: 맵 6223/Y, 상대 v2. v2 {'Y': 30, 'K': 0} → 후보 {'Y': 10, 'K': 17}. 상세 수치와 리플레이 경로는 [analysis.json](analysis.json)에 보존했다.

## 기록 해석

`crossplay-table.json`은 원 경기마다 양쪽 관점을 집계한다. 각 run의 `summary.json`은 원래 candidate 열의 결과이므로 상호 대전 전체 순위에는 crossplay table을 사용한다.

모든 경기 요약·응답시간·진단 지표는 `runs/*/results.jsonl`, 패배·무승부와 첫 맵 승리의 전체 진행은 `runs/*/replays/*.json.gz`에 있다. gzip을 풀어 기존 JSON 리플레이처럼 읽을 수 있다. 실행 바이너리는 보존하지 않으며 실제 소스·헤더·SDK 스냅샷과 해시를 남겼다.

원격 작업은 TMP 안에서 실행됐다. 실제 자원 제한·정리 결과는 `remote_supervisor.json`, `transport_receipt.json`, `transport.jsonl`을 확인한다. 이 보고서는 실제 제출 ZIP 교체나 사이트 업로드를 수행했다는 뜻이 아니다.
