#define main midgame_bot_main
#include "main.cpp"
#undef main
#include <cassert>

void legal(const State& s,int t,const Action& a) {
    assert(a_equal(a,a_clean(s,t,a)));
    int stock[3][N]{},money=s.res[t],tele=0;
    for(int k=0;k<3;++k) copy(s.u[t][k],s.u[t][k]+N,stock[k]);
    for(auto p:a.spawn) {
        int b=board.at[p.pos]; assert(p.count>0);
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

int main() {
    p::Init in;in.width=in.height=15;in.terrain.assign(15,string(15,'.'));in.bases={pair{0,7},pair{14,7}};
    in.buildings={{0,7,7,"ENG"},{1,6,7,"HOSPITAL"},{2,0,0,"WATCH"},{3,14,14,"WATCH"}};
    board.init(in);
    State s;s.turn=100;fill(s.owner,s.owner+BMAX,-1);
    s.owner[0]=s.owner[1]=s.owner[2]=0;s.owner[3]=1;
    for(int b=0;b<board.nb;++b)s.score[b]=2;
    s.u[0][F][112]=1;s.u[0][W][111]=3;s.u[0][W][113]=3;
    s.u[1][F][97]=1;s.u[1][W][127]=5;
    Action seed;seed.moves={{F,112,97,1},{W,111,110,3},{W,113,114,3}};
    Action enemy;enemy.moves={{F,97,112,1},{W,127,112,5}};
    Action jointly;assert(m1_preserve(s,0,seed,0,jointly));legal(s,0,jointly);
    State after=advance(s,jointly,enemy);assert(after.owner[0]==0 && after.u[0][F][112]==1);
    // Both partial repairs lose ownership; holding F and converging W must be atomic.
    Action only_flag=seed;only_flag.moves.erase(only_flag.moves.begin());
    assert(advance(s,only_flag,enemy).owner[0]!=0);
    Action only_w=jointly;only_w.moves.push_back({F,112,97,1});
    assert(advance(s,only_w,enemy).owner[0]!=0);
    // Insufficient stock must not be invented or funded by same-turn arrivals.
    State shortfall=s;shortfall.u[0][W][111]=0;shortfall.u[0][W][110]=3;
    Action arriving=seed;arriving.moves={{F,112,97,1},{W,110,111,3},{W,113,114,3}};
    Action impossible;assert(!m1_preserve(shortfall,0,arriving,0,impossible));
    // Same-turn production may reinforce when spawned at an owned adjacent hospital.
    shortfall.u[0][W][110]=0;shortfall.res[0]=6;Action produced=seed;
    produced.spawn={{W,111,3}};assert(m1_preserve(shortfall,0,produced,0,jointly));legal(shortfall,0,jointly);
    assert(advance(shortfall,jointly,enemy).owner[0]==0);
    State quiet=s;quiet.u[1][W][127]=quiet.u[1][F][97]=0;
    assert(!m1_preserve(quiet,0,seed,0,impossible));
    mt19937 random(202609291);double maximum=0;int generated=0;
    for(int rep=0;rep<18;++rep) {
        State r;r.turn=25+random()%132;r.res[0]=random()%41;r.res[1]=random()%41;
        for(int b=0;b<board.nb;++b){r.owner[b]=int(random()%3)-1;r.score[b]=1+random()%4;if(r.owner[b]>=0)r.u[r.owner[b]][F][board.pos[b]]=1;}
        for(int t=0;t<2;++t)for(int i=0;i<24;++i){int c=random()%N;r.u[t][F][c]+=random()%2;r.u[t][W][c]+=1+random()%14;}
        for(int us=0;us<2;++us) {
            Action original=a_clean(r,us,policy(r,us,0));
            for(int b=0;b<board.nb;++b){Action candidate;if(m1_preserve(r,us,original,b,candidate)){legal(r,us,candidate);++generated;}}
            auto started=AClock::now();Action actual=s3_decide(r,us,started);double ms=chrono::duration<double,milli>(AClock::now()-started).count();
            legal(r,us,actual);maximum=max(maximum,ms);assert(ms<300);
        }
    }
    auto expired=AClock::now();assert(a_equal(s3_decide(s,0,expired,-1),m1_base_decide(s,0,expired,-1)));
    cout<<"joint_hold_convergence=pass partial_repairs_fail=pass no_arrival_reuse=pass same_turn_production=pass decisions=36 generated_candidates="<<generated<<" legality=pass max_ms="<<maximum<<"\n";
}
