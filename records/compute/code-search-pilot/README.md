# 코드 탐색 실행 파일럿

해석과 재실행 명령은 [CPU·GPU 실측 문서](../../../docs/15-CPU와GPU실측결과.md)에 있다. 모든 시간은 현재 로컬 노트북 측정이며, 원격 RTX 3090 서버의 실측이 아니다.

| 경로 | 내용 |
|---|---|
| `stages/result.json` | 공식 관측 483회에 대한 판단 구간 시간과 원본/계측 명령 해시 |
| `stages/instrumented.cpp` | 실행한 계측 소스 |
| `executors/comparison.json` | 같은 8작업의 프로세스/스레드 × 작업자 1·2·4·8 비교 |
| `executors/*/manifest.json` | 후보·헤더·엔진·상대 파일과 실행 바이너리의 해시, 소스 커밋, 실행 환경 |
| `executors/*/snapshot/` | 대전에서 실제 사용한 소스·설정 스냅샷 |
| `executors/*/results.jsonl` | 개별 경기 결과, 턴 응답시간, 논리적 경기 진행 해시 |
| `executors/*/session-*.json` | 실행 시간, 완료 상태, 재개 여부, 명령 |
| `gpu-evaluation/result.json` | 공통 평가함수의 CPU 원본 대조, CPU 시간, GPU 실행 가능 여부 |
| `gpu-evaluation/*-build.log` | CPU·CUDA 커널 빌드 로그 |
| `nvrtc-setup.json` | 임시 다운로드한 NVIDIA NVRTC wheel 버전·URL·SHA256 |
| `nvidia-smi.log` | 로컬 GPU 조회 원문 |
| `validation.json` | 도구 검사와 입력 원본 보존 여부 |

8작업은 `baseline/eng140 × 맵 5000·5001 × Y/K × 팀원 봇`이다. 실행 방식별 반복을 합쳐 64개의 독립 경기라고 부르지 않는다. 이 파일럿은 처리량 비교이므로 모든 경기의 상세 상태 저장을 끄고 결과·응답시간·진행 해시를 저장했다. 후보 튜닝에는 기본 상세 리플레이 옵션을 사용한다.

실행 바이너리·공유 라이브러리·PTX는 각 실행의 `.gitignore`로 제외한다. wheel과 CUDA 설치 파일은 저장소에 넣지 않았다. 측정에 사용한 소스 커밋과 각 파일 해시가 각 보고서에 있으며, 파일 해시를 실행 코드의 최종 식별 기준으로 사용한다.
