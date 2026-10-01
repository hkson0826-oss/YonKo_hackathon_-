"""Compare v3 and the two matching variants on the fixed 8100 opening."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile

import audit_v3_decision as decision
from engine.pipeline import run_turn
from mapgen import generate, to_state
from runner.protocol import parse_commands, serialize_init, serialize_turn
from runner.replay import snapshot

ROOT = decision.ROOT
GENERATOR = ROOT / "experiments/local_league/v3_repairs.py"
PROBE = r'''
void early_probe(const State& s,int us,const Action& chosen,double elapsed) {
    cerr<<setprecision(12)<<"{\"ms\":"<<elapsed<<",\"aborted\":"<<audit_aborted<<",\"chosen\":";
    audit_action(chosen);cerr<<",\"trace\":[";
    for(int i=0;i<int(audit_rows.size());++i) {
        auto row=audit_rows[i];if(i)cerr<<",";
        cerr<<"{\"stage\":"<<quoted(row.stage)<<",\"index\":"<<row.index<<",\"source\":"<<row.source<<",\"value\":"<<row.value<<",\"action\":";
        audit_action(row.action);cerr<<"}";
    }
    cerr<<"],\"initial_plans\":[";
    for(int i=0;i<4;++i) {
        if(i)cerr<<",";Action first=a_clean(s,us,policy(s,us,i));
        cerr<<"{\"script\":"<<i<<",\"action\":";audit_action(first);cerr<<",\"rollouts\":[";
        for(int j=0;j<4;++j) {
            State trial=s;
            for(int depth=0;depth<3;++depth) {
                Action own=depth?policy(trial,us,i):first,opp=policy(trial,1-us,j);
                trial=advance(trial,own,opp);if(abs(evaluation(trial,us))>=80000)break;
            }
            if(j)cerr<<",";
            cerr<<"{\"opponent\":"<<j<<",\"raw\":"<<RAW(trial,us)<<",\"modified\":"<<evaluation(trial,us)<<",\"units\":[";
            for(int t=0;t<2;++t) {
                if(t)cerr<<",";cerr<<"["<<accumulate(trial.u[t][F],trial.u[t][F]+N,0)<<","<<accumulate(trial.u[t][W],trial.u[t][W]+N,0)<<"]";
            }
            cerr<<"]}";
        }
        cerr<<"]}";
    }
    cerr<<"]}\n";
}
'''


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def analyze(arena, manifest_path):
    manifest = json.loads(manifest_path.read_text())
    case = next(c for c in manifest["cases"] if c["candidate"] == "f3_matching_mission" and c["seed"] == 8100 and c["team"] == "Y")
    paths = {name:arena / case[name+"_replay"] for name in ("candidate","baseline")}
    replays = {}
    for name,path in paths.items():
        expected = manifest.get("replay_sha256",{}).get(case[name+"_replay"])
        if expected and sha(path) != expected:
            raise ValueError(f"Preview/final replay hash differs: {path}")
        replays[name] = json.load(gzip.open(path,"rt"))
    replay = replays["candidate"]
    state = to_state(generate(8100,replay["config"]))
    payload = serialize_init(state,"Y")
    for i in range(3):
        payload += serialize_turn(state,"Y",i+1)
        if i<2:
            frame=replay["turns"][i]
            state,_=run_turn(state,parse_commands(frame["commands"]["Y"]),parse_commands(frame["commands"]["K"]))
            assert snapshot(state)==frame["state"]==replays["baseline"]["turns"][i]["state"]
    spec=importlib.util.spec_from_file_location("f3_opening_repairs",GENERATOR)
    repairs=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(repairs)
    source=decision.SOURCE.read_text()
    variants={c["id"]:c["source"] for c in repairs.variants(source)}
    pool={"v3":source,"f3_matching":variants["f3_matching"],"f3_matching_mission":variants["f3_matching_mission"]}
    results={}
    with tempfile.TemporaryDirectory(dir="/tmp",prefix="yk-f3-opening-") as folder:
        for name,src in pool.items():
            traced=decision.instrument(src).replace("if(v.turn<121)","if(v.turn<3)")
            traced=traced.replace("if(v.turn==121) audit_after_decision(s,us,a,","if(v.turn==3) early_probe(s,us,a,")
            probe=PROBE.replace("RAW(","evaluation(" if name=="v3" else "f3_base_evaluation(")
            anchor="vector<string> decide(const p::View& v, const p::Init& in) {"
            traced=decision.change(traced,anchor,probe+"\n"+anchor)
            path=Path(folder)/(name+".cpp")
            path.write_text(traced)
            binary=path.with_suffix("")
            subprocess.run(["g++","-std=c++20","-O2","-I",str(decision.SOURCE.parent),str(path),"-o",str(binary)],check=True,capture_output=True)
            process=subprocess.run([str(binary)],input=payload,text=True,capture_output=True,check=True,timeout=30)
            report=json.loads(process.stderr)
            report.update(output=process.stdout.split("END\n")[-2].strip().splitlines(),source_sha256=hashlib.sha256(src.encode()).hexdigest(),instrumented_source_sha256=hashlib.sha256(traced.encode()).hexdigest())
            for plan in report["initial_plans"]:
                for key in ("raw","modified"):
                    values=[v[key] for v in plan["rollouts"]]
                    plan[key+"_aggregate"] = .75*sum(values)/4+.25*min(values)
            results[name]=report
    return dict(schema=1,scope="Fixed 8100/Y turn 3 legal-observation decision audit; no new match or completed-batch ranking.",
                script_sha256=sha(Path(__file__)),generator_sha256=sha(GENERATOR),reused_audit_script_sha256=sha(Path(decision.__file__)),
                case_manifest_path=str(manifest_path),case_manifest_sha256=sha(manifest_path),
                replay_paths={k:str(v) for k,v in paths.items()},replay_sha256={k:sha(v) for k,v in paths.items()},
                observation_input_sha256=hashlib.sha256(payload.encode()).hexdigest(),legal_observation=payload,versions=results,
                matching_equals_matching_mission=results["f3_matching"]["output"]==results["f3_matching_mission"]["output"],
                v3_matches_recorded=results["v3"]["output"]==replays["baseline"]["turns"][2]["commands"]["Y"],
                matching_mission_matches_recorded=results["f3_matching_mission"]["output"]==replay["turns"][2]["commands"]["Y"],
                same_script_actions_across_versions=all(results["v3"]["initial_plans"][i]["action"]==results["f3_matching"]["initial_plans"][i]["action"]==results["f3_matching_mission"]["initial_plans"][i]["action"] for i in range(4)))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arena",type=Path,default=ROOT/"records/league/loop3-iteration1/runs/development")
    parser.add_argument("--case-manifest",type=Path,default=ROOT/"records/league/loop3-checkpoints/iteration1/case-preview.json")
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    evidence=analyze(args.arena,args.case_manifest)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({k:v for k,v in evidence.items() if isinstance(v,bool)}))
    for name,version in evidence["versions"].items():
        print(name,version["ms"],version["aborted"],[(p["script"],p["raw_aggregate"],p["modified_aggregate"]) for p in version["initial_plans"]])


if __name__=="__main__":
    main()
