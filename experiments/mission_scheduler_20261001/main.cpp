#include "protocol.hpp"
#include <chrono>
#include <cmath>
#include <limits>
#include <numeric>
#include <queue>
#include <tuple>

using namespace std;
namespace mission {
constexpr int CELLS = 225, MAX_BUILDINGS = 32, INF = 10000;
enum Kind { F, W, S };
enum Type { PLAZA, HALL, STATION, LIBRARY, ENG, HOSPITAL, WATCH, DEPOT };
const array<string, 8> names = {"PLAZA", "HALL", "STATION", "LIBRARY", "ENG", "HOSPITAL", "WATCH", "DEPOT"};
struct Board {
    int width = 15, height = 15, size = 225, count = 0, home = 0, away = 224;
    bool reverse = false;
    array<int, CELLS> at{};
    array<vector<int>, CELLS> adj;
    int distance[CELLS][CELLS]{};
    array<int, MAX_BUILDINGS> pos{}, type{}, id{};
    int canonical(int c) const { return reverse ? size - 1 - c : c; }
    void init(const p::Init& in) {
        width = in.width; height = in.height; size = width * height;
        if (size > CELLS || in.buildings.size() > MAX_BUILDINGS) throw runtime_error("map limit");
        reverse = in.team == "K";
        home = in.base().first + width * in.base().second;
        auto eb = in.bases[in.team == "Y" ? 1 : 0]; away = eb.first + width * eb.second;
        at.fill(-1); count = int(in.buildings.size());
        for (int c = 0; c < size; ++c) {
            adj[c].clear();
            if (!in.passable(c % width, c / width)) continue;
            for (auto [dx,dy] : {pair{0,-1}, pair{0,1}, pair{-1,0}, pair{1,0}})
                if (in.passable(c % width + dx,c / width + dy)) adj[c].push_back(c + dx + width * dy);
            sort(adj[c].begin(), adj[c].end(), [&](int a,int b) {return canonical(a) < canonical(b);});
        }
        for (int b = 0; b < count; ++b) {
            const auto& v = in.buildings[b]; pos[b] = v.x + width * v.y; id[b] = v.id; at[pos[b]] = b;
            type[b] = int(find(names.begin(), names.end(), v.type) - names.begin());
        }
        for (int c = 0; c < size; ++c) {
            fill(distance[c], distance[c] + size, INF);
            if (!in.passable(c % width, c / width)) continue;
            queue<int> q; q.push(c); distance[c][c] = 0;
            while (!q.empty()) {int v=q.front();q.pop(); for (int n:adj[v]) if (distance[c][n] == INF) {
                distance[c][n]=distance[c][v]+1;q.push(n);
            }}
        }
    }
} board;

struct World {
    int turn = 0, left = 0, money = 0, enemyMoney = 0, warriorCost = 3, enemyWarriorCost = 3;
    int own[3][CELLS]{}, enemy[3][CELLS]{};
    array<int, MAX_BUILDINGS> owner{}, stage{};
    array<double, MAX_BUILDINGS> points{};
    vector<int> sites, enemySites, stations, enemyStations;
    bool library = false, engineering = false;
    bool has(int side, int type) const {
        for (int b=0;b<board.count;++b) if (owner[b]==side && board.type[b]==type) return true;
        return false;
    }
    explicit World(const p::View& v,const p::Init& in) {
        turn=v.turn;left=max(0,161-turn);money=v.my_resource;enemyMoney=v.opp_resource;
        owner.fill(-1);points.fill(-1);
        for (auto& u:v.units) {
            int c=u.x+board.width*u.y; int k=u.kind=="F"?F:u.kind=="W"?W:S;
            if (c>=0&&c<board.size) (u.team==in.team?own:enemy)[k][c]+=u.count;
        }
        for (auto& b:v.buildings) {
            int i=board.at[b.x+board.width*b.y];if(i<0)continue;
            owner[i]=b.owner==in.team?0:b.owner==in.opp?1:-1;stage[i]=b.stage;
            points[i]=b.score>=0?b.score:-1;
        }
        const auto observedPoints=points;
        for (int b=0;b<board.count;++b) if (observedPoints[b]<0) {
            int mirror=board.at[board.size-1-board.pos[b]];
            bool center=board.pos[b]%board.width>=5&&board.pos[b]%board.width<=9;
            points[b]=mirror>=0&&observedPoints[mirror]>=0?observedPoints[mirror]:(center?3:1.5);
        }
        sites.push_back(board.home);enemySites.push_back(board.away);
        for(int b=0;b<board.count;++b) {
            if(board.type[b]==HOSPITAL && owner[b]>=0) (owner[b]==0?sites:enemySites).push_back(board.pos[b]);
            if(board.type[b]==STATION && owner[b]>=0) (owner[b]==0?stations:enemyStations).push_back(board.pos[b]);
        }
        engineering=has(0,ENG);library=has(0,LIBRARY);
        warriorCost=engineering?2:3;enemyWarriorCost=has(1,ENG)?2:3;
    }
};
struct Memory { int expected, goal, previousDistance, age=0, stalled=0; };
vector<Memory> memories;
int lastTurn=0;
array<bool, MAX_BUILDINGS> depotSeen{};

struct Forecast {
    array<int,CELLS> reachableW{}, reachableF{}, staticW{}, nearestOwnW{};
    array<int,CELLS> coordinatedW{};
    explicit Forecast(const World& w) {
        nearestOwnW.fill(INF);
        for(int c=0;c<board.size;++c) {
            staticW[c]=w.enemy[W][c];
            reachableW[c]=w.enemy[W][c];reachableF[c]=w.enemy[F][c];
            for(int n:board.adj[c]) {reachableW[c]+=w.enemy[W][n];reachableF[c]+=w.enemy[F][n];}
            bool production=false;
            for(int site:w.enemySites) if(board.distance[site][c]<=1) production=true;
            if(production) reachableW[c]+=w.enemyMoney/w.enemyWarriorCost;
            if(find(w.enemyStations.begin(),w.enemyStations.end(),c)!=w.enemyStations.end()) {
                int teleW=0,teleF=0;
                for(int src:w.enemyStations) if(src!=c) {teleW=max(teleW,min(5,w.enemy[W][src]));teleF=max(teleF,min(5,w.enemy[F][src]));}
                reachableW[c]+=teleW;reachableF[c]+=teleF;
            }
            for(int n=0;n<board.size;++n) if(w.own[W][n]) nearestOwnW[c]=min(nearestOwnW[c],board.distance[n][c]);
        }
        // A coherent extra forecast uses each enemy stack and its production budget once.
        vector<int> targets;
        for(int c=0;c<board.size;++c) if(w.own[F][c]) targets.push_back(c);
        if(targets.empty()) targets.push_back(board.home);
        for(int src=0;src<board.size;++src) if(w.enemy[W][src]) {
            int goal=*min_element(targets.begin(),targets.end(),[&](int a,int b){return board.distance[src][a]<board.distance[src][b];});
            int dest=src;
            for(int n:board.adj[src]) if(board.distance[n][goal]<board.distance[dest][goal]) dest=n;
            coordinatedW[dest]+=w.enemy[W][src];
        }
        int site=w.enemySites.front(),target=targets.front(),best=INF;
        for(int s:w.enemySites) for(int t:targets) if(board.distance[s][t]<best) {best=board.distance[s][t];site=s;target=t;}
        int dest=site;for(int n:board.adj[site]) if(board.distance[n][target]<board.distance[dest][target]) dest=n;
        coordinatedW[dest]+=w.enemyMoney/w.enemyWarriorCost;
    }
};

double value(const World& w,int b) {
    double result=9*w.points[b];
    double duration=min(36,w.left);
    if(w.owner[b]==1) result+=7*w.points[b];
    if(board.type[b]==ENG && (!w.engineering || w.owner[b]==0)) result+=duration*2.1;
    if(board.type[b]==HALL) result+=duration*1.5;
    if(board.type[b]==HOSPITAL) {
        vector<int> savings;
        for(int j=0;j<board.count;++j) if(w.owner[j]!=0) {
            int current=INF;for(int s:w.sites) current=min(current,board.distance[s][board.pos[j]]);
            savings.push_back(max(0,current-board.distance[board.pos[b]][board.pos[j]]));
        }
        sort(savings.rbegin(),savings.rend());int saving=0;
        for(int i=0;i<min(3,int(savings.size()));++i)saving+=savings[i];
        result+=min(1.,w.left/30.)*(14+min(48,saving*2));
    }
    if(board.type[b]==DEPOT&&!depotSeen[b])result+=16*min(1.,w.left/15.);
    if(board.type[b]==LIBRARY&&!w.library)result+=12*min(1.,w.left/25.);
    if(board.type[b]==STATION)result+=min(1.,w.left/25.)*(w.stations.empty()?4:12);
    return result;
}
struct Move {int kind,from,to,count;bool tele=false;};
struct Production {int kind,site,count;};
struct Assigned {int from,next,goal,age,stalled;bool spawned=false;};
struct Plan {
    array<int,CELLS> availableW{}, arrivalW{}, arrivalF{};
    array<int,MAX_BUILDINGS> claims{}, goalSupply{};
    int money=0, spent=0, captureRequirement=0; bool teleUsed=false;
    double score=0;
    vector<Move> moves;
    vector<Production> births;
    vector<Assigned> flags;
};
void addMove(Plan& p,int kind,int from,int to,int count,bool tele=false) {
    if(!count)return;
    if(from!=to) p.moves.push_back({kind,from,to,count,tele});
    if(kind==W) p.arrivalW[to]+=count; else if(kind==F)p.arrivalF[to]+=count;
    if(tele)p.teleUsed=true;
}
void produce(Plan& p,int kind,int site,int count,int cost) {
    if(count<=0)return;
    p.births.push_back({kind,site,count});p.money-=count*cost;p.spent+=count*cost;
    if(kind==W)p.availableW[site]+=count;
}
bool stationLink(const World& w,int from,int to) {
    return from!=to&&find(w.stations.begin(),w.stations.end(),from)!=w.stations.end()&&
        find(w.stations.begin(),w.stations.end(),to)!=w.stations.end();
}

// Reserve one complete escort bundle, including newly produced warriors.
bool escort(Plan& p,const World& w,int dest,int required) {
    int missing=max(0,required-p.arrivalW[dest]);if(!missing)return true;
    vector<int> sources{dest};for(int n:board.adj[dest])sources.push_back(n);
    stable_sort(sources.begin(),sources.end(),[&](int a,int b){
        auto price=[&](int c){int building=board.at[c];return (c==dest?0:2)+(w.own[F][c]?5:0)+(building>=0&&w.owner[building]==0?1:0);};
        return price(a)<price(b);
    });
    for(int src:sources) {
        int take=min(missing,p.availableW[src]);p.availableW[src]-=take;addMove(p,W,src,dest,take);missing-=take;
        if(!missing)return true;
    }
    if(!p.teleUsed) for(int src:w.stations) if(stationLink(w,src,dest)) {
        int take=min({missing,5,p.availableW[src]});
        if(take) {p.availableW[src]-=take;addMove(p,W,src,dest,take,true);missing-=take;break;}
    }
    if(!missing)return true;
    int spawnSite=-1;
    for(int site:w.sites) if(board.distance[site][dest]<=1 && (spawnSite<0||board.distance[site][dest]<board.distance[spawnSite][dest]))spawnSite=site;
    int spendable=max(0,p.money-max(0,p.captureRequirement-10));
    if(spawnSite<0||spendable/w.warriorCost<missing)return false;
    produce(p,W,spawnSite,missing,w.warriorCost);p.availableW[spawnSite]-=missing;addMove(p,W,spawnSite,dest,missing);
    return true;
}

struct Token {int pos,goal=-1,age=0,stalled=0;bool newFlag=false;};
vector<Token> tokens(const World& w) {
    array<int,CELLS> left{};copy(w.own[F],w.own[F]+board.size,left.begin());
    vector<Token> result;
    for(const auto& m:memories) if(m.expected>=0&&m.expected<board.size&&left[m.expected]>0&&m.goal>=0&&m.goal<board.count) {
        --left[m.expected];int d=board.distance[m.expected][board.pos[m.goal]];
        int stall=d<m.previousDistance?0:m.stalled+1;
        bool valid=w.owner[m.goal]!=0&&stall<4&&m.age<max(14,d+8);
        result.push_back({m.expected,valid?m.goal:-1,m.age+1,valid?stall:0,false});
    }
    for(int c=0;c<board.size;++c) for(int n=0;n<left[c];++n)result.push_back({c,-1,0,0,false});
    return result;
}

struct Defender {int building,deadline,need;double worth;};
vector<Defender> defenseTasks(const World& w) {
    array<int,MAX_BUILDINGS> eta;eta.fill(INF);
    for(int src=0;src<board.size;++src) if(w.enemy[F][src]) {
        int best=-1,bestEta=INF;double rank=-1e30;
        for(int b=0;b<board.count;++b) if(w.owner[b]==0) {
            int d=board.distance[src][board.pos[b]];
            for(int s:w.enemyStations) for(int t:w.enemyStations)if(s!=t)d=min(d,board.distance[src][s]+1+board.distance[t][board.pos[b]]);
            if(d>5)continue;
            double r=value(w,b)/(d+2.);
            if(r>rank){rank=r;best=b;bestEta=d;}
        }
        if(best>=0)eta[best]=min(eta[best],bestEta);
    }
    vector<Defender> tasks;
    for(int b=0;b<board.count;++b) if(eta[b]<=5) {
        int threateningW=0;
        for(int src=0;src<board.size;++src)if(board.distance[src][board.pos[b]]<=eta[b])threateningW+=w.enemy[W][src];
        tasks.push_back({b,max(1,eta[b]),threateningW+1,value(w,b)/(eta[b]+1.)});
    }
    sort(tasks.begin(),tasks.end(),[](const auto&a,const auto&b){return a.worth>b.worth;});return tasks;
}

int warriorStep(const Plan& p,const Forecast& f,int src,int goal,int amount) {
    int best=src;double rank=-1e30;
    vector<int> opts=board.adj[src];opts.push_back(src);
    for(int next:opts) {
        int d=board.distance[next][goal];if(d>=INF)continue;
        int loss=max(0,f.staticW[next]-p.arrivalW[next]-amount);
        double score=-3.*d-4.*loss+(next!=src?.2:0);
        if(next==goal)score+=2;
        if(score>rank){rank=score;best=next;}
    }
    return best;
}
void reserveDefenders(Plan& p,const World& w,const Forecast& f,const vector<Defender>& tasks) {
    for(const auto& task:tasks) {
        int target=board.pos[task.building];
        // Large battles stay discretionary; an uncertain raid cannot consume the whole army.
        int total=accumulate(p.availableW.begin(),p.availableW.end(),0);
        int need=min(task.need,max(1,total/3));
        vector<int> sources;
        for(int c=0;c<board.size;++c)if(p.availableW[c]&&board.distance[c][target]<=task.deadline)sources.push_back(c);
        sort(sources.begin(),sources.end(),[&](int a,int b){return board.distance[a][target]<board.distance[b][target];});
        for(int src:sources) {
            int available=p.availableW[src];
            if(w.own[F][src])available=max(0,available-f.reachableW[src]);
            int take=min(need,available);if(!take)continue;
            int next=warriorStep(p,f,src,target,take);
            if(board.distance[next][target]>=task.deadline&&next!=target)continue;
            p.availableW[src]-=take;addMove(p,W,src,next,take);p.goalSupply[task.building]+=take;need-=take;
            if(!need)break;
        }
        if(need&&task.deadline<=2) {
            int site=-1,best=INF;for(int s:w.sites)if(board.distance[s][target]<best){site=s;best=board.distance[s][target];}
            if(best<=task.deadline&&site>=0) {
                int take=min(need,p.money/w.warriorCost);
                if(take) {produce(p,W,site,take,w.warriorCost);p.availableW[site]-=take;
                    int next=warriorStep(p,f,site,target,take);addMove(p,W,site,next,take);p.goalSupply[task.building]+=take;}
            }
        }
    }
}

struct Candidate {int goal,from,next;bool tele=false,spawn=false;double rank=0;};
double progressCost(const World& w,const Forecast& f,int start,int goal) {
    // Six-step route preview: stationary enemy obstacles are a risk cost, not a promised future.
    array<double,CELLS> current,next;current.fill(1e20);current[start]=0;
    double best=board.distance[start][goal]*1.0;
    for(int t=1;t<=6;++t) {
        next.fill(1e20);
        for(int c=0;c<board.size;++c)if(current[c]<1e19) {
            auto relax=[&](int d){double hazard=min(16,max(w.enemy[W][d]*3,f.coordinatedW[d]*(t<=2?2:1)));
                if(f.nearestOwnW[d]<=t)hazard*=.35;
                next[d]=min(next[d],current[c]+1+hazard+(d==c?.3:0));};
            relax(c);for(int d:board.adj[c])relax(d);
        }
        current=next;
        double route=1e20;for(int c=0;c<board.size;++c)route=min(route,current[c]+board.distance[c][goal]);
        if(t==1||route<best)best=route;
    }
    return best;
}
vector<Candidate> candidates(const World& w,const Forecast& f,const Token& token) {
    vector<int> starts=token.newFlag?w.sites:vector<int>{token.pos};
    vector<Candidate> out;
    for(int src:starts) {
        vector<pair<double,int>> goals;
        for(int b=0;b<board.count;++b)if(w.owner[b]!=0) {
            int distance=board.distance[src][board.pos[b]];
            if(distance>=INF||max(1,distance)>w.left)continue;
            double rank=value(w,b)/(distance+3.);
            if(token.goal==b)rank+=3;
            goals.push_back({rank,b});
        }
        sort(goals.begin(),goals.end(),[](auto a,auto b){return a.first!=b.first?a.first>b.first:a.second<b.second;});
        if(goals.size()>5)goals.resize(5);
        for(auto [_,b]:goals) {
            int goal=board.pos[b];
            vector<pair<int,bool>> steps{{src,false}};for(int n:board.adj[src])steps.push_back({n,false});
            for(int n:w.stations)if(stationLink(w,src,n))steps.push_back({n,true});
            for(auto [dest,tele]:steps) {
                int d=board.distance[dest][goal];
                if(d>board.distance[src][goal]+1)continue;
                double route=progressCost(w,f,dest,goal);
                int eta=1+d;
                double gain=value(w,b)/(eta+2.);
                if(w.left<=4) {
                    int effect=1+d;double terminal=0;
                    if(effect<=w.left)terminal+=w.points[b]*(w.owner[b]==1?1.:1.3);
                    if(effect+1<=w.left&&w.owner[b]==1)terminal+=w.points[b]*1.3;
                    gain=terminal*12;
                }
                gain-=route*.24;
                if(token.goal==b)gain+=2.4;
                if(dest==src&&src!=goal)gain-=1.2;
                if(dest==goal)gain+=3;
                if(tele)gain-=.4;
                if(w.enemy[F][dest])gain-=2;
                out.push_back({b,src,dest,tele,token.newFlag,gain});
            }
        }
    }
    sort(out.begin(),out.end(),[](const auto&a,const auto&b){return a.rank>b.rank;});
    if(out.size()>24)out.resize(24);
    return out;
}

Plan assignFlags(Plan seed,const World& w,const Forecast& f,vector<Token> flags,chrono::steady_clock::time_point until) {
    stable_sort(flags.begin(),flags.end(),[&](const auto&a,const auto&b){
        if(a.newFlag!=b.newFlag)return !a.newFlag;
        if(a.newFlag)return false;
        if(f.reachableW[a.pos]!=f.reachableW[b.pos])return f.reachableW[a.pos]>f.reachableW[b.pos];
        return a.goal>=0&&b.goal<0;
    });
    vector<Plan> beam{move(seed)};
    for(const Token& token:flags) {
        auto options=candidates(w,f,token);vector<Plan> next;
        for(const auto& old:beam) {
            if(token.newFlag)next.push_back(old);
            bool accepted=false;
            for(const auto& c:options) {
                if(c.spawn&&old.money<5)continue;
                if(c.tele&&old.teleUsed)continue;
                if(old.claims[c.goal]&&board.pos[c.goal]!=c.from)continue;
                Plan p=old;
                if(c.spawn)produce(p,F,c.from,1,5);
                int building=board.at[c.next];
                if(building>=0&&w.owner[building]!=0&&!p.arrivalF[c.next])
                    p.captureRequirement+=(board.type[building]==PLAZA?4:2)-(w.library?1:0);
                if(p.money<max(0,p.captureRequirement-10))continue;
                if(c.tele)p.teleUsed=true;
                int need=f.reachableW[c.next];
                if(f.reachableF[c.next])++need;
                if(!escort(p,w,c.next,need))continue;
                int added=p.spent-old.spent;
                double score=c.rank-.16*added;
                // Survival against a staying opponent is mandatory, even when the forecast moves it away.
                if(p.arrivalW[c.next]<f.staticW[c.next])continue;
                addMove(p,F,c.from,c.next,1,c.tele);
                p.flags.push_back({c.from,c.next,c.goal,token.goal==c.goal?token.age:0,token.goal==c.goal?token.stalled:0,c.spawn});
                p.claims[c.goal]++;p.goalSupply[c.goal]+=max(0,need);p.score+=score;
                next.push_back(move(p));accepted=true;
            }
            if(!token.newFlag&&!accepted) {
                // Every existing F receives a legal action, even if no robustly safe mission exists.
                int dest=token.pos;double best=-1e30;
                vector<int> cells=board.adj[token.pos];cells.push_back(token.pos);
                for(int c:cells) {
                    int support=old.arrivalW[c]+old.availableW[c];
                    double rank=-1000*max(0,f.staticW[c]-support)-10*max(0,f.reachableW[c]-support);
                    if(token.goal>=0)rank-=board.distance[c][board.pos[token.goal]];
                    if(c==token.pos)rank+=.1;
                    if(rank>best){best=rank;dest=c;}
                }
                Plan p=old;
                Plan protectedPlan=p;
                if(escort(protectedPlan,w,dest,f.staticW[dest]))p=move(protectedPlan);
                addMove(p,F,token.pos,dest,1);
                p.flags.push_back({token.pos,dest,token.goal,token.age,token.stalled,false});p.score-=5;
                next.push_back(move(p));
            }
        }
        stable_sort(next.begin(),next.end(),[](const Plan&a,const Plan&b){return a.score>b.score;});
        if(next.size()>12)next.resize(12);
        if(!next.empty())beam=move(next);
        // Candidate count remains bounded even after the soft deadline; finish all remaining F legally.
        if(chrono::steady_clock::now()>until&&beam.size()>1)beam.resize(1);
    }
    return move(beam.front());
}

struct WarriorGoal {int building,need;double worth;};
vector<WarriorGoal> warriorGoals(const Plan& p,const World& w,const vector<Defender>& defense) {
    vector<WarriorGoal> result;
    for(int b=0;b<board.count;++b) {
        int goal=board.pos[b];int pressure=w.enemy[W][goal];
        for(int c=0;c<board.size;++c)if(board.distance[c][goal]<=2)pressure+=w.enemy[W][c]/2;
        if(p.claims[b])result.push_back({b,max(3,pressure+2),value(w,b)*1.3});
        else if(w.owner[b]==1)result.push_back({b,max(3,pressure+1),value(w,b)*.65});
    }
    for(const auto& d:defense)result.push_back({d.building,d.need,d.worth*2.5});
    if(result.empty())for(int b=0;b<board.count;++b)if(w.owner[b]!=0)result.push_back({b,3,value(w,b)});
    if(result.empty()&&board.count)result.push_back({0,1,1});
    return result;
}
void finishWarriors(Plan& p,const World& w,const Forecast& f,const vector<Defender>& defense) {
    auto goals=warriorGoals(p,w,defense);
    int captureReserve=0;
    for(int b=0;b<board.count;++b)if(p.arrivalF[board.pos[b]]&&w.owner[b]!=0)
        captureReserve+=(board.type[b]==PLAZA?4:2)-(w.library?1:0);
    int reserve=max(0,captureReserve-10);
    int available=max(0,p.money-reserve)/w.warriorCost;
    for(int n=0;n<available;++n) {
        int site=w.sites.front(),goalIndex=-1;double best=-1e30;
        for(int s:w.sites)for(int g=0;g<int(goals.size());++g) {
            auto& task=goals[g];int d=board.distance[s][board.pos[task.building]];
            double marginal=task.worth/(d+3.)/(1.+double(p.goalSupply[task.building])/max(1,task.need));
            if(marginal>best){best=marginal;site=s;goalIndex=g;}
        }
        produce(p,W,site,1,w.warriorCost);
        if(goalIndex>=0)p.goalSupply[goals[goalIndex].building]++;
    }
    // Production's tentative preference is not a second reservation of those warriors.
    p.goalSupply.fill(0);
    for(auto& a:p.flags)if(a.goal>=0)p.goalSupply[a.goal]+=max(0,p.arrivalW[a.next]);
    vector<int> sources;
    for(int c=0;c<board.size;++c)if(p.availableW[c])sources.push_back(c);
    stable_sort(sources.begin(),sources.end(),[&](int a,int b){return p.availableW[a]>p.availableW[b];});
    for(int src:sources) {
        int amount=p.availableW[src];if(!amount)continue;
        int bestGoal=-1;double best=-1e30;
        for(int g=0;g<int(goals.size());++g) {
            const auto& task=goals[g];int d=board.distance[src][board.pos[task.building]];
            double utility=task.worth/(d+2.)/(1.+double(p.goalSupply[task.building])/max(1,task.need));
            if(w.enemy[F][board.pos[task.building]]&&d<=2)utility+=5;
            if(utility>best){best=utility;bestGoal=g;}
        }
        if(bestGoal<0){p.availableW[src]=0;addMove(p,W,src,src,amount);continue;}
        int b=goals[bestGoal].building,goal=board.pos[b];
        if(!p.teleUsed) {
            int to=-1,saving=1;
            for(int station:w.stations)if(stationLink(w,src,station)) {
                int gain=board.distance[src][goal]-1-board.distance[station][goal];
                if(gain>saving){saving=gain;to=station;}
            }
            if(to>=0) {int count=min(5,amount);p.availableW[src]-=count;amount-=count;
                addMove(p,W,src,to,count,true);p.goalSupply[b]+=count;}
        }
        if(amount) {int next=warriorStep(p,f,src,goal,amount);p.availableW[src]-=amount;
            addMove(p,W,src,next,amount);p.goalSupply[b]+=amount;}
    }
    // Do not drip an unescorted smaller group into a stationary larger enemy stack.
    array<bool,CELLS> stop{};
    for(int c=0;c<board.size;++c)stop[c]=p.arrivalF[c]==0&&p.arrivalW[c]<f.staticW[c];
    for(auto& m:p.moves)if(m.kind==W&&stop[m.to]) {
        p.arrivalW[m.to]-=m.count;p.arrivalW[m.from]+=m.count;m.to=m.from;m.tele=false;
    }
}

vector<string> commands(const Plan& p,const World& w) {
    vector<string> out;
    int production[3][CELLS]{};for(const auto& v:p.births)production[v.kind][v.site]+=v.count;
    for(int k=0;k<3;++k)for(int c=0;c<board.size;++c)if(production[k][c]) {
        string kind(1,"FWS"[k]);int count=production[k][c];
        if(c==board.home)out.push_back(p::spawn(kind,count));
        else out.push_back(p::spawn(kind,count,c%board.width,c/board.width));
    }
    vector<Move> all=p.moves;
    sort(all.begin(),all.end(),[](const Move&a,const Move&b){return tie(a.tele,a.kind,a.from,a.to)<tie(b.tele,b.kind,b.from,b.to);});
    for(size_t i=0;i<all.size();) {
        size_t j=i+1;int count=all[i].count;
        while(j<all.size()&&tie(all[j].tele,all[j].kind,all[j].from,all[j].to)==tie(all[i].tele,all[i].kind,all[i].from,all[i].to)){count+=all[j].count;++j;}
        const auto& m=all[i];
        if(m.from!=m.to) {
            string kind(1,"FWS"[m.kind]);
            if(m.tele)out.push_back(p::tele(m.from%board.width,m.from/board.width,kind,count,m.to%board.width,m.to/board.width));
            else {int dx=m.to%board.width-m.from%board.width,dy=m.to/board.width-m.from/board.width;
                string direction=dx==1?"R":dx==-1?"L":dy==1?"D":"U";
                out.push_back(p::move(m.from%board.width,m.from/board.width,kind,count,direction));}
        }
        i=j;
    }
    vector<pair<double,int>> priority;
    for(int b=0;b<board.count;++b)if(p.arrivalF[board.pos[b]]&&w.owner[b]!=0)priority.push_back({value(w,b),b});
    sort(priority.rbegin(),priority.rend());vector<pair<int,int>> coords;
    for(auto [_,b]:priority)coords.push_back({board.pos[b]%board.width,board.pos[b]/board.width});
    if(!coords.empty())out.push_back(p::priority(coords));
    return out;
}

vector<string> decide(const p::View& view,const p::Init& in) {
    auto start=chrono::steady_clock::now();
    if(lastTurn==0||view.turn<=lastTurn) {board.init(in);memories.clear();depotSeen.fill(false);}
    World w(view,in);Forecast f(w);
    for(int b=0;b<board.count;++b)if(w.owner[b]==0&&board.type[b]==DEPOT)depotSeen[b]=true;
    auto flags=tokens(w);int actual=int(flags.size());
    int targets=0;for(int b=0;b<board.count;++b)targets+=w.owner[b]!=0;
    int desired=min(7,max(2,(targets+1)/2));
    if(w.left<12)desired=min(desired,4);
    int extra=min(actual==0?2:1,max(0,desired-actual));
    for(int i=0;i<extra;++i)flags.push_back({-1,-1,0,0,true});
    Plan seed;seed.money=w.money;copy(w.own[W],w.own[W]+board.size,seed.availableW.begin());
    auto defense=defenseTasks(w);reserveDefenders(seed,w,f,defense);
    Plan plan=assignFlags(move(seed),w,f,move(flags),start+chrono::milliseconds(95));
    finishWarriors(plan,w,f,defense);
    memories.clear();
    for(const auto& a:plan.flags)if(a.goal>=0)memories.push_back({a.next,a.goal,board.distance[a.from][board.pos[a.goal]],a.age,a.stalled});
    lastTurn=view.turn;return commands(plan,w);
}
}
int main(){return p::run(mission::decide);}
