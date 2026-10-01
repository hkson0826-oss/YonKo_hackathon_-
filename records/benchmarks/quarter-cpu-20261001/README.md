공식 2026-10-01 10:42:10 공지의 봇별 0.25 vCPU·일반 300ms·첫 3초 wall 제한을 반영한 로컬 실행 검증 계획이다. 공지는 root가 브라우저에서 확인해 전달했다. 본선도 같은 vCPU라는 내용이지만 서버 CPU 모델, quota period, cgroup burst 설정은 공개되지 않았다. 따라서 이전 normal-CPU 384경기의 응답 시간과 승률을 서버 실행 조건의 검증으로 간주하면 안 된다.

현재 상태는 **코드·계획 준비와 calibration 완료, 대전 0개**다. root가 연구 브랜치에 커밋·푸시한 뒤 확인 신호를 보내면 동결 해시를 기록하고 실행한다. `plan.json`은 실행 전 계획 상태를 보존한다. 실제 완료 여부는 이후 `execution.json`, `results.jsonl`, `summary.json`으로 판단한다.

- 대상: 동결 arena의 siphon, v8, v9_main, v9_lock, mission4. 소스·SDK·바이너리 SHA-256을 계획에 기록하며 실행 전 다시 확인한다.
- 맵: 기존 파일럿·확대 시험 범위와 다른 시드 23400 하나. 각 후보 대 v8 양 진영 10경기를 실제 25% CPU에서 실행한다. v8 자기 대전 두 경기도 런타임 기준선으로 포함한다.
- 대조: 같은 맵에서 v9_main·v9_lock 대 v8 양 진영 normal4경기. 총14경기를 한 경기씩 순차 실행한다.
- 각 봇만 서로 다른 임시 systemd user scope로 실행한다. SDK/runner는 두 scope 밖에서 실행하고, 시작 메타데이터와 서로 다른 cgroup 경로를 검증한다. 기존 사용자 서비스 설정과 전역 설정은 변경하지 않는다.
- quarter는 `CPUQuota=25%`, `CPUQuotaPeriodSec=100ms`, 실제 `cpu.max=25000 100000`, `cpu.max.burst=0` 조건이다. **100ms period는 로컬에서 명시한 조건이며 서버와 같다고 확인된 값이 아니다.** CPU를 네 배 느린 기기로 바꾸거나 SIGSTOP로 흉내 낸 실험이 아니다.
- normal은 해당 scope에 CPU 제한을 설정하지 않는다. 호스트에서 CPU controller가 비활성인 normal scope는 `cpu.max` 파일이 없으며, 활성 상태의 `max PERIOD`도 제한 없음으로 검사한다. 상위 cgroup의 제한도 launch metadata에 기록한다.
- 양 조건 모두 cgroup `memory.max=402653184`와 RLIMIT_AS 384MiB를 적용한다. SDK의 시작 전 첫 응답 타이머를 유지하므로 첫 3초에 systemd scope 생성·Python launcher·봇 기동·INIT도 포함한다. 일반 턴 300ms, 경기 전체 180초 wall를 적용한다.
- 각 scope의 `cpu.stat`, `memory.peak`, `memory.events`, 출력 길이·행 제한, 첫 턴/일반 턴 응답 시간, 몰수 원인을 저장한다. scope 구성 실패는 봇 성능 패배와 분리해 `infrastructure_error`로 기록한다.
- 모든 종료 경로에서 이 실험의 고유 scope만 kill/stop하고 `LoadState=not-found` 및 cgroup 제거를 확인한다. 정리 실패가 있으면 실험 완료로 인정하지 않는다. SIGTERM도 정리 경로로 처리한다.
- `sdk_replay_audit`는 파싱 결과와 공식 SDK 상태 전이가 저장 리플레이와 같은지 확인한다. 이것만으로 명령 clipping이 없다고 주장하지 않는다. 전체 종료 후 동결 arena의 기존 `audit_deadline_actions.py`를 별도로 실행해 공유 생산 예산·이동 재고·TELE·무시 명령을 `strict-action-audit.json`에 기록한다.

calibration은 CPU 계산 0.25초짜리 임시 프로세스 두 개로 실시했다. 마지막 검사는 normal CPU 0.250138초 / wall 0.251055초, quarter CPU 0.250117초 / wall 1.080863초였다. quarter 실제 CPU/wall 비율은 0.23141, `nr_throttled=12`이며 두 scope 제거가 확인됐다. `calibration/validation.json`은 현재 harness 해시와 일치하고 실행 전 필수 검사에 사용한다. 초기 normal 검사에서 `cpu.max`가 반드시 있어야 한다는 가정 때문에 실패한 시도도 별도 파일에 보존했다. 봇을 돌린 실패가 아니다.

root 확인 후 실행 명령:

```bash
python /tmp/yk-quarter-cpu-20261001/run_checks.py --run --frozen-commit <ROOT가_푸시한_커밋>
```

시스템 사용자 버스 접근이 차단된 샌드박스에서는 실행할 수 없다. 이 검사는 승인된 호스트 명령으로 실행한다. stdout에는 게임별 완료 상태만 내보내고 리플레이와 세부 측정은 이 임시 디렉터리 안에 보존한다.

이 작은 표본은 런타임과 정책의 CPU 민감도를 확인하는 용도다. v9_lock은 시계 기반 난수를 쓰고 시간 예산 탐색도 수행하므로 같은 맵 normal/quarter의 승패 차이를 CPU quota 하나의 순수 인과 효과로 단정할 수 없다. 1맵 결과로 후보 전체 승률이나 서버 제출 안전성을 확정하지 않는다.

동결 대상은 `plan.json`, `launch_bot.py`, `busy_probe.py`, `run_checks.py`, 이 README, `environment.json`, `calibration/*.json`이다. `__pycache__`, 작성 중 사용한 `revise_harness.py`, 이후 경기 결과는 실행 전 코드 동결 대상에 넣지 않는다.
