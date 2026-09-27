from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("joint_allocator", ROOT / "experiments/local_league/joint_allocator.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
sys.path.insert(0, str(ROOT / "yk-development-tools"))
from engine.commands import Move, Spawn
from engine.config import load_config
from engine.pipeline import run_turn
from engine.state import Building, new_game

HARNESS = r'''
#undef main
#include <cassert>
void legal(const State& s,int t,const Action& a) {
    int pool[3][N],budget=s.res[t];
    for(int k=0;k<3;++k)copy(s.u[t][k],s.u[t][k]+N,pool[k]);
    for(auto x:a.spawn) {
        assert(x.count>0 && x.kind>=0 && x.kind<3 && x.pos>=0 && x.pos<N);
        int b=board.at[x.pos];assert(x.pos==board.base[t] || (b>=0 && board.type[b]==HOSPITAL && s.owner[b]==t));
        budget-=x.count*cost(s,t,x.kind);assert(budget>=0);pool[x.kind][x.pos]+=x.count;
    }
    for(auto x:a.moves) {
        assert(x.count>0 && !x.tele && board.dist[x.from][x.to]==1);
        pool[x.kind][x.from]-=x.count;assert(pool[x.kind][x.from]>=0);
    }
    bool used[BMAX]{};for(int b:a.priority){assert(b>=0 && b<board.nb && !used[b]);used[b]=true;}
}
int main(int argc,char**argv) {
    p::Init in;in.width=in.height=15;in.terrain.assign(15,string(15,'.'));
    in.bases={pair{0,7},pair{14,7}};
    in.buildings={{0,7,7,"WATCH"},{1,5,7,"ENG"},{2,10,10,"HOSPITAL"}};board.init(in);
    State s;s.turn=159;fill(s.owner,s.owner+BMAX,0);for(int b=0;b<board.nb;++b)s.score[b]=b?1:4;
    string scenario=argc>1?argv[1]:"contest";int profile=argc>2?atoi(argv[2]):0;
    if(scenario=="random") {
        mt19937 gen(172913);
        for(int rep=0;rep<120;++rep) {
            State r;r.turn=gen()%160;
            for(int b=0;b<board.nb;++b){r.owner[b]=int(gen()%3)-1;r.score[b]=1+gen()%4;r.stage[b]=r.owner[b]<0?gen()%2:2;}
            for(int t=0;t<2;++t){r.res[t]=gen()%41;for(int k=0;k<2;++k)for(int j=0;j<20;++j)r.u[t][k][gen()%N]+=1+gen()%9;}
            for(int t=0;t<2;++t)for(int p=0;p<4;++p)legal(r,t,joint_policy(r,t,p));
        }
        return 0;
    }
    if(scenario=="contest") {
        s.u[0][F][111]=1;s.u[0][W][112]=3;s.u[1][W][113]=3;s.u[1][F][127]=1;
    } else if(scenario=="escort") {
        s.owner[0]=-1;s.u[0][F][111]=1;s.u[0][W][97]=3;s.u[1][W][113]=3;
    } else if(scenario=="arrival") {
        s.owner[0]=-1;s.turn=100;s.u[0][F][111]=1;s.u[0][W][110]=3;s.u[1][W][113]=3;
    } else if(scenario=="surplus") {
        s.turn=100;s.owner[0]=1;s.u[0][F][111]=1;s.u[0][W][110]=500;s.u[1][W][113]=2;
    } else if(scenario=="multifront") {
        s.turn=100;s.owner[0]=s.owner[1]=1;
        s.u[0][F][111]=2;s.u[0][W][111]=500;
    } else if(scenario=="neutralize") {
        s.owner[0]=1;s.u[0][F][111]=1;
    } else if(scenario=="spawn") {
        s.turn=0;fill(s.owner,s.owner+BMAX,-1);s.res[0]=20;
    } else if(scenario=="capture") {
        s.turn=158;s.owner[0]=1;s.u[0][F][112]=1;
        auto first=joint_policy(s,0,profile);legal(s,0,first);
        auto neutral=advance(s,first,Action{});assert(neutral.owner[0]==-1);
        auto second=joint_policy(neutral,0,profile);legal(neutral,0,second);
        auto owned=advance(neutral,second,Action{});assert(owned.owner[0]==0);return 0;
    }
    auto a=joint_policy(s,0,profile);legal(s,0,a);
    for(auto x:a.spawn)cout<<"S "<<x.kind<<" "<<x.pos<<" "<<x.count<<"\n";
    for(auto x:a.moves)cout<<"M "<<x.kind<<" "<<x.from<<" "<<x.to<<" "<<x.count<<"\n";
}
'''


class JointAllocatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / "submissions/tuned/main.cpp").read_text()
        cls.rows = MODULE.variants(cls.source)
        cls.temp = tempfile.TemporaryDirectory(prefix="yk-joint-")
        cls.folder = Path(cls.temp.name)
        cpp = cls.folder / "bridge.cpp"
        cpp.write_text("#define main submitted_main\n" + cls.rows[0]["source"] + HARNESS)
        cls.binary = cls.folder / "bridge"
        subprocess.run(["g++", "-std=c++20", "-O2", "-I", str(ROOT / "submissions/tuned"), str(cpp), "-o", str(cls.binary)],
                       check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def commands(self, scenario, profile=0):
        result = subprocess.run([str(self.binary), scenario, str(profile)], check=True, capture_output=True, text=True)
        commands = []
        for line in result.stdout.splitlines():
            parts = line.split()
            if parts[0] == "S":
                kind, pos, count = map(int, parts[1:])
                commands.append(Spawn("FWS"[kind], count, pos % 15, pos // 15))
            else:
                kind, src, dst, count = map(int, parts[1:])
                commands.append(Move(src % 15, src // 15, "FWS"[kind], count, {1: "R", -1: "L", 15: "D", -15: "U"}[dst-src]))
        return commands

    def state(self, owner="Y"):
        state = new_game(load_config(), buildings=[Building(0, 7, 7, "WATCH", 4, owner, 2 if owner != "N" else 0)],
                         resources={"Y": 0, "K": 0})
        state.add_unit(6, 7, "Y", "F", 1)
        return state

    def test_eight_unique_candidates_preserve_exact_transition_and_protocol(self):
        self.assertEqual(len(self.rows), 8)
        self.assertEqual(len({r["source"] for r in self.rows}), 8)
        transition = self.source.split("State advance(", 1)[1].split("double building_value", 1)[0]
        protocol = self.source.split("vector<string> decide(", 1)[1]
        for row in self.rows:
            self.assertEqual(row["source"].split("State advance(", 1)[1].split("double building_value", 1)[0], transition)
            restored = row["source"].split("vector<string> decide(", 1)[1]
            restored = restored.replace("candidates[i]=joint_own_policy(s,us,i);", "candidates[i]=policy(s,us,i);")
            restored = restored.replace("own=d==0?candidates[i]:joint_own_policy(trial,us,i)", "own=d==0?candidates[i]:policy(trial,us,i)")
            self.assertEqual(restored, protocol)
            original_policy = self.source.split("Action policy(", 1)[1].split("double evaluation(", 1)[0]
            actual_policy = row["source"].split("Action policy(", 1)[1].split("Action joint_own_policy(", 1)[0]
            self.assertEqual(actual_policy.strip(), original_policy.strip())
            self.assertTrue(row["parameters"]["own_only"])
        with self.assertRaises(ValueError):
            MODULE.variants("changed layout")

    def test_all_variants_compile(self):
        for row in self.rows:
            cpp = self.folder / (row["id"] + ".cpp")
            cpp.write_text(row["source"])
            subprocess.run(["g++", "-std=c++20", "-fsyntax-only", "-I", str(ROOT / "submissions/tuned"), str(cpp)],
                           check=True, capture_output=True)

    def test_960_random_actions_preserve_origin_counts_and_production_budget(self):
        self.commands("random")

    def test_joint_flag_contest_preserves_owned_building_official_engine(self):
        for profile in range(4):
            state = self.state()
            state.add_unit(7, 7, "Y", "W", 3)
            state.add_unit(8, 7, "K", "W", 3)
            state.add_unit(7, 8, "K", "F", 1)
            after, _ = run_turn(state, self.commands("contest", profile), [Move(8, 7, "W", 3, "L"), Move(7, 8, "F", 1, "U")])
            self.assertEqual(after.buildings[0].owner, "Y")
            self.assertEqual(after.get_unit(7, 7, "Y", "F"), 1)
            self.assertEqual(after.get_unit(7, 7, "K", "F"), 1)

    def test_joint_escort_reaches_same_cell_and_captures_official_engine(self):
        for profile in range(4):
            state = self.state("N")
            state.add_unit(7, 6, "Y", "W", 3)
            state.add_unit(8, 7, "K", "W", 3)
            after, _ = run_turn(state, self.commands("escort", profile), [Move(8, 7, "W", 3, "L")])
            self.assertEqual(after.buildings[0].owner, "Y")
            self.assertEqual(after.get_unit(7, 7, "Y", "F"), 1)

    def test_two_move_escort_cannot_be_reused_as_same_turn_arrival(self):
        for profile in range(4):
            commands = self.commands("arrival", profile)
            self.assertFalse(any(isinstance(c, Move) and c.kind == "W" and c.x == 6 for c in commands))
            self.assertFalse(any(isinstance(c, Move) and c.kind == "F" and c.direction == "R" for c in commands))

    def test_safe_surplus_does_not_stay_on_filled_owned_engineering(self):
        for profile in range(4):
            commands = self.commands("surplus", profile)
            sent = sum(c.count for c in commands if isinstance(c, Move) and c.kind == "W" and (c.x, c.y) == (5, 7))
            self.assertEqual(sent, 500)

    def test_surplus_reinforces_two_attack_fronts_in_finite_chunks(self):
        for profile in range(4):
            commands = self.commands("multifront", profile)
            moved = {direction: sum(c.count for c in commands if isinstance(c, Move) and c.kind == "W" and c.direction == direction)
                     for direction in ("L", "R")}
            self.assertEqual(moved["L"] + moved["R"], 500)
            self.assertGreaterEqual(moved["L"], 200)
            self.assertGreaterEqual(moved["R"], 200)

    def test_last_turn_enemy_neutralization_and_two_turn_capture(self):
        for profile in range(4):
            state = self.state("K")
            after, _ = run_turn(state, self.commands("neutralize", profile), [])
            self.assertEqual(after.buildings[0].owner, "N")
            self.commands("capture", profile)

    def test_fresh_spawn_can_move_before_combat(self):
        commands = self.commands("spawn")
        self.assertTrue(any(isinstance(c, Spawn) and c.kind == "F" for c in commands))
        self.assertTrue(any(isinstance(c, Move) and c.kind == "F" and (c.x, c.y) == (0, 7) for c in commands))




REVISION_HARNESS = HARNESS.replace(
    'if(scenario=="contest") {',
    r'''if(scenario=="relay") {
        s.turn=100;board.at[112]=-1;board.pos[0]=116;board.at[116]=0;s.owner[0]=-1;
        s.u[0][F][111]=1;s.u[0][W][114]=3;s.u[1][W][127]=3;
    } else if(scenario=="flags7") {
        s.turn=60;s.res[0]=10;board.nb=9;fill(board.at,board.at+N,-1);
        for(int b=0;b<9;++b){board.pos[b]=b+10;board.at[b+10]=b;board.type[b]=WATCH;s.owner[b]=-1;s.score[b]=3;}
        s.u[0][F][board.base[0]]=7;s.u[0][W][board.base[0]]=20;
    } else if(scenario=="early_equivalence") {
        auto equal=[](const Action& a,const Action& b) {
            assert(a.spawn.size()==b.spawn.size() && a.moves.size()==b.moves.size() && a.priority==b.priority);
            for(int i=0;i<int(a.spawn.size());++i){auto x=a.spawn[i],y=b.spawn[i];assert(x.kind==y.kind && x.pos==y.pos && x.count==y.count);}
            for(int i=0;i<int(a.moves.size());++i){auto x=a.moves[i],y=b.moves[i];assert(x.kind==y.kind && x.from==y.from && x.to==y.to && x.count==y.count && x.tele==y.tele);}
        };
        mt19937 gen(42911);
        for(int turn=0;turn<30;++turn) {
            State r;r.turn=turn;r.res[0]=gen()%41;
            for(int b=0;b<board.nb;++b){r.owner[b]=int(gen()%3)-1;r.score[b]=1+gen()%4;}
            for(int t=0;t<2;++t)for(int j=0;j<15;++j)r.u[t][j%2][gen()%N]+=1+gen()%9;
            for(int style=0;style<4;++style)equal(policy(r,0,style),joint_own_policy(r,0,style));
        }
        return 0;
    } else if(scenario=="contest") {''',
).replace('auto a=joint_policy(s,0,profile);legal(s,0,a);', 'auto a=joint_own_policy(s,0,2);legal(s,0,a);')


class JointAllocatorRevisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import hashlib
        cls.source = (ROOT / "submissions/tuned/main.cpp").read_text()
        cls.original = MODULE.variants(cls.source)
        cls.expected_original_sha256 = {
            "j_balanced_direct": "cd6d85a40f589a28e3fbff52968970c00518685b752c97c9d45da608a20570e3",
            "j_balanced_portfolio": "534f55f1d6641ed788ca637663456e43375297d8016ac9832c589b0a012c8422",
            "j_pressure_direct": "2507e32ff1e0fcbc10b93b3af90381ef23f9f6151d3a56469ae584c83cc95b28",
            "j_pressure_portfolio": "caae86336aa83781d9670763ba31c392721cb2e5eea7287c3b6654e4d2bc0143",
            "j_defensive_direct": "8cd17787c6b5e17f2da9878c00380d773435798296175209a870dda5befec644",
            "j_defensive_portfolio": "132c00d4f97e311960b21be22d3edacfd020789b8f63ad5c6dc3e9a625be6896",
            "j_reclaim_direct": "f90303517503b5948f714ae0aaa378ada33bc6a2d33f22d4d0131ba8b6a80654",
            "j_reclaim_portfolio": "8e12a82b5559a227983b17d31b61dada416b99045c987e5d94780a8a7a8092ff",
        }
        cls.before = {r["id"]: hashlib.sha256(r["source"].encode()).hexdigest() for r in cls.original}
        cls.rows = MODULE.variants_iteration2(cls.source)
        cls.temp = tempfile.TemporaryDirectory(prefix="yk-joint-revision-")
        cls.folder = Path(cls.temp.name)
        cls.binaries = {}
        for row in cls.rows + [next(r for r in cls.original if r["id"] == "j_reclaim_portfolio")]:
            path = cls.folder / (row["id"] + ".cpp")
            path.write_text("#define main submitted_main\n" + row["source"] + REVISION_HARNESS)
            binary = cls.folder / row["id"]
            subprocess.run(["g++", "-std=c++20", "-O2", "-I", str(ROOT / "submissions/tuned"), str(path), "-o", str(binary)],
                           check=True, capture_output=True)
            cls.binaries[row["id"]] = binary

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def output(self, name, scenario):
        return subprocess.run([str(self.binaries[name]), scenario], check=True, capture_output=True, text=True).stdout

    def test_original_eight_source_hashes_stay_frozen_and_four_new_ids_are_unique(self):
        import hashlib
        self.assertEqual(self.before, self.expected_original_sha256)
        self.assertEqual({r["id"]: hashlib.sha256(r["source"].encode()).hexdigest() for r in MODULE.variants(self.source)}, self.before)
        self.assertEqual(len(self.rows), 4)
        self.assertEqual(len({r["source"] for r in self.rows}), 4)
        self.assertTrue(all(r["id"].startswith("j_v2_") for r in self.rows))

    def test_each_revision_passes_existing_random_legality_and_tactics(self):
        for row in self.rows:
            for scenario in ("random", "contest", "escort", "arrival", "neutralize", "capture", "surplus", "multifront"):
                self.output(row["id"], scenario)

    def test_delayed_revisions_preserve_every_original_policy_before_turn_thirty(self):
        for row in self.rows:
            if row["parameters"].get("start_turn"):
                self.output(row["id"], "early_equivalence")

    def test_flag_capacity_stops_replacing_warriors_with_an_eighth_flag(self):
        original = self.output("j_reclaim_portfolio", "flags7")
        revised = self.output("j_v2_reclaim_flags7", "flags7")
        self.assertIn("S 0 ", original)
        self.assertNotIn("S 0 ", revised)

    def test_blocked_flag_relay_moves_support_toward_the_waypoint(self):
        original = self.output("j_reclaim_portfolio", "relay")
        self.assertEqual(sum(int(line.split()[4]) for line in original.splitlines() if line.startswith("M 1 114 115 ")), 3)
        for name in ("j_v2_reclaim_relay", "j_v2_reclaim_relay_delayed"):
            revised = self.output(name, "relay")
            self.assertEqual(sum(int(line.split()[4]) for line in revised.splitlines() if line.startswith("M 1 114 113 ")), 3)
            self.assertNotIn("M 0 111 112", revised)


if __name__ == "__main__":
    unittest.main()
