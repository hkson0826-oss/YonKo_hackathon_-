# 동결 후보 제출 준비 검토

2026-09-28. 두 번째 리그가 실행 중일 때 수행한 읽기 전용 검토다. 우승 후보를 가정하거나 ZIP을 생성하지 않았고, 봇 소스·Git·서버를 변경하지 않았다.

## 제출 구성과 근거

현재 생성하는 C++ 후보에 필요한 ZIP 루트 파일은 **`main.cpp`, `protocol.hpp`, `generated.hpp`, `submission.json`의 4개**다. 메타데이터는 `{"schemaVersion":1,"language":"cpp"}`다. `search.hpp`는 SDK 예제의 구성일 뿐 현재 `main.cpp`의 의존성이 아니므로 필요 없다.

동결 경기의 `manifest.json`에서 채택 후보 ID, `source`, `source_sha256`, `frozen_sha256`을 읽어 **실제로 대전한 소스**를 복사한다. 현재 생성기를 다시 실행한 파일이나 수정한 파일로 대체하지 않는다. 후보 디렉터리의 두 헤더와 `snapshot/submissions/tuned/submission.json`도 동결 해시에 대조한다. ZIP은 TMP의 4개 파일 전용 폴더에서 만든다. 생성기는 다른 보조 `.cpp`도 재귀 포함하므로 실험 소스 폴더를 통째로 지정하면 안 된다.

근거는 [SDK 포장 코드](../../../yk-development-tools/bots/dist/starter/submission.py), [검사 코드](../../../yk-development-tools/bots/dist/starter/run_tests.py), [배포 규칙](../../../yk-development-tools/docs/rulebook.md), [제한 JSON](../../../yk-development-tools/bots/dist/starter/limits.json)이다. 웹 운영 제한은 2026-09-27의 [사이트 확인 기록](../../../docs/10-사이트운영과보정점수.md)을 재사용했으며 이번 검토에서 웹을 다시 조회하지 않았다.

## 사용할 명령

아래는 **향후 실행 예시**이며 이번 검토에서 실행한 명령이 아니다. 프로젝트 루트에서 `arena`를 완료된 최종 검증 폴더로 지정하고, 실제 추천이 `v2`이면 기존 ZIP을 보존한다. 다음 스크립트는 추천 후보가 별도로 승격된 경우에만 진행한다.

```bash
set -euo pipefail
arena=records/league/loop2-iteration2
package_tmp=$(mktemp -d /tmp/yk-submission-review-XXXXXX)
trap 'rm -rf -- "$package_tmp"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
export TMPDIR="$package_tmp"
export PYTHONDONTWRITEBYTECODE=1

python3 - "$arena" "$package_tmp" <<'PY'
import hashlib, json, pathlib, shutil, sys
arena, temporary = map(pathlib.Path, sys.argv[1:])
manifest = json.loads((arena / 'manifest.json').read_text())
result = json.loads((arena / 'campaign-result.json').read_text())
candidate = result['recommended']
assert result['phase'] == 'final' and candidate != 'v2'
assert candidate == result['primary_candidate']
assert result['promotion_decisions'][candidate]['promoted']
target = temporary / 'source'
target.mkdir()
source = arena / manifest['bots'][candidate]['source']
assert hashlib.sha256(source.read_bytes()).hexdigest() == manifest['bots'][candidate]['source_sha256']
for name in ('main.cpp', 'protocol.hpp', 'generated.hpp', 'submission.json'):
    item = source.parent / name if name != 'submission.json' else arena / 'snapshot/submissions/tuned/submission.json'
    expected = manifest['frozen_sha256'][str(item.relative_to(arena))]
    assert hashlib.sha256(item.read_bytes()).hexdigest() == expected
    shutil.copyfile(item, target / name)
print(candidate)
PY

python3 yk-development-tools/bots/dist/starter/make_submission.py \
  --source "$package_tmp/source" --output "$package_tmp/submission-candidate.zip"
python3 yk-development-tools/bots/dist/starter/run_tests.py \
  --zip "$package_tmp/submission-candidate.zip" --compiler g++ --seed 0 \
  > "$package_tmp/sdk-validation.json"
```

예시의 `arena` 경로는 실제 최종 실행 경로와 맞춰야 한다. 포장 후에는 `zipfile`로 멤버가 정확히 위 4개인지, 모든 멤버의 바이트가 복사한 소스와 같은지 검사한다. `zipfile.Path`나 `extractall`만으로 검사를 대신하지 않는다. ZIP 자체 SHA-256과 각 멤버의 SHA-256을 모두 기록한다. **압축 파일 ≤5MiB, 멤버 원본 크기 합 ≤20MiB, 파일 ≤200개**도 별도 확인한다. 크기·개수 제한은 현재 `inspect_zip()`의 검사 항목에 없다.

SDK 결과는 `ok`뿐 아니라 `issues == []`와 `warnings == []`를 확인해야 한다. 포장·검사가 통과한 실제 ZIP을 로컬 `artifacts/`의 새 버전 파일로 복사하고, 생성 및 검증 기록을 `records/submissions/<새버전>/`에 함께 남긴 뒤 TMP를 제거한다. 기존 `submission-v2.zip`은 덮어쓰지 않는다.

## 독립 CPU 검사

실제 채점 환경은 C++20/GCC 12.2.0, CPU, 384MiB, 첫 턴 3000ms·이후 300ms, 경기 최대 3분이다. 로컬 `g++`의 버전과 사용 CPU는 기록해야 하며 다른 버전에서의 통과를 GCC 12.2.0 통과라고 표기하지 않는다. 이번 읽기 확인에서 `prlimit`, `timeout`, `g++`, `c++`는 존재했고 `g++-12`는 찾지 못했다. 패키지 설치는 하지 않았다.

TMP에 복사한 소스를 실제 ZIP과 같은 옵션으로 빌드하고 별도 주소공간 제한을 적용하는 기본 명령은 다음과 같다.

```bash
g++ -std=c++20 -O2 -I "$package_tmp/source" \
  "$package_tmp/source/main.cpp" -o "$package_tmp/bot"
timeout --kill-after=5s 180s \
  python3 yk-development-tools/bots/dist/starter/run_tests.py \
  --bot "prlimit --as=402653184:402653184 -- $package_tmp/bot" --seed 0 \
  > "$package_tmp/memory-limited-validation.json"
```

위 TMP 경로는 `mktemp`로 만든 공백 없는 경로다. 임의 경로로 일반화할 때는 봇 명령을 `shlex.join()`으로 만들어야 한다. 이 주소공간 제한은 서버 메모리 격리와 같은 측정 방식이 아니며, `timeout`은 이 로컬 검사 전체의 벽시계 상한이다. 리그는 프로세스당 768MiB 제한으로 실행됐으므로 리그 통과만으로 384MiB 검사를 통과했다고 주장하면 안 된다.

SDK smoke는 무행동 상대와 Y 진영으로 진행해 조기에 끝날 수 있다. 따라서 채택 후보에는 이미 확보한 **강한 상대·양 진영·160턴 사례**의 응답 분포와 최대값을 함께 사용하고, 최종 ZIP에서 꺼내 빌드한 봇으로 적어도 강한 상대와 양 진영 CPU 대전을 다시 확인한다. 공식 엔진의 160턴을 줄이지 않고 300ms 제한을 유지한다. 원격 검사를 추가하면 기존 TMP supervisor와 90% 상한을 유지한다.

예를 들어 제출 포장의 CPU 회귀 확인에는 다음 명령으로 기존 v2와 2개 맵·양 진영 4경기를 실행할 수 있다. 7001–7002는 이미 사용한 개발 맵이므로 **새 성능 검증 표본으로 합산하지 않는다**. `summary.forfeits == 0`, 4경기 완료, 실제 최대 응답과 `full_length_matches`를 확인한다. 긴 경기가 없으면 기존 최종 검증 리플레이 중 장기 상태를 추가 점검한다.

```bash
g++ -std=c++20 -O2 "$arena/snapshot/candidates/v2/main.cpp" -o "$package_tmp/v2"
python3 tests/benchmark.py \
  --candidate "prlimit --as=402653184:402653184 -- $package_tmp/bot" \
  --opponent "$package_tmp/v2" --start 7001 --seeds 2 --workers 1 \
  --output "$package_tmp/paired-cpu-validation.json" \
  --save-losses "$package_tmp/cpu-replays"
```

이 benchmark는 경기별 최대 시간과 결과를 남기지만 stdout/stderr 한도 계수는 하지 않는다. 따라서 SDK 출력 검사와 함께 사용하며, 경기당 3분 벽시계 제한도 별도 감시해야 한다. `play_local.py`로 두 명령의 순서를 바꿔 두 진영을 실행하면 `--replay`로 승리까지 상세 저장할 수 있다.

## SDK 검사 범위의 차이

| 항목 | 현재 로컬 도구의 범위 | 제출 전 판단 |
|---|---|---|
| ZIP 구조 | 경로·중복·심볼릭링크·메타데이터·확장자 검사 | 실제 ZIP 해시·4개 멤버·크기 제한 추가 확인 |
| 출력량 | `run_tests.py`가 stdout/stderr를 계수하지만 초과를 경고로 반환 | 경고 1개도 허용하지 않음. 서버에서는 몰수 |
| 시간 | 프로세스 기동/입력 전송부터 `END` 수신까지 측정 | CPU·경쟁 부하가 다른 서버의 시간 보장은 아님 |
| 자원 격리 | SDK 자체에는 384MiB·프로세스 32개·네트워크/파일 격리가 없음 | 외부 제한과 실제 플랫폼 검사 구분 |
| 행동 검사 | 문법·좌표·장애물·명시적 병원 생산을 검사 | 모든 전술 합법성·최적성 검사를 대신하지 않음 |
| 장기 부하 | 무행동 상대라 초반 즉시 승리로 종료될 수 있음 | 강한 상대의 긴 경기·종반 로그 확인 |
| 빌드 | ZIP 안의 모든 `.cpp`를 C++20/O2로 함께 컴파일 | 다른 `main()`·불필요한 `.cpp` 혼입 방지 |

`protocol.hpp`는 각 명령과 `END`를 출력한 뒤 flush하고 EOF까지 입력을 받는 루프를 유지한다. 디버그 문자열을 stdout에 추가하거나 응답 직후 프로세스를 종료하는 변경은 하지 않는다.

## 데이터·관측 검토

현재 `a_*`, `q_*`, `j_*` 생성 코드와 공통 헤더에서 외부 모델 파일, 신경망 가중치, 임의 데이터 조회, GPU 호출, 네트워크, 파일 쓰기, 자식 프로세스 실행을 발견하지 못했다. 최종 제출에는 생성기 Python·연구 자료·리플레이·실험 설정 JSON이 들어가지 않는다. `generated.hpp`는 제공 프로토콜 상수이며 실험으로 학습한 배열이 아니다.

봇은 INIT 지형·거점, 현재 입력의 양측 병력·자원·소유권·공개된 점수와 경기 중 기억만 읽는다. 미공개 건물 점수는 규칙의 대칭성 및 합법 범위로 추정하며 원본 리플레이의 숨은 점수를 읽지 않는다. `a_error`는 현재 경기의 직전 관측과 가상 전이 오차로 계산하는 작은 런타임 통계다. 사전 학습 가중치나 외부 저장 데이터를 제출하는 방식이 아니다.

최종 기록은 **선택된 candidate ID → 동결 소스 SHA → 최종 ZIP 멤버 SHA → ZIP SHA → 빌드/SDK/CPU 검사 실행 ID**로 연결한다. 업로드와 사이트의 사용 코드 선택은 사용자가 수행한다. 이 검토 문서는 실제 제출 통과나 우승을 확정하지 않는다.
