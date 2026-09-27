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
from runner.protocol import parse_commands, serialize_init, serialize_turn
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


REVISION_MAIN = r'''
int main(int argc,char**argv) {
    if(argc>1 && string(argv[1])=="protocol") return original_bot_main(1,argv);
    p::Init in;in.width=in.height=15;in.terrain.assign(15,string(15,'.'));in.bases={pair{0,7},pair{14,7}};
    in.buildings={{0,7,7,"ENG"},{1,6,7,"HALL"},{2,10,10,"HOSPITAL"},{3,3,3,"STATION"},{4,11,11,"STATION"}};
    board.init(in);State s;fill(s.owner,s.owner+BMAX,-1);for(int b=0;b<board.nb;++b)s.score[b]=2;s.turn=50;
    string mode=argc>1?argv[1]:"random";
    if(mode=="safe_mission") {
        s.owner[1]=0;s.u[0][F][111]=1;s.u[0][F][127]=1;s.u[0][W][111]=3;s.u[1][W][113]=3;s.u[1][W][110]=1;
        Action a,out;a.moves={{F,127,142,1}};
        assert(f3_mission(s,0,a,0,out));legal(s,0,out);
        assert(!f3_v2_safe_mission(s,0,a,0,out));
        s.u[1][W][110]=0;assert(f3_v2_safe_mission(s,0,a,0,out));legal(s,0,out);
    } else if(mode=="reserve") {
        s.owner[0]=0;s.u[0][W][112]=20;s.u[1][W][113]=9;s.u[1][F][113]=1;
        Action a,out;a.moves={{W,112,97,20}};
        assert(f3_v2_warrior_reserve(s,0,a,0,out));legal(s,0,out);
        int moving=0;for(auto m:out.moves)if(m.kind==W&&m.from==112)moving+=m.count;
        assert(moving==10);
        for(auto m:out.moves)cout<<m.kind<<" "<<m.from<<" "<<m.to<<" "<<m.count<<"\n";
        s.u[1][F][113]=0;assert(!f3_v2_warrior_reserve(s,0,a,0,out));
        s.u[1][F][113]=1;s.u[0][W][112]=8;a.moves[0].count=8;
        assert(!f3_v2_warrior_reserve(s,0,a,0,out));
        s.u[0][W][112]=0;s.u[0][W][97]=20;s.u[1][W][113]=30;a.moves={{W,97,112,20}};
        assert(!f3_v2_warrior_reserve(s,0,a,0,out));
    } else if(mode=="production") {
        for(int turn:{20,70,130,159}) for(int us=0;us<2;++us) {
            State r;r.turn=turn;r.res[0]=r.res[1]=20;fill(r.owner,r.owner+BMAX,-1);
            for(int b=0;b<board.nb;++b)r.score[b]=2;
            r.owner[0]=0;r.owner[1]=1;
            for(int t=0;t<2;++t) {r.u[t][F][board.base[t]]=2;r.u[t][W][board.base[t]]=8;r.u[t][F][97+t*30]=1;r.u[t][W][97+t*30]=4;}
            f3_v2_local_phase=false;
            assert(evaluation(r,us)==f3_base_evaluation(r,us));
            Action old=original_plan_decide(r,us,AClock::now(),100000);
            Action revised=a_decide(r,us,AClock::now(),100000);legal(r,us,revised);
            assert(old.spawn.size()==revised.spawn.size());
            for(int i=0;i<int(old.spawn.size());++i) {
                auto a=old.spawn[i],b=revised.spawn[i];assert(a.kind==b.kind&&a.pos==b.pos&&a.count==b.count);
            }
        }
    } else {
        mt19937 random(81008103);
        for(int rep=0;rep<45;++rep) {
            State r;r.turn=random()%160;r.res[0]=random()%41;r.res[1]=random()%41;
            for(int b=0;b<board.nb;++b){r.owner[b]=int(random()%3)-1;r.score[b]=1+random()%4;}
            for(int t=0;t<2;++t)for(int i=0;i<12;++i){r.u[t][F][random()%N]+=random()%2;r.u[t][W][random()%N]+=1+random()%14;}
            for(int t=0;t<2;++t)for(int j=0;j<4;++j) {
                Action a=a_clean(r,t,policy(r,t,j));
                for(int b=0;b<board.nb;++b){Action out;if(f3_v2_safe_mission(r,t,a,b,out))legal(r,t,out);if(f3_v2_warrior_reserve(r,t,a,b,out))legal(r,t,out);}
            }
        }
    }
}
'''


class V3RevisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source=(ROOT/"submissions/iterative-v3/main.cpp").read_text()
        cls.candidates=repairs.variants_iteration2(cls.source)
        cls.temp=tempfile.TemporaryDirectory(prefix="yk-v3-revision-",dir="/tmp")
        cls.addClassCleanup(cls.temp.cleanup)
        cls.binaries={}
        old=cls.source[cls.source.index("Action a_decide("):cls.source.index("vector<string> decide(")]
        old=old.replace("Action a_decide(","Action original_plan_decide(",1)
        harness=HARNESS[:HARNESS.index("int main(int argc")]+old+REVISION_MAIN
        for candidate in cls.candidates:
            path=Path(cls.temp.name)/(candidate["id"]+".cpp")
            path.write_text("#define main original_bot_main\n"+candidate["source"]+harness)
            binary=path.with_suffix("")
            subprocess.run(["g++","-std=c++20","-O1","-I",str(ROOT/"submissions/iterative-v3"),str(path),"-o",str(binary)],capture_output=True,check=True)
            cls.binaries[candidate["id"]]=binary

    def run_case(self,name,mode):
        return subprocess.run([str(self.binaries[name]),mode],capture_output=True,text=True,check=True).stdout

    def test_previous_six_sources_unchanged_and_four_new_unique(self):
        evidence=json.loads((ROOT/"records/league/loop3-design/v3-forensics-evidence.json").read_text())
        expected={c["id"]:c["source_sha256"] for c in evidence["candidate_manifest"]}
        for c in repairs.variants(self.source):
            self.assertEqual(hashlib.sha256(c["source"].encode()).hexdigest(),expected[c["id"]])
        self.assertEqual(len(self.candidates),4)
        self.assertEqual(len({c["source"] for c in self.candidates}),4)
        for c in self.candidates:
            self.assertNotIn(c["id"],expected)
            self.assertIn("double limit=135.0",c["source"])
            self.assertIn("opp=policy(trial,1-us,j)",c["source"])
        movement=next(c["source"] for c in self.candidates if c["id"]=="f3_v2_movement_matching")
        self.assertIn("incumbent.value=local_value;",movement)
        self.assertIn("limit,local_value)) goto finished;",movement)

    def test_movement_matching_preserves_raw_policy_production_on_both_sides(self):
        self.run_case("f3_v2_movement_matching","production")

    def test_safe_mission_rejects_new_exposure_but_allows_safe_escort(self):
        self.run_case("f3_v2_safe_econ_mission","safe_mission")

    def test_warrior_reserve_kills_incoming_flag_without_inventing_units(self):
        output=self.run_case("f3_v2_warrior_reserve","reserve")
        commands=[]
        for line in output.splitlines():
            kind,src,dest,n=map(int,line.split())
            commands.append(Move(src%15,src//15,"FWS"[kind],n,{1:"R",-1:"L",15:"D",-15:"U"}[dest-src]))
        state=new_game(load_config(),buildings=[Building(0,7,7,"ENG",2,"Y",2)],resources={"Y":0,"K":0})
        state.add_unit(7,7,"Y","W",20);state.add_unit(8,7,"K","W",9);state.add_unit(8,7,"K","F",1)
        after,_=run_turn(state,commands,[Move(8,7,"W",9,"L"),Move(8,7,"F",1,"L")])
        self.assertEqual(after.buildings[0].owner,"Y")
        self.assertEqual(after.get_unit(7,7,"Y","W"),1)
        self.assertEqual(after.get_unit(7,7,"K","F"),0)

    def test_revision_guards_legal_on_random_states(self):
        for c in self.candidates:
            self.run_case(c["id"],"random")

    def observed_opening(self,name,job):
        path=ROOT/"records/league/loop3-iteration1/runs/development/replays"/(job+".json.gz")
        replay=json.load(gzip.open(path,"rt"))
        state=to_state(generate(replay["seed"],replay["config"]))
        payload=serialize_init(state,"Y")
        for i in range(3):
            payload+=serialize_turn(state,"Y",i+1)
            if i<2:
                frame=replay["turns"][i]
                state,_=run_turn(state,parse_commands(frame["commands"]["Y"]),parse_commands(frame["commands"]["K"]))
                self.assertEqual(snapshot(state),frame["state"])
        output=subprocess.run([str(self.binaries[name]),"protocol"],input=payload,text=True,capture_output=True,check=True,timeout=30).stdout
        return output.split("END\n")[-2].strip().splitlines(),replay

    def test_8100_opening_production_bias_repaired_by_both_evaluation_variants(self):
        for name in ("f3_v2_soft_matching","f3_v2_movement_matching"):
            output,_=self.observed_opening(name,"dc4c8be77789f922f7c6dbbe")
            spawns=[line.split() for line in output if line.startswith("SPAWN ")]
            self.assertEqual(sum(int(p[2]) for p in spawns if p[1]=="F"),0)
            self.assertEqual(sum(int(p[2]) for p in spawns if p[1]=="W"),4)

    def test_8101_successful_flag_step_retained_with_movement_only_matching(self):
        output,replay=self.observed_opening("f3_v2_movement_matching","d968dcf49e4c49e323aa072e")
        self.assertIn("MOVE 2 6 F 1 L",output)
        self.assertIn("MOVE 2 6 F 1 L",replay["turns"][2]["commands"]["Y"])


if __name__ == "__main__":
    unittest.main()
