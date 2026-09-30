# guard3 / 사이트 v8 제출 기록

[제출 ZIP](../../../artifacts/submission-20260929-guard3.zip) · [소스](../../../submissions/deadline-20260929-guard3/) · [결과와 한계](../../../docs/27-20260929-guard3제출.md)

요청된 9/29 20:00 KST 마감은 지키지 못했다. 로컬 포장은 19:32에 통과했지만 파일 첨부 단계가 장시간 지연됐고, 실제 사이트 등록은 9/30 01:19의 v8이다. 업로드와 선택을 구분한 현재 상태 및 모의 전투 결과는 [site-receipt.json](site-receipt.json)에 기록한다.

- ZIP SHA256: `15fe3b7931e25fa6fbd6364536d39190fd6fe8e564405ed223bb28b33615f03f` (15,847 bytes).
- main.cpp SHA256: `61a4f25113d9bf2c387a59ddc770a3143de6311e3fd2e004827a66eb78edfbc9`.
- 포함 파일: main.cpp, protocol.hpp, generated.hpp, submission.json.
- [채택 판정](decision.json): 분리한 선택 6맵·최종 10맵에서 고정 소스를 비교했다. 최종 Y 45/50, K 44/50승이며 로컬 v4는 31/50, 38/50승이다. 사이트 기존 v7 소스는 없어 직접 비교하지 못했다.
- [실제 ZIP 검사](validation.json): 압축 해제·멤버 해시 대조·GCC12.2 재빌드·SDK 실행 1경기·새 CPU 4경기를 통과했다. 300ms/첫 턴 3000ms/384MiB 제한에서 출력 문제는 없었다.
- [임시 GCC12 기록](../deadline-20260929-gcc12.json): 공식 Debian 패키지를 /tmp에서만 사용하고 정리했다. 호스트 환경이 공식 서버 컨테이너와 동일하다고 주장하지 않는다.

`evidence/`에는 선택·최종의 원본 결과, 계획, 해시가 있다. `replays/`에는 실제 ZIP CPU 검사 4경기가 있다. 전체 개발 리플레이와 도구는 jisang의 records/deadline/20260929에 보존했다. ZIP 자체를 업로드하며 다시 감싸지 않는다.
