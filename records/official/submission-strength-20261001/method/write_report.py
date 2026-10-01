"""Render the descriptive comparison without a synthetic official score."""
import json
from pathlib import Path
H=Path(__file__).resolve().parent
p=json.loads((H/'strength-analysis.json').read_text());rank=json.loads((H/'previous-rank-sensitivity.json').read_text())
def rate(x):return '—' if x is None else f'{100*x:.1f}%'
def record(r):return f"{r['wins']}승 {r['losses']}패 ({r['n']})"
def ci(v):return f"[{100*v[0]:.1f}, {100*v[1]:.1f}]%" if v else '—'
text=['# 공식 제출별 상대 구성과 성적 비교','',
'최신 목록131경기와 현재87팀 표를 연결했다. #9와 #11은 모두12승12패다. 공통 상대8팀에서는 #11이4승, #9가2승이지만 작은 표본과 상대 버전·시점 차이 때문에 최강 제출을 확정하지 못한다. 과거 #4는 당시19위·보정66.2%·9승4패로 별도 검토할 가치가 있는 제출이다. 과거의 좋은 공식 성적과 현재 동일 조건에서 확인한 코드 강도를 구분해야 한다.','',
'현재 보정되지 않은 승점률은 `(승+0.5×무)/경기수`이며131경기에는 무승부가 없다. 최신 도움말은 이 승점률, 승률, 상대 기반 동률 지표의 순서를 설명한다. 옛61.0/66.2 보정율 산식과 같다고 확인된 것은 아니다. 최신 #11의 세 지표는0.5,0.5,0.19134964로 계산된다(승리 상대 승점률 합4.5923913÷24). 화면의3차값이나타팀대진까지확보한것은아니므로55위순위전체를재현했다는뜻은아니다. 최대12라운드라는 도움말과 현재23~24경기 표의 정확한 일정 관계는 미확인이다. 학교 소속 Y를 실제 맵 위치 Y로 바꾸어 해석하지 않는다.','',
'## 제출별 원성적과 최신 상대 구성','',
'아래 상대 등수·승점률은 모두 **10/1 17시 현재 표**다. 과거 제출의 대진 당시에 이 정도 강도였다는 뜻이 아니다. 평균은 만난 경기 수로 가중했으며, 중복 상대를1회씩 세는 평균도 JSON에 별도로 있다. LOO는17시 우리 경기의 기여만 해당 상대의17시 전적에서 뺐다. 과거 경기 결과를 현재 전적에서 임의로 차감하지 않았다.','',
'| 서버 제출 | 승/패 | 승점률 | 승률 Wilson95% | 상대 평균/중앙 등수 | 상대 평균 승점률 | 최신 LOO 평균 |','|---|---:|---:|---|---:|---:|---:|']
for s,r in p['submissions'].items():text.append(f"| #{s} | {r['wins']}/{r['losses']} | {rate(r['point_rate'])} | {ci(r['win_rate_wilson95_descriptive'])} | {r['opponent_rank']['mean']:.2f}/{r['opponent_rank']['median']:g} | {rate(r['opponent_point_rate']['mean'])} | {rate(r['opponent_point_rate_latest_loo']['mean'])} |")
r=p['source_group_8_plus_11']['summary'];text.append(f"| #8+#11 동일 소스 | {r['wins']}/{r['losses']} | {rate(r['point_rate'])} | {ci(r['win_rate_wilson95_descriptive'])} | {r['opponent_rank']['mean']:.2f}/{r['opponent_rank']['median']:g} | {rate(r['opponent_point_rate']['mean'])} | {rate(r['opponent_point_rate_latest_loo']['mean'])} |")
text+=['','Wilson 구간은 독립 시행을 가정한 설명용 구간이다. 반복 상대와 Swiss 대진 선택·시점 차이를 보정한 구간이 아니다. #8+#11은48경기·37개 상대이며 같은 소스 확인에 따른 시간 민감도 묶음이다. 새 모형으로 만든 보정 승률이 아니다.','',
'등수만 보면 #11의 상대평균51.96위가 #9의56.46위보다 앞선다. 하지만 평균 상대승점률은45.00% 대46.39%로 반대다. #11이 확실히 더 강한 상대를 만났다는 하나의 결론으로 묶을 수 없다. 낮은 순위의 극단적인 성적과 다수 동승점팀의 동률 순서가 두 요약에 다르게 작용한다.','',
'## 최신 등수 사분위와 상위12 상대','',
'87팀의 표시등수를 기준으로 상위1~22, 중간23~65, 하위66~87로 나눴다. 동일 승점률인13/24팀들이15~32위에 걸쳐 있어 등수 구간이 같은 승점률팀을 가른다. 이를 피하는 별도 승점률 구간(q25=45.833%,q75=54.167%,경계동률은중간)도 strength-analysis.json에 제공한다. 어느 구간도 공식 보정 점수는 아니다.','',
'| 제출 | 상위25% 승/경기 | 중간50% 승/경기 | 하위25% 승/경기 | 상위12 승/경기 |','|---|---:|---:|---:|---:|']
for s,r in [*p['submissions'].items(),('8+11',p['source_group_8_plus_11']['summary'])]:
 cells=[r['rank_buckets'][x] for x in ['top25_rank','middle50_rank','bottom25_rank']]+[r['top12']]
 text.append('| #'+s+' | '+' | '.join(f"{v['wins']}/{v['n']}" for v in cells)+' |')
text+=['','세 구간을 무조건 같은 비중으로 평균하면 #9가 #11보다24.3%p 높아진다. 이 값은 #9의 상위 구간 단1경기 승리에 전체의1/3을 배정해 생긴다. 반대로 공통 상대 비교는 #11 쪽이다. 이 불안정한 구간 평균을 최종 추천 점수로 쓰지 않는다.','',
'## #9와 #11의 시점을 맞춘 등수 민감도','',
'최신 순위 이동 화살표로 직전 등수를 추론했다. 직전 시점이10시라는 연결은 회차 순서와 우리팀50위 기록에 의존한다. 과거 전체 승무패표를 복구한 것이 아니다.','',
'| 대진 | 상대 평균 등수 | 중앙 등수 | 평균 등수/87 | 상위/중간/하위 승·경기 |','|---|---:|---:|---:|---|']
for key,label in [('submission9_at_inferred10am','#9 ·10시 추론'),('submission11_at_observed5pm','#11 ·17시 실측')]:
 v=rank[key];cs=[v['rank_bands'][k] for k in ['top25_rank','middle50_rank','bottom25_rank']];text.append(f"| {label} | {v['opponent_rank_mean']:.2f} | {v['opponent_rank_median']:g} | {rate(v['opponent_mean_rank_fraction_of87'])} | "+' / '.join(f"{c['wins']}/{c['n']}" for c in cs)+' |')
text+=['','시점에 가까운 등수로 바꾸면 상대 평균 차이는1등 정도다. 현재 등수를 과거에 소급했을 때 보였던4.5등 차이는 줄어든다. 두 순위표의 상대 코드와 대진도 바뀌었으므로 순위가 비슷하다는 것이 절대 실력까지 같다는 뜻은 아니다.','',
'## 공통 상대 비교','',
'같은 팀 이름과 등록 소속을 맞췄지만 상대 제출 버전·맵·실제 위치는 맞추지 못했다. 한 상대를 여러 번 만났으면 상대 내 평균을 먼저 구하고 상대들을 동일 가중했다. 상대 단위20,000회 bootstrap의95% 구간을 함께 제시한다.','',
'| 비교(A−B) | 공통 상대 | A/B 상대별 평균 승점률 | 차이 | 조건부95% 구간 |','|---|---:|---:|---:|---|']
for pair in [('9','11'),('8','9'),('9','8+11'),('4','8+11')]:
 c=next(c for c in p['common_opponent_comparisons'] if (c['a'],c['b'])==pair)
 text.append(f"| #{pair[0]}−#{pair[1]} | {c['common_opponents']} | {rate(c['a_common_macro_point_rate'])}/{rate(c['b_common_macro_point_rate'])} | {100*c['macro_difference_a_minus_b']:+.1f}%p | {ci(c['common_opponent_bootstrap95'])} |")
c=next(c for c in p['common_opponent_comparisons'] if (c['a'],c['b'])==('9','11'))
text+=['','| 공통 상대 | #9 | #11 |','|---|---|---|']
for v in c['details']:text.append(f"| {v['opponent']} | {'승' if v['a_outcomes'][0] else '패'} | {'승' if v['b_outcomes'][0] else '패'} |")
text+=['','#11이 박박이·올림픽 정신·요미에게 패→승, 인공저능에게 승→패였으며 나머지4팀은 같았다. #11−#9 차이는+25%p지만 구간은−25~+75%p다. 이8팀 비교에 확인된3개 기권승은 포함되지 않는다.','',
'## 과거 #3과 #4','',
'#3은 현재 전체 목록에서5승1패(83.3%)이고6경기 모두 정상종료로 확인됐다. 작은 표본이며 당시 보관한 초기 화면은4승1패·5경기·보정61.0%였다. 현재6경기를 옛5경기 화면과 동일한 표본으로 취급하지 않는다. 높은83.3%만으로 현재 최강이라고 선택할 근거는 부족하다.','',
'#4는 당시9승4패·19위·보정66.2%였다. 당시 전체104팀 중 실제 경기와 순위가 있는 팀은56개다. 상대평균24.31위와 중앙22위를 현재87팀의 등수와 그대로 비교하지 않았다. 표시등수/활성팀수로 정규화하면 상대평균43.41%,중앙39.29%이고, 우리 당시19/56=33.93%였다(낮을수록상위).','',
'| #4 당시56팀 내 상대층 | 승/패 |','|---|---:|','| 상위25% ·1~14위 | 0/4 |','| 중간50% ·15~42위 | 6/0 |','| 하위25% ·43~56위 | 3/0 |','',
'동시기 상대 승점률 평균은56.59%였다. #4는 중하위 상대를 안정적으로 이겼으나 당시 상위층4팀에는 모두 패했다.13경기 모두 정상 즉시/점수 종료였으며 참새튀김기전도 즉시승리이지 기권승이 아니다. 최신17시 등수에 소급하면 #4가 지금 상위12인 상대에게2승2패인 것으로 보인다. 이 차이가 바로 현재 상대 강도를 과거 버전에 소급할 수 없는 이유다.','',
'## 실행 오류를 분리한 성적','',
'전체 공식 승패를 유지하고, 확인된 상대 기권승을 뺀 민감도를 별도로 기록한다. 원인이 확인되지 않은 오래된 경기는 정상 또는 기권으로 추정하지 않는다.','',
'| 제출 | 확인 정상 경기 | 확인 상대 기권승 | 개별 종료 미확인 | 확인 기권승만 제외한 승/패 |','|---|---:|---:|---:|---:|']
for s,r in p['submissions'].items():
 v=r['excluding_confirmed_opponent_forfeit_wins'];text.append(f"| #{s} | {r['confirmed_normal_only']['n']} | {r['confirmed_opponent_forfeit_wins']} | {r['individual_forfeit_status_unknown']} | {v['wins']}/{v['losses']} |")
text+=['','팀 리더보드의 errors 열은 어느 경기의 오류인지를 알려주지 않는다. 그것만으로 우리 경기의 승리를 기권승으로 바꾸지 않았다. #9 확인 기권승은 신촌도 우리땅·개우진보러갈까이며, #11은 Re:verse가 확인됐다. 최신24경기 상세UI를 모두 연결했으며 #11의 나머지23경기는 정상11승12패로 확인됐다. 전체131경기 중68경기 종료이유(정상65·기권3)를 확인했고63개는 미확인으로 남겼다.','',
'## 추천에 사용할 수 있는 결론','',
'과거 공식 성적의 후보로 #4를 계속 고려해야 한다.9승4패·당시19위·보정66.2%는 실제 근거이고,13경기가 모두 정상 종료였다는 점도 확인됐다. 현재 #11이 모든 과거 제출보다 강하다고 이 자료로 선언할 수 없다. #3의 높은 비율은6경기라는 규모를 함께 말해야 한다.','',
'최근 #9와 #11 중에서는 공통 상대8팀 성적과 확인된 기권을 제외한 결과가 #11 쪽에 기울지만, 원성적은 동률이고 비교 구간도 넓다. 현재 #11을 유지하는 판단에 보탤 관측은 되지만 확정 우위의 증명은 아니다. #8+#11 동일 소스 묶음도25승23패로 #9보다 소폭 높을 뿐이다.','',
'현재 동일 조건의 강도는 출처가 확인된 소스들의 별도 고정 상대·맵·실행 조건 대전으로 판단해야 한다. 이전0.25vCPU 내부128경기는 고정된 로컬 후보군에 대한 근거이고, 최근 서버#9의 ZIP/소스 동일성이 확인되지 않았다면 서버#9를 직접 이겼다는 증명으로 사용할 수 없다. 공식자료만으로 #4→#11의 순위를 확정하거나 #4로 즉시 되돌리는 결론 모두 과하다. 최종 추천에는 root가 확인한 제출물 연결·실제 운영 상태를 함께 반영한다.','',
'원본과 계산은 [strength-analysis.json](strength-analysis.json), [경기별 연결](enriched-matches.json), [최신 LOO 표](latest-opponents-loo.json), [직전 등수 민감도](previous-rank-sensitivity.json)에 있다. `analyze_strength.py --repo-root <repo>`와 `rank_sensitivity.py --repo-root <repo>`로 재현한다. NumPy가 있는 번들Python을 사용한다.']
round_table=['## 회차별 성적','', '상대 순위는 이 표에서도17시 최신 값을 사용한 회고이며, 동시기 순위로 오인하지 않는다.','', '| 회차 | 승/패 | 상대 평균/중앙 등수 |', '|---|---:|---:|']
for label,value in p['rounds'].items():round_table.append(f"| {label} | {value['wins']}/{value['losses']} | {value['opponent_rank']['mean']:.2f}/{value['opponent_rank']['median']:g} |")
round_table.append('')
at=text.index('## 최신 등수 사분위와 상위12 상대')
text[at:at]=round_table
(H/'results.md').write_text('\n'.join(text)+'\n')
