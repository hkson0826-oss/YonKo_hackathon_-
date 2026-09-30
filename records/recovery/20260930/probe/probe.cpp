#define main submission_main
#include "main.cpp"
#undef main
#include "old_guard.inc"
#include <cassert>
int checks=0;
bool equal(const Action&a,const Action&b) {
    if(a.spawn.size()!=b.spawn.size()||a.moves.size()!=b.moves.size()||a.priority!=b.priority)return false;
    for(size_t i=0;i<a.spawn.size();++i) {auto x=a.spawn[i],y=b.spawn[i];if(x.kind!=y.kind||x.pos!=y.pos||x.count!=y.count)return false;}
    for(size_t i=0;i<a.moves.size();++i) {auto x=a.moves[i],y=b.moves[i];if(x.kind!=y.kind||x.from!=y.from||x.to!=y.to||x.count!=y.count||x.tele!=y.tele)return false;}
    return true;
}
void check(string name,bool ok) {cout<<name<<": "<<(ok?"PASS":"FAIL")<<endl;++checks;if(!ok)exit(2);}
State setup(vector<pair<int,int>> econ={{78,ENG}}) {
    p::Init in;in.width=in.height=15;in.terrain=vector<string>(15,string(15,'.'));in.bases[0]={1,5};in.bases[1]={14,5};
    int i=0;for(auto [pos,type]:econ)in.buildings.push_back({i++,pos%15,pos/15,types[type]});
    board=Board{};board.init(in);State s;s.turn=20;fill(s.owner,s.owner+BMAX,-1);for(int b=0;b<board.nb;++b)s.owner[b]=0;s.u[1][F][83]=1;return s;
}
int projected_w(const State&s,const Action&a,int pos) {int n=s.u[0][W][pos];for(auto p:a.spawn)if(p.kind==W&&p.pos==pos)n+=p.count;for(auto m:a.moves)if(m.kind==W){if(m.from==pos)n-=m.count;if(m.to==pos)n+=m.count;}return n;}
int main() {
#include "fixtures.inc"
    for(int incoming=0;incoming<=5;++incoming){
        State s=setup();s.u[0][W][78]=1;s.u[0][W][77]=incoming;
        Action a;a.moves={{W,78,79,1}};if(incoming)a.moves.push_back({W,77,78,incoming});
        auto old=old_guard(s,0,a),now=deadline_guard(s,0,a);
        check("threshold_"+to_string(incoming),incoming<3?equal(old,now):equal(now,a_clean(s,0,a)));
        check("defense_retained_"+to_string(incoming),projected_w(s,now,78)>=1);
    }
    {
        State s=setup();s.u[0][W][78]=1;board.base[0]=77;s.res[0]=6;
        Action a;a.spawn={{W,77,3}};a.moves={{W,78,79,1},{W,77,78,3}};
        check("same_turn_production_counts",equal(deadline_guard(s,0,a),a_clean(s,0,a)));
        s.res[0]=4;
        check("clipped_production_does_not_skip",equal(deadline_guard(s,0,a),old_guard(s,0,a)));
    }
    {
        State s=setup({{77,ENG},{79,HALL},{93,HALL}});s.u[0][W][78]=3;s.u[1][F][83]=0;s.u[1][F][82]=1;
        Action a;a.moves={{W,78,77,3}};auto b=deadline_guard(s,0,a);
        check("two_other_reservations_keep_one",projected_w(s,b,77)>=1);
        check("two_other_reservations_happen",projected_w(s,b,77)==1);
    }
    {
        State s=setup();s.u[0][W][78]=1;s.u[0][F][78]=1;
        Action a;a.moves={{W,78,79,1},{F,78,79,1}};
        check("flag_escort_stays_intact",equal(deadline_guard(s,0,a),a_clean(s,0,a)));
    }
    {
        State s=setup();s.u[0][W][78]=1;s.u[0][W][77]=3;s.u[1][W][79]=1;
        Action a;a.moves={{W,78,79,1},{W,77,78,3}};
        check("enemy_warrior_threat_unchanged",equal(deadline_guard(s,0,a),old_guard(s,0,a)));
        s.turn=150;
        check("turn150_unchanged",equal(deadline_guard(s,0,a),a));
    }
    {
        State s=setup({{78,ENG},{202,STATION},{82,STATION}});s.owner[1]=s.owner[2]=1;
        s.u[1][F][83]=0;s.u[1][F][202]=1;s.u[0][W][78]=1;
        Action a;a.moves={{W,78,79,1}};
        auto b=deadline_guard(s,0,a);
        check("enemy_flag_teleport_alert_preserved",equal(b,old_guard(s,0,a))&&!equal(b,a_clean(s,0,a)));
    }
    {
        State s=setup({{78,ENG},{77,STATION},{50,STATION}});s.u[0][W][50]=3;s.u[0][W][78]=1;
        Action a;a.moves={{W,78,79,1},{W,50,77,3,true},{W,77,78,3}};
        auto b=deadline_guard(s,0,a);
        check("teleport_arrival_not_reused",equal(b,old_guard(s,0,a))&&projected_w(s,b,78)>=1);
    }
    cout<<"checks="<<checks<<" all_passed=true\n";
}
