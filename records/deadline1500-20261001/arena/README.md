# 15:00 제출 전 후보 비교 계획

대전 시작 전 상태. root의 연구 커밋·푸시 및 실행 신호를 기다린다. 이번 범위는 128개 선택 경기와, v8 이외 후보가 선택될 때 64개 확인 경기뿐이다.

- 후보: v8, mission4, v9_lock, v8_flagguard. 상대: s3_selective_contact, r3_opponent_league, j_balanced_portfolio, siphon.
- 선택 맵 23500–23503, 확인 맵 23600–23603, 모든 후보·상대를 양 진영으로 비교한다.
- 봇 8개 전부 GCC 12.2.0 빌드. 각 봇에 독립 cgroup CPU 25%/100ms, 메모리 384MiB 및 주소 공간 384MiB. SDK runner는 제한 scope 밖에 있다. 서버의 quota 주기는 미공개다.
- 8개 독립 SDK worker 병렬. 봇 합계 최대4vCPU/6GiB, 관측 호스트20논리CPU/가용18.1GiB에서 운영한다.
- 14:42:20 신규 경기 중단, 14:43:00 진행 경기 중단 및 scope 정리. 정상 평균20초이면 전체192경기 약8분, 보수적30초이면12분이다.
- 오류·몰수·엄격 명령 감사 문제0 및 모든 scope 제거 확인이 필수다. 선택과 확인 기준은 plan.json의 selection_policy에 고정했다. 선택 승점이 v8과 동률이면 v8 우선이다.
- 확인에서는 선택된 후보 하나와 v8만 비교한다. 전체/Y/j_balanced 승점 각각 v8 이상이고 전체 또는 Y 개선이 있을 때 교체한다. 실패하면 v8이며 확인 맵에서 다른 후보를 재선택하지 않는다.
- launcher/runtime은 기존 14개 0.25vCPU 경기에서 검증된 소스 그대로다. parallel_matches.py가 경기별 프로세스를 추가하고 각 replay를 SDK 전이 및 별도 strict auditor로 검증한다.

실행: `python parallel_matches.py --phase selection --frozen-commit <root SHA>`; 선택 후보가 v8 이외이면 `--phase confirmation --selected <name> --frozen-commit <same SHA>`. 봇·소스·SDK·감사기·harness 해시는 plan.json에 포함된다. 실제 결과는 selection/ 또는 confirmation/에 기록하며 준비 문구를 완료 주장으로 해석하지 않는다.
