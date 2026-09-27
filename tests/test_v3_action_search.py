import hashlib
import importlib.util
import json
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


REVISION_CHECKS = r'''
    double base_values[4]{-46.3334821429,-46.3334821429,-46.3334821429,-51.7389583333};
    double bad_values[4]{-12.3209821429,-12.3209821429,-12.3209821429,-82.565922619};
    double good_base[4]{150.990613831,150.990613831,117.959101662,156.204304307};
    double good_values[4]{152.411598679,151.361598679,119.716393329,156.575289155};
    assert(s3v2_minimum_gain(base_values,bad_values)<-30);
    assert(s3v2_minimum_gain(good_base,good_values)>0);
    if(S3V2_MODE==1) {
        assert(!s3v2_accept(-43.053143601,-48.698377976,s3v2_minimum_gain(base_values,bad_values)));
        assert(s3v2_accept(138.691263303,137.516894221,s3v2_minimum_gain(good_base,good_values)));
    }
    if(S3V2_MODE==1 || S3V2_MODE==3) {
        assert(!s3v2_accept(20,10,-.001));
        assert(s3v2_accept(20,10,0));
    }
    assert(!s3v2_accept(10,10,100));
    assert(!s3v2_accept(9,10,100));
    double expected=0,actual=0,values[4]{};
    assert(a_evaluate(s,0,fallback,0,3,weights,AClock::now(),1000,expected));
    assert(s3v2_values(s,0,fallback,0,3,weights,AClock::now(),1000,values,actual));
    assert(abs(expected-actual)<1e-9);
    actual=12345;
    assert(!s3v2_values(s,0,fallback,0,3,weights,AClock::now(),-1,values,actual));
    assert(actual==12345);
'''


class V3ActionRevisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / 'submissions/iterative-v3/main.cpp').read_text()
        cls.candidates = SEARCH.variants_iteration2(cls.source)

    def test_original_hashes_and_revision_population(self):
        original = json.loads((ROOT / 'records/league/loop3-design/action-search-validation.json').read_text())
        expected = {c['id']: c['source_sha256'] for c in original['candidates']}
        actual = {c['id']: hashlib.sha256(c['source'].encode()).hexdigest() for c in SEARCH.variants(self.source)}
        self.assertEqual(expected, actual)
        self.assertEqual(len(self.candidates), 4)
        self.assertEqual(len({hashlib.sha256(c['source'].encode()).hexdigest() for c in self.candidates}), 4)
        for candidate in self.candidates:
            self.assertTrue(candidate['id'].startswith('s3_v2_'))
            self.assertEqual(candidate['parameters']['parent'], 's3_screen_refine')
            self.assertIn(self.source.split('State advance(', 1)[1].split('double building_value(', 1)[0], candidate['source'])
            self.assertIn(self.source.split('double evaluation(', 1)[1].split('constexpr int A_MIX=', 1)[0], candidate['source'])
            self.assertIn(self.source.split('    State s; s.turn=v.turn-1;', 1)[1].split('    Action a=forced_policy', 1)[0], candidate['source'])

    def test_revisions_compile_counterexamples_legality_and_deadline(self):
        with tempfile.TemporaryDirectory(prefix='yk-v3-action-revision-', dir='/tmp') as folder:
            folder = Path(folder)
            harness = HARNESS.replace('    return 0;\n}', REVISION_CHECKS + '\n    return 0;\n}')
            for candidate in self.candidates:
                src, binary = folder / 'check.cpp', folder / 'check'
                src.write_text('#define main bot_main\n' + candidate['source'] + harness)
                build = subprocess.run(['g++', '-std=c++20', '-O2', '-I', str(ROOT / 'submissions/iterative-v3'),
                                        str(src), '-o', str(binary)], capture_output=True, text=True, timeout=60)
                self.assertEqual(build.returncode, 0, candidate['id'] + '\n' + build.stderr)
                check = subprocess.run([str(binary)], capture_output=True, text=True, timeout=5)
                self.assertEqual(check.returncode, 0, candidate['id'] + '\n' + check.stderr)


if __name__ == '__main__':
    unittest.main()
