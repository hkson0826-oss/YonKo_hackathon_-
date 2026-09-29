#define main endgame_bot_main
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
    in.buildings={{0,5,7,"ENG"},{1,9,7,"HALL"},{2,10,10,"HOSPITAL"},{3,0,0,"WATCH"},{4,14,14,"WATCH"}};
    board.init(in);
    State joint;joint.turn=159;joint.res[0]=joint.res[1]=0;fill(joint.owner,joint.owner+BMAX,-1);
    joint.owner[3]=0;joint.owner[4]=1;joint.score[0]=joint.score[1]=3;joint.score[2]=1;joint.score[3]=1;joint.score[4]=5;
    joint.u[0][F][109]=joint.u[0][F][115]=1;
    Action abandoned;abandoned.moves={{F,109,94,1},{F,115,100,1}};
    vector<Action> first=e1_choices(joint,0,abandoned,109);
    bool paired=false;
    for(const Action& a:first) for(const Action& b:e1_choices(joint,0,a,115)) {
        legal(joint,0,b);State next=advance(joint,b,Action{});
        paired|=next.owner[0]==0 && next.owner[1]==0 && evaluation(next,0)>80000;
    }
    assert(paired);
    // A terminal attack only needs to neutralize an enemy-owned site to deny its points.
    joint.owner[0]=1;joint.u[0][F][115]=0;joint.score[0]=6;
    bool denied=false;
    for(const Action& a:e1_choices(joint,0,abandoned,109)) {
        State next=advance(joint,a,Action{});denied|=next.owner[0]==-1;
    }
    assert(denied);
    // A spawned flag is a source in the same turn; arriving flags are not.
    joint.turn=158;joint.res[0]=5;joint.owner[2]=0;
    Action production;production.spawn={{F,160,1}};production=a_clean(joint,0,production);
    auto groups=e1_groups(joint,0,production);
    assert(find(groups.begin(),groups.end(),160)!=groups.end());
    for(auto a:e1_choices(joint,0,production,160)) legal(joint,0,a);
    mt19937 random(20260929);double maximum=0;
    for(int rep=0;rep<18;++rep) {
        State s;s.turn=157+rep%3;s.res[0]=random()%41;s.res[1]=random()%41;
        for(int b=0;b<board.nb;++b){s.owner[b]=int(random()%3)-1;s.score[b]=1+random()%4;}
        for(int t=0;t<2;++t)for(int i=0;i<24;++i){int c=random()%N;s.u[t][F][c]+=random()%2;s.u[t][W][c]+=1+random()%14;}
        for(int us=0;us<2;++us) {
            Action seed=a_clean(s,us,policy(s,us,0));
            for(int c:e1_groups(s,us,seed))for(const Action& a:e1_choices(s,us,seed,c))legal(s,us,a);
            auto started=AClock::now();Action result=s3_decide(s,us,started);double ms=chrono::duration<double,milli>(AClock::now()-started).count();
            legal(s,us,result);maximum=max(maximum,ms);assert(ms<300);
        }
    }
    joint.turn=80;auto now=AClock::now();
    assert(a_equal(s3_decide(joint,0,now,-1),s3_base_decide(joint,0,now,-1)));
    cout<<"joint_capture=pass neutralization=pass production_stock=pass random_states=36 legality=pass max_ms="<<maximum<<"\n";
}
