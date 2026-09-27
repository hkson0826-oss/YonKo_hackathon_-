# v3 제출물과 실행 검증

2026-09-28 KST. [submission-v3.zip](../../../artifacts/submission-v3.zip)은 잠금 후보 `a_v2_terminal_local`이다. [최종 성능·패배 분석](../../../docs/19-반복개선검증결과.md)의 사전 채택 조건을 통과했다. 업로드와 사이트 제출 선택은 아직 하지 않았으며, 로컬 v3와 사이트 버전 번호는 별개다.

| 항목 | 값 |
|---|---|
| ZIP 크기 | 12,207바이트 |
| ZIP SHA-256 | `ce94e80a49d833be8b3c093a34319d8b9cdb5b7ec8d86b91a4b2831b18d799cb` |
| 평가 소스 커밋 | `c64d5831becfeef0c5468a77fbae5d25c77792f6` |
| main.cpp SHA-256 | `52268569e17d7fc40fd46f0996b2da684768902b4af27ec059c4b068911c4473` |
| 파일 | `main.cpp`, `protocol.hpp`, `generated.hpp`, `submission.json` |
| 소스 | [submissions/iterative-v3](../../../submissions/iterative-v3/) |

[패키지 도구](../../../experiments/package_frozen_candidate.py)는 원래 검증과 추가 감사의 통과 여부·최초 후보 잠금·동일 소스·전체 리플레이 검증 기록을 확인했다. SDK 형식 검사 후 실제 ZIP을 TMP에 풀어 C++20/O2로 컴파일했다. 다른 소스로 검사한 뒤 ZIP을 교체하지 않았다.

- [SDK 검사](sdk-smoke.json): seed 0·무행동 상대 17턴의 기본 실행 1경기, 문제·출력 경고 없음, stderr 0바이트. SDK 전체 테스트 모음을 새로 실행했다는 뜻은 아니다.
- [CPU 실행](cpu-matches.json): 시드 7550·7551, v2 상대 양 진영 4경기, 오류·몰수 없음. 2경기는 160턴까지 진행했다. 4경기 성적은 별도의 승률 승격 조건으로 쓰지 않았다.
- CPU 실행 제한: 첫 턴 3,000ms, 이후 300ms, 프로세스별 주소공간 384MiB, 전체 프로세스 180초. 후보 최대 응답 136.58ms.
- 환경: GCC 16.2.1/C++20, Linux, Python 3.14.7. 공식 GCC 12.2.0 컨테이너를 재현한 검사는 아니다.

각 경기의 응답 시간 배열·출력량·전체 리플레이를 보존했다. [validation.json](validation.json)에 SDK·평가 파일·ZIP 멤버별 해시, 명령, 환경, TMP 삭제 상태가 있다. 빌드 로그는 [후보](build-candidate-from-zip.json)와 [v2](build-frozen-v2.json), ZIP 형식 검사는 [zip-inspection.json](zip-inspection.json)에 있다.

재현할 때는 기존 결과를 덮어쓰지 않는 새 출력 경로를 지정한다. 빌드·실행 임시 파일은 도구가 `/tmp`에서 만들고 정리한다.

```bash
PYTHONDONTWRITEBYTECODE=1 python3 experiments/package_frozen_candidate.py \
  --arena records/league/loop2-iteration2 \
  --audit records/league/loop2-cross-family \
  --source-output submissions/iterative-v3-recheck \
  --zip-output artifacts/submission-v3-recheck.zip \
  --record-output records/submissions/v3-recheck \
  --compiler g++
```
