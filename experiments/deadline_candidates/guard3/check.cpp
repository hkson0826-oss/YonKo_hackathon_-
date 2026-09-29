#define main guard1_program_main
#include "main.cpp"
#undef main
#include <cassert>
void setup(vector<p::Building> buildings,pair<int,int> home={1,5}) {
    board=Board{};p::Init in;in.width=in.height=15;in.team="Y";in.opp="K";
    in.terrain=vector<string>(15,string(15,'.'));in.bases={home,pair{13,9}};in.buildings=buildings;board.init(in);
}
int c(int x,int y){return x+15*y;}
int moving(const Action& a,int src,int to) {int n=0;for(auto m:a.moves) if(m.kind==W && m.from==src && m.to==to)n+=m.count;return n;}
int production(const Action& a,int src){int n=0;for(auto p:a.spawn)if(p.kind==W && p.pos==src)n+=p.count;return n;}
int total_production(const Action& a){int n=0;for(auto p:a.spawn)n+=p.count* (p.kind==W?2:5);return n;}
int main(){
    setup({{0,1,10,"HALL","Y"}});
    State s;s.turn=10;s.res[0]=12;s.owner[0]=0;s.u[1][F][c(7,10)]=1;s.u[0][W][c(3,7)]=2;
    Action a;a.moves.push_back({W,c(3,7),c(4,7),2});
    Action fixed=deadline_guard(s,0,a);
    assert(moving(fixed,c(3,7),c(3,8))==1);
    assert(moving(fixed,c(3,7),c(4,7))==1);
    s.u[1][W][c(6,10)]=1;assert(a_equal(deadline_guard(s,0,a),a));
    s.u[1][W][c(6,10)]=0;s.turn=150;assert(a_equal(deadline_guard(s,0,a),a));
    s.turn=10;s.u[0][W][c(3,7)]=0;s.u[0][W][c(9,7)]=2;
    Action late;late.moves.push_back({W,c(9,7),c(8,7),2});assert(a_equal(deadline_guard(s,0,late),late));
    setup({{0,0,9,"ENG","Y"},{1,1,1,"HALL","Y"},{2,4,4,"HOSPITAL","Y"}});
    s=State{};s.turn=18;s.res[0]=12;s.owner[0]=s.owner[1]=s.owner[2]=0;
    s.u[1][F][c(0,14)]=1;s.u[1][F][c(7,1)]=1;
    a=Action{};a.spawn.push_back({W,c(4,4),6});a.moves.push_back({W,c(4,4),c(5,4),6});
    fixed=deadline_guard(s,0,a);
    assert(production(fixed,c(1,5))==1);
    assert(production(fixed,c(4,4))==5);
    assert(total_production(fixed)==total_production(a));
    assert(moving(fixed,c(1,5),c(1,6))==1);
    // The other defense may use the hospital stock since its ETA is exactly six.
    assert(moving(fixed,c(4,4),c(4,3))==1);
    assert(moving(fixed,c(4,4),c(5,4))==4);
    setup({{0,1,10,"HALL","Y"}});
    s=State{};s.turn=10;s.owner[0]=0;s.u[1][F][c(3,10)]=1;s.u[0][W][c(1,10)]=1;
    a=Action{};a.moves.push_back({W,c(1,10),c(2,10),1});fixed=deadline_guard(s,0,a);
    assert(fixed.moves.empty());

    // Diverting the sole W would expose the seed's F to one adjacent enemy W.
    setup({{0,1,10,"HALL","Y"}});
    s=State{};s.turn=10;s.owner[0]=0;
    s.u[1][F][c(3,10)]=1;s.u[1][W][c(4,9)]=1;
    s.u[0][F][c(3,8)]=1;s.u[0][W][c(2,9)]=1;
    a=Action{};a.moves={{F,c(3,8),c(3,9),1},{W,c(2,9),c(3,9),1}};
    assert(a_equal(deadline_guard(s,0,a),a));
    // The other available origin can defend without breaking that escort.
    s.u[0][W][c(1,12)]=1;a.moves.push_back({W,c(1,12),c(2,12),1});
    fixed=deadline_guard(s,0,a);
    assert(moving(fixed,c(2,9),c(3,9))==1);
    assert(moving(fixed,c(1,12),c(1,11))==1);
    // Moving production away is subject to the same projected-F protection.
    setup({{0,1,10,"HALL","Y"},{1,2,9,"HOSPITAL","Y"}},{1,9});
    s=State{};s.turn=10;s.res[0]=3;s.owner[0]=s.owner[1]=0;
    s.u[1][F][c(3,10)]=1;s.u[1][W][c(4,9)]=1;s.u[0][F][c(3,8)]=1;
    a=Action{};a.spawn={{W,c(2,9),1}};a.moves={{F,c(3,8),c(3,9),1},{W,c(2,9),c(3,9),1}};
    assert(a_equal(deadline_guard(s,0,a),a));
    // An enemy F currently at its station can TELE once, then walk to HALL.
    setup({{0,1,10,"HALL","Y"},{1,13,1,"STATION","K"},{2,3,10,"STATION","K"}});
    s=State{};s.turn=10;s.owner[0]=0;s.owner[1]=s.owner[2]=1;
    s.u[1][F][c(13,1)]=1;s.u[0][W][c(1,7)]=1;
    a=Action{};a.moves={{W,c(1,7),c(2,7),1}};
    fixed=deadline_guard(s,0,a);assert(moving(fixed,c(1,7),c(1,8))==1);
    s.owner[2]=-1;assert(a_equal(deadline_guard(s,0,a),a));
    s.owner[2]=1;s.owner[1]=-1;assert(a_equal(deadline_guard(s,0,a),a));
    s.owner[1]=1;s.u[1][W][c(13,1)]=1;assert(a_equal(deadline_guard(s,0,a),a));
    std::cout<<"guard3: all guard1 checks plus escort, safe alternate, production escort, TELE ETA/ownership and W TELE checks passed\n";
}
