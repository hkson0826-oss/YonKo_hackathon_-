import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("v3_repairs", ROOT / "experiments/local_league/v3_repairs.py")
repairs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repairs)
sys.path.insert(0, str(ROOT / "yk-development-tools"))
from engine.commands import Move
from engine.config import load_config
from engine.pipeline import run_turn
from engine.state import Building, new_game
from mapgen import generate, to_state
from runner.protocol import parse_commands
from runner.replay import snapshot


HARNESS = r'''
#undef main
#include <cassert>
void legal(const State& s,int t,const Action& a) {
    int stock[3][N]{},money=s.res[t],tele=0;
    for(int k=0;k<3;++k) copy(s.u[t][k],s.u[t][k]+N,stock[k]);
    for(auto p:a.spawn) {
        int b=board.at[p.pos];assert(p.count>0);
        assert(p.pos==board.base[t] || (b>=0 && board.type[b]==HOSPITAL && s.owner[b]==t));
        assert(p.count*cost(s,t,p.kind)<=money);money-=p.count*cost(s,t,p.kind);stock[p.kind][p.pos]+=p.count;
    }
    for(auto m:a.moves) {
        assert(m.count>0 && stock[m.kind][m.from]>=m.count);stock[m.kind][m.from]-=m.count;
        if(m.tele) {
            assert(++tele<=1 && m.count<=5);int x=board.at[m.from],y=board.at[m.to];
            assert(x>=0 && y>=0 && x!=y && board.type[x]==STATION && board.type[y]==STATION && s.owner[x]==t && s.owner[y]==t);
        } else assert(board.dist[m.from][m.to]==1);
    }
}
int main(int argc,char**argv) {
    p::Init in;in.width=in.height=15;in.terrain.assign(15,string(15,'.'));in.bases={pair{0,7},pair{14,7}};
    in.buildings={{0,7,7,"ENG"},{1,5,7,"HALL"},{2,10,10,"HOSPITAL"},{3,3,3,"STATION"},{4,11,11,"STATION"}};
    board.init(in);State s;fill(s.owner,s.owner+BMAX,-1);for(int b=0;b<board.nb;++b)s.score[b]=2;
    string mode=argc>1?argv[1]:"random";
    if(mode=="mission" || mode=="understrength" || mode=="arrival") {
        s.turn=100;s.u[0][F][111]=1;s.u[0][W][111]=4;s.u[1][W][113]=3;s.u[1][F][127]=1;
        Action a,out;a.moves={{F,111,110,1},{W,111,110,4}};
        if(mode=="understrength") {s.u[0][W][111]=3;a.moves[1].count=3;}
        if(mode=="arrival") {s.u[0][W][111]=0;s.u[0][W][110]=4;a.moves[1]={W,110,111,4};}
        bool found=f3_mission(s,0,a,0,out);
        if(mode!="mission") {assert(!found);return 0;}
        assert(found);legal(s,0,out);
        for(auto m:out.moves) cout<<m.kind<<" "<<m.from<<" "<<m.to<<" "<<m.count<<"\n";
    } else if(mode=="matching") {
        board.nb=2;board.pos[0]=111;board.pos[1]=113;board.type[0]=board.type[1]=WATCH;
        s.u[0][F][112]=1;s.turn=50;
        double one=f3_access(s,0,true),many=f3_access(s,0,false);
        assert(abs(2*one-many)<1e-8);
        s.u[0][F][112]=2;assert(abs(f3_access(s,0,true)-many)<1e-8);
        s.u[0][F][112]=0;assert(f3_access(s,0,true)==0);
    } else if(mode=="terminal") {
        s.turn=160;s.owner[0]=0;s.owner[1]=1;s.u[0][F][board.base[0]]=1;
        assert(evaluation(s,0)==f3_base_evaluation(s,0));assert(evaluation(s,1)==f3_base_evaluation(s,1));
        s.occupation[1]=100;assert(evaluation(s,0)==f3_base_evaluation(s,0));
        s.owner[2]=1;assert(evaluation(s,0)==f3_base_evaluation(s,0));
    } else if(mode=="flow") {
        s.turn=50;double before=f3_supply(s,0);s.owner[2]=0;
        assert(f3_supply(s,0)>before);s.turn=160;assert(f3_supply(s,0)==0);
    } else {
        mt19937 random(73387321);
        for(int rep=0;rep<60;++rep) {
            State r;r.turn=random()%160;r.res[0]=random()%41;r.res[1]=random()%41;
            for(int b=0;b<board.nb;++b) {r.owner[b]=int(random()%3)-1;r.score[b]=1+random()%4;}
            for(int t=0;t<2;++t) for(int i=0;i<12;++i) {
                r.u[t][F][random()%N]+=random()%2;r.u[t][W][random()%N]+=1+random()%16;
            }
            for(int t=0;t<2;++t) {
                assert(isfinite(evaluation(r,t)));
                for(int j=0;j<4;++j) {
                    Action base=a_clean(r,t,policy(r,t,j));legal(r,t,base);
                    for(int b=0;b<board.nb;++b) {Action out;if(f3_mission(r,t,base,b,out))legal(r,t,out);}
                }
            }
        }
    }
}
'''


class V3RepairTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / "submissions/iterative-v3/main.cpp").read_text()
        cls.candidates = repairs.variants(cls.source)
        cls.temp = tempfile.TemporaryDirectory(prefix="yk-v3-repairs-", dir="/tmp")
        cls.addClassCleanup(cls.temp.cleanup)
        cls.binaries = {}
        for candidate in cls.candidates:
            source = Path(cls.temp.name) / (candidate["id"] + ".cpp")
            source.write_text("#define main original_bot_main\n" + candidate["source"] + HARNESS)
            binary = source.with_suffix("")
            subprocess.run(["g++", "-std=c++20", "-O1", "-I", str(ROOT / "submissions/iterative-v3"), str(source), "-o", str(binary)],
                           capture_output=True, check=True)
            cls.binaries[candidate["id"]] = binary

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def run_case(self, name, mode):
        return subprocess.run([str(self.binaries[name]), mode], capture_output=True, text=True, check=True).stdout

    def test_unique_candidates_preserve_transition_opponents_and_global_deadline(self):
        self.assertEqual(len(self.candidates), 6)
        self.assertEqual(len({x["source"] for x in self.candidates}), 6)
        transition = self.source[self.source.index("State advance("):self.source.index("double building_value(")]
        policies = self.source[self.source.index("Action assignment_policy("):self.source.index("double evaluation(")]
        for candidate in self.candidates:
            self.assertIn(transition, candidate["source"])
            self.assertIn(policies, candidate["source"])
            self.assertIn("opp=policy(trial,1-us,j)", candidate["source"])
            self.assertIn("double limit=135.0", candidate["source"])
            self.assertNotEqual(candidate["source"], self.source)
        with self.assertRaises(ValueError):
            repairs.variants(self.source.replace("int forced_policy = -1;", ""))

    def test_hungarian_does_not_reuse_a_flag_for_several_targets(self):
        self.run_case("f3_matching", "matching")

    def test_reachable_supply_rewards_a_useful_hospital_and_expires(self):
        self.run_case("f3_supply_flow", "flow")

    def test_all_candidates_keep_terminal_tiebreaks_and_legal_actions(self):
        for item in self.candidates:
            self.run_case(item["id"], "terminal")
            self.run_case(item["id"], "random")

    def test_economic_mission_cannot_reuse_arrivals_or_ignore_enemy_flags(self):
        self.run_case("f3_econ_mission", "arrival")
        self.run_case("f3_econ_mission", "understrength")
        commands = []
        for line in self.run_case("f3_econ_mission", "mission").splitlines():
            kind, src, dest, count = map(int, line.split())
            commands.append(Move(src % 15, src // 15, "FWS"[kind], count, {1:"R",-1:"L",15:"D",-15:"U"}[dest-src]))
        state = new_game(load_config(), buildings=[Building(0, 7, 7, "ENG", 2)], resources={"Y":0,"K":0})
        for team,kind,x,y,n in (("Y","F",6,7,1),("Y","W",6,7,4),("K","W",8,7,3),("K","F",7,8,1)):
            state.add_unit(x,y,team,kind,n)
        after, _ = run_turn(state, commands, [Move(8,7,"W",3,"L"),Move(7,8,"F",1,"U")])
        self.assertEqual(after.buildings[0].owner, "Y")
        self.assertEqual(after.get_unit(7,7,"Y","W"), 1)

    def test_7311_adjacent_hospital_counterfactual_in_official_engine(self):
        path = ROOT / "records/league/loop2-iteration2/runs/holdout/replays/f8ffbf0bac6d3b96a7752aa0.json.gz"
        with gzip.open(path, "rt") as stream:
            replay = json.load(stream)
        state = to_state(generate(replay["seed"], replay["config"]))
        frame = replay["turns"][0]
        actual, _ = run_turn(state, parse_commands(frame["commands"]["Y"]), parse_commands(frame["commands"]["K"]))
        self.assertEqual(snapshot(actual), frame["state"])
        alternate = list(frame["commands"]["K"])
        alternate[alternate.index("MOVE 11 4 F 1 D")] = "MOVE 11 4 F 1 L"
        trial, _ = run_turn(state, parse_commands(frame["commands"]["Y"]), parse_commands(alternate))
        self.assertEqual(actual.buildings[8].owner, "N")
        self.assertEqual(trial.buildings[8].owner, "K")
        self.assertEqual(trial.resources["K"], actual.resources["K"]-2)

    def test_forensic_manifest_snapshots_economy_and_fixed_opponent_counterfactuals(self):
        from experiments import analyze_gain_cases as audit
        evidence = json.loads((ROOT / "records/league/loop3-design/v3-forensics-evidence.json").read_text())
        self.assertEqual(hashlib.sha256(self.source.encode()).hexdigest(), evidence["base_source_sha256"])
        original = audit.REPLAYS
        replays = {}
        verified = 0
        try:
            for case in evidence["cases"]:
                audit.REPLAYS = (ROOT / case["path"]).parent
                checked, replay, _ = audit.check_case(case["map_seed"], case["candidate"], case["job_id"], case["sha256"])
                self.assertEqual(checked["economy"], case["economy"])
                self.assertEqual(checked["result"], case["result"])
                verified += checked["verified_frames"]
                replays[case["map_seed"], case["candidate"]] = replay
        finally:
            audit.REPLAYS = original
        self.assertEqual(verified, evidence["verified_frames"])
        for case in evidence["counterfactuals"]:
            replay = replays[case["map_seed"], "a_v2_terminal_local"]
            state = to_state(generate(replay["seed"], replay["config"]))
            for frame in replay["turns"][:case["turn"]-1]:
                state, _ = run_turn(state, parse_commands(frame["commands"]["Y"]), parse_commands(frame["commands"]["K"]))
            frame = replay["turns"][case["turn"]-1]
            commands = {t: list(frame["commands"][t]) for t in "YK"}
            i = commands[case["team"]].index(case["replaced"])
            if case["replacement"] is None:
                commands[case["team"]].pop(i)
            else:
                commands[case["team"]][i] = case["replacement"]
            trial, _ = run_turn(state, parse_commands(commands["Y"]), parse_commands(commands["K"]))
            self.assertEqual(trial.buildings[case["target_id"]].owner, case["alternate_owner"])
            self.assertEqual(audit.scores(trial), case["alternate_score"])
            self.assertEqual(trial.resources, case["alternate_resources"])


if __name__ == "__main__":
    unittest.main()
