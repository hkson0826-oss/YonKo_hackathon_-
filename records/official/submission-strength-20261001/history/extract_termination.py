from pathlib import Path
import json, hashlib, collections, datetime
R=Path('/tmp/yk-new-bot-20261001');H=Path(__file__).resolve().parent
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
hist=json.loads((H/'historical-matches.json').read_text())['matches']
paths=sum([list((R/d).glob('*.json')) for d in ['artifacts/firstround_results','V4_replay','records/official/latest-20261001/raw','records/official/round-20261001-1000/raw']],[])
raw={};orphans=[]
for p in paths:
 d=json.loads(p.read_text());gid=d.get('gameId')
 if not gid:continue
 item={'gameId':gid,'reason':d['result']['reason'],'winner':d['result']['winner'],'source':{'path':str(p.relative_to(R)),'repository':str(R),'sha256':sha(p),'json_pointer':'/result/reason','kind':'official_raw'},'raw_result':d['result'],'evaluationId':d.get('evaluationId'),'last_observation_turn':d['turns'][-1]['observation']['turn']}
 if gid in raw:assert raw[gid]['raw_result']==item['raw_result']
 raw[gid]=item
ui_path=R/'records/official/opponent-intel-20260928/haemyeonhae-ui-observations.json';ui=json.loads(ui_path.read_text());assert ui['end_reason_display']=='즉시 승리' and ui['site_submission']==3
known=[]
for m in hist:
 item={'round':m['round_label'],'submission':m['submission'],'opponent':m['opponent'],'gameId':m['game_id'],'outcome':m['outcome'],'reason':None,'termination_class':'unknown','source':None}
 gid=m['game_id']
 if gid in raw:
  item.update(raw[gid]);reason=item['reason'];assert reason in ('instant','score','forfeit');item['termination_class']='forfeit' if reason=='forfeit' else 'normal'
  assert (item['winner']==m['side'])==(m['outcome']=='win'),item
 elif gid==ui['game_id']:
  item.update(reason='instant',termination_class='normal',winner='Y',last_observation_turn=ui['last_turn'],source={'path':str(ui_path.relative_to(R)),'repository':str(R),'sha256':sha(ui_path),'json_pointer':'/end_reason_display','kind':'authenticated_UI_explicit_terminal_reason'},qualification='Raw is absent in current worktree; explicit authenticated UI terminal reason 即時勝利/T38 retained. No inference from victory or turn count alone.')
 known.append(item)
matched={x['gameId'] for x in known if x['source']}
assert set(raw)<=matched,set(raw)-matched
assert len(raw)==43 and len(known)==131
counts=collections.Counter(x['termination_class'] for x in known);by_sub={}
for v in range(1,12):
 ms=[m for m in known if m['submission']==v]
 if ms:by_sub[str(v)]={'games':len(ms),'classes':dict(collections.Counter(m['termination_class'] for m in ms)),'reasons':dict(collections.Counter(m['reason'] for m in ms if m['reason']))}
metadata={'created_kst':datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).isoformat(),'total_historical_UI_matches':131,'raw_confirmed':43,'UI_explicit_terminal_confirmed':1,'counts':dict(counts),'by_submission':by_sub,'scope':'Directly read retained official raw result.reason, plus explicit old 하면해 UI end_reason_display. No source/Git/browser mutation. Match keyed by gameId from historical identity join; no fuzzy name inference.','merge_rule':'Only non-null reason rows add knowledge. Unknown here means no source in this bounded archive extraction; do not overwrite another verified newer UI termination such as submission11 Re:verse.','limits':['Normal denotes non-forfeit official termination (instant/score), not no strategic error or both bot runtimes independently audited.','Forfeit internal cause is unavailable in these raw objects.','No inference of forfeit from opponent leaderboard error count, short game length, or extreme score.','Other old UI checkpoint summaries without retained raw are not promoted in this extraction; only explicitly requested 하면해 terminal UI exception is included.'],'special_check':{'submission4_참새튀김기':next(x for x in known if x['submission']==4 and x['opponent']=='참새튀김기')}}
(H/'known-termination.json').write_text(json.dumps({'metadata':metadata,'matches':known},ensure_ascii=False,indent=2)+'\n')
print(json.dumps(metadata,ensure_ascii=False,indent=2))
