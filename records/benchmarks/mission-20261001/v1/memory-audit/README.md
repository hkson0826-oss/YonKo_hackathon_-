# v1 임무 기억 계측

고정 v1 소스 SHA256 `657693b842b738ce92f0e3b99746e3d6d10a44fe8ab5f52b6433b28bc8a950b3`를 별도 wrapper에 포함했다. 원본 후보 파일은 계측을 위해 수정하지 않았다.

`analyze.py`는 공식 SDK로 원본 명령을 실행해 다음 합법 관측을 복원하고, 공개 점수 마스크를 적용한 프로토콜을 wrapper에 보낸다. wrapper의 모든 출력 명령을 원본과 비교한다. 비공개 리플레이 점수나 상대 명령은 봇 입력에 직접 추가하지 않는다.

범위는 pilot-direct 8경기 전체와 development-common에서 seed19012 양 진영 6경기 및 seed19010 Y 3경기, 총 17경기다. 공통 상대 9경기는 실패 진단을 위해 사후 선택한 표본이며 전체 common 결과가 아니다. 기억 복구율은 F 개체 식별이 아니라 코드의 가상 임무 토큰 집계다.

- `recovered_valid_missions`: 다음 관측 수량과 대조해 목표가 유효하게 복구된 기존 F 토큰 수.
- `continued_missions`: 출력 임무의 age가 0보다 큰 수. 이전 목표를 이어간 가상 임무 수다.
- `one_step_reverse_flow_units`: 전 턴 A→B와 이번 턴 B→A F 흐름의 최솟값 합. 같은 병사의 물리적 왕복임을 식별한 값은 아니며, 합류 셀의 서로 다른 F가 교차한 경우도 포함한다.
- `F_hold_units`: 현재 F + 명령의 신규 F 생산 − MOVE/TELE 출발 F. 음수는 0으로 제한한다.

재현:

```sh
g++ -O2 -std=c++20 /tmp/yk-mission-memory-audit-20261001/trace.cpp -o /tmp/yk-mission-memory-trace-20261001
python3 -B /tmp/yk-mission-memory-audit-20261001/analyze.py
```

분석기의 SDK·arena 경로는 당시 `/tmp/yk-new-bot-20261001/yk-development-tools`와 `/tmp/yk-mission-arena-v1-20261001/runs`로 고정돼 있다. 다른 위치에 재현할 때는 이 두 경로, OUT과 wrapper 실행 경로를 바꾸되 `source-v1` 해시와 원본 replay 해시를 먼저 대조한다. `summary.json`은 경기별, `aggregate.json`은 묶음별 결과이며 각 job JSON에 턴별 기억과 원명령 예시가 있다.

기억이 작동한다는 검사는 기억이 승률을 개선한다는 제거 실험이 아니다. 역방향 흐름 총량만으로 패배 원인을 확정하지 않는다. 특히 v2 수정의 근거는 seed19012 Y 대 s3의 TURN13에서 병원 앞 F와 W가 합류하지 못한 구체적 상태와 별도 공식 엔진 반사실이다.
