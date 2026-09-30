# 독립 임무 봇 v3 — 실행 검증 기록

이 ZIP은 연구 후보다. 이 작업에서 서버 업로드·대회용 선택을 하지 않았다. 최종 비교와 전달 후보는 [검증 결과](../../../docs/31-독립임무봇검증결과.md)를 따른다. 사이트에서 별도로 선택된 서버 v9와 구분한다.

- [소스](../../../submissions/mission-scheduler-20261001/main.cpp): `5cff84e533234f02fa8665de009ec7b2d10641c5baf5a33ac3fcc7edddb434e1`
- [ZIP](../../../artifacts/mission-scheduler-20261001.zip): `1837a01407b6e2783824db305acf1a95df2c0eb04527642b1274db4c17579dce`, 12,411바이트, 소스·헤더·메타데이터 4파일
- 정확한 ZIP 추출본을 GCC 12.2/C++20/O2로 빌드했다. SDK smoke 1경기와 별도 2맵·양 진영 4경기를 통과했다. CPU 4경기는 3승 1패, 오류·몰수 0이며 승률 우위 증거로 쓰지 않는다.
- 일반 턴 300ms·첫 턴 3초·주소 공간 384MiB·경기 180초·출력 한도를 적용했다. 후보 관측 최대 응답 7.46ms, 명령 무시·수량 잘림 0이다. 서버 자체 환경의 최악 실행 시간을 보장하는 값은 아니다.
- 임시 GCC·빌드 디렉터리 삭제, 환경·signal 복구, 입력 해시 불변을 확인했다. [원 검증](validation.json), [CPU 경기](cpu-matches.json), [명령 감사](action-audit.json), [ZIP 검사](zip-inspection.json).

프로젝트 루트에서 빌드한다.

```sh
g++ -std=c++20 -O2 submissions/mission-scheduler-20261001/main.cpp -o /tmp/yk-mission-v3
python3 -B yk-development-tools/bots/dist/starter/run_tests.py --zip artifacts/mission-scheduler-20261001.zip
```

`python3 -B experiments/verify_gcc12_tmp.py --zip artifacts/mission-scheduler-20261001.zip --output /tmp/yk-mission-v3-gcc12-new.json --direct-wrapper`는 임시 GCC12 빌드와 SDK smoke를 다시 수행한다. 출력은 새 경로를 사용한다. 저장된 4경기 CPU 검증 전체를 다시 실행하는 명령은 아니다. 원 arena manifest의 `/tmp` 경로는 당시 실행 위치이며 현재 checkout의 파일 경로를 뜻하지 않는다.

v3 고정 당시 독립 행동 검사 11개는 통과했다. 이후 추가한 종반 병원 F 생산 계약은 v3의 알려진 실패이며 v4에서 수정했다. 현재 12개 전부를 v3가 통과한다고 해석하면 안 된다.
