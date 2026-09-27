"""Separate three-step continuation intervention on the fixed 7338 decision."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

import audit_v3_decision as decision
from engine.commands import Spawn
from engine.pipeline import run_turn
from mapgen import generate, to_state
from runner.protocol import parse_commands, serialize_init, serialize_turn
from runner.replay import snapshot

ROOT = decision.ROOT

PROBE = r'''
Action cont_pin(const State& s,int us,Action action) {
    int left=max(0,s.u[us][F][158]-1);
    vector<Movement> moves;
    for(auto move:action.moves) {
        if(move.kind==F && move.from==158) {move.count=min(move.count,left);left-=move.count;}
        if(move.count>0) moves.push_back(move);
    }
    action.moves=moves;return action;
}
void cont_state(const State& s,int us) {
    cerr<<"{\"turn\":"<<s.turn<<",\"evaluation\":"<<evaluation(s,us)<<",\"scores\":["<<points(s,0)<<","<<points(s,1)<<"]";
    cerr<<",\"resources\":["<<s.res[0]<<","<<s.res[1]<<"],\"owners\":[";
    for(int b=0;b<board.nb;++b){if(b)cerr<<",";cerr<<s.owner[b];}
    cerr<<"],\"units\":[";bool comma=false;
    for(int t=0;t<2;++t) for(int k=0;k<3;++k) for(int c=0;c<N;++c) if(s.u[t][k][c]) {
        if(comma)cerr<<",";comma=true;cerr<<"["<<t<<","<<k<<","<<c<<","<<s.u[t][k][c]<<"]";
    }
    cerr<<"]}";
}
void cont_probe(const State& s,int us,const Action& chosen,double elapsed) {
    int continuation=0;double best=-1e100;
    for(const auto& row:audit_rows) if(row.stage=="base" && row.value>best) {best=row.value;continuation=row.index;}
    Action held=cont_pin(s,us,chosen);
    cerr<<setprecision(12)<<"{\"search_ms\":"<<elapsed<<",\"aborted_evaluations\":"<<audit_aborted<<",\"continuation\":"<<continuation<<",\"rollouts\":[";
    bool comma=false;
    for(int opponent=0;opponent<4;++opponent) for(int variant=0;variant<3;++variant) {
        if(comma)cerr<<",";comma=true;
        cerr<<"{\"opponent_script\":"<<opponent<<",\"variant\":"<<variant<<",\"steps\":[";State trial=s;
        for(int depth=0;depth<3;++depth) {
            Action own=depth?policy(trial,us,continuation):(variant?held:chosen),opp=policy(trial,1-us,opponent);
            Action proposed=own;
            if(variant==2 && depth) own=cont_pin(trial,us,own);
            if(depth)cerr<<",";
            cerr<<"{\"own_proposed\":";audit_action(proposed);cerr<<",\"own_applied\":";audit_action(own);
            cerr<<",\"opponent\":";audit_action(opp);
            trial=us==0?advance(trial,own,opp):advance(trial,opp,own);
            cerr<<",\"after\":";cont_state(trial,us);cerr<<"}";
            if(abs(evaluation(trial,us))>=80000) break;
        }
        cerr<<"]}";
    }
    cerr<<"]}\n";
}
'''


def instrument(source):
    source = decision.instrument(source)
    source = decision.change(source, "vector<string> decide(const p::View& v, const p::Init& in) {", PROBE + "\nvector<string> decide(const p::View& v, const p::Init& in) {")
    return decision.change(source, "if(v.turn==121) audit_after_decision(s,us,a,chrono::duration<double,milli>(AClock::now()-start).count());",
                           "if(v.turn==121) cont_probe(s,us,a,chrono::duration<double,milli>(AClock::now()-start).count());")


def commands(action, initial, team):
    out = decision.commands(action, initial)
    for i, (_, pos, count) in enumerate(action["spawn"]):
        base = (pos % 15, pos // 15) == initial.bases[team]
        out[i] = Spawn(out[i].kind, count, None if base else pos % 15, None if base else pos // 15)
    return out


def totals(units):
    return [[sum(n for side,kind,_,n in units if side==t and kind==k) for k in range(3)] for t in range(2)]


def analyze():
    replay = json.load(gzip.open(decision.REPLAY, "rt"))
    initial = to_state(generate(replay["seed"], replay["config"]))
    state = initial
    blocks = [serialize_init(state, "Y")]
    for i in range(decision.TURN):
        blocks.append(serialize_turn(state, "Y", i+1))
        if i < decision.TURN-1:
            frame = replay["turns"][i]
            state, _ = run_turn(state, parse_commands(frame["commands"]["Y"]), parse_commands(frame["commands"]["K"]))
            assert snapshot(state)==frame["state"]
    source = decision.SOURCE.read_text()
    probe = instrument(source)
    with tempfile.TemporaryDirectory(prefix="yk-v3-continuation-", dir="/tmp") as folder:
        path = Path(folder)/"probe.cpp"
        path.write_text(probe)
        binary = path.with_suffix("")
        subprocess.run(["g++","-std=c++20","-O2","-I",str(decision.SOURCE.parent),str(path),"-o",str(binary)], check=True, capture_output=True)
        result = subprocess.run([str(binary)], input="".join(blocks), text=True, capture_output=True, check=True, timeout=60)
        trace = json.loads(result.stderr)
        output = result.stdout.split("END\n")[-2].strip().splitlines()
    verified = 0
    for rollout in trace["rollouts"]:
        official = state
        for depth,step in enumerate(rollout["steps"]):
            if rollout["variant"]==2 and depth:
                proposed,applied=step["own_proposed"],step["own_applied"]
                self_move=lambda m:m[0]==0 and m[1]==decision.CELL
                assert proposed["spawn"]==applied["spawn"] and proposed["priority"]==applied["priority"]
                assert [m for m in proposed["moves"] if not self_move(m)]==[m for m in applied["moves"] if not self_move(m)]
                assert sum(m[3] for m in applied["moves"] if self_move(m))<=max(0,official.get_unit(8,10,"Y","F")-1)
            official, _ = run_turn(official, commands(step["own_applied"],initial,"Y"), commands(step["opponent"],initial,"K"))
            after = step["after"]
            expected_units = sorted([0 if t=="Y" else 1,"FWS".index(k),x+15*y,n] for (x,y,t,k),n in official.units.items() if n)
            assert expected_units==sorted(after["units"])
            assert [official.resources[t] for t in "YK"]==after["resources"]
            assert [{"N":-1,"Y":0,"K":1}[b.owner] for b in official.sorted_buildings()]==after["owners"]
            assert [sum(b.score for b in official.buildings.values() if b.owner==t) for t in "YK"]==after["scores"]
            after["unit_counts"] = totals(after["units"])
            verified += 1
    aggregate = {}
    for variant,name in enumerate(("exit_original","hold_original","hold_pinned_two_turns")):
        values = [r["steps"][-1]["after"]["evaluation"] for r in trace["rollouts"] if r["variant"]==variant]
        aggregate[name] = dict(per_opponent=values,mean=sum(values)/4,worst=min(values),value=.75*sum(values)/4+.25*min(values))
    effects = []
    for opponent in range(4):
        old = next(r for r in trace["rollouts"] if r["opponent_script"]==opponent and r["variant"]==1)
        new = next(r for r in trace["rollouts"] if r["opponent_script"]==opponent and r["variant"]==2)
        steps = []
        for depth,(a,b) in enumerate(zip(old["steps"],new["steps"]),1):
            changes = []
            for i,(oa,ob) in enumerate(zip(a["after"]["owners"],b["after"]["owners"])):
                if oa!=ob:
                    building=initial.sorted_buildings()[i]
                    changes.append(dict(id=building.id,position=[building.x,building.y],type=building.btype,original=oa,pinned=ob))
            def near(action):
                return [m for m in action["moves"] if m[0]==0 and m[1]==decision.CELL]
            steps.append(dict(depth=depth,turn=120+depth,own_moves_from_station_original=near(a["own_applied"]),
                              own_moves_from_station_pinned=near(b["own_applied"]),owners_changed=changes,
                              own_generated_action_equal=a["own_proposed"]==b["own_proposed"],
                              opponent_action_equal=a["opponent"]==b["opponent"],
                              original_score=a["after"]["scores"],pinned_score=b["after"]["scores"],
                              original_counts=a["after"]["unit_counts"],pinned_counts=b["after"]["unit_counts"]))
        effects.append(dict(opponent_script=opponent,steps=steps))
    sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    return dict(schema=1,source_sha256=sha(decision.SOURCE),script_sha256=sha(Path(__file__)),
                reused_audit_script_sha256=sha(Path(decision.__file__)),probe_source_sha256=hashlib.sha256(probe.encode()).hexdigest(),
                input_payload_sha256=hashlib.sha256("".join(blocks).encode()).hexdigest(),
                replay_path=str(decision.REPLAY.relative_to(ROOT)),replay_sha256=sha(decision.REPLAY),
                first_output_equals_recorded=output==replay["turns"][120]["commands"]["Y"],
                verified_initial_transitions=120,verified_simulated_transitions=verified,
                aggregate=aggregate,effects=effects,trace=trace,
                scope="Only an internal three-turn policy-assumption intervention. Four opponent scripts react to each resulting state. Official engine validates transitions, not actual opponent behavior or a whole-game win.")


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    evidence=analyze()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({"output_equal":evidence["first_output_equals_recorded"],"verified_simulated_transitions":evidence["verified_simulated_transitions"],"aggregate":evidence["aggregate"]},ensure_ascii=False))


if __name__=="__main__":
    main()
