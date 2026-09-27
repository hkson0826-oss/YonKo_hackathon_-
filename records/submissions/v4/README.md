# v4 제출물과 검사 기록

현재 추천 파일은 [submission-v4.zip](../../../artifacts/submission-v4.zip)이다. 압축을 풀거나 다시 묶지 않고 ZIP 자체를 업로드한다. 사이트 업로드와 제출 선택은 사용자가 진행한다. 사이트의 버전 번호와 로컬 파일명은 별개다.

- 후보: `s3_v2_screen_paired_guard`; [최종 C++ 소스](../../../submissions/iterative-v4/main.cpp).
- ZIP: 14,441 bytes, SHA-256 `b3f7fee0154ff08a7f563e8b0036dd7b649d136e949e641ebe69a8c0ba7cd3da`.
- 포함 파일: `main.cpp`, `protocol.hpp`, `generated.hpp`, `submission.json` 네 개. 실행 파일·학습 가중치·실험 로그는 포함하지 않았다.
- 본 확인 128맵과 추가 감사 48맵의 사전 조건을 통과했다. smoke·교차 대전을 포함해 6,416경기·179고유맵, 오류·몰수 0이다. [공유 요약·남은 약점](../../../docs/24-s3독립검증결과.md), [집계·출처](evidence/comparison.json).

## 실제 ZIP 검사

ZIP 추출본을 Debian GCC 12.2.0-14+deb12u1로 컴파일했다. SDK 기본 실행 1경기와 새 맵9450·9451의 양 진영 4경기를 통과했으며, 일반 턴300ms·첫 턴3000ms·프로세스 주소공간384MiB를 적용했다. 최대 후보 응답은 **130.73ms**, 오류·몰수·출력 경고는 0이다. CPU 4경기는 형식·실행 검사이며 승률을 판단하는 추가 표본으로 사용하지 않았다.

[검사·멤버 해시](validation.json) · [SDK 실행](sdk-smoke.json) · [CPU 경기](cpu-matches.json) · [GCC12 임시 도구체인](../v4-gcc12.json) · [실행 로그](packaging-log.jsonl).

컴파일러와 빌드·실행 중간물은 `/tmp`에서만 사용해 제거했다. 환경 변수와 신호 핸들러도 복구됐다. 전역 패키지를 설치하지 않았다. 사용한 CPU·호스트 링커·커널·격리는 공식 컨테이너와 다르므로 사이트 검사는 업로드 후 확인한다. 기존 v3 ZIP과 사용자 제공 공식 원본은 보존했다.

## 고정 근거와 재현

[본 확인 원본](https://github.com/hkson0826-oss/YonKo_hackathon_-/tree/92b08a0395045fcef4abe468dfebe066163b45ff/records/league/loop3-s3-confirmation), [추가 감사 원본](https://github.com/hkson0826-oss/YonKo_hackathon_-/tree/92b08a0395045fcef4abe468dfebe066163b45ff/records/league/loop3-s3-audit), [패키징 도구](https://github.com/hkson0826-oss/YonKo_hackathon_-/blob/92b08a0395045fcef4abe468dfebe066163b45ff/experiments/package_gcc12_candidate.py)는 `jisang`의 고정 커밋에 있다. main에는 최종 소스·ZIP·검증 요약·실제 ZIP 검사 기록만 선별했다.

전체 패키징 재현은 위 커밋을 별도 TMP checkout에 준비하고 기존 결과를 덮지 않는 새 출력 경로로 실행한다. 필요한 Python·SDK·원본 리그 파일은 해당 커밋에 포함되어 있다.

```bash
python3 -B experiments/package_gcc12_candidate.py \
  --arena records/league/loop3-s3-confirmation \
  --audit records/league/loop3-s3-audit \
  --source-output /tmp/NEW_RUN/source \
  --zip-output /tmp/NEW_RUN/submission.zip \
  --record-output /tmp/NEW_RUN/records \
  --compiler-record /tmp/NEW_RUN/gcc12.json \
  --cpu-seed-start 9450
```

`NEW_RUN`은 새 TMP 작업 디렉터리로 바꾸고 필요한 결과를 회수한 뒤 제거한다. 같은 두 맵을 재사용하는 명령은 기존 제출 검사 재현용이다.
