# 독립 임무 봇 v4 — 실행 검증 기록

이 ZIP은 연구 후보다. 이 작업에서 서버 업로드·대회용 선택을 하지 않았다. 최종 비교와 전달 후보는 [검증 결과](../../../docs/31-독립임무봇검증결과.md)를 따른다. 사이트에서 별도로 선택된 서버 v9와 구분한다.

- [소스](../../../submissions/mission-scheduler-v4-20261001/main.cpp): `b06263e5cffee351fa23e6279b2f6f5f1cda0a5c1106cfc3516c005aad97c9e7`
- [ZIP](../../../artifacts/mission-scheduler-v4-20261001.zip): `351cb2246f3a9b7dee240e032e55b62cf298c08f1dbe608b1864dacd14325e14`, 12,471바이트, 소스·헤더·메타데이터 4파일
- 정확한 ZIP 추출본을 GCC 12.2/C++20/O2로 빌드했다. SDK smoke 1경기와 별도 2맵·양 진영 4경기를 통과했다. CPU 4경기는 3승 1패, 오류·몰수 0이며 승률 우위 증거로 쓰지 않는다.
- 일반 턴 300ms·첫 턴 3초·주소 공간 384MiB·경기 180초·출력 한도를 적용했다. 후보 관측 최대 응답 6.71ms, 명령 무시·수량 잘림 0이다. 서버 자체 환경의 최악 실행 시간을 보장하는 값은 아니다.
- 임시 GCC·빌드 디렉터리 삭제, 환경·signal 복구, 입력 해시 불변을 확인했다. [원 검증](validation.json), [CPU 경기](cpu-matches.json), [명령 감사](action-audit.json), [ZIP 검사](zip-inspection.json).

프로젝트 루트에서 빌드한다.

```sh
g++ -std=c++20 -O2 submissions/mission-scheduler-v4-20261001/main.cpp -o /tmp/yk-mission-v4
python3 -B yk-development-tools/bots/dist/starter/run_tests.py --zip artifacts/mission-scheduler-v4-20261001.zip
```

`python3 -B experiments/verify_gcc12_tmp.py --zip artifacts/mission-scheduler-v4-20261001.zip --output /tmp/yk-mission-v4-gcc12-new.json --direct-wrapper`는 임시 GCC12 빌드와 SDK smoke를 다시 수행한다. 출력은 새 경로를 사용한다. 저장된 4경기 CPU 검증 전체를 다시 실행하는 명령은 아니다. 원 arena manifest의 `/tmp` 경로는 당시 실행 위치이며 현재 checkout의 파일 경로를 뜻하지 않는다.

v4는 공식 관측과 SDK를 사용하는 독립 행동 검사 12개를 통과했다. `MISSION_SCHEDULER_SOURCE=submissions/mission-scheduler-v4-20261001/main.cpp python3 -B tests/test_mission_scheduler.py`로 실행한다. 필요한 공식·개발 리플레이가 없으면 검사가 skip되므로 결과의 skip 수까지 확인한다.
