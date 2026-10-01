# 15:00 제출 후보 패키지 검증

네 후보 ZIP은 선택 결과가 나오기 전에 준비했다. 각각 실제 ZIP에서 소스를 풀어 GCC12.2 C++20/O2로 빌드하고 공식 SDK smoke를 통과했다. **ZIP 내부 파일 해시와 재빌드 바이너리 해시가 모두 고정 선택 리그와 일치한다.** 후보 채택·업로드 완료를 뜻하지 않는다.

| 후보 | 제출 ZIP | ZIP SHA256 | 소스·바이너리 연결 |
|---|---|---|---|
| v8 | [ZIP](../../../artifacts/deadline1500-20261001-v8.zip) | `07689054fa1723b90e96630d34d5e28e6864137672222aba56cf3c2af293d631` | [GCC12·SDK 검사](evidence/v8-exact-zip-gcc12.json) |
| mission4 | [ZIP](../../../artifacts/deadline1500-20261001-mission4.zip) | `d83b6831fff05c34a24c7c42ff374d1a2b4b7f65d2fbdfc5f3d7b74e9e9989ff` | [GCC12·SDK 검사](evidence/mission4-exact-zip-gcc12.json) |
| v9_lock | [ZIP](../../../artifacts/deadline1500-20261001-v9_lock.zip) | `89baa2b9861e86121744e6245e45f08472da5ceaaf5e8053b70d3d0fe542bf80` | [GCC12·SDK 검사](evidence/v9_lock-exact-zip-gcc12.json) |
| v8_flagguard | [ZIP](../../../artifacts/deadline1500-20261001-flagguard.zip) | `a2ddbeb96df0707aad7d7a81c7ef202d99995c4b493ac6d07fec00f3a09d7d21` | [GCC12·SDK 검사](evidence/flagguard-exact-zip-gcc12.json) |

전체 source/main/header/metadata 및 binary SHA256은 [manifest.json](manifest.json)에 있다. 소스 원문은 [고정 arena 소스](../arena/sources/), 실행 인자·빌드 명령은 [선택 계획](../arena/plan.json)에 보존했다. 네 후보 모두 실행 인자가 없다. v9-lock에 지원하지 않는 seed 인자를 추가하지 않는다.

검사는 ZIP 루트의 main.cpp/protocol.hpp/generated.hpp/submission.json 네 파일, SDK ZIP 구조 검사, 실제 ZIP 컴파일, SDK 프로토콜 smoke, Debian sysroot 안에서의 동적 의존성 해석을 포함한다. 원본 ZIP을 재압축하지 않고 artifacts/에 그대로 복사했다. 실행 바이너리·라이브러리·개인 인증 자료는 ZIP과 기록에 포함하지 않았다.

SDK smoke는 강도 평가 또는 0.25 vCPU 검사가 아니다. 별도 선택·확인 리그가 같은 GCC12 wrapper와 동일 바이너리를 사용한다. 공식 서버의 CPU 하드웨어·quota 주기·커널까지 동일하다는 주장은 하지 않는다. 임시 sysroot 경로가 ELF에 포함되므로, 새 임시 경로에서 재빌드한 binary SHA가 달라도 곧 소스 불일치를 뜻하지 않는다. 이 기록의 byte 일치는 동일 toolchain context에서 비교한 결과다.

## 독립 리뷰

- [flagguard 읽기 검토](reviews/flagguard-read-only-review.json): 실제 생산·W 전체 도착 장부를 반영하는 좁은 현재 적 W 검사. 미래 적 행동, 이미 정지한 F, 탈출 불가 상태까지의 생존 보장은 아니다.
- [harness 최초 검토](reviews/harness-read-only-review.json)와 [수정 후 확인](reviews/harness-read-only-review-v2.json): 종료 시 worker 회수 경계가 보강됐다. 실제 scope cleanup 완료 여부는 리그 결과로 확인한다.
- Mission4의 이전 최종 검증 실패는 유지한다. 이번 선택은 새 CPU 조건의 별도 비교이며 [확정 사전 계획](../plan.json)을 따른다.

## 재검사와 임시 환경

저장소 루트에서 기존 검증기를 사용할 수 있다. 출력 JSON은 아직 없는 /tmp 경로로 지정한다.

```sh
python3 -B experiments/verify_gcc12_tmp.py --zip artifacts/deadline1500-20261001-v8.zip --output /tmp/deadline1500-v8-recheck.json --direct-wrapper --budget-seconds 600
```

[컴파일러 준비 기록](evidence/toolchain-setup.json)은 공식 Debian 패키지 SHA256 검사·버전·linker 정보를 보존한다. 패키지 목록의 HTTPS/SHA256은 검사했지만 OpenPGP 서명을 별도로 검증한 것은 아니다. 최초 제한 환경의 DNS 실패는 [별도 기록](evidence/toolchain-initial-dns-failure.json)에 남겼다. toolchain은 리그 때문에14:48 KST까지 유지하며, 이 보관 시점에는 정리 완료를 주장하지 않는다. 원래 /tmp 경로는 실행 이력이며, 읽을 때 필요한 현재 파일은 위 상대 링크와 manifest를 사용한다.
