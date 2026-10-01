"""Read-only official participant-view analysis. Unknown scores remain unknown."""
from pathlib import Path
from collections import Counter
import datetime,hashlib,json,sys,statistics
OUT=Path(__file__).resolve().parent
REPO=next((p for p in OUT.parents if (p/'experiments/analyze_official_round1.py').is_file()),Path('/tmp/yk-new-bot-20261001'))
RAW=OUT.parent/'raw' if (OUT.parent/'raw').is_dir() else REPO/'records/official/round-20261001-1000/raw'
sys.dont_write_bytecode=True;sys.path.insert(0,str(REPO/'experiments'));import analyze_official_round1 as base
cfg=json.loads((base.SDK/'config/balance.json').read_text());sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
IDENTITY={'rolling-game-fd86a6c092d1fc50f9a07fe53dc51a22e2445e934d45f58202192d30c675b2ad':{'opponent':'박박이','submission':9,'source':'root authenticated current-round collection task message'}}
for f in [RAW.parent/'matches.json',RAW.parent/'identity.json']:
 if f.is_file():
  data=json.loads(f.read_text()); rr=data if isinstance(data,list) else data.get('matches',[])
  for r in rr:IDENTITY[r.get('gameId',r.get('game_id'))]=r

def bounds(buildings,known):
 out={}
 for team in ['Y','K','N']:
  lo=hi=0
  for b in buildings:
   if b['owner']!=team:continue
   if b['id'] in known:l=h=known[b['id']]
   elif b['type']=='PLAZA':l=h=3
   else:l,h=(2,4) if 5<=b['x']<=9 else (1,2)
   lo+=l;hi+=h
  out[team]=[lo,hi]
 return out

def analyze(f):
 g=json.loads(f.read_text());side=g['side'];enemy='K' if side=='Y' else 'Y';bs=base.infer_bases(g);frames=g['turns'];rows=[];production=Counter();dead=Counter();ew=0;cost=0;flag=[];ownership=[];economy={s:Counter() for s in ['Y','K']};hold=[];known={};command_status=Counter()
 for i,frame in enumerate(frames):
  obs=frame['observation'];assert i==frame['turn']==obs['turn']==frame['turnIndex'];build=obs['buildings'];known.update({b['id']:b['score'] for b in build if 'score'in b});legal=base.mirrored_scores(build,known);actual_bounds=bounds(build,legal)
  if obs['scores'].get(side) is not None:assert actual_bounds[side][0]<=obs['scores'][side]<=actual_bounds[side][1]
  bc={s:dict(Counter(b['type'] for b in build if b['owner']==s)) for s in ['Y','K']}
  row={'turn':i,'phase':frame['phase'],'transition_applied':frame['phase']=='AFTER_COMMANDS','public_scores':obs['scores'],'legal_score_bounds':actual_bounds,'known_building_scores':dict(legal),'units':base.unit_totals(obs['units']),'resources':obs['resources'],'building_counts':bc,'events':obs['events'],'response_ms':obs.get('myResponseMs'),'stdout_bytes':obs.get('myStdoutBytes'),'ownership_changes':[]}
  if i:
   command_status[frame['command']['status']]+=1
   if frame['phase']=='BEFORE_COMMANDS':
    assert i==len(frames)-1 and g['result'].get('forfeit')
    before=frames[i-1]['observation']
    state_keys=['buildings','map','occTurns','resources','scores','side','units']
    assert all(obs[k]==before[k] for k in state_keys), 'Forfeit-before-commands changed game state'
    row['unexecuted_own_commands']=frame['command']['lines']
    row['unexecuted_reason']='Terminal opponent forfeit before commands; own status ok records response, not applied actions.'
   else:assert frame['phase']=='AFTER_COMMANDS'
  else:assert frame['phase']=='START'
  if i and row['transition_applied']:
   before=frames[i-1]['observation'];prev={b['id']:b for b in before['buildings']}
   tx=base.own_transition(frames[i-1],frame,bs,cfg,side);row['own_transition']=tx;row['command_input_observation_turn']=i-1
   production.update(tx['production']);dead.update(tx['casualties']);ew+=tx['enemy_w_production_inferred'];cost+=tx['production_resource_cost']
   for s in ['Y','K']:
    for kind in ['ENG','HOSPITAL']:economy[s]['turns_with_'+kind.lower()+'_at_production']+=int(any(b['type']==kind and b['owner']==s for b in before['buildings']))
    economy[s]['hall_count_sum_at_turn_start']+=sum(b['type']=='HALL' and b['owner']==s for b in before['buildings'])
   for b in build:
    old=prev[b['id']]
    if old['owner']!=b['owner']:
     x,y=b['x'],b['y'];v={'turn':i,'id':b['id'],'type':b['type'],'x':x,'y':y,'from':old['owner'],'to':b['owner'],'score_known_before':base.mirrored_scores(before['buildings'],{q['id']:q['score'] for q in before['buildings'] if 'score'in q}).get(b['id']),'before_local_units':[u for u in before['units'] if abs(u[2]-x)+abs(u[3]-y)<=2],'after_cell_units':[u for u in obs['units'] if u[2:4]==[x,y]]};row['ownership_changes'].append(v);ownership.append(v)
   for c in tx['casualty_cells']:
    if c['kind']!='F':continue
    x,y=c['x'],c['y'];flag.append({'turn':i,**c,'before_building':next((b for b in before['buildings'] if [b['x'],b['y']]==[x,y]),None),'before_local_units':[u for u in before['units'] if abs(u[2]-x)+abs(u[3]-y)<=2],'after_local_units':[u for u in obs['units'] if abs(u[2]-x)+abs(u[3]-y)<=2],'actual_own_commands':frame['command']['lines']})
   if tx['casualties']['F']:
    state=base.state_from_observation(before,bs,cfg);commands=base.parse_commands(frame['command']['lines']);after,_=base.run_turn(state,commands if side=='Y' else [],commands if side=='K' else []);af=sum(v for (x,y,s,k),v in after.units.items() if (s,k)==(side,'F'));bf=base.unit_totals(before['units'])[side]['F'];lost=bf+tx['production']['F']-af
    hold.append({'turn':i,'actual_F_casualties':tx['casualties']['F'],'F_casualties_enemy_no_spawn_no_move':lost,'scope':'One-turn legal stationary opponent response from actual previous observation; no opponent-order recovery or whole-game result claim. Unknown building scores placeholder0 in SDK state do not enter spawn/move/combat counts.'})
  rows.append(row)
 for k in ['F','W','S']:assert production[k]-dead[k]==rows[-1]['units'][side][k]
 assert production['W']-ew==rows[-1]['units'][side]['W']-rows[-1]['units'][enemy]['W']
 econloss=[e for e in ownership if e['from']==side and e['type'] in ['ENG','HALL','HOSPITAL']]
 firstecon={s:{kind:next((r['turn'] for r in rows if r['building_counts'][s].get(kind,0)),None) for kind in ['ENG','HALL','HOSPITAL']} for s in ['Y','K']}
 intervals=[]
 for b in frames[0]['observation']['buildings']:
  if b['type'] not in ['ENG','HALL','HOSPITAL']:continue
  runs=[];owner=None;start=0
  for i,fr in enumerate(frames):
   cur=next(q['owner'] for q in fr['observation']['buildings'] if q['id']==b['id'])
   if cur!=owner:
    if owner is not None:runs.append({'owner':owner,'start':start,'end':i-1})
    owner=cur;start=i
  runs.append({'owner':owner,'start':start,'end':len(frames)-1});intervals.append({**b,'ownership_intervals':runs})
 phase=[]
 for a,z in [(1,20),(21,40),(41,80),(81,120),(121,140),(141,160)]:
  rr=[r for r in rows if a<=r['turn']<=z and r['transition_applied']]
  if not rr:continue
  phase.append({'start':a,'end_turn':rr[-1]['turn'],'production':dict(sum((Counter(r['own_transition']['production']) for r in rr),Counter())),'casualties':dict(sum((Counter(r['own_transition']['casualties']) for r in rr),Counter())),'enemy_W_production_inferred':sum(r['own_transition']['enemy_w_production_inferred'] for r in rr),'end':{k:rr[-1][k] for k in ['turn','public_scores','legal_score_bounds','units','building_counts']}})
 t=rows[-1]['turn'];win=g['result']['winner'];result='win' if win==side else 'loss' if win==enemy else 'draw';normal=[r['response_ms'] for r in rows[2:] if r['response_ms']is not None]
 firstgap=next((r for r in rows if r['building_counts'][enemy].get('ENG',0)>0 and not r['building_counts'][side].get('ENG',0)),None)
 summary={'source':str(f),'source_relative_to_archive':'../raw/'+f.name,'sha256':sha(f),**{k:g.get(k) for k in ['gameId','evaluationId','seriesId','side','schemaVersion','botPerspectiveVersion','protocolVersion','rulesetVersion','result']},'identity':IDENTITY.get(g['gameId']),'round_context':{'published_round':'2026-10-01 10:00 KST','played_site_submission':9,'currently_selected_site_submission':10,'context_source':'root authenticated site collection message; replay JSON alone has no submission number'},'our_result':result,'turn_count':t,'completed_transition_count':sum(r['transition_applied'] for r in rows),'terminal_phase':frames[-1]['phase'],'forfeit':g['result'].get('forfeit',False),'our_win_forfeit':result=='win' and g['result'].get('forfeit',False),'termination_phase':'before_140' if t<140 else 'turn_140' if t==140 else '141_to_160','late_phase_observed':t>140,'final_public_scores':rows[-1]['public_scores'],'final_legal_score_bounds':rows[-1]['legal_score_bounds'],'final_units':rows[-1]['units'],'production':dict(production),'casualties':dict(dead),'production_resource_spend':cost,'enemy_W_production_inferred':ew,'economy':economy,'economic_first_capture':firstecon,'first_ENG_disadvantage':({k:firstgap[k] for k in ['turn','units','building_counts']} if firstgap else None),'first_own_economic_loss':econloss[0] if econloss else None,'economic_losses':econloss,'economic_ownership_intervals':intervals,'first_F_loss':flag[0] if flag else None,'F_loss_events':flag,'stationary_enemy_F_probes':hold,'command_status_counts':dict(command_status),'first_response_ms':rows[1]['response_ms'],'normal_response_ms':{'max':max(normal,default=None),'median':statistics.median(normal) if normal else None,'over_300ms':sum(v>300 for v in normal)},'own_spawn_move_transition_checks':sum(r['transition_applied'] for r in rows),'checkpoints':[{k:r[k] for k in ['turn','public_scores','legal_score_bounds','units','building_counts']} for r in rows if r['turn'] in {0,5,10,15,20,30,40,60,80,100,120,140,150,158,159,160,t}],'phases':phase,'full_reconstruction':False,'opponent_commands_available':False,'hidden_scores_filled':False}
 if summary['identity'] and 'submission_version' in summary['identity']:
  identity=summary['identity']; assert identity['submission_version']==9 and identity['team']==side
  assert identity['outcome']=={'win':'W','loss':'L','draw':'D'}[result]
 summary['submission_zip_sha256']=None
 summary['submission_source_byte_identity']='Server ZIP hash unavailable; site version9 identified by authenticated match listing only.'
 return {'summary':summary,'turns':rows,'ownership_changes':ownership}

paths=sorted(RAW.glob('*.json'));games=[];errors=[]
for f in paths:
 try:games.append(analyze(f))
 except Exception as e:errors.append({'source':str(f),'sha256':sha(f),'error':repr(e)})
meta={'created_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'expected_games':24,'downloaded_paths':len(paths),'analyzed_games':len(games),'complete_round':len(games)==24 and {g['summary']['gameId'] for g in games}==set(IDENTITY),'outcomes':dict(Counter(g['summary']['our_result'] for g in games)),'forfeit_wins':sum(g['summary']['our_win_forfeit'] for g in games),'ordinary_wins':sum(g['summary']['our_result']=='win' and not g['summary']['forfeit'] for g in games),'errors':errors,'scope':'All downloaded current-round raw files; identity set and outcomes checked against authenticated match listing. Uses our previous observation and actual own commands. Enemy commands absent. No invented hidden scores.','own_spawn_move_transition_checks':sum(g['summary']['own_spawn_move_transition_checks'] for g in games),'dependencies':{str(p):sha(p) for p in [Path(__file__),REPO/'experiments/analyze_official_round1.py',base.SDK/'engine/pipeline.py',base.SDK/'engine/state.py',base.SDK/'config/balance.json',base.SDK/'runner/protocol.py']},'limits':['Legal score bounds use current revealed values plus exact180degree score symmetry; unknown side scores remain null.','Observed economic loss/first F death is not automatically first causal strategy error.','Own spawn/move stages checked against SDK; no full official replay reproduction without opponent commands.','Stationary enemy probe is a one-turn legal response, not actual opponent reconstruction or proof of an alternate whole-game win.','Old rounds and local benchmark results are excluded.','Two terminal BEFORE_COMMANDS forfeit frames contain a successful own response but no applied actions; they are excluded from production, deaths and transition counts. Opponent forfeit cause is unavailable.','Server ZIP/source byte identity is unverified; internal policy mode cannot be inferred from observed move patterns alone.']}
manifest_path=RAW.parent/'raw-manifest.json';manifest=json.loads(manifest_path.read_text());by_id={g['summary']['gameId']:g['summary'] for g in games}
manifest_errors=[]
for entry in manifest['files']:
 actual=by_id.get(entry['gameId']);path=RAW.parent/entry['path']
 if actual is None or entry['sha256']!=sha(path) or entry['bytes']!=path.stat().st_size or entry['result']!=actual['result']:manifest_errors.append(entry['gameId'])
meta['raw_manifest_audit']={'manifest_sha256':sha(manifest_path),'entries':len(manifest['files']),'same_game_id_set':set(by_id)=={e['gameId'] for e in manifest['files']},'mismatches':manifest_errors}
meta['runtime_recorded']={'own_response_count':sum(sum(s['summary']['command_status_counts'].values()) for s in games),'own_status_counts':dict(sum((Counter(g['summary']['command_status_counts']) for g in games),Counter())),'first_turn_max_ms':max(g['summary']['first_response_ms'] for g in games),'normal_turn_max_ms':max(g['summary']['normal_response_ms']['max'] for g in games),'normal_over_300ms':sum(g['summary']['normal_response_ms']['over_300ms'] for g in games),'first_over_3000ms':sum(g['summary']['first_response_ms']>3000 for g in games),'scope':'Official own-response telemetry, not enemy runtime, memory audit, or attribution of forfeit cause.'}
meta['termination_counts']=dict(Counter(('win_forfeit' if g['summary']['our_win_forfeit'] else g['summary']['our_result']+'_'+g['summary']['result']['reason']+'_'+g['summary']['termination_phase']) for g in games))
meta['external_runtime_notice']={'source':'https://yonsei-vs-korea-hackathon.kr/announcements','title':'[FAQ] 에이전트 CPU 사용 한도 및 실행 시간 관련','published_at':'2026-10-01 10:42:10 KST','provenance':'Root reported authenticated official-page read; this analyzer did not fetch page.','per_agent_vcpu':0.25,'normal_elapsed_ms':300,'first_elapsed_ms':3000,'scope':'This report uses actual official replay telemetry; do not equate separate unthrottled local arenas with this environment.'}
OUT.mkdir(parents=True,exist_ok=True);(OUT/'analysis.json').write_text(json.dumps({'metadata':meta,'matches':games},ensure_ascii=False,indent=2)+'\n');(OUT/'summary.json').write_text(json.dumps({'metadata':meta,'matches':[g['summary'] for g in games]},ensure_ascii=False,indent=2)+'\n')
md=['# 10월 1일 10:00 공식 회차 — 전체 24경기 분석','',f"수집·분석 {len(games)}/24경기, 원본 결과 {meta['outcomes'].get('win',0)}승 {meta['outcomes'].get('loss',0)}패. 일반 승리 {meta['ordinary_wins']}건, 상대 기권 승리 {meta['forfeit_wins']}건입니다. 분석 실패 {len(errors)}건. 공식 목록의 경기 ID·진영·승패를 대조했습니다. 이 회차는 서버 제출 #9로 치렀고 현재 선택 #10과 구분합니다.",'','패배는 140턴 전 instant 4건, 141~160턴 instant 5건, 160턴 점수패 3건입니다. 박박이전은 HALL·병원을 한 번도 확보하지 못하고 T43에 끝나며, 2325전은 경제거점을 끝까지 지켜도 F 28명 중 27명이 죽습니다. 占쏙옙전은 공개점수 T120 35:4에서 최종 15:17로 역전패하며 최종 W 548:94의 우위를 점수로 지키지 못했습니다. 세 현상을 하나의 종반 모드 문제로 단정할 수 없습니다.','','일반 승리 10건과 상대 기권 승리 2건을 구분합니다. 200OK·공주전은 경제 선점과 W 생산 우위를 동반한 조기 승리입니다. 조선김(18:15)·인공저능(17:16)은 초반 장기 열세를 뒤집었고 인공저능전은 W 생산이 뒤져도 이겼습니다. 맵·상대·경기 길이가 달라 단순 생산 합계를 정책의 인과 효과로 해석하지 않습니다. [세부 사례와 공개 입력](cases.md), [턴별 장부](analysis.json), [원본 폴더](../raw/).','','상대 명령·숨은 점수는 확보되지 않았습니다. 우리 생산·이동 단계만 공식 SDK로 검사하고 미공개 점수는 null 및 합법 범위로 보존했습니다. 명령 t의 입력은 관측 t−1입니다.','','| 상대/ID | 결과·종료 | 공개Y:K | 합법 K 범위 | W생산 우리:상대(역산) | F생산/손실 | 첫경제손실 |','|---|---|---|---:|---:|---:|---|']
for g in sorted(games,key=lambda g:(g['summary']['our_result'],g['summary']['turn_count'])):
 s=g['summary'];ident=s['identity'] or {};e=s['first_own_economic_loss'];md.append(f"| {ident.get('opponent',s['gameId'][13:21])} | {s['our_result']} T{s['turn_count']} {s['result']['reason']} | {s['final_public_scores'].get('Y')}:{s['final_public_scores'].get('K') if s['final_public_scores'].get('K') is not None else '미공개'} | {s['final_legal_score_bounds']['K'][0]}–{s['final_legal_score_bounds']['K'][1]} | {s['production'].get('W',0)}:{s['enemy_W_production_inferred']} | {s['production'].get('F',0)}/{s['casualties'].get('F',0)} | {'T'+str(e['turn'])+' '+e['type'] if e else '없음'} |")
md+=['',f"우리 생산·이동 {meta['own_spawn_move_transition_checks']}턴을 검사했습니다. 신촌도 우리땅 T24, 개우진보러갈까 T17은 명령 실행 전 상대 기권이며 각각 실제 전이는 23·16회입니다. 마지막 미실행 명령은 생산·손실에 포함하지 않습니다. 140턴 이전 종료를 종반 붕괴로 부르지 않습니다. 첫 경제 손실과 F사망은 관측 사실이며 원인 단정은 개별 공개 상태·명령 검토 뒤에 합니다. 상세 거점 소유 구간, 모든 F 손실과 주변 공개 병력, 턴별 생산·전사는 analysis.json에 있습니다."]
(OUT/'summary.md').write_text('\n'.join(md)+'\n');print(json.dumps({k:v for k,v in meta.items() if k!='dependencies'},ensure_ascii=False,indent=2))
