import importlib.util
import gzip
import json
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("causal_repairs", ROOT / "experiments/local_league/causal_repairs.py")
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
    int stock[3][N]{},resource=s.res[t];
    for(int k=0;k<3;++k)copy(s.u[t][k],s.u[t][k]+N,stock[k]);
    for(auto x:a.spawn) {
        assert(x.count>0);int b=board.at[x.pos];
        assert(x.pos==board.base[t] || (b>=0&&board.type[b]==HOSPITAL&&s.owner[b]==t));
        assert(x.count*cost(s,t,x.kind)<=resource);
        resource-=x.count*cost(s,t,x.kind);stock[x.kind][x.pos]+=x.count;
    }
    int tele=0;
    for(auto x:a.moves) {
        assert(x.count>0&&stock[x.kind][x.from]>=x.count);
        stock[x.kind][x.from]-=x.count;
        if(x.tele) {
            assert(++tele<=1&&x.count<=5);
            int p=board.at[x.from],q=board.at[x.to];
            assert(p>=0&&q>=0&&p!=q&&board.type[p]==STATION&&board.type[q]==STATION);
            assert(s.owner[p]==t&&s.owner[q]==t);
        } else assert(board.dist[x.from][x.to]==1);
    }
}
int main(int argc,char**argv) {
    p::Init in;in.width=in.height=15;in.terrain.assign(15,string(15,'.'));
    in.bases={pair{0,7},pair{14,7}};
    in.buildings={{0,7,7,"WATCH"},{1,5,7,"ENG"},{2,10,10,"HOSPITAL"},
                  {3,3,3,"STATION"},{4,11,11,"STATION"}};
    board.init(in);
    State s;s.turn=159;fill(s.owner,s.owner+BMAX,-1);
    for(int b=0;b<board.nb;++b)s.score[b]=b?1:4;
    string mode=argc>1?argv[1]:"random";
    if(mode=="contest"||mode=="arrival") {
        s.owner[0]=0;s.u[0][W][112]=3;s.u[0][F][111]=1;
        s.u[1][W][113]=3;s.u[1][F][127]=1;
        Action a;a.moves={{W,112,127,3}};
        if(mode=="arrival") {
            s.u[0][W][112]=0;s.u[0][W][110]=3;a.moves={{W,110,111,3}};
        }
        a=causal_guard(s,0,a,1,1,0,0);legal(s,0,a);
        for(auto x:a.moves)cout<<x.kind<<" "<<x.from<<" "<<x.to<<" "<<x.count<<"\n";
    } else if(mode=="denial") {
        board.nb=1;s.owner[0]=1;s.u[0][F][111]=1;
        Action a=causal_policy(s,0,0);legal(s,0,a);
        bool arrived=false;for(auto x:a.moves)arrived|=x.kind==F&&x.to==112;
        assert(arrived);
        State after=advance(s,a,{});assert(after.owner[0]==-1&&after.turn==160);
    } else {
        mt19937 random(89271);
        for(int rep=0;rep<180;++rep) {
            State r;r.turn=random()%160;r.res[0]=random()%41;r.res[1]=random()%41;
            for(int b=0;b<board.nb;++b){r.owner[b]=int(random()%3)-1;r.score[b]=1+random()%4;}
            for(int k=0;k<3;++k)for(int t=0;t<2;++t)for(int i=0;i<14;++i)
                r.u[t][k][random()%N]+=1+random()%15;
            for(int t=0;t<2;++t)for(int style=0;style<4;++style) {
                legal(r,t,causal_policy(r,t,style));legal(r,t,policy(r,t,style));
            }
        }
    }
}
'''


class CausalRepairTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / "submissions/tuned/main.cpp").read_text()
        cls.candidates = repairs.variants(cls.source)
        cls.temp = tempfile.TemporaryDirectory(prefix="yk-causal-test-", dir="/tmp")
        cls.folder = Path(cls.temp.name)
        cls.binaries = {}
        for item in cls.candidates:
            path = cls.folder / (item["id"] + ".cpp")
            path.write_text("#define main original_bot_main\n" + item["source"] + HARNESS)
            binary = path.with_suffix("")
            subprocess.run(["g++", "-std=c++20", "-O1", "-I", str(ROOT / "submissions/tuned"),
                            str(path), "-o", str(binary)], check=True, capture_output=True)
            cls.binaries[item["id"]] = binary

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def run_case(self, name, case):
        return subprocess.run([str(self.binaries[name]), case], check=True, capture_output=True, text=True).stdout

    def test_eight_distinct_interventions_preserve_opponent_policy_and_transition(self):
        self.assertEqual(len(self.candidates), 8)
        self.assertEqual(len({x["source"] for x in self.candidates}), 8)
        original_policy = self.source[self.source.index("Action policy("):self.source.index("double evaluation(")]
        transition = self.source[self.source.index("State advance("):self.source.index("double building_value(")]
        for item in self.candidates:
            self.assertIn(original_policy, item["source"])
            self.assertIn(transition, item["source"])
            self.assertIn("opp=policy(trial,1-us,j)", item["source"])
            self.assertIn("candidates[i]=causal_policy(s,us,i)", item["source"])
        with self.assertRaises(ValueError):
            repairs.variants(self.source.replace("candidates[i]=policy(s,us,i);", ""))

    def test_all_variants_legal_for_random_state_and_both_sides(self):
        for item in self.candidates:
            self.run_case(item["id"], "random")

    def test_last_turn_denial_is_not_rejected_as_incomplete_capture(self):
        for name in ("q_deadline", "q_coordinated"):
            self.run_case(name, "denial")

    def test_guard_pair_preserves_ownership_in_official_engine(self):
        commands = []
        for line in self.run_case("q_guard_own", "contest").splitlines():
            kind, origin, dest, count = map(int, line.split())
            commands.append(Move(origin % 15, origin // 15, "FWS"[kind], count,
                                 {1: "R", -1: "L", 15: "D", -15: "U"}[dest-origin]))
        state = new_game(load_config(), buildings=[Building(0, 7, 7, "WATCH", 4, "Y", 2)],
                         resources={"Y": 0, "K": 0})
        for team, kind, x, y, count in (("Y", "W", 7, 7, 3), ("Y", "F", 6, 7, 1),
                                        ("K", "W", 8, 7, 3), ("K", "F", 7, 8, 1)):
            state.add_unit(x, y, team, kind, count)
        after, _ = run_turn(state, commands, [Move(8, 7, "W", 3, "L"), Move(7, 8, "F", 1, "U")])
        self.assertEqual(after.buildings[0].owner, "Y")
        self.assertEqual(after.get_unit(7, 7, "Y", "F"), 1)
        self.assertEqual(after.get_unit(7, 7, "K", "F"), 1)

    def test_incoming_warriors_cannot_be_reused_as_origin_stock(self):
        self.assertEqual(self.run_case("q_guard_own", "arrival").strip(), "1 110 111 3")

    def test_recorded_v2_loss_has_exact_one_turn_flag_defense_counterfactual(self):
        path = ROOT / "records/league/campaign-001/runs/holdout/replays/3b795a184589921f9c21d623.json.gz"
        with gzip.open(path, "rt") as stream:
            replay = json.load(stream)
        state = to_state(generate(replay["seed"], replay["config"]))
        for frame in replay["turns"][:155]:
            state, _ = run_turn(state, parse_commands(frame["commands"]["Y"]),
                                parse_commands(frame["commands"]["K"]))
            self.assertEqual(snapshot(state), frame["state"])
        frame = replay["turns"][155]
        commands = parse_commands(frame["commands"]["Y"])
        changed = [Move(5, 11, "F", 1, "D") if isinstance(c, Move) and
                   (c.x, c.y, c.kind, c.count, c.direction) == (5, 11, "F", 1, "U") else c
                   for c in commands]
        self.assertEqual(sum(a != b for a, b in zip(commands, changed)), 1)
        actual, _ = run_turn(state, commands, parse_commands(frame["commands"]["K"]))
        alternative, _ = run_turn(state, changed, parse_commands(frame["commands"]["K"]))
        self.assertEqual(snapshot(actual), frame["state"])
        self.assertEqual(actual.buildings[11].owner, "N")
        self.assertEqual(alternative.buildings[11].owner, "Y")
        self.assertIn(11, state.revealed["Y"])


class CausalRepairIteration2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / "submissions/tuned/main.cpp").read_text()
        cls.candidates = repairs.variants_iteration2(cls.source)
        cls.temp = tempfile.TemporaryDirectory(prefix="yk-causal-iteration2-test-", dir="/tmp")
        cls.folder = Path(cls.temp.name)
        cls.binaries = {}
        tactical = r'''
    } else if(mode=="tactical") {
        board.nb=1;s.owner[0]=0;s.u[0][F][112]=1;s.u[1][F][113]=1;
        Action original;original.moves={{F,112,111,1}};
        Action opponent;opponent.moves={{F,113,112,1}};
        auto result=causal_tactical_with_predictions(s,0,original,{opponent,opponent,opponent,opponent});
        legal(s,0,result);State held=advance(s,result,opponent),lost=advance(s,original,opponent);
        assert(held.owner[0]==0&&lost.owner[0]==-1);
        causal_iteration2_deadline=chrono::steady_clock::now()-chrono::milliseconds(1);
        auto expired=causal_tactical_with_predictions(s,0,original,{opponent});
        assert(expired.moves.size()==original.moves.size()&&expired.moves[0].to==111);
        causal_iteration2_deadline=chrono::steady_clock::time_point::max();
'''
        for item in cls.candidates:
            harness = HARNESS
            if item["parameters"].get("tactical"):
                harness = harness.replace("    } else {\n        mt19937", tactical + "    } else {\n        mt19937")
                harness = harness.replace("legal(r,t,causal_policy(r,t,style));",
                                          "legal(r,t,causal_tactical(r,t,causal_policy(r,t,style)));")
            path = cls.folder / (item["id"] + ".cpp")
            path.write_text("#define main original_bot_main\n" + item["source"] + harness)
            binary = path.with_suffix("")
            subprocess.run(["g++", "-std=c++20", "-O2", "-I", str(ROOT / "submissions/tuned"),
                            str(path), "-o", str(binary)], check=True, capture_output=True)
            cls.binaries[item["id"]] = binary

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_old_eight_candidate_bytes_remain_frozen(self):
        expected = {
            "q_guard_own": "15d2b79bcf1ab9e6963c08368d3e26806da82dc0365c6fb685727bbabe1548f7",
            "q_escort_own": "f27fe1d0158fc701e6b034ecacc8a2e9f0e50c11153225d61a7c88a191a4ef75",
            "q_capacity": "b6b007aa5b8cf5605e363e0cbf4a955554e04304ea46a3f704e8d4211835ee2c",
            "q_threat_window": "c943b16a28d19768705925b2d6aa9dc04547af342ca77747d96afdad96985d79",
            "q_rendezvous": "cf4a119a50621d395b6be4eb472a0968accc733fc6216f75be2b86fded31b2e5",
            "q_deadline": "14978aa2df0386dd25cbc8011ced8d47fce2712a8500fc1d69a962299aa9d160",
            "q_balanced_front": "4f0c85395b5ebdcc3581e31f3d855343b1a2c5a7de5cb2606f3676285405fc12",
            "q_coordinated": "392ef885d85128d86c28cbb6a766e8363828d233b6384f52a27ecf507e7240e2",
        }
        actual = {x["id"]: hashlib.sha256(x["source"].encode()).hexdigest() for x in repairs.variants(self.source)}
        self.assertEqual(actual, expected)
        self.assertEqual(len(self.candidates), 4)
        original_policy = self.source[self.source.index("Action policy("):self.source.index("double evaluation(")]
        for item in self.candidates:
            self.assertIn(original_policy, item["source"])
            self.assertIn("opp=policy(trial,1-us,j)", item["source"])

    def test_revised_actions_are_legal_with_same_turn_production(self):
        for item in self.candidates:
            subprocess.run([str(self.binaries[item["id"]]), "random"], check=True, capture_output=True)

    def test_tactical_revision_can_retain_flag_contested_ownership(self):
        for item in self.candidates:
            if item["parameters"].get("tactical"):
                subprocess.run([str(self.binaries[item["id"]]), "tactical"], check=True, capture_output=True)


if __name__ == "__main__":
    unittest.main()
