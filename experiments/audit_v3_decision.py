"""Audit v3's 7338/Y turn-121 decision using only its serialized observations."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "yk-development-tools"))
from engine.commands import Move, Priority, Spawn, Tele
from engine.pipeline import run_turn
from mapgen import generate, to_state
from runner.protocol import parse_commands, serialize_init, serialize_turn
from runner.replay import snapshot

REPLAY = ROOT / "records/league/loop2-iteration2/runs/holdout/replays/f68cd4938fe81851c1314689.json.gz"
SOURCE = ROOT / "submissions/iterative-v3/main.cpp"
TURN = 121
CELL = 8 + 15 * 10


TRACE = r'''
#include <iomanip>
struct AuditRow {string stage;int source,index;double value;Action action;};
vector<AuditRow> audit_rows;
vector<pair<double,int>> audit_groups;
int audit_aborted=0;
void audit_action(const Action& a) {
    cerr<<"{\"spawn\":[";bool comma=false;
    for(auto p:a.spawn) {if(comma)cerr<<",";comma=true;cerr<<"["<<p.kind<<","<<p.pos<<","<<p.count<<"]";}
    cerr<<"],\"moves\":[";comma=false;
    for(auto m:a.moves) {if(comma)cerr<<",";comma=true;cerr<<"["<<m.kind<<","<<m.from<<","<<m.to<<","<<m.count<<","<<m.tele<<"]";}
    cerr<<"],\"priority\":[";
    for(int i=0;i<int(a.priority.size());++i) {if(i)cerr<<",";cerr<<a.priority[i];}
    cerr<<"]}";
}
'''


POST = r'''
void audit_after_decision(const State& s,int us,const Action& chosen,double elapsed) {
    const int cell=158,b=board.at[cell];
    Action held=chosen;
    held.moves.erase(remove_if(held.moves.begin(),held.moves.end(),[&](auto m){return m.kind==F && m.from==cell;}),held.moves.end());
    Action scripts[4];for(int j=0;j<4;++j)scripts[j]=a_clean(s,us,policy(s,us,j));
    cerr<<setprecision(12)<<"{\"search_ms\":"<<elapsed<<",\"aborted_evaluations\":"<<audit_aborted<<",\"turn\":"<<s.turn+1;
    cerr<<",\"estimated_scores\":[";
    for(int i=0;i<board.nb;++i) {if(i)cerr<<",";cerr<<"["<<board.id[i]<<","<<s.score[i]<<","<<s.revealed[us][i]<<"]";}
    cerr<<"],\"occupation_estimate\":["<<s.occupation[0]<<","<<s.occupation[1]<<"],\"groups\":[";
    for(int i=0;i<int(audit_groups.size());++i) {if(i)cerr<<",";cerr<<"["<<audit_groups[i].second<<","<<-audit_groups[i].first<<"]";}
    cerr<<"],\"chosen\":";audit_action(chosen);cerr<<",\"hold_only\":";audit_action(held);
    cerr<<",\"scripts\":[";for(int j=0;j<4;++j){if(j)cerr<<",";audit_action(scripts[j]);}
    cerr<<"],\"trace\":[";
    for(int i=0;i<int(audit_rows.size());++i) {
        const auto& r=audit_rows[i];if(i)cerr<<",";
        cerr<<"{\"stage\":"<<quoted(r.stage)<<",\"source\":"<<r.source<<",\"index\":"<<r.index<<",\"value\":"<<r.value<<",\"action\":";
        audit_action(r.action);cerr<<"}";
    }
    cerr<<"],\"counterfactual_rollouts\":[";
    int continuation=0;double basebest=-1e100;
    for(const auto& row:audit_rows) if(row.stage=="base" && row.value>basebest) {basebest=row.value;continuation=row.index;}
    for(int j=0;j<4;++j) {
        if(j)cerr<<",";cerr<<"{\"opponent_script\":"<<j<<",\"first_opponent\":";
        Action opp=policy(s,1-us,j);audit_action(opp);cerr<<",\"alternatives\":[";
        for(int k=0;k<2;++k) {
            if(k)cerr<<",";State trial=s;cerr<<"{\"hold\":"<<k<<",\"states\":[";
            for(int d=0;d<3;++d) {
                Action own=d?policy(trial,us,continuation):(k?held:chosen),enemy=policy(trial,1-us,j);
                trial=us==0?advance(trial,own,enemy):advance(trial,enemy,own);
                if(d)cerr<<",";cerr<<"{\"turn\":"<<trial.turn<<",\"target_owner\":"<<trial.owner[b]<<",\"own_F\":"<<trial.u[us][F][cell]<<",\"enemy_F\":"<<trial.u[1-us][F][cell]<<",\"evaluation\":"<<evaluation(trial,us);
                cerr<<",\"score\":["<<points(trial,0)<<","<<points(trial,1)<<"],\"resources\":["<<trial.res[0]<<","<<trial.res[1]<<"],\"unit_counts\":[";
                for(int t=0;t<2;++t) {if(t)cerr<<",";cerr<<"[";for(int kind=0;kind<3;++kind){if(kind)cerr<<",";cerr<<accumulate(trial.u[t][kind],trial.u[t][kind]+N,0);}cerr<<"]";}
                cerr<<"],\"own_moves_from_target\":[";bool comma=false;
                for(auto m:own.moves) if(m.from==cell) {if(comma)cerr<<",";comma=true;cerr<<"["<<m.kind<<","<<m.from<<","<<m.to<<","<<m.count<<"]";}
                cerr<<"]}";
                if(abs(evaluation(trial,us))>=80000) break;
            }
            cerr<<"]}";
        }
        cerr<<"]}";
    }
    cerr<<"],\"continuation\":"<<continuation<<"}\n";
}
'''


def change(source, old, new, count=1):
    if source.count(old) != count:
        raise ValueError(f"Unexpected instrumentation anchor count: {old[:80]!r}")
    return source.replace(old, new)


def instrument(source):
    source = change(source, "using AClock=chrono::steady_clock;", TRACE + "\nusing AClock=chrono::steady_clock;")
    source = change(source, ">=limit) return false;", ">=limit) {++audit_aborted;return false;}")
    source = change(source, "        plans[i].value=value;", '        audit_rows.push_back({"base",-1,i,value,plans[i].action});\n        plans[i].value=value;')
    source = change(source, "        sort(groups.begin(),groups.end());", "        sort(groups.begin(),groups.end());audit_groups=groups;")
    source = change(source, "                if(value>incumbent.value) {incumbent.action=trial;incumbent.value=value;}",
                    '                audit_rows.push_back({"local",src,-1,value,trial});\n                if(value>incumbent.value) {incumbent.action=trial;incumbent.value=value;}', 2)
    source = change(source, "vector<string> decide(const p::View& v, const p::Init& in) {", POST + "\nvector<string> decide(const p::View& v, const p::Init& in) {")
    anchor = "    Action a=forced_policy>=0?policy(s,us,forced_policy):a_decide(s,us,start);"
    source = change(source, anchor, '    if(v.turn<121) return {};\n' + anchor + '\n    if(v.turn==121) audit_after_decision(s,us,a,chrono::duration<double,milli>(AClock::now()-start).count());')
    return source


def commands(action, initial):
    buildings = initial.sorted_buildings()
    base = initial.bases["Y"]
    result = []
    for kind, pos, n in action["spawn"]:
        result.append(Spawn("FWS"[kind], n, None if (pos % 15, pos // 15) == base else pos % 15,
                            None if (pos % 15, pos // 15) == base else pos // 15))
    for kind, src, dest, n, tele in action["moves"]:
        if tele:
            result.append(Tele(src % 15, src // 15, "FWS"[kind], n, dest % 15, dest // 15))
        else:
            result.append(Move(src % 15, src // 15, "FWS"[kind], n, {1:"R",-1:"L",15:"D",-15:"U"}[dest-src]))
    result.append(Priority([(buildings[b].x, buildings[b].y) for b in action["priority"]]))
    return result


def analyze():
    replay = json.load(gzip.open(REPLAY, "rt"))
    initial = to_state(generate(replay["seed"], replay["config"]))
    state = initial
    blocks = [serialize_init(state, "Y")]
    for index in range(TURN):
        blocks.append(serialize_turn(state, "Y", index + 1))
        if index < TURN - 1:
            frame = replay["turns"][index]
            state, _ = run_turn(state, parse_commands(frame["commands"]["Y"]), parse_commands(frame["commands"]["K"]))
            assert snapshot(state) == frame["state"]
    payload = "".join(blocks)
    source = SOURCE.read_text()
    executions = {}
    with tempfile.TemporaryDirectory(prefix="yk-v3-decision-audit-", dir="/tmp") as folder:
        for name, text in (("original", source), ("instrumented", instrument(source))):
            path = Path(folder) / f"{name}.cpp"
            path.write_text(text)
            binary = path.with_suffix("")
            subprocess.run(["g++", "-std=c++20", "-O2", "-I", str(SOURCE.parent), str(path), "-o", str(binary)], check=True, capture_output=True)
            started = time.monotonic()
            result = subprocess.run([str(binary)], input=payload, text=True, capture_output=True, check=True, timeout=120)
            outputs = [x.strip().splitlines() for x in result.stdout.split("END\n")[:-1]]
            assert len(outputs) == TURN
            executions[name] = dict(elapsed_seconds=time.monotonic()-started, final_output=outputs[-1],
                                    instrumented_source_sha256=hashlib.sha256(text.encode()).hexdigest())
            if name == "instrumented":
                trace = json.loads(result.stderr)
    actual_commands = replay["turns"][TURN-1]["commands"]
    fixed = parse_commands(actual_commands["K"])
    one_step = []
    for name in ("chosen", "hold_only"):
        after, _ = run_turn(state, commands(trace[name], initial), fixed)
        one_step.append(dict(action=name, target_owner=after.buildings[12].owner,
                             scores={t:sum(b.score for b in after.buildings.values() if b.owner==t) for t in "YK"},
                             equals_recorded_snapshot=snapshot(after)==replay["turns"][TURN-1]["state"]))
    def remaining_f(action):
        return state.get_unit(8,10,"Y","F") - sum(m[3] for m in action["moves"] if m[0]==0 and m[1]==CELL)
    trace["script_flag_retention"] = [remaining_f(a) for a in trace["scripts"]]
    trace["evaluated_candidates_retaining_flag"] = [i for i,row in enumerate(trace["trace"]) if remaining_f(row["action"])>0]
    trace["internal_aggregate"] = {}
    for option in (0,1):
        values = [r["alternatives"][option]["states"][-1]["evaluation"] for r in trace["counterfactual_rollouts"]]
        trace["internal_aggregate"]["hold_only" if option else "chosen"] = .75*sum(values)/4 + .25*min(values)
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    return dict(schema=1, source_sha256=sha(SOURCE), replay_path=str(REPLAY.relative_to(ROOT)), replay_sha256=sha(REPLAY),
                script_sha256=sha(Path(__file__)), observation_payload_sha256=hashlib.sha256(payload.encode()).hexdigest(),
                observations=TURN, verified_preceding_transitions=TURN-1,
                unknown_building_ids=[b.id for b in state.sorted_buildings() if b.id not in state.revealed["Y"]],
                legal_target_observation=blocks[-1], executions=executions,
                instrumented_equals_original=executions["instrumented"]["final_output"]==executions["original"]["final_output"],
                original_equals_recorded=executions["original"]["final_output"]==actual_commands["Y"],
                trace=trace, official_fixed_opponent_one_step=one_step,
                scope="Original and traced choices consume only legal protocol observations. Actual opponent commands are used after both processes exit, only for one-step diagnostics.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    evidence = analyze()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k:evidence[k] for k in ("instrumented_equals_original","original_equals_recorded")}, ensure_ascii=False))
    print(json.dumps({k:evidence["trace"][k] for k in ("search_ms","aborted_evaluations","script_flag_retention","evaluated_candidates_retaining_flag","internal_aggregate")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
