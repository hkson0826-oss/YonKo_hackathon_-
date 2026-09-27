# GCC 12.2 호환성 보완 검사

2026-09-28 KST. **보존 v3 ZIP을 Debian GCC 12.2.0으로 컴파일하고 SDK 프로토콜 smoke를 통과했다.** 단일 compiler 경로를 요구하는 최종 패키징 도구에 연결할 TMP wrapper도 직접 실행으로 확인했다. 공식 대회 컨테이너와 동일하다는 검증은 아니다.

## 확인한 환경과 범위

| 대상 | 확인 결과 |
|---|---|
| 로컬 | Omarchy/Arch, x86_64, GCC 16.2.1, glibc 2.44. PATH 및 `/usr/bin`, `/usr/local/bin`에서 g++-12를 찾지 못함 |
| `yonsei-root` | Ubuntu 24.04.3, GCC 13.3.0. PATH 및 `/usr/bin`의 컴파일러는 13 계열이며 g++-12 없음. 조회만 수행 |
| SDK | `bots/dist/starter/limits.json`은 C++20/GCC 12.2.0을 명시. `run_tests.py`는 C++20/O2로 빌드 |
| 공식 컨테이너 | 배포 SDK에서 Dockerfile·이미지 digest·정확한 시스템 라이브러리 구성을 찾지 못함. Docker 권한 변경·데몬 실행 없음 |

SDK의 `docs/PLATFORM_OPERATIONS.md`도 로컬 도구가 서버 격리·CPU·메모리 환경을 재현하지 않는다고 명시한다. GCC major 12라는 이유로 공식 환경과 같다고 판단하지 않았다.

## 공식 배포처와 TMP 추출

Firecrawl의 developer-index 및 scrape로 GNU·Debian 원문을 확인했다. GNU는 자체 범용 사전 빌드 배포를 보장하지 않고 외부 제작 바이너리를 구분한다. Debian bookworm의 공식 패키지는 정확히 `g++-12 12.2.0-14+deb12u1`이며 C++ 개발 헤더도 같은 버전이다. [GNU 안내](https://gcc.gnu.org/install/binaries.html), [Debian g++-12](https://packages.debian.org/bookworm/g++-12), [libstdc++-12-dev](https://packages.debian.org/bookworm/libstdc++-12-dev).

`https://deb.debian.org/debian/`의 HTTPS `Packages.xz`와 11개 `.deb`를 매번 새로운 `/tmp/yk-gcc12-*/` 안에 받았다. 패키지 다운로드 합계는 **51,882,084바이트**다. 패키지 URL·버전·실측 SHA-256을 기록하고 공식 인덱스의 SHA와 대조했다. 별도 OpenPGP 검증은 하지 않았다. 패키지 설치 스크립트는 실행하지 않고 ar/tar 내용만 추출하며, 절대 symlink를 TMP 내부 상대 경로로 바꾸고 경로 이탈을 거부한다. 전역 패키지·설정·권한은 바꾸지 않았다.

컴파일러와 C++12 헤더, glibc 개발 파일·런타임, libstdc++12/libgcc를 TMP에 둔다. 컴파일 시 `-B`와 `--sysroot`로 해당 경로를 선택하고, 컴파일러 자체의 실행 의존성 및 assembler/linker는 로컬 것을 사용한다. [GCC 12.2 경로 옵션](https://gcc.gnu.org/onlinedocs/gcc-12.2.0/gcc/Directory-Options.html)에 근거한 구성이다. 소스에서 GCC를 새로 빌드하거나 서버에 설치할 필요는 없었다.

## 실제 검증 기록

검사 ZIP SHA-256은 `ce94e80a49d833be8b3c093a34319d8b9cdb5b7ec8d86b91a4b2831b18d799cb`, 추출 `main.cpp` SHA는 `52268569e17d7fc40fd46f0996b2da684768902b4af27ec059c4b068911c4473`이다. ZIP 원본과 제출 소스를 수정하지 않았다.

- [최초 검사](compiler-compatibility-v3-attempt1.json): Debian 12.2.0 C++20/O2 컴파일 성공, 4.87초. 명시적 Debian loader·library-path로 SDK seed 0, 17턴 통과. stdout 9,293바이트, stderr 0, 경고 없음.
- [자식 종료 처리 보완 후 검사](compiler-compatibility-v3.json): 같은 ZIP과 SDK smoke 통과. 이전 기록 보존.
- [단일 compiler wrapper 검사](compiler-compatibility-v3-direct.json): wrapper로 만든 ELF를 **직접 실행**해 같은 SDK smoke 통과. ELF interpreter와 `--list` 결과에서 Debian TMP loader·libstdc++·libm·libgcc·libc 경로 확인.
- [정리 검사](compiler-compatibility-cleanup.json): 정상 종료, 시간 초과 시 자식 process group 종료, context 사용자의 예외에도 TMP 삭제 상태 기록을 확인. 마지막 변경은 예외 정리 상태를 기록하는 얇은 context wrapper이며 빌드·런타임 구성은 바꾸지 않음.

각 실행의 TMP는 종료 후 삭제되었다. 다운로드와 생성 바이너리는 남기지 않는다. SIGTERM은 정리 가능한 예외로 전환하고, subprocess 시간 초과·중단 시 생성한 process group을 종료한다. 강제 SIGKILL이나 전원 차단까지 자동 정리를 보장하는 것은 아니다.

## 최종 패키징 연결

[검증 도구](../../../experiments/verify_gcc12_tmp.py)는 기본 방식과 직접 실행 방식을 구분한다. `compiler`는 인수 목록이며 명시적 loader 호출이 필요하다. **`args.compiler`에는 `compiler_wrapper` 단일 경로를 사용한다.** wrapper는 다음 링크 설정도 넣는다.

- ELF interpreter: TMP의 Debian `ld-linux-x86-64.so.2`
- RPATH: TMP의 Debian `lib/x86_64-linux-gnu`, `usr/lib/x86_64-linux-gnu`
- `--disable-new-dtags`: 간접 의존성에도 해당 RPATH가 적용되게 함

따라서 `package_frozen_candidate.run(args)`의 컴파일과 `validate_runtime` 직접 실행 전체가 아래 context 안에 있어야 한다. 이 도구에서는 실제 최종 패키징이나 후보 선택을 실행하지 않았다.

```python
from experiments.verify_gcc12_tmp import gcc12_toolchain
from experiments import package_frozen_candidate

compiler_report = {}
try:
    with gcc12_toolchain(compiler_report) as toolchain:
        args.compiler = toolchain['compiler_wrapper']
        package_frozen_candidate.run(args)
finally:
    # compiler_report를 신규 JSON에 기록한다. context 종료 후 삭제 상태도 포함된다.
    save_new_compiler_record(compiler_report)
```

단독 검증은 아래처럼 실행한다. 이미 존재하는 결과 파일은 덮어쓰지 않는다.

```bash
PYTHONDONTWRITEBYTECODE=1 python3 experiments/verify_gcc12_tmp.py \
  --zip artifacts/submission-v3.zip --direct-wrapper \
  --output records/league/loop3-design/compiler-check-NEW.json
```

TMP 바이너리는 context 종료 후 interpreter와 라이브러리가 없어져 실행할 수 없다. 소스 ZIP에는 이 경로·바이너리가 들어가지 않는다. 재사용 API는 x86_64 Linux 전용이다.

## 남는 차이

Debian 패치 버전, host binutils, 컴파일러 실행 라이브러리, CPU·커널·스케줄링, 대회 격리 방식은 다를 수 있다. 이번 SDK smoke는 300ms/첫 턴 3000ms 프로토콜 검사이며 384MiB 컨테이너·전체 강도 검사가 아니다. 패키징의 별도 384MiB 주소공간/CPU 검증을 대신하지 않는다. 최종 업로드의 실제 사이트 빌드·검사는 여전히 사용자가 확인한다.
