# 최신 공식 회차의 부분 리플레이 분석

**사이트에서 확인한 최신 회차 목록은12경기(7승5패)지만, 다운로드 원본은 붉은 산호초전1개뿐이다.** 이 폴더에서 생산·이동·F손실·소유권을 전 턴 분석한 범위는 그1경기의98턴이다. 나머지11경기·4패의 세부 전개를 분석했다고 주장하지 않는다. 다른 경기의 화면 관측은 상위 폴더의 별도 UI 기록을 따른다.

경기 ID·상대·진영·결과·사이트 제출8은 [수집 목록](../matches.json)과 대조했다. 원본에 제출 ZIP 바이트 해시는 없으므로 사이트 버전8과 정확한 서버 ZIP 해시를 리플레이 자체만으로 증명하지 않는다. 원본은 변경하지 않았다.

## 확인한 사실

- 붉은 산호초전은98턴 즉시 패배다. 최종 Y점수0은 원본 공개값이며 **K점수35는 공개된 거점 점수와180도 대칭으로 정확히 재구성한 합계**다. 원본 K총점 필드는null이다. 직접 공개12개·대칭5개로17건물 모두 확정됐고, 음수·미지점수·중간값을 대입하지 않았다.
- 초반 경제 거점 침투로 설명되는 패배가 아니다. 양쪽 모두5턴에 ENG/HALL/병원을 갖췄고, 우리 최초 경제 손실은89턴 ENG다. 우리 F는37생산/34사망, W생산465 대 상대560으로 전방 점령·F반복 소모와 생산 격차가 경제 상실보다 먼저 나타난다.
- 29턴 F2/W2가 이미 적W3이 있는 HALL로 진입해 F2가 사망했다. 실제 우리 행동에 적 전원 정지라는 합법 반응을 적용해도 공식 엔진에서 같은 F2손실이 난다.
- 당시 공개 상태의 v8내부 상대정책0·2는 이 손실을 이미 예측하고1·3만 생존을 예측한다. '네 모델이 모두 위험을 못 봤다'는 설명은 기각한다. 전체 시간제한 행동 선택을 재현하지 않았으므로 선택 이유는 미확정이다.
- 같은 상태에서 F2를 북쪽으로 철수시키는 대안은 정지+네 내부모델의1턴 검사에서 F를 보존한다. 이는1턴 전투 반례이며 전체 경기 승리나 실제 상대 명령 재현이 아니다.

## 파일

| 파일 | 내용 |
|---|---|
| [summary.md](summary.md), [summary.json](summary.json) | 수집된 경기만의 수치, 누락된 수집 ID 목록, 시점·소스·SDK 해시 |
| [analysis.json](analysis.json) | 전 턴 생산·손실·소유권, 모든 F전사 전후 주변병력·실제 우리명령 |
| [cases.md](cases.md) | 개막·22/29턴 F손실·중반 점수·늦은 경제 붕괴의 관측과 한계 |
| [development-cases-partial.json](development-cases-partial.json) |22·29·46·89턴의 실제 합법 입력과 우리명령·다음 관측. 후대 숨은 점수를 삽입하지 않음 |
| [score-reconstruction-evidence.json](score-reconstruction-evidence.json) |17거점 각각의 점수·직접 공개/대칭 출처·첫 공개 턴 |
| [model-probe-reproducible.json](model-probe-reproducible.json) | 고정29턴 상태·기록행동/철수대안 × 내부4모델/정지의1턴 결과·해시 |
| [analyze_latest.py](analyze_latest.py) | 공식 참가자 뷰 분석. 기존 공식 분석기의 생산·이동 검증을 재사용 |
| [run_model_probes.py](run_model_probes.py), [probe_v8_models.cpp](probe_v8_models.cpp), [probe_v8_models-input.txt](probe_v8_models-input.txt) | v8소스와 고정 공개 상태로 모델 반례 재현; 임시 실행 파일은 자동 제거 |
| [verify_score_reconstruction.py](verify_score_reconstruction.py) | 임의 점수 보정 없이17건물의 정확한 합계를 재검증 |

상대 명령은 원본에 없다. 상대 W생산은 전투에서 양쪽 W가 같은 수만큼 사라지는 규칙으로 역산했으며, 상대 F생산·손실은 복원하지 않았다. 우리 생산·이동98전이는 공식 SDK로 확인했지만 전체 상대 명령을 갖춘 경기 재현은 아니다. 명령98개는 전부`ok`이고 시간초과는 없었다. 모델probe의 C++전이는 독립된1턴 진단이며 정지 반응에 대한 F사망은 별도로 공식 Python엔진에서 확인했다.

## 재현

저장소 루트에서 아래 명령을 사용한다. 아직 수집되지 않은 경기는 만들거나 추정하지 않는다. 분석 출력은 이 폴더에 쓰며, 새 원본을 추가한 뒤 실행하면 분석 범위와 누락 목록을 다시 계산한다.

```bash
python3 -B records/official/latest-20261001/analysis/analyze_latest.py --expected-games 12 --identity records/official/latest-20261001/matches.json
python3 -B records/official/latest-20261001/analysis/verify_score_reconstruction.py
python3 -B records/official/latest-20261001/analysis/run_model_probes.py
```

새 분석 결과를 과거 완료 기록과 분리할 때에는 각 스크립트의`--output`을 새 경로로 지정한다. 분석기는 거점 점수를 전부 직접/대칭으로 확정할 수 없는 원본에서 추정 총점을 만들지 않고 중단한다. 현재 경기의 숨은 값은 모두 정확히 확정 가능하다. 사용한 공식 실패 상태는 개발 사례이며 새 검증 맵 성적에 합치지 않는다.
