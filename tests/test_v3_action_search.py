import hashlib
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('v3_action_search', ROOT / 'experiments/local_league/v3_action_search.py')
SEARCH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SEARCH)


HARNESS = r'''
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
    State s;fill(s.owner,s.owner+BMAX,-1);fill(s.score,s.score+BMAX,3);
    s.turn=30;s.res[0]=s.res[1]=30;s.u[0][F][112]=2;s.u[0][W][112]=7;
    s.u[0][F][114]=1;s.u[0][W][114]=4;
    Action current;current.moves={{F,112,127,2},{W,112,127,7},{F,114,129,1},{W,114,129,4}};
    auto choices=s3_choices(s,0,current,112,true);
    bool flag_wait=false,warrior_wait=false,both_wait=false,reserve=false,split=false;
    for(const Action& a:choices) {
        assert(a_equal(a,a_clean(s,0,a)));
        int fm=0,wm=0,wdepart=0;vector<int> wt;
        for(auto m:a.moves) if(m.from==112) {
            fm+=m.kind==F;wm+=m.kind==W;
            if(m.kind==W) {wdepart+=m.count;wt.push_back(m.to);}
        }
        flag_wait|=!fm && wm;warrior_wait|=fm && !wm;both_wait|=!fm && !wm;
        reserve|=wdepart>0 && wdepart<7;
        split|=wt.size()==2 && wt[0]!=wt[1] && wdepart==7;
        assert(wdepart<=7);
    }
    assert(flag_wait && warrior_wait && both_wait && reserve && split);
    // Joint convergence changes both origins atomically; independent greedy acceptance is not required.
    bool converge=false;
    for(const Action& a:s3_joint_choices(s,0,current,112,114)) {
        assert(a_equal(a,a_clean(s,0,a)));
        int left=0,right=0;
        for(auto m:a.moves) if(m.kind==W && m.to==113) {left+=m.from==112?m.count:0;right+=m.from==114?m.count:0;}
        converge|=left==7 && right==4;
    }
    assert(converge);
    // Sanitization cannot spend arriving units, and generated splits preserve production budgets.
    s.u[0][W][1]=7;
    Action produced;produced.spawn={{W,0,2}};produced.moves={{W,1,0,7}};
    produced=a_clean(s,0,produced);
    for(const Action& a:s3_choices(s,0,produced,0,true)) {
        assert(a_equal(a,a_clean(s,0,a)));
        int spent=0;for(auto m:a.moves) if(m.from==0 && m.kind==W) spent+=m.count;
        assert(spent<=2);
    }
    assert(s3_contact(s,0,112));
    assert(!s3_contact(s,0,114));
    s.u[1][W][113]=5;assert(s3_contact(s,0,114));
    auto fallback=a_clean(s,0,policy(s,0,0));
    auto expired=s3_decide(s,0,AClock::now(),-1);
    assert(a_equal(expired,fallback));
    double weights[4]{.25,.25,.25,.25};
    APlan best{current,0,12345};
    assert(!s3_try(s,0,fallback,0,3,weights,AClock::now(),-1,best));
    assert(a_equal(best.action,current) && best.value==12345);
    auto started=AClock::now();auto live=s3_decide(s,0,started,20);
    assert(a_equal(live,a_clean(s,0,live)));
    assert(chrono::duration<double,milli>(AClock::now()-started).count()<300);
    return 0;
}
'''


class V3ActionSearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / 'submissions/iterative-v3/main.cpp').read_text()
        cls.candidates = SEARCH.variants(cls.source)

    def test_population_and_frozen_rules(self):
        self.assertEqual(len(self.candidates), 7)
        self.assertEqual(len({hashlib.sha256(c['source'].encode()).hexdigest() for c in self.candidates}), 7)
        transition = self.source.split('State advance(', 1)[1].split('double building_value(', 1)[0]
        evaluation = self.source.split('double evaluation(', 1)[1].split('constexpr int A_MIX=', 1)[0]
        observation = self.source.split('    State s; s.turn=v.turn-1;', 1)[1].split('    Action a=forced_policy', 1)[0]
        for candidate in self.candidates:
            self.assertIn(transition, candidate['source'])
            self.assertIn(evaluation, candidate['source'])
            self.assertIn(observation, candidate['source'])
            self.assertTrue(candidate['id'].startswith('s3_'))
        with self.assertRaises(ValueError):
            SEARCH.variants(self.source.replace('Action a_decide(', 'Action changed('))

    def test_all_variants_compile_action_conservation_and_budget(self):
        with tempfile.TemporaryDirectory(prefix='yk-v3-action-', dir='/tmp') as folder:
            folder = Path(folder)
            for candidate in self.candidates:
                src, binary = folder / 'check.cpp', folder / 'check'
                src.write_text('#define main bot_main\n' + candidate['source'] + HARNESS)
                build = subprocess.run(['g++', '-std=c++20', '-O2', '-I', str(ROOT / 'submissions/iterative-v3'),
                                        str(src), '-o', str(binary)], capture_output=True, text=True, timeout=60)
                self.assertEqual(build.returncode, 0, candidate['id'] + '\n' + build.stderr)
                check = subprocess.run([str(binary)], capture_output=True, text=True, timeout=5)
                self.assertEqual(check.returncode, 0, candidate['id'] + '\n' + check.stderr)


if __name__ == '__main__':
    unittest.main()
