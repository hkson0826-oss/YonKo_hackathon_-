import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("league_repairs", ROOT / "experiments/local_league/repairs.py")
repairs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repairs)
sys.path.insert(0, str(ROOT / "yk-development-tools"))
from engine.commands import Move, Spawn
from engine.config import load_config
from engine.pipeline import run_turn
from engine.state import Building, new_game


HARNESS = r'''
#undef main
#include <cassert>
void check_legal(const State& s,int t,const Action& a) {
    int stock[3][N]{},resource=s.res[t];
    for(int k=0;k<3;++k) copy(s.u[t][k],s.u[t][k]+N,stock[k]);
    for(auto x:a.spawn) {
        assert(x.count>0); int b=board.at[x.pos];
        assert(x.pos==board.base[t] || (b>=0 && board.type[b]==HOSPITAL && s.owner[b]==t));
        assert(x.count*cost(s,t,x.kind)<=resource);
        resource-=x.count*cost(s,t,x.kind); stock[x.kind][x.pos]+=x.count;
    }
    int tele=0;
    for(auto x:a.moves) {
        assert(x.count>0 && stock[x.kind][x.from]>=x.count);
        stock[x.kind][x.from]-=x.count;
        if(x.tele) {
            assert(++tele<=1 && x.count<=5);
            int p=board.at[x.from],q=board.at[x.to];
            assert(p>=0 && q>=0 && p!=q && board.type[p]==STATION && board.type[q]==STATION);
            assert(s.owner[p]==t && s.owner[q]==t);
        } else assert(board.dist[x.from][x.to]==1);
    }
}
void emit_action(const Action& a) {
    for(auto x:a.spawn) cout<<"S "<<x.kind<<" "<<x.pos<<" "<<x.count<<"\n";
    for(auto x:a.moves) cout<<"M "<<x.kind<<" "<<x.from<<" "<<x.to<<" "<<x.count<<"\n";
}
int main(int argc,char**argv) {
    p::Init in; in.width=in.height=15;in.terrain.assign(15,string(15,'.'));
    in.bases={pair{0,7},pair{14,7}};
    in.buildings={{0,7,7,"WATCH"},{1,5,7,"ENG"},{2,10,10,"HOSPITAL"},
                  {3,3,3,"STATION"},{4,11,11,"STATION"}};
    board.init(in);
    State s; s.turn=159;fill(s.owner,s.owner+BMAX,-1);
    for(int b=0;b<board.nb;++b)s.score[b]=b?1:4;
    s.owner[0]=0;s.owner[1]=0;s.owner[2]=1;
    string mode=argc>1?argv[1]:"contest";
    if(mode=="contest" || mode=="spawn" || mode=="arrival") {
        s.u[0][W][112]=3;s.u[0][F][111]=1;
        s.u[1][W][113]=3;s.u[1][F][127]=1;
        Action a;a.moves={{W,112,127,3}};
        if(mode=="spawn") {
            s.u[0][W][112]=0; s.res[0]=6;board.type[0]=HOSPITAL;
            a.spawn={{W,112,3}};
        }
        if(mode=="arrival") {
            s.u[0][W][112]=0;s.u[0][W][110]=3;
            a.moves={{W,110,111,3}};
        }
        a=repair_action(s,0,a,1,2,0,0);check_legal(s,0,a);emit_action(a);
    } else if(mode=="engineering") {
        s.turn=60;s.u[0][W][110]=3;s.u[0][F][109]=1;
        s.u[1][W][111]=3;s.u[1][F][125]=1;
        Action a;a.moves={{W,110,95,3}};
        a=repair_action(s,0,a,2,1,0,0);check_legal(s,0,a);emit_action(a);
    } else if(mode=="escort") {
        s.owner[0]=-1;s.u[0][W][97]=3;s.u[0][F][111]=1;s.u[1][W][113]=3;
        Action a;a.moves={{W,97,82,3},{F,111,112,1}};
        a=repair_action(s,0,a,0,0,0,2);check_legal(s,0,a);emit_action(a);
    } else if(mode=="terminal") {
        s.turn=160;s.owner[0]=1;s.owner[1]=0;s.owner[2]=-1;
        double losing=evaluation(s,0);s.score[1]=2;double less_losing=evaluation(s,0);
        assert(less_losing>losing && less_losing < -90000);
        s.score[1]=5;assert(evaluation(s,0)>90000);
    } else if(mode=="terminal_zero_score") {
        board.nb=17;
        State r;r.turn=160;
        fill(r.owner,r.owner+BMAX,-1);fill(r.score,r.score+BMAX,1);
        for(int b=0;b<7;++b) {r.owner[b]=1;r.score[b]=4;}
        for(int b=7;b<10;++b) {r.owner[b]=0;r.score[b]=b==9?3:4;}
        r.score[16]=2;
        assert(points(r,0)==11 && points(r,1)==28);
        double preserving=evaluation(r,0),winning=evaluation(r,1);
        for(int b=7;b<10;++b)r.owner[b]=-1;
        double eliminated=evaluation(r,0),dominating=evaluation(r,1);
        assert(preserving>eliminated && preserving < -90000 && eliminated < -90000);
        assert(dominating>winning && winning>90000);
        r.turn=159;assert(evaluation(r,0)==-100000 && evaluation(r,1)==100000);
        r.turn=160;r.owner[0]=0;
        for(int b=1;b<7;++b)r.owner[b]=-1;
        r.owner[7]=1;
        r.occupation[0]=2;r.occupation[1]=1;assert(evaluation(r,0)==90000);
        r.occupation[0]=1;assert(evaluation(r,0)==0);
        r.u[0][W][0]=1;assert(evaluation(r,0)==80000);
        assert(evaluation(r,1)==-80000);
    } else if(mode=="random") {
        mt19937 local_rng(1729);
        for(int repeat=0;repeat<180;++repeat) {
            State r;r.turn=local_rng()%160;r.res[0]=local_rng()%41;r.res[1]=local_rng()%41;
            for(int b=0;b<board.nb;++b) {r.owner[b]=int(local_rng()%3)-1;r.score[b]=1+local_rng()%4;}
            for(int k=0;k<3;++k)for(int t=0;t<2;++t)for(int j=0;j<12;++j)
                r.u[t][k][local_rng()%N]+=1+local_rng()%7;
            for(int t=0;t<2;++t)for(int style=0;style<4;++style)check_legal(r,t,policy(r,t,style));
        }
    }
}
'''


class LeagueRepairTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / "submissions/tuned/main.cpp").read_text()
        cls.candidates = repairs.variants(cls.source)
        cls.temp = tempfile.TemporaryDirectory()
        cls.folder = Path(cls.temp.name)
        combined = next(x for x in cls.candidates if x["id"] == "r_combined")
        path = cls.folder / "harness.cpp"
        path.write_text("#define main original_bot_main\n" + combined["source"] + HARNESS)
        cls.binary = cls.folder / "harness"
        subprocess.run(["g++", "-std=c++20", "-O2", "-I", str(ROOT / "submissions/tuned"),
                        str(path), "-o", str(cls.binary)], check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def commands(self, scenario):
        output = subprocess.run([str(self.binary), scenario], check=True, capture_output=True, text=True).stdout
        commands = []
        for line in output.splitlines():
            fields = line.split()
            if fields[0] == "S":
                kind, pos, count = map(int, fields[1:])
                commands.append(Spawn("FWS"[kind], count, pos % 15, pos // 15))
            else:
                kind, src, dest, count = map(int, fields[1:])
                direction = {1: "R", -1: "L", 15: "D", -15: "U"}[dest - src]
                commands.append(Move(src % 15, src // 15, "FWS"[kind], count, direction))
        return commands

    def position(self, engineering=False, hospital=False):
        x, y = (5, 7) if engineering else (7, 7)
        kind = "ENG" if engineering else "HOSPITAL" if hospital else "WATCH"
        building = Building(0, x, y, kind, 4, "Y", 2)
        buildings = [building]
        if hospital:
            buildings.append(Building(1, 5, 7, "ENG", 1, "Y", 2))
        state = new_game(load_config(), buildings=buildings, resources={"Y": 6 if hospital else 0, "K": 0})
        if not hospital:
            state.add_unit(x, y, "Y", "W", 3)
        state.add_unit(x-1, y, "Y", "F", 1)
        state.add_unit(x+1, y, "K", "W", 3)
        state.add_unit(x, y+1, "K", "F", 1)
        enemy = [Move(x+1, y, "W", 3, "L"), Move(x, y+1, "F", 1, "U")]
        return state, enemy

    def test_candidates_are_distinct_and_source_anchor_is_guarded(self):
        self.assertEqual(len(self.candidates), 10)
        self.assertEqual(len({x["id"] for x in self.candidates}), 10)
        self.assertEqual(len({x["source"] for x in self.candidates}), 10)
        with self.assertRaises(ValueError):
            repairs.variants(self.source.replace("Action policy(", "Action changed_policy("))

    def test_all_variants_compile(self):
        for item in self.candidates:
            path = self.folder / (item["id"] + ".cpp")
            path.write_text(item["source"])
            subprocess.run(["g++", "-std=c++20", "-fsyntax-only", "-I", str(ROOT / "submissions/tuned"),
                            str(path)], check=True, capture_output=True)

    def test_joint_flag_warrior_defense_matches_official_engine(self):
        state, enemy = self.position()
        after, _ = run_turn(state, self.commands("contest"), enemy)
        self.assertEqual(after.buildings[0].owner, "Y")
        self.assertEqual(after.get_unit(7, 7, "Y", "F"), 1)
        self.assertEqual(after.get_unit(7, 7, "K", "F"), 1)
        self.assertEqual(after.get_unit(7, 7, "Y", "W"), 0)

    def test_new_hospital_production_can_join_same_turn_defense(self):
        state, enemy = self.position(hospital=True)
        after, _ = run_turn(state, self.commands("spawn"), enemy)
        self.assertEqual(after.buildings[0].owner, "Y")
        self.assertEqual(after.get_unit(7, 7, "Y", "W"), 0)

    def test_unreachable_arrivals_are_not_reused_as_available_defenders(self):
        commands = self.commands("arrival")
        self.assertEqual(len(commands), 1)
        self.assertEqual((commands[0].x, commands[0].y, commands[0].count), (5, 7, 3))

    def test_last_engineering_discount_is_retained_by_flag_contest(self):
        state, enemy = self.position(engineering=True)
        after, _ = run_turn(state, self.commands("engineering"), enemy)
        self.assertEqual(after.buildings[0].owner, "Y")

    def test_joint_escort_arrives_in_time_and_survives_equal_combat(self):
        state = new_game(load_config(), buildings=[Building(0, 7, 7, "WATCH", 4, "N", 0)],
                         resources={"Y": 0, "K": 0})
        state.add_unit(7, 6, "Y", "W", 3)
        state.add_unit(6, 7, "Y", "F", 1)
        state.add_unit(8, 7, "K", "W", 3)
        after, _ = run_turn(state, self.commands("escort"), [Move(8, 7, "W", 3, "L")])
        self.assertEqual(after.get_unit(7, 7, "Y", "F"), 1)
        self.assertEqual(after.buildings[0].owner, "Y")

    def test_terminal_margin_keeps_actual_outcome_tiers_ordered(self):
        subprocess.run([str(self.binary), "terminal"], check=True, capture_output=True)

    def test_terminal_zero_score_loss_is_worse_than_preserving_eleven_points(self):
        subprocess.run([str(self.binary), "terminal_zero_score"], check=True, capture_output=True)

    def test_random_states_preserve_production_origin_counts_and_single_teleport(self):
        subprocess.run([str(self.binary), "random"], check=True, capture_output=True)


if __name__ == "__main__":
    unittest.main()
