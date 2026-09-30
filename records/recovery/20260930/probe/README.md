# guard4 방어 예약 반례 검사

저장소 루트에서 다음 명령으로 25검사를 재현한다. 생성한 실행 파일은 `/tmp`에만 둔다.

```bash
g++ -std=c++20 -O2 -I submissions/recovery-20260930-guard4 records/recovery/20260930/probe/probe.cpp -o /tmp/yk-guard4-probe
/tmp/yk-guard4-probe
```

`fixtures.inc`는 두 기록된 공통 상태와 기준선 행동을 고정한 입력이다. 원본 경로·해시는 `fixture-sources.json`에 있다. `make_probe.py`의 원래 임시 경로는 당시 생성 이력이며, 이미 보존된 fixture로 재현할 때 다시 실행할 필요가 없다. 테스트는 최초 행동 차이와 경계 조건을 확인하며 전체 경기 승률 개선을 증명하지 않는다.
