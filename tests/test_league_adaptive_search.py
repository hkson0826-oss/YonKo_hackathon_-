import importlib.util
import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("adaptive_search", ROOT / "experiments/local_league/adaptive_search.py")
adaptive = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adaptive)


class AdaptiveSearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = (ROOT / "submissions/tuned/main.cpp").read_text()
        cls.variants = adaptive.variants(cls.original)

    def test_unique_and_preserves_observation_transition(self):
        self.assertEqual(len(self.variants), 8)
        self.assertEqual(len({item["source"] for item in self.variants}), 8)
        transition = self.original.split("State advance(", 1)[1].split("double building_value(", 1)[0]
        observation = self.original.split("    State s; s.turn=v.turn-1;", 1)[1].split(adaptive.START, 1)[0]
        for item in self.variants:
            self.assertIn(transition, item["source"])
            self.assertIn(observation, item["source"])
        with self.assertRaises(ValueError):
            adaptive.variants(self.original.replace(adaptive.START, "changed"))

    def test_compile_all(self):
        with tempfile.TemporaryDirectory(prefix="yk-adaptive-compile-", dir="/tmp") as directory:
            target = pathlib.Path(directory)
            for item in self.variants:
                source = target / (item["id"] + ".cpp")
                source.write_text(item["source"])
                proc = subprocess.run(["g++", "-std=c++20", "-O2", "-I", str(ROOT / "submissions/tuned"),
                                       str(source), "-o", str(target / item["id"])], capture_output=True, text=True, timeout=60)
                self.assertEqual(proc.returncode, 0, item["id"] + "\n" + proc.stderr)

    def test_action_mixing_observation_fit_and_budget(self):
        source = adaptive._build(self.original, mix=True, local=True, memory=True, uncertain=True)
        harness = r'''
#define main bot_main
''' + source + r'''
#undef main
#include <cassert>
#include <sstream>
string key(const Action& a) {
    ostringstream out;
    for(auto p:a.spawn) out<<"S"<<p.kind<<","<<p.pos<<","<<p.count<<";";
    for(auto m:a.moves) out<<"M"<<m.kind<<","<<m.from<<","<<m.to<<","<<m.count<<","<<m.tele<<";";
    for(int b:a.priority) out<<"P"<<b<<";";
    return out.str();
}
int main() {
    fill(board.at,board.at+N,-1); board.nb=3;board.base[0]=0;board.base[1]=224;
    board.pos[0]=16;board.pos[1]=208;board.pos[2]=112;
    for(int b=0;b<3;++b) {board.at[board.pos[b]]=b;board.type[b]=b==2?PLAZA:STATION;}
    for(int c=0;c<N;++c) {
        board.pass[c]=true;
        for(int q=0;q<N;++q) {
            board.dist[c][q]=abs(c%15-q%15)+abs(c/15-q/15);
            if(board.dist[c][q]==1) board.adj[c].push_back(q);
        }
    }
    State s;s.res[0]=7;s.res[1]=30;s.u[0][F][0]=2;
    fill(s.owner,s.owner+BMAX,-1);fill(s.score,s.score+BMAX,3);
    Action dirty; dirty.spawn={{W,0,10},{F,20,2}};
    dirty.moves={{W,0,1,9},{W,1,2,9},{F,0,2,1},{F,0,15,3}};
    dirty.priority={2,2,-1,999,0};
    auto cleaned=a_clean(s,0,dirty);
    assert(cleaned.spawn.size()==1 && cleaned.spawn[0].count==2);
    assert(cleaned.moves.size()==2 && cleaned.moves[0].count==2 && cleaned.moves[1].count==2);
    assert(cleaned.priority==vector<int>({2,0}));
    Action warrior;warrior.moves={{W,0,1,8},{F,0,15,1}};
    Action flag;flag.spawn={{W,0,1}};flag.moves={{F,0,1,1},{W,0,15,1}};
    auto mixed=a_mix(s,0,flag,warrior);
    assert(mixed.moves.size()==2 && mixed.moves[0].kind==W && mixed.moves[0].to==1 && mixed.moves[0].count==1);
    assert(mixed.moves[1].kind==F && mixed.moves[1].to==1);
    auto patched=a_patch(s,0,mixed,cleaned,0);
    assert(patched.spawn.size()==1 && patched.spawn[0].count==1);
    assert(patched.moves.size()==2 && patched.moves[0].count==1 && patched.moves[1].to==15);
    s.owner[0]=s.owner[1]=0;s.u[0][W][16]=10;s.u[0][F][208]=1;
    Action tele;tele.moves={{W,16,208,10,true},{F,208,16,1,true}};
    auto legaltele=a_clean(s,0,tele);
    assert(legaltele.moves.size()==1 && legaltele.moves[0].count==5);
    s.revealed[0][0]=true;s.score[0]=s.score[1]=2;
    auto low=a_scenario(s,0,0),high=a_scenario(s,0,1);
    assert(low.score[0]==2 && low.score[1]==2 && high.score[1]==2);
    s.revealed[0][0]=false;
    low=a_scenario(s,0,0); high=a_scenario(s,0,1);
    assert(low.score[0]==low.score[1] && high.score[0]==high.score[1]);
    assert(low.score[0]==1 && high.score[0]==2 && low.score[2]==3);
    State observed=s,predicted=s;assert(a_prediction_error(predicted,observed,0)==0);
    predicted.u[1][W][1]=3;assert(a_prediction_error(predicted,observed,0)==3);
    a_error[0]=0;a_error[1]=a_error[2]=a_error[3]=40;
    double weights[4];a_previous=false;a_observe(s,0,weights);
    assert(weights[0]>.6 && weights[1]>=.10 && abs(accumulate(weights,weights+4,0.0)-1)<1e-9);
    double result=12345;auto start=AClock::now();
    assert(!a_evaluate(s,0,mixed,0,3,weights,start,-1,result) && result==12345);
    assert(a_evaluate(s,0,mixed,0,1,weights,AClock::now(),1000,result) && isfinite(result));
    auto fallback=a_clean(s,0,policy(s,0,0));
    assert(key(a_decide(s,0,AClock::now(),-1))==key(fallback));
    // A matching one-step model keeps finite normalized weights using only visible state.
    s.turn=3; a_previous_state=s; a_previous_action=mixed; a_previous=true;
    Action opp=policy(s,1,0);State next=advance(s,mixed,opp);a_observe(next,0,weights);
    for(double w:weights) assert(isfinite(w) && w>=.10);
    assert(abs(accumulate(weights,weights+4,0.0)-1)<1e-9);
    return 0;
}
'''
        with tempfile.TemporaryDirectory(prefix="yk-adaptive-logic-", dir="/tmp") as directory:
            src = pathlib.Path(directory) / "check.cpp"
            binary = pathlib.Path(directory) / "check"
            src.write_text(harness)
            subprocess.run(["g++", "-std=c++20", "-O2", "-I", str(ROOT / "submissions/tuned"),
                            str(src), "-o", str(binary)], check=True, capture_output=True, timeout=60)
            proc = subprocess.run([str(binary)], capture_output=True, text=True, timeout=20)
            self.assertEqual(proc.returncode, 0, proc.stderr)


class AdaptiveRevisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = (ROOT / "submissions/tuned/main.cpp").read_text()
        cls.revisions = adaptive.variants_iteration2(cls.original)

    def test_revision_compile_and_old_population_unchanged(self):
        self.assertEqual(len(adaptive.variants(self.original)), 8)
        self.assertEqual(len(self.revisions), 4)
        self.assertEqual(len({v["source"] for v in self.revisions}), 4)
        with tempfile.TemporaryDirectory(prefix="yk-adaptive-revision-", dir="/tmp") as directory:
            directory = pathlib.Path(directory)
            for candidate in self.revisions:
                source = directory / (candidate["id"] + ".cpp")
                source.write_text(candidate["source"])
                proc = subprocess.run(["g++", "-std=c++20", "-O2", "-I", str(ROOT / "submissions/tuned"),
                                       str(source), "-o", str(directory / candidate["id"])],
                                      capture_output=True, text=True, timeout=60)
                self.assertEqual(proc.returncode, 0, candidate["id"] + "\n" + proc.stderr)

    def test_terminal_order_and_independent_wait_moves(self):
        candidate = next(x for x in self.revisions if x["id"] == "a_v2_tactical_local")
        harness = r'''
#define main bot_main
''' + candidate["source"] + r'''
#undef main
#include <cassert>
int main() {
    fill(board.at,board.at+N,-1);board.nb=3;board.base[0]=0;board.base[1]=224;
    board.pos[0]=112;board.pos[1]=16;board.pos[2]=208;
    for(int b=0;b<3;++b) {board.at[board.pos[b]]=b;board.type[b]=b==0?PLAZA:ENG;}
    for(int c=0;c<N;++c) {
        board.pass[c]=true;
        for(int q=0;q<N;++q) {
            board.dist[c][q]=abs(c%15-q%15)+abs(c/15-q/15);
            if(board.dist[c][q]==1) board.adj[c].push_back(q);
        }
    }
    State s;s.turn=160;s.score[0]=3;s.score[1]=s.score[2]=2;
    s.owner[0]=s.owner[1]=1;s.owner[2]=-1;
    double loss0=evaluation(s,0);s.owner[2]=0;double loss2=evaluation(s,0);
    assert(loss0<loss2 && loss2<-99000);
    s.owner[0]=0;assert(evaluation(s,0)>99000);
    State late=s;late.turn=159;late.owner[0]=-1;late.u[0][F][112]=1;
    late.u[0][W][112]=10;late.u[0][F][0]=4;late.u[0][W][0]=80;
    assert(a2_importance(late,0,112)>a2_importance(late,0,0));
    Action current;current.moves={{F,112,127,1},{W,112,113,7}};
    auto choices=a2_neighborhood(late,0,current,112);
    bool flag_wait=false,warrior_wait=false,both_wait=false,separate=false;
    for(const auto& a:choices) {
        assert(a_equal(a,a_clean(late,0,a)));
        int fm=0,wm=0;for(auto m:a.moves) {fm+=m.kind==F;wm+=m.kind==W;}
        flag_wait|=!fm && wm;warrior_wait|=fm && !wm;both_wait|=!fm && !wm;
        for(auto f:a.moves) for(auto w:a.moves) if(f.kind==F && w.kind==W) separate|=f.to!=w.to;
    }
    assert(flag_wait && warrior_wait && both_wait && separate);
    Action empty;late.res[0]=20;late.res[1]=20;late.owner[0]=-1;
    auto keep=advance(late,empty,empty);auto leave=advance(late,current,empty);
    assert(keep.owner[0]==0 && leave.owner[0]==-1);
    assert(evaluation(keep,0)>evaluation(leave,0));
    return 0;
}
'''
        with tempfile.TemporaryDirectory(prefix="yk-adaptive-revision-logic-", dir="/tmp") as directory:
            source = pathlib.Path(directory) / "check.cpp"
            binary = pathlib.Path(directory) / "check"
            source.write_text(harness)
            subprocess.run(["g++", "-std=c++20", "-O2", "-I", str(ROOT / "submissions/tuned"),
                            str(source), "-o", str(binary)], check=True, capture_output=True, timeout=60)
            proc = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
            self.assertEqual(proc.returncode, 0, proc.stderr)


if __name__ == "__main__":
    unittest.main()
