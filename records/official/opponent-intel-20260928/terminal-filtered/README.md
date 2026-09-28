# 종결 관측의 미래 위협 제외

후속 실험에서 행동 위협을 읽을 때는 이 폴더의 `census.json`을 사용한다. 상위 폴더의 최초 분석은 수정하지 않고 보존했다.

소스 `bdd4c9498f434c85b1621b9b13522b4aae8c8c69`에서 18경기·15상대·1,978턴을 다시 분석했다. 조기종료 최종 관측에는 다음 명령이 없으므로 다음 3개 위협 행을 제외했다.

- 뚜띠태하소불고기와멸치두명 2차전: 종료 107턴의 2행
- 신촌도 우리땅 2차전: 종료 92턴의 1행

위협 행은 1,360개에서 1,357개로 줄었다. 종결 관측 자체와 나머지 턴별 관측은 그대로 보존했다. 종료 전 관측은 사후에 알게 된 조기종료 시각이 아니라 규칙상 160턴 한도로 경로를 계산한다.

`comparison-verification.json`에서 위협 목록 이외의 18개 경기 프로필 전체, 최초 위협, 생산·점수·승패, 승패별 관측 빈도가 모두 같음을 확인했다. 기존 산출물의 해시와 18개 경기 원본 해시도 일치한다. 신규 성능 실험이나 추가 경기 확보를 의미하지 않는다.

실행:

```bash
PYTHONDONTWRITEBYTECODE=1 python -B experiments/build_opponent_census.py --output records/official/opponent-intel-20260928/terminal-filtered
PYTHONDONTWRITEBYTECODE=1 python -B records/official/opponent-intel-20260928/terminal-filtered/verify_prior_census.py
```

두 명령은 기존 결과를 덮어쓰지 않으며 출력이 이미 있으면 중단한다. 재실행할 때는 별도 임시 복사본을 사용한다.
