"""Summarize a completed frozen league, including matched improvements and regressions."""
import argparse
import json
from pathlib import Path


def read_rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def point(row):
    return float(row["win"]) + .5 * row["draw"]


def paired_diagnostics(rows, candidate, team):
    indexed = {(r["candidate"],r["map_seed"],r["team"],r["opponent"]):r for r in rows if r["status"]=="complete"}
    deltas, improvements, regressions = [], [], []
    for (name,seed,side,opponent), new in indexed.items():
        old = indexed.get(("v2",seed,side,opponent))
        if name != candidate or side != team or old is None:
            continue
        new_d, old_d = new["diagnostics"][side], old["diagnostics"][side]
        new_turns, old_turns = max(1,new["result"]["turns"]), max(1,old["result"]["turns"])
        evidence={"seed":seed,"team":side,"opponent":opponent,
                  "point_delta":point(new)-point(old),"old_result":old["result"],"new_result":new["result"],
                  "old_replay":old.get("replay"),"new_replay":new.get("replay"),
                  "engineering_fraction_delta":new_d["engineering_turns"]/new_turns-old_d["engineering_turns"]/old_turns,
                  "warrior_production_per_turn_delta":new_d["production"]["W"]/new_turns-old_d["production"]["W"]/old_turns,
                  "old_diagnostics":old_d,"new_diagnostics":new_d}
        deltas.append(evidence)
        if point(new)>point(old): improvements.append(evidence)
        if point(new)<point(old): regressions.append(evidence)
    return {"paired_games":len(deltas),"improved_results":len(improvements),"regressed_results":len(regressions),
            "mean_engineering_fraction_delta":sum(r["engineering_fraction_delta"] for r in deltas)/len(deltas) if deltas else None,
            "mean_warrior_production_per_turn_delta":sum(r["warrior_production_per_turn_delta"] for r in deltas)/len(deltas) if deltas else None,
            "examples_improved":sorted(improvements,key=lambda r:(r["point_delta"],r["new_result"]["score"][team]),reverse=True)[:6],
            "examples_regressed":sorted(regressions,key=lambda r:r["point_delta"])[:6],
            "interpretation":"Matched map/side/opponent observations, not causal isolation; match length and strategy both change."}


def analyze(arena):
    result=json.loads((arena/"campaign-result.json").read_text())
    manifest=json.loads((arena/"manifest.json").read_text())
    holdout=json.loads((arena/"runs/holdout/summary.json").read_text())
    rows=read_rows(arena/"runs/holdout/results.jsonl")
    analysis={"result":result,"candidates":{name:{"metadata":manifest["bots"][name],"holdout":holdout["by_candidate"][name],
                      "paired_diagnostics":{team:paired_diagnostics(rows,name,team) for team in "YK"}}
                      for name in result["finalists"]}}
    (arena/"analysis.json").write_text(json.dumps(analysis,ensure_ascii=False,indent=2)+'\n')
    lines=["# 다양한 후보 리그 결과","",f"완료 경기 **{result['total_matches']:,}전**, 후보 {result['candidate_count']}개. 내부 승격 기준 추천은 **{result['recommended']}**다.","",
           "| 단계 | 경기 수 |","|---|---:|"]
    for stage,count in result["stage_match_counts"].items(): lines.append(f"| {stage} | {count:,} |")
    lines += ["","최종 후보는 선택 단계에서 고정했다. 아래 수치는 24개 새 맵과 고정 상대 5개에서의 검증이며 실제 참가자 전체에 대한 승률 추정은 아니다.","",
              "| 후보 | Y 승/무/패 | Y 승점률 | K 승점률 | v2 대비 Y 차이·맵 bootstrap 95% 구간 | 몰수 | 최대 응답 |","|---|---|---:|---:|---|---:|---:|"]
    for name in ["v2",*result["finalists"]]:
        s=holdout["by_candidate"][name];y=s["Y"];k=s["K"]
        cmp=result["holdout_comparisons"].get(name,{}).get("Y")
        comparison="기준선" if cmp is None else f"{cmp['point_rate_difference']*100:+.1f}%p [{cmp['map_cluster_bootstrap_95pct'][0]*100:+.1f}, {cmp['map_cluster_bootstrap_95pct'][1]*100:+.1f}]"
        lines.append(f"| {name} | {y['wins']}/{y['draws']}/{y['losses']} | {y['point_rate']:.1%} | {k['point_rate']:.1%} | {comparison} | {s['forfeits']} | {s['max_turn_ms']:.1f}ms |")
    lines += ["","승격 기준은 사전에 정했다: 주 후보의 Y 개선 3%p 이상·구간 하한 양수·양쪽 무오류/무몰수·상대별 Y 회귀 10%p 이내. 보조 후보가 더 좋아 보여도 그 결과를 보고 주 후보를 바꾸려면 새로운 검증 맵을 사용한다."]
    for name,entry in analysis["candidates"].items():
        d=entry["paired_diagnostics"]["Y"]
        lines += ["",f"## {name}","",entry["metadata"]["hypothesis"],"",f"사전 약점: {entry['metadata']['weakness']}","",
                  f"같은 Y 조건에서 결과가 개선된 경기는 {d['improved_results']}개, 회귀한 경기는 {d['regressed_results']}개다. 공학관 할인 보유 비율의 평균 차이는 {d['mean_engineering_fraction_delta']*100:+.1f}%p, 턴당 W 생산 차이는 {d['mean_warrior_production_per_turn_delta']:+.2f}명이다. 경기 길이·행동이 함께 달라지므로 원인 효과로 단정하지 않는다.","",
                  "| 상대 | Y 승점률 차이 |","|---|---:|"]
        for op,cmp in result["opponent_Y_comparisons"][name].items(): lines.append(f"| {op} | {cmp['point_rate_difference']*100:+.1f}%p |")
        for key,label in (("examples_improved","개선 사례"),("examples_regressed","회귀 사례")):
            if d[key]:
                e=d[key][0]
                lines += ["",f"{label}: 맵 {e['seed']}/Y, 상대 {e['opponent']}. v2 {e['old_result']['score']} → 후보 {e['new_result']['score']}. 상세 수치와 리플레이 경로는 [analysis.json](analysis.json)에 보존했다."]
    lines += ["","## 기록 해석","","`crossplay-table.json`은 원 경기마다 양쪽 관점을 집계한다. 각 run의 `summary.json`은 원래 candidate 열의 결과이므로 상호 대전 전체 순위에는 crossplay table을 사용한다.","",
              "모든 경기 요약·응답시간·진단 지표는 `runs/*/results.jsonl`, 패배·무승부와 첫 맵 승리의 전체 진행은 `runs/*/replays/*.json.gz`에 있다. gzip을 풀어 기존 JSON 리플레이처럼 읽을 수 있다. 실행 바이너리는 보존하지 않으며 실제 소스·헤더·SDK 스냅샷과 해시를 남겼다.","",
              "원격 작업은 TMP 안에서 실행됐다. 실제 자원 제한·정리 결과는 `remote_supervisor.json`, `transport_receipt.json`, `transport.jsonl`을 확인한다. 이 보고서는 실제 제출 ZIP 교체나 사이트 업로드를 수행했다는 뜻이 아니다."]
    (arena/"README.md").write_text('\n'.join(lines)+'\n')
    return analysis


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("arena",type=Path)
    args=parser.parse_args()
    analyze(args.arena.resolve())
