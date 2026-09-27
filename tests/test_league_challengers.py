from __future__ import annotations

import importlib.util
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("league_challengers", ROOT / "experiments/local_league/challengers.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


BRIDGE = r'''
#define main submitted_main
#include "candidate.cpp"
#undef main
#include <cassert>
void initialize_board() {
    board.nb=4;board.base[0]=0;board.base[1]=224;
    fill(board.at,board.at+N,-1);
    for (int c=0;c<N;++c) {
        board.pass[c]=true;board.adj[c].clear();
        for (int q=0;q<N;++q) {
            board.dist[c][q]=abs(c%15-q%15)+abs(c/15-q/15);
            if (board.dist[c][q]==1) board.adj[c].push_back(q);
        }
    }
    int positions[4]={32,96,112,192},types_[4]={ENG,HALL,WATCH,HOSPITAL};
    for (int b=0;b<4;++b) {board.pos[b]=positions[b];board.at[positions[b]]=b;board.id[b]=b;board.type[b]=types_[b];}
}
State empty_state() {
    State s;s.res[0]=s.res[1]=20;
    for (int b=0;b<4;++b) {s.owner[b]=-1;s.score[b]=3;}
    return s;
}
void legal(const State& s,int t,const Action& a) {
    int available[3][N],budget=s.res[t];
    for (int k=0;k<3;++k) copy(s.u[t][k],s.u[t][k]+N,available[k]);
    for (auto x:a.spawn) {
        assert(x.pos>=0 && x.pos<N && x.kind>=0 && x.kind<3 && x.count>0);
        int b=board.at[x.pos];assert(x.pos==board.base[t] || (b>=0 && board.type[b]==HOSPITAL && s.owner[b]==t));
        budget-=x.count*cost(s,t,x.kind);assert(budget>=0);available[x.kind][x.pos]+=x.count;
    }
    for (auto x:a.moves) {
        assert(x.from>=0 && x.from<N && x.to>=0 && x.to<N && x.kind>=0 && x.kind<3 && x.count>0);
        assert(!x.tele && board.dist[x.from][x.to]==1);
        available[x.kind][x.from]-=x.count;assert(available[x.kind][x.from]>=0);
    }
    bool used[BMAX]{};
    for (int b:a.priority) {assert(b>=0 && b<board.nb && !used[b]);used[b]=true;}
}
int main() {
    initialize_board();
    using Fn=Action(*)(const State&,int);
    vector<Fn> algorithms{challenge_economy,challenge_territory,challenge_spearhead};
    mt19937 random(8844);
    for (int i=0;i<64;++i) {
        State s=empty_state();s.turn=i*2;
        for (int t=0;t<2;++t) {
            s.res[t]=random()%41;
            for (int j=0;j<30;++j) {int c=random()%N;s.u[t][j%2][c]+=1+random()%5;}
        }
        for (int b=0;b<4;++b) {s.owner[b]=int(random()%3)-1;s.stage[b]=s.owner[b]<0?0:2;}
        for (Fn f:algorithms) for (int t=0;t<2;++t) legal(s,t,f(s,t));
    }
    // Production happens before movement: fresh flags leave the base legally.
    State fresh=empty_state();fresh.res[0]=10;
    for (Fn f:algorithms) {
        Action a=f(fresh,0);legal(fresh,0,a);bool flag_moves=false;
        for (auto m:a.moves) if (m.kind==F && m.from==board.base[0]) flag_moves=true;
        assert(flag_moves);
    }
    // F contests preserve ownership; local W must not abandon an immediate threat.
    State defense=empty_state();defense.turn=159;defense.res[0]=0;
    defense.owner[2]=0;defense.stage[2]=2;defense.u[0][F][112]=1;defense.u[0][W][112]=3;
    defense.u[1][F][113]=1;defense.u[1][W][113]=2;
    Action defended=challenge_territory(defense,0);legal(defense,0,defended);
    for (auto m:defended.moves) assert(m.from!=112);
    Action attack;attack.moves.push_back({F,113,112,1});attack.moves.push_back({W,113,112,2});
    State kept=advance(defense,defended,attack);assert(kept.owner[2]==0);
    // Enemy ownership needs two capture phases, so the flag remains on its goal.
    State capture=empty_state();capture.turn=80;capture.owner[0]=1;capture.stage[0]=2;capture.u[0][F][32]=1;
    Action first=challenge_economy(capture,0);legal(capture,0,first);
    State neutral=advance(capture,first,Action{});assert(neutral.owner[0]==-1);
    Action second=challenge_economy(neutral,0);legal(neutral,0,second);
    State ours=advance(neutral,second,Action{});assert(ours.owner[0]==0);
}
'''


class ChallengerTests(unittest.TestCase):
    def test_variants_are_independent_and_distinct(self):
        rows = MODULE.variants((ROOT / "submissions/tuned/main.cpp").read_text())
        self.assertEqual(len(rows), 6)
        self.assertEqual(len({r["id"] for r in rows}), 6)
        self.assertEqual(len({r["source"] for r in rows}), 6)
        self.assertNotIn("assignment_policy(", MODULE.CPP)
        self.assertNotIn("policy(", MODULE.CPP)
        for row in rows:
            self.assertTrue(row["id"].startswith("c_"))
            self.assertTrue(row["hypothesis"] and row["weakness"])
        with self.assertRaises(ValueError):
            MODULE.variants("layout changed")

    @unittest.skipUnless(shutil.which("g++"), "g++ required")
    def test_legal_actions_and_tactical_counterexamples(self):
        rows = MODULE.variants((ROOT / "submissions/tuned/main.cpp").read_text())
        with tempfile.TemporaryDirectory(prefix="yk-challengers-") as directory:
            temp = Path(directory)
            (temp / "candidate.cpp").write_text(rows[0]["source"])
            (temp / "bridge.cpp").write_text(BRIDGE)
            subprocess.run(["g++", "-std=c++20", "-O2", "-I", str(ROOT / "submissions/tuned"),
                            str(temp / "bridge.cpp"), "-o", str(temp / "bridge")], check=True, capture_output=True, text=True)
            subprocess.run([str(temp / "bridge")], check=True, timeout=30, capture_output=True, text=True)


if __name__ == "__main__":
    unittest.main()
