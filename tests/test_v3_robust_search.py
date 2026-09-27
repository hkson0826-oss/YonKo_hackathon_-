from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('v3_robust', ROOT / 'experiments/local_league/v3_robust_search.py')
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
sys.path.insert(0, str(ROOT / 'yk-development-tools'))
from engine.commands import Move
from engine.config import load_config
from engine.pipeline import run_turn
from engine.state import Building, new_game

HARNESS = r'''
#undef main
#include <cassert>
void legal(const State& s,int t,const Action& a) {
    assert(a_equal(a,a_clean(s,t,a)));
    int left[3][N],budget=s.res[t];
    for(int k=0;k<3;++k)copy(s.u[t][k],s.u[t][k]+N,left[k]);
    for(auto p:a.spawn) {budget-=cost(s,t,p.kind)*p.count;assert(budget>=0);left[p.kind][p.pos]+=p.count;}
    for(auto m:a.moves) {left[m.kind][m.from]-=m.count;assert(left[m.kind][m.from]>=0);}
}
int main(int argc,char** argv) {
    p::Init in;in.width=in.height=15;in.terrain.assign(15,string(15,'.'));
    in.bases={pair{0,7},pair{14,7}};
    in.buildings={{0,7,7,"WATCH"},{1,5,7,"ENG"},{2,10,10,"HOSPITAL"}};board.init(in);
    State s;s.turn=159;fill(s.owner,s.owner+BMAX,-1);for(int b=0;b<board.nb;++b)s.score[b]=b?1:4;
    s.owner[0]=0;s.owner[1]=1;s.u[0][F][112]=1;s.u[1][W][113]=2;
    string test=argc>1?argv[1]:"response";
    if(test=="response") {
        Action own,opp;auto before=s;
        assert(r3_response(s,0,own,opp,2,AClock::now(),1000));legal(s,1,opp);
        auto after=r3_step(s,0,own,opp);assert(after.u[0][F][112]==0 && after.owner[0]==-1);
        assert(s.u[0][F][112]==1 && s.owner[0]==0);
        for(auto m:opp.moves)cout<<m.kind<<" "<<m.from<<" "<<m.to<<" "<<m.count<<"\n";
    } else if(test=="matrix") {
        assert(r3_regret_choice({{9,0},{4,4}})==0);
        auto matching=r3_mixture({{1,-1},{-1,1}});
        assert(abs(matching[0]-.5)<1e-9 && abs(matching[1]-.5)<1e-9);
        auto dominated=r3_mixture({{3,3},{0,0}});
        assert(dominated[0]>.99 && dominated[1]<.01);
        auto rock=r3_mixture({{0,-1,1},{1,0,-1},{-1,1,0}});
        assert(abs(accumulate(rock.begin(),rock.end(),0.0)-1)<1e-9);
        for(double x:rock)assert(abs(x-1./3)<1e-9);
    } else if(test=="deadline") {
        double value=123;double weights[4]={.25,.25,.25,.25};Action empty;
        assert(!a_evaluate(s,0,empty,0,3,weights,AClock::now(),-1,value));assert(value==123);
        Action opponent;assert(!r3_response(s,0,empty,opponent,2,AClock::now(),-1));
        auto expected=a_clean(s,0,policy(s,0,0));
        auto old=AClock::now()-chrono::seconds(1);assert(a_equal(r3_decide(s,0,old),expected));
    } else if(test=="observe") {
        s.turn=20;s.res[0]=s.res[1]=20;Action own=policy(s,0,0);
        r3_previous=true;r3_previous_state=s;r3_previous_action=own;
        auto observed=r3_step(s,0,own,r3_fixed(s,1,0));
        r3_observe(observed,0,AClock::now(),1000);
        assert(r3_error[0]==0);assert(abs(accumulate(r3_weights,r3_weights+6,0.0)-1)<1e-9);
        for(double w:r3_weights)assert(w>=.1 && w<=.5);
        double saved[6];copy(r3_error,r3_error+6,saved);observed.turn+=2;
        r3_observe(observed,0,AClock::now(),1000);
        for(int j=0;j<6;++j)assert(saved[j]==r3_error[j]);
    } else if(test=="legal") {
        mt19937 random(721399);
        for(int rep=0;rep<80;++rep) {
            State state;state.turn=random()%160;
            for(int b=0;b<board.nb;++b){state.owner[b]=int(random()%3)-1;state.score[b]=1+random()%4;}
            for(int t=0;t<2;++t){state.res[t]=random()%41;for(int j=0;j<12;++j)state.u[t][j%2][random()%N]+=1+random()%8;}
            for(int t=0;t<2;++t) for(int model=0;model<6;++model)legal(state,t,r3_fixed(state,t,model));
        }
        State spawn=s;spawn.res[1]=6;spawn.u[1][W][board.base[1]]=2;
        Action dirty;dirty.spawn={{W,board.base[1],20}};
        dirty.moves={{W,board.base[1],board.base[1]-1,20},{W,board.base[1]-1,board.base[1]-2,20}};
        auto a=r3_redirect(spawn,1,dirty,board.base[1],board.base[1]-1,false);legal(spawn,1,a);
        assert(a.spawn[0].count==6/cost(spawn,1,W) && a.moves.size()==1 && a.moves[0].count==2);
    }
}
'''


class V3RobustSearchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / 'submissions/iterative-v3/main.cpp').read_text()
        cls.rows = MODULE.variants(cls.source)
        cls.tmp = tempfile.TemporaryDirectory(prefix='yk-v3-robust-', dir='/tmp')
        cls.folder = Path(cls.tmp.name)
        source = cls.folder / 'bridge.cpp'
        source.write_text('#define main submitted_main\n' + cls.rows[5]['source'] + HARNESS)
        cls.binary = cls.folder / 'bridge'
        result = subprocess.run(['g++','-std=c++20','-O2','-I',str(ROOT/'submissions/iterative-v3'),str(source),'-o',str(cls.binary)],capture_output=True,text=True,timeout=90)
        if result.returncode:
            cls.tmp.cleanup()
            raise AssertionError(result.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def invoke(self, scenario):
        result = subprocess.run([str(self.binary),scenario],capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr)
        return result.stdout

    def test_eight_distinct_sources_preserve_v3_transition_observation_and_actual_policy(self):
        self.assertEqual(len(self.rows),8)
        self.assertEqual(len({r['source'] for r in self.rows}),8)
        self.assertEqual(hashlib.sha256(self.source.encode()).hexdigest(),'52268569e17d7fc40fd46f0996b2da684768902b4af27ec059c4b068911c4473')
        for row in self.rows:
            self.assertEqual(row['source'].split('State advance(',1)[1].split('double building_value(',1)[0],self.source.split('State advance(',1)[1].split('double building_value(',1)[0])
            self.assertEqual(row['source'].split('Action policy(',1)[1].split('double evaluation(',1)[0],self.source.split('Action policy(',1)[1].split('double evaluation(',1)[0])
            observation=row['source'].split('vector<string> decide(',1)[1].replace('r3_decide(s,us,start);','a_decide(s,us,start);')
            self.assertEqual(observation,self.source.split('vector<string> decide(',1)[1])
            self.assertEqual(row['parameters']['opponent_scope'],'internal_only')
        with self.assertRaises(ValueError): MODULE.variants('invalid source')

    def test_all_sources_compile(self):
        for row in self.rows:
            p=self.folder/(row['id']+'.cpp');p.write_text(row['source'])
            r=subprocess.run(['g++','-std=c++20','-fsyntax-only','-I',str(ROOT/'submissions/iterative-v3'),str(p)],capture_output=True,text=True,timeout=60)
            self.assertEqual(r.returncode,0,row['id']+'\n'+r.stderr)

    def test_minimax_regret_and_zero_sum_matrix_counterexamples(self):
        self.invoke('matrix')

    def test_incomplete_evaluation_is_rejected_and_legal_fallback_survives(self):
        self.invoke('deadline')

    def test_opponent_weights_use_only_adjacent_observed_transition(self):
        self.invoke('observe')

    def test_960_random_model_actions_and_spawn_budget_no_arrival_reuse(self):
        self.invoke('legal')

    def test_adversarial_local_response_matches_official_engine(self):
        commands=[]
        for line in self.invoke('response').splitlines():
            kind,src,dst,count=map(int,line.split())
            commands.append(Move(src%15,src//15,'FWS'[kind],count,{1:'R',-1:'L',15:'D',-15:'U'}[dst-src]))
        state=new_game(load_config(),buildings=[Building(0,7,7,'WATCH',4,'Y',2),Building(1,5,7,'ENG',1,'K',2)],resources={'Y':0,'K':0})
        state.add_unit(7,7,'Y','F',1);state.add_unit(8,7,'K','W',2)
        after,_=run_turn(state,[],commands)
        self.assertEqual(after.get_unit(7,7,'Y','F'),0)
        self.assertEqual(after.buildings[0].owner,'N')


if __name__=='__main__':
    unittest.main()
