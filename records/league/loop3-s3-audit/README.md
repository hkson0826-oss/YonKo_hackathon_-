# s3의 별도 48맵 감사

고정 후보 `s3_v2_screen_paired_guard`와 v3를 같은 48개 맵·9상대·양 진영에서 비교했다. 1,728경기, 오류·몰수 0이며 사전 6조건을 모두 통과했다. Y는 v3 266/432승에서 후보 290승, K는 256승에서 278승으로 개선됐다.

Y의 맵 bootstrap 95% 구간은 +0.23~11.11%p, K는 +0.69~9.49%p다. 추가 상대군 Y는 +3.47%p지만 구간에 0이 포함된다. 상대별 Y에서 r3_opponent_league −1/48승, f3_v2_warrior_reserve −3/48승의 회귀는 남았다. 정해 둔 상대별 허용 한도 12.5%p 이내이며 기준을 바꾸지 않았다.

전체 리플레이 1,728개와 소스 117개 해시, 기존 공식 원본·ZIP 불변, 원격 TMP·관련 프로세스 정리를 확인했다. 이는 통계·기록 검증이며 실제 ZIP/GCC12 검사 결과와 구분한다.

[두 실행의 합본 분석](../loop3-s3-summary/README.md) · [원본 판정](audit-result.json) · [전체 파일 검증](artifact-verification.json) · [독립 재집계](../loop3-design/s3-audit-independent-review.md).
