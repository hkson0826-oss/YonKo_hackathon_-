// v9-lock: v8 (deadline-20260929-guard3) + score-aware endgame (LOCK when leading, ALLIN when trailing).
#include "protocol.hpp"
#include <chrono>
#include <fstream>
#include <iomanip>
#include <sstream>
#include <cmath>
#include <numeric>
#include <queue>
#include <random>

using namespace std;
constexpr int N = 225, BMAX = 17, INF = 10000;
enum { F, W, S };
enum { PLAZA, HALL, STATION, LIBRARY, ENG, HOSPITAL, WATCH, DEPOT };
const vector<string> types = {"PLAZA", "HALL", "STATION", "LIBRARY", "ENG", "HOSPITAL", "WATCH", "DEPOT"};
const string kinds = "FWS";
struct Board {
    int nb = 0, base[2]{};
    int pos[BMAX]{}, type[BMAX]{}, id[BMAX]{}, at[N], dist[N][N];
    vector<int> adj[N];
    bool pass[N]{};
    void init(const p::Init& in) {
        fill(at, at + N, -1);
        for (int c = 0; c < N; ++c) {
            pass[c] = in.passable(c % 15, c / 15);
            if (!pass[c]) continue;
            for (auto [dx, dy] : {pair{0,-1}, pair{0,1}, pair{-1,0}, pair{1,0}})
                if (in.passable(c % 15 + dx, c / 15 + dy)) adj[c].push_back(c + dx + 15 * dy);
        }
        for (int t = 0; t < 2; ++t) base[t] = in.bases[t].first + 15 * in.bases[t].second;
        nb = int(in.buildings.size());
        for (int b = 0; b < nb; ++b) {
            const auto& x = in.buildings[b];
            pos[b] = x.x + 15 * x.y; id[b] = x.id; at[pos[b]] = b;
            type[b] = int(find(types.begin(), types.end(), x.type) - types.begin());
        }
        for (int c = 0; c < N; ++c) {
            fill(dist[c], dist[c] + N, INF);
            if (!pass[c]) continue;
            queue<int> q; q.push(c); dist[c][c] = 0;
            while (!q.empty()) {
                int u = q.front(); q.pop();
                for (int v : adj[u]) if (dist[c][v] == INF) {
                    dist[c][v] = dist[c][u] + 1; q.push(v);
                }
            }
        }
    }
} board;

struct State {
    int turn = 0, res[2]{}, u[2][3][N]{};
    int owner[BMAX]{}, stage[BMAX]{};
    bool claimed[2][BMAX]{}, revealed[2][BMAX]{};
    double score[BMAX]{}, occupation[2]{};
};
struct Production { int kind, pos, count; };
struct Movement { int kind, from, to, count; bool tele = false; };
struct Action { vector<Production> spawn; vector<Movement> moves; vector<int> priority; };
bool has(const State& s, int t, int type) {
    for (int b = 0; b < board.nb; ++b) if (s.owner[b] == t && board.type[b] == type) return true;
    return false;
}
int cost(const State& s, int t, int kind) {
    return kind == F ? 5 : kind == S ? 2 : has(s,t,ENG) ? 2 : 3;
}
double points(const State& s, int t) {
    double r = 0;
    for (int b = 0; b < board.nb; ++b) if (s.owner[b] == t) r += s.score[b];
    return r;
}
int income(const State& s, int t) {
    int r = 10;
    for (int b = 0; b < board.nb; ++b) if (s.owner[b] == t && board.type[b] == HALL) r += 2;
    return r;
}

// ---- v9: score-aware endgame (1/0 scoring: only P(win) matters) ---------------
// From V9_SWITCH the root decision estimates the current score margin with the 180-degree mirror.
//   LOCK  (estimated lead):  minimise variance. Every owned building gets defenders timed to the
//                            enemy F arrival (teleport reserved for defence first); search is risk averse.
//   ALLIN (estimated deficit): maximise variance. No defensive reservation, extra all-in script,
//                            search is risk seeking.
//   NORMAL: before V9_SWITCH, and an unresolved tie region.
enum { V9_NORMAL = 0, V9_LOCK = 1, V9_ALLIN = 2 };
constexpr int V9_SWITCH = 140;     // turn (completed turns) at which the score-aware endgame starts
constexpr int V9_HORIZON = 6;      // endgame guard looks at enemy F arriving within this many turns
constexpr int V9_MID = 1;          // pre-endgame: deadline_guard also covers escorted HALL/ENG raids
constexpr int V9_MID_MAX = 4;      // largest escorted raid (need) the pre-endgame guard answers
int v9_mode = V9_NORMAL;
bool v9_known[BMAX]{};             // score is exact: revealed, mirror revealed, or plaza
double v9_margin = 0, v9_margin_low = 0;

// ---- v9 trace: decision report, local only -------------------------------------
// Enabled with the command-line argument --trace=<file>. The server starts the bot without
// arguments, so the submitted behaviour and stdout protocol are unchanged. Stage functions write
// why they did what they did; decide() flushes once per turn.
ofstream v9_trace_file;
bool v9_tracing = false;
#define V9LOG(...) do { if (v9_tracing) v9_trace_file << __VA_ARGS__; } while (0)
const char* v9_mode_name(int m) { return m == V9_LOCK ? "LOCK" : m == V9_ALLIN ? "ALLIN" : "NORMAL"; }
string v9_cell(int c) { return "(" + to_string(c%15) + "," + to_string(c/15) + ")"; }
string v9_bname(int b) { return types[board.type[b]] + "#" + to_string(board.id[b]) + v9_cell(board.pos[b]); }

State advance(State s, const Action& ay, const Action& ak) {
    const Action* actions[2] = {&ay, &ak};
    ++s.turn;
    for (int b = 0; b < board.nb; ++b) if (s.owner[b] < 0) s.stage[b] = 0;
    for (int t = 0; t < 2; ++t) for (auto a : actions[t]->spawn) {
        int b = board.at[a.pos];
        if (a.pos != board.base[t] && !(b >= 0 && board.type[b] == HOSPITAL && s.owner[b] == t)) continue;
        int c = cost(s,t,a.kind), n = min(a.count, s.res[t] / c);
        s.res[t] -= n * c; s.u[t][a.kind][a.pos] += n;
    }
    int arrivals[2][3][N]{};
    for (int t = 0; t < 2; ++t) {
        bool tele_used = false;
        for (auto a : actions[t]->moves) {
            if (a.tele) {
                int src = board.at[a.from], dst = board.at[a.to];
                if (tele_used || src < 0 || dst < 0 || src == dst ||
                    board.type[src] != STATION || board.type[dst] != STATION ||
                    s.owner[src] != t || s.owner[dst] != t) continue;
                a.count = min(a.count, 5);
            }
            int n = min(a.count, s.u[t][a.kind][a.from]);
            s.u[t][a.kind][a.from] -= n; arrivals[t][a.kind][a.to] += n;
            if (a.tele && n) tele_used = true;
        }
    }
    for (int t = 0; t < 2; ++t) for (int k = 0; k < 3; ++k)
        for (int c = 0; c < N; ++c) s.u[t][k][c] += arrivals[t][k][c];
    for (int c = 0; c < N; ++c) {
        int n = min(s.u[0][W][c], s.u[1][W][c]);
        s.u[0][W][c] -= n; s.u[1][W][c] -= n;
        for (int t = 0; t < 2; ++t) if (s.u[1-t][W][c] > 0) {
            int b = board.at[c];
            if (s.u[t][F][c] && b >= 0 && s.owner[b] == t) { s.owner[b] = -1; s.stage[b] = 1; }
            s.u[t][F][c] = s.u[t][S][c] = 0;
        }
    }
    bool library[2] = {has(s,0,LIBRARY), has(s,1,LIBRARY)};
    for (int t = 0; t < 2; ++t) s.res[t] = min(40, s.res[t] + income(s,t));
    int bonus[2]{};
    for (int t = 0; t < 2; ++t) {
        vector<int> order, rest;
        bool used[BMAX]{};
        for (int b : actions[t]->priority) if (b >= 0 && b < board.nb && !used[b]) {
            used[b] = true; order.push_back(b);
        }
        for (int b = 0; b < board.nb; ++b) if (!used[b]) rest.push_back(b);
        sort(rest.begin(), rest.end(), [&](int a, int b) {
            double va = s.revealed[t][a] ? s.score[a] : 0, vb = s.revealed[t][b] ? s.score[b] : 0;
            if (va != vb) return va > vb;
            return t == 0 ? board.pos[a] < board.pos[b] : board.pos[a] > board.pos[b];
        });
        order.insert(order.end(), rest.begin(), rest.end());
        for (int b : order) {
            int c = board.pos[b];
            if (!s.u[t][F][c] || s.u[1-t][F][c] || s.owner[b] == t) continue;
            int cap = (board.type[b] == PLAZA ? 4 : 2) - library[t];
            if (s.res[t] < cap) continue;
            s.res[t] -= cap;
            if (s.owner[b] < 0) {
                s.owner[b] = t; s.stage[b] = 2; s.revealed[t][b] = true;
                if (board.type[b] == DEPOT && !s.claimed[t][b]) {
                    s.claimed[t][b] = true; bonus[t] += 15;
                }
            } else { s.owner[b] = -1; s.stage[b] = 1; }
        }
    }
    for (int t = 0; t < 2; ++t) {
        s.res[t] = min(40, s.res[t] + bonus[t]); s.occupation[t] += points(s,t);
        for (int b = 0; b < board.nb; ++b) {
            int c = board.pos[b];
            if (s.owner[b] == t || s.u[t][F][c] || s.u[t][W][c] || s.u[t][S][c]) s.revealed[t][b] = true;
            for (int j = 0; j < board.nb; ++j) if (s.owner[j] == t && board.type[j] == WATCH &&
                max(abs(c%15-board.pos[j]%15),abs(c/15-board.pos[j]/15)) <= 3) s.revealed[t][b] = true;
            for (int v = 0; v < N; ++v) if (s.u[t][S][v] &&
                max(abs(c%15-v%15),abs(c/15-v/15)) <= 2) s.revealed[t][b] = true;
        }
    }
    return s;
}

double building_value(const State& s, int t, int b, int style) {
    double future = min(1.0, (160.0 - s.turn) / 35.0);
    double v = 7 * s.score[b];
    if (s.owner[b] == 1-t) v *= 1.55;
    if (board.type[b] == ENG && (!has(s,t,ENG) || s.owner[b] == t)) v += (style == 1 ? 65 : 48) * future;
    if (board.type[b] == HALL) v += (style == 1 ? 75 : 55) * future;
    if (board.type[b] == HOSPITAL) {
        double saving = 0;
        for (int j = 0; j < board.nb; ++j) if (s.owner[j] != t)
            saving += max(0, board.dist[board.base[t]][board.pos[j]] - board.dist[board.pos[b]][board.pos[j]]);
        v += min(40.0, 6 + saving * .55) * future;
    }
    if (board.type[b] == DEPOT && !s.claimed[t][b]) v += 18 * future;
    if (board.type[b] == LIBRARY && !has(s,t,LIBRARY)) v += 7 * future;
    if (board.type[b] == STATION) v += 6 * future;
    return v;
}

struct Goal { int pos, need; double value; };
// Distance-based assignment, adapted from teammate delineate-v1 (351c32e).
Action assignment_policy(const State& s, int t) {
    Action a;
    int enemy = 1-t, remaining_turns = 160-s.turn;
    int own[2][N]{}, danger[N]{}, local[N]{};
    for (int k=0;k<2;++k) copy(s.u[t][k],s.u[t][k]+N,own[k]);
    vector<int> sources{board.base[t]}, enemy_sources{board.base[enemy]}, targets;
    for (int b=0;b<board.nb;++b) {
        if (s.owner[b]!=t) targets.push_back(b);
        if (board.type[b]==HOSPITAL && s.owner[b]>=0)
            (s.owner[b]==t?sources:enemy_sources).push_back(board.pos[b]);
    }
    for (int c=0;c<N;++c) if (board.pass[c]) {
        danger[c]=s.u[enemy][W][c];
        for (int q:board.adj[c]) danger[c]+=s.u[enemy][W][q];
        for (int q=0;q<N;++q) if (board.dist[c][q]<=3) local[c]+=s.u[enemy][W][q];
        for (int q:enemy_sources) if (board.dist[c][q]<=1) {danger[c]+=s.res[enemy]/cost(s,enemy,W);break;}
    }
    bool engineering=has(s,t,ENG);
    auto value=[&](int b) {
        double bonus=0;
        if (board.type[b]==HALL) bonus=5;
        if (board.type[b]==ENG && !engineering) bonus=5;
        if (board.type[b]==HOSPITAL) bonus=4;
        if (board.type[b]==DEPOT) bonus=2;
        if (board.type[b]==LIBRARY) bonus=1;
        if (board.type[b]==STATION) bonus=.5;
        return 1.4*s.score[b]+bonus*min(1.0,remaining_turns/60.0);
    };
    int capture_cost=0;
    for (int b:targets) {
        bool near=own[F][board.pos[b]]>0;
        for (int c:board.adj[board.pos[b]]) near|=own[F][c]>0;
        if (near) capture_cost+=(board.type[b]==PLAZA?4:2)-has(s,t,LIBRARY);
    }
    int budget=max(0,s.res[t]-max(0,capture_cost-10));
    auto produce=[&](int kind) {
        if (budget<cost(s,t,kind)) return false;
        double best=1e20;int site=sources.front();
        for (int c:sources) for (int b=0;b<board.nb;++b) if (targets.empty() || s.owner[b]!=t) {
            double v=board.dist[c][board.pos[b]]-value(b);
            if (v<best) {best=v;site=c;}
        }
        int distance=INF;
        for (int b=0;b<board.nb;++b) if (targets.empty() || s.owner[b]!=t)
            distance=min(distance,board.dist[site][board.pos[b]]);
        if (distance>remaining_turns) return false;
        ++own[kind][site];budget-=cost(s,t,kind);a.spawn.push_back({kind,site,1});
        return true;
    };
    int nf=accumulate(own[F],own[F]+N,0), desired=targets.empty()?0:min(6,max(2,int(targets.size())));
    for (int i=0;i<(nf<2?2:1) && nf<desired;++i) if (produce(F)) ++nf;
    while (produce(W)) {}
    int flags[N];copy(own[F],own[F]+N,flags);
    int assigned[BMAX]{};
    vector<pair<int,int>> missions;
    for (int f=0;f<nf && !targets.empty();++f) {
        int src=-1,target=-1;double best=1e20;
        for (int c=0;c<N;++c) if (flags[c]) for (int b:targets) {
            int distance=board.dist[c][board.pos[b]];
            if (distance+(s.owner[b]==enemy)>remaining_turns) continue;
            double v=distance-value(b)+18*assigned[b]+min(10,s.u[enemy][W][board.pos[b]])*.7;
            if (v<best) {best=v;src=c;target=b;}
        }
        if (src<0) break;
        --flags[src];++assigned[target];missions.push_back({src,target});
    }
    vector<Goal> tasks;
    for (int b=0;b<board.nb;++b) {
        int c=board.pos[b];
        if (s.owner[b]==t) {
            bool nearby=false;
            for (int q=0;q<N;++q) if (s.u[enemy][F][q] && board.dist[q][c]<=2) nearby=true;
            if (local[c] || nearby) tasks.push_back({c,max(1,local[c]+1),value(b)+7});
        } else if (assigned[b] || s.u[enemy][F][c]) {
            tasks.push_back({c,max(1,local[c]+1),value(b)+2});
        }
    }
    if (tasks.empty()) for (int b:targets) tasks.push_back({board.pos[b],1,value(b)});
    int planned[N]{},allocated[N]{},moving[2][N][4]{};
    vector<int> warriors;
    for (int c=0;c<N;++c) if (own[W][c]) warriors.push_back(c);
    sort(warriors.begin(),warriors.end(),[&](int x,int y){return own[W][x]>own[W][y];});
    auto route=[&](int src,int dest,int kind,int n) {
        if (src==dest) return;
        int d=dest-src,dir=d==-15?0:d==15?1:d==-1?2:3;
        moving[kind][src][dir]+=n;
    };
    auto options=[&](int c) {
        vector<int> out{c};
        if (t==0) out.insert(out.end(),board.adj[c].begin(),board.adj[c].end());
        else for (int delta:{15,-15,1,-1}) {
            int q=c+delta;
            if (find(board.adj[c].begin(),board.adj[c].end(),q)!=board.adj[c].end()) out.push_back(q);
        }
        return out;
    };
    for (int c:warriors) for (int i=0;i<own[W][c];++i) {
        if (tasks.empty()) {++planned[c];continue;}
        int target=c;double best=1e20;
        for (auto task:tasks) {
            double v=board.dist[c][task.pos]-task.value+4*max(0,allocated[task.pos]-task.need+1);
            if (v<best) {best=v;target=task.pos;}
        }
        ++allocated[target];int dest=c;
        for (int q:options(c)) if (board.dist[q][target]<board.dist[dest][target]) dest=q;
        ++planned[dest];route(c,dest,W,1);
    }
    for (auto [c,b]:missions) {
        int dest=c;double best=1e20;
        for (int q:options(c)) {
            double v=1000*(danger[q]>planned[q])+board.dist[q][board.pos[b]]+.01*danger[q];
            if (v<best) {best=v;dest=q;}
        }
        route(c,dest,F,1);
    }
    for (int c=0;c<N;++c) if (flags[c] && danger[c]>planned[c]) {
        for (int q:options(c)) if (danger[q]<=planned[q]) {route(c,q,F,flags[c]);break;}
    }
    int delta[4]={-15,15,-1,1};
    for (int k=0;k<2;++k) for (int c=0;c<N;++c) for (int d=0;d<4;++d)
        if (moving[k][c][d]) a.moves.push_back({k,c,c+delta[d],moving[k][c][d]});
    a.priority=targets;
    stable_sort(a.priority.begin(),a.priority.end(),[&](int x,int y){return value(x)>value(y);});
    return a;
}

// v9: sources a team can spawn from (base first, then owned hospitals).
vector<int> v9_sources(const State& s,int t) {
    vector<int> out{board.base[t]};
    for(int b=0;b<board.nb;++b) if(board.type[b]==HOSPITAL && s.owner[b]==t) out.push_back(board.pos[b]);
    return out;
}

// v9: station-aware travel time for team t. Either walk, or walk to an owned station s1 (d1 turns),
// teleport to another owned station s2 (1 turn, at most 5 units of one kind per team per turn), walk on.
// Station ownership is taken as of now; the route is re-planned every turn.
struct V9Route {int eta,s1,s2,d1;};   // s1<0: walking is fastest
vector<int> v9_stations(const State& s,int t) {
    vector<int> out;
    for(int b=0;b<board.nb;++b) if(board.type[b]==STATION && s.owner[b]==t) out.push_back(board.pos[b]);
    return out;
}
V9Route v9_route(const vector<int>& stations,int from,int to) {
    V9Route r{board.dist[from][to],-1,-1,0};
    if(stations.size()<2) return r;
    for(int a:stations) {
        int d1=board.dist[from][a];
        if(d1+1>=r.eta) continue;
        for(int b:stations) if(b!=a && d1+1+board.dist[b][to]<r.eta) r={d1+1+board.dist[b][to],a,b,d1};
    }
    return r;
}
int v9_eta(const vector<int>& stations,int from,int to) {return v9_route(stations,from,to).eta;}
// One step along the route: toward the entry station, the teleport itself, or toward the target.
Movement v9_step(const vector<int>& stations,int kind,int from,int to,int count,bool tele_free,const int* danger) {
    V9Route r=v9_route(stations,from,to);
    if(r.s1>=0 && r.d1==0 && tele_free && count<=5) return {kind,from,r.s2,count,true};
    int goal=r.s1>=0 && r.d1>0 ? r.s1 : to;
    if(from==goal) return {kind,from,from,0};
    int dest=from,low=INF;
    for(int q:board.adj[from]) if(board.dist[q][goal]<board.dist[from][goal] && (danger?danger[q]:0)<low) {
        dest=q;low=danger?danger[q]:0;
    }
    return {kind,from,dest,count};
}

// v9: endgame flag demand replaces the flat 3-F cap after turn 145. A flag is worth keeping when a
// target is still reachable before turn 160, or when an owned building may need an immediate recapture.
int v9_flag_target(const State& s,int t,int desired) {
    int enemy=1-t, remaining=160-s.turn, useful=0;
    auto sources=v9_sources(s,t);
    auto ours=v9_stations(s,t), theirs=v9_stations(s,enemy);
    for(int b=0;b<board.nb;++b) {
        int pos=board.pos[b];
        if(s.owner[b]!=t) {
            int d=INF;
            for(int c:sources) d=min(d,v9_eta(ours,c,pos));
            for(int c=0;c<N;++c) if(s.u[t][F][c]) d=min(d,v9_eta(ours,c,pos));
            if(d<=remaining) ++useful;
        } else {
            bool threatened=false;
            for(int c=0;c<N && !threatened;++c) if(s.u[enemy][F][c] && v9_eta(theirs,c,pos)<=5) threatened=true;
            if(threatened) ++useful;
        }
    }
    return min(desired,max(useful?2:0,useful));
}

// v9: all-in script for a trailing endgame. Defence is abandoned.
// - Station-aware routes for both sides (walk, or walk + teleport + walk).
// - Weak-spot targeting: a target's worth is divided by the enemy W that can defend it in time. A
//   defender that guards its highest-score buildings first leaves the lower ones open; we go there.
// - At the root decision only, a random factor (0.6-1.4) per target spreads the choice among
//   near-equal targets so the attack is not predictable. Search rollouts stay deterministic.
// - Escorts are all-or-nothing: a further mission launches only with a complete escort (taking two
//   buildings must not cost both). The first mission always goes; trailing, a partial chance beats none.
bool v9_randomize=false;              // set only for the root call in a_decide
vector<string> v9_allin_notes;        // root-call explanation for the trace
mt19937 v9_rng(uint32_t(chrono::steady_clock::now().time_since_epoch().count()));
Action v9_allin_policy(const State& s,int t) {
    Action a;
    const int enemy=1-t, remaining=160-s.turn;
    const bool root=v9_randomize;
    if(root) v9_allin_notes.clear();
    int avail[2][N];
    for(int k=0;k<2;++k) copy(s.u[t][k],s.u[t][k]+N,avail[k]);
    auto sources=v9_sources(s,t), enemy_sources=v9_sources(s,enemy);
    auto ours=v9_stations(s,t), theirs=v9_stations(s,enemy);
    const int espawn=s.res[enemy]/cost(s,enemy,W);
    int danger[N]{};
    for(int c=0;c<N;++c) if(board.pass[c]) {
        danger[c]=s.u[enemy][W][c];
        for(int q:board.adj[c]) danger[c]+=s.u[enemy][W][q];
        for(int q:enemy_sources) if(board.dist[c][q]<=1) {danger[c]+=espawn;break;}
    }
    // defend[b][e]: enemy W (walking or by teleport, plus a fresh spawn) able to stand on b within e turns.
    static int defend[BMAX][24];
    for(int b=0;b<board.nb;++b) {
        fill(defend[b],defend[b]+24,0);
        if(s.owner[b]==t) continue;
        int pos=board.pos[b];
        for(int c=0;c<N;++c) if(s.u[enemy][W][c]) defend[b][min(23,v9_eta(theirs,c,pos))]+=s.u[enemy][W][c];
        int sd=INF;
        for(int c:enemy_sources) sd=min(sd,board.dist[c][pos]);
        if(sd<24) defend[b][sd]+=espawn;
        for(int e=1;e<24;++e) defend[b][e]+=defend[b][e-1];
    }
    auto defenders=[&](int b,int e){return defend[b][clamp(e,0,23)];};
    double noise[BMAX];
    for(int b=0;b<board.nb;++b) noise[b]=root?uniform_real_distribution<double>(.6,1.4)(v9_rng):1.0;
    auto gain=[&](int b,int eta) {
        if(eta>remaining) return 0.0;
        if(s.owner[b]==enemy) return s.score[b]*(eta<remaining?2.0:1.0);
        return s.score[b];
    };
    auto worth=[&](int b,int eta) {
        return gain(b,eta)/(eta+1.0)/(1.0+.35*defenders(b,eta))*noise[b];
    };
    // Production: F while useful targets outnumber flags, everything else into W near the best target.
    int budget=s.res[t], nf=0, useful=0;
    for(int c=0;c<N;++c) nf+=avail[F][c];
    for(int b=0;b<board.nb;++b) if(s.owner[b]!=t) {
        int d=INF;
        for(int c:sources) d=min(d,v9_eta(ours,c,board.pos[b]));
        if(d<=remaining) ++useful;
    }
    auto best_site=[&]() {
        int site=sources.front(); double best=-1e20;
        for(int c:sources) for(int b=0;b<board.nb;++b) if(s.owner[b]!=t) {
            double v=worth(b,v9_eta(ours,c,board.pos[b]));
            if(v>best) {best=v;site=c;}
        }
        return site;
    };
    if(nf<min(7,useful) && budget>=5) {
        int site=best_site();
        a.spawn.push_back({F,site,1}); ++avail[F][site]; budget-=5; ++nf;
    }
    if(budget>=cost(s,t,W)) {
        int site=best_site(), n=budget/cost(s,t,W);
        a.spawn.push_back({W,site,n}); avail[W][site]+=n;
    }
    // Missions: best (flag, target) by worth; escort need = enemy W able to meet the flag + 1.
    bool assigned[BMAX]{}, skip[BMAX]{};
    int left[N]; copy(avail[F],avail[F]+N,left);
    int free_w[N]; copy(avail[W],avail[W]+N,free_w);
    int tele_cap[24]; fill(tele_cap,tele_cap+24,5);   // one teleport (<=5 units) per future turn
    struct Send {int from,to,count;};
    vector<Send> sends;
    vector<pair<int,int>> missions;
    for(int round=0;round<2*BMAX;++round) {
        double best=0; int src=-1,goal=-1;
        for(int c=0;c<N;++c) if(left[c]) for(int b=0;b<board.nb;++b) {
            if(assigned[b] || skip[b] || s.owner[b]==t) continue;
            double v=worth(b,v9_eta(ours,c,board.pos[b]));
            if(v>best) {best=v;src=c;goal=b;}
        }
        if(src<0) break;
        int pos=board.pos[goal], eta=v9_eta(ours,src,pos), need=defenders(goal,eta+1)+1, got=0;
        int limit=max(eta,1)+1;
        vector<pair<int,int>> cells;   // (eta, cell)
        for(int c=0;c<N;++c) if(free_w[c]) {
            V9Route r=v9_route(ours,c,pos);
            if(r.eta<=limit) cells.push_back({r.eta,c});
        }
        sort(cells.begin(),cells.end());
        vector<Send> take; int tele_used[24]{};
        for(auto [e,c]:cells) {
            if(got>=need) break;
            V9Route r=v9_route(ours,c,pos);
            int k=min(need-got,free_w[c]);
            if(r.s1>=0) {   // needs a teleport on turn d1: capacity is shared
                int d1=min(23,r.d1);
                k=min(k,tele_cap[d1]-tele_used[d1]);
                if(k<=0) continue;
                tele_used[d1]+=k;
            }
            take.push_back({c,pos,k}); got+=k;
        }
        bool complete=got>=need, first=missions.empty();
        if(!complete && !first) {
            skip[goal]=true;
            if(root) v9_allin_notes.push_back("skip " + v9_bname(goal) + ": escort " + to_string(got) + "/" +
                                              to_string(need) + " incomplete, not risking the missions already set");
            continue;
        }
        for(auto& x:take) {free_w[x.from]-=x.count; sends.push_back(x);}
        for(int d=0;d<24;++d) tele_cap[d]-=tele_used[d];
        --left[src]; assigned[goal]=true; missions.push_back({src,goal});
        if(root) {
            ostringstream note;
            note << "attack " << v9_bname(goal) << " score " << s.score[goal] << (s.owner[goal]==enemy?" (enemy)":" (neutral)")
                 << ": F " << v9_cell(src) << " eta " << eta << (v9_route(ours,src,pos).s1>=0?" via station":"")
                 << ", enemy defenders in time " << defenders(goal,eta) << ", escort " << got << "/" << need
                 << (complete?"":" (partial: first mission always goes)") << ", random x" << fixed << setprecision(2) << noise[goal];
            v9_allin_notes.push_back(note.str());
        }
    }
    // Spare W reinforce the nearest mission, otherwise the nearest non-owned building.
    for(int c=0;c<N;++c) if(free_w[c]) {
        int target=-1,bd=INF;
        for(auto [src,b]:missions) {int e=v9_eta(ours,c,board.pos[b]); if(e<bd) {bd=e;target=board.pos[b];}}
        if(target<0) for(int b=0;b<board.nb;++b) if(s.owner[b]!=t) {
            int e=v9_eta(ours,c,board.pos[b]); if(e<bd) {bd=e;target=board.pos[b];}
        }
        if(target>=0) sends.push_back({c,target,free_w[c]});
    }
    // Moves: W first (escorts may take the teleport), then flags avoiding cells they would lose.
    bool tele_free=true; int planned[N]{};
    for(auto x:sends) {
        Movement m=v9_step(ours,W,x.from,x.to,x.count,tele_free,danger);
        planned[m.to]+=x.count;
        if(m.to==x.from || m.count<=0) continue;
        if(m.tele) tele_free=false;
        a.moves.push_back(m);
    }
    int risk[N];
    for(int c=0;c<N;++c) risk[c]=danger[c]>planned[c]?6+danger[c]-planned[c]:0;
    for(auto [src,b]:missions) {
        Movement m=v9_step(ours,F,src,board.pos[b],1,tele_free,risk);
        if(m.to==src || m.count<=0) continue;
        if(m.tele) tele_free=false;
        a.moves.push_back(m);
    }
    a.priority.resize(board.nb); iota(a.priority.begin(),a.priority.end(),0);
    sort(a.priority.begin(),a.priority.end(),[&](int x,int y){
        if(assigned[x]!=assigned[y]) return assigned[x];
        return s.score[x]>s.score[y];
    });
    return a;
}

Action policy(const State& s, int t, int style) {
    if (style==3) return assignment_policy(s,t);
    if (style==4) return v9_allin_policy(s,t);
    Action a;
    int enemy = 1-t, available[3][N]{};
    for (int k = 0; k < 3; ++k) copy(s.u[t][k], s.u[t][k]+N, available[k]);
    int danger[N]{}, near_enemy[N]{}, enemy_flag_dist[N];
    fill(enemy_flag_dist, enemy_flag_dist+N, INF);
    for (int c = 0; c < N; ++c) if (board.pass[c]) {
        danger[c] = s.u[enemy][W][c];
        for (int v : board.adj[c]) danger[c] += s.u[enemy][W][v];
        for (int v = 0; v < N; ++v) {
            if (board.dist[c][v] <= 3) near_enemy[c] += s.u[enemy][W][v];
            if (s.u[enemy][F][v]) enemy_flag_dist[c] = min(enemy_flag_dist[c], board.dist[c][v]);
        }
    }
    vector<int> enemy_sources{board.base[enemy]}, sources{board.base[t]}, stations;
    for (int b = 0; b < board.nb; ++b) {
        if (board.type[b] == HOSPITAL && s.owner[b] >= 0)
            (s.owner[b] == t ? sources : enemy_sources).push_back(board.pos[b]);
        if (board.type[b] == STATION && s.owner[b] == t) stations.push_back(board.pos[b]);
    }
    for (int c = 0; c < N; ++c) if (board.pass[c]) {
        bool reachable = false;
        for (int v : enemy_sources) if (board.dist[c][v] <= 1) reachable = true;
        if (reachable) danger[c] += s.res[enemy] / cost(s,enemy,W);
        if (board.at[c] >= 0 && board.type[board.at[c]] == STATION && s.owner[board.at[c]] == enemy) {
            int remote = 0;
            for (int b = 0; b < board.nb; ++b) if (board.type[b] == STATION && s.owner[b] == enemy && board.pos[b] != c)
                remote = max(remote, min(5, s.u[enemy][W][board.pos[b]]));
            danger[c] += remote;
        }
    }
    int nf = accumulate(available[F],available[F]+N,0), nw = accumulate(available[W],available[W]+N,0);
    int targets = 0, immediate_cost = 0;
    for (int b = 0; b < board.nb; ++b) if (s.owner[b] != t) {
        ++targets;
        bool nearby = available[F][board.pos[b]] > 0;
        for (int v : board.adj[board.pos[b]]) nearby |= available[F][v] > 0;
        if (nearby) immediate_cost += (board.type[b] == PLAZA ? 4 : 2) - has(s,t,LIBRARY);
    }
    int budget = max(0, s.res[t] - max(0, immediate_cost - 10));
    int desired_flags = min(style == 2 ? 5 : 7, max(2, targets));
    if (s.turn < 3) desired_flags = 4;
    if (s.turn > 145) desired_flags = v9_flag_target(s,t,desired_flags);
    auto spawn_at = [&](int kind, int count) {
        int best = sources.front(); double best_value = -1e20;
        for (int c : sources) {
            double v = -1e20;
            for (int b = 0; b < board.nb; ++b) if (s.owner[b] != t || enemy_flag_dist[board.pos[b]] <= 4) {
                double value = building_value(s,t,b,style) / (board.dist[c][board.pos[b]] + 2.0);
                if (kind == F) value -= .6 * near_enemy[board.pos[b]] / (board.dist[c][board.pos[b]] + 2.0);
                v = max(v,value);
            }
            if (kind == F && danger[c] > available[W][c]) v -= 50;
            if (v > best_value) {best = c; best_value = v;}
        }
        a.spawn.push_back({kind,best,count}); available[kind][best] += count;
        budget -= count * cost(s,t,kind);
    };
    int make_flags = min(max(0,desired_flags-nf), budget/5);
    if (nf >= 2 && s.turn >= 2) make_flags = min(make_flags,1);
    if (nf >= 2 && nw < 2 && s.turn >= 2) make_flags = 0;
    if (make_flags) spawn_at(F,make_flags);
    if (budget >= cost(s,t,W)) spawn_at(W,budget/cost(s,t,W));

    // Assign one flag to each useful target before routing escorts.
    int wanted[N]{}, assigned[BMAX]{};
    vector<pair<int,int>> flag_tasks;
    int left[N]; copy(available[F],available[F]+N,left);
    for (int round = 0; round < BMAX; ++round) {
        double best = -1e20; int src = -1, goal = -1;
        for (int c = 0; c < N; ++c) if (left[c]) for (int b = 0; b < board.nb; ++b) {
            if (assigned[b] || s.owner[b] == t) continue;
            int d = board.dist[c][board.pos[b]];
            if (d > 160-s.turn) continue;
            double risk = max(0.0,near_enemy[board.pos[b]] - nw*.3);
            double v = building_value(s,t,b,style)/(d+2.0) - risk/(d+3.0) * (style == 2 ? .9 : 1.8);
            if (d == 0) v += 10;
            if (s.owner[b] == enemy && s.u[enemy][F][board.pos[b]]) v -= 3;
            if (v > best) {best = v; src = c; goal = b;}
        }
        if (src < 0) break;
        --left[src]; assigned[goal] = 1; flag_tasks.push_back({src,goal});
    }
    for (auto [src,b] : flag_tasks) {
        int next = src;
        for (int v : board.adj[src]) if (board.dist[v][board.pos[b]] < board.dist[next][board.pos[b]]) next = v;
        ++wanted[next];
    }
    vector<Goal> goals;
    for (int b = 0; b < board.nb; ++b) {
        int c = board.pos[b];
        double v = building_value(s,t,b,style);
        int need = max(1, near_enemy[c] + 1);
        if (s.owner[b] == t) {
            if (enemy_flag_dist[c] > 5 && !(available[F][c] && danger[c])) continue;
            v *= (style == 0 ? 2.0 : 1.4) / (1 + .18*enemy_flag_dist[c]);
            need = max(1,danger[c]+1);
        } else if (!assigned[b]) v *= .55;
        goals.push_back({c,need,v});
    }
    for (int c = 0; c < N; ++c) {
        if (s.u[enemy][F][c]) goals.push_back({c, max(1,danger[c]+1), min(50.0, 13.0+5*s.u[enemy][F][c])});
        if (wanted[c] && danger[c]) goals.push_back({c,danger[c]+1,50.0});
    }
    if (goals.empty()) goals.push_back({board.base[enemy],1,1});
    vector<int> warriors;
    for (int c = 0; c < N; ++c) if (available[W][c]) warriors.push_back(c);
    sort(warriors.begin(),warriors.end(),[&](int x,int y){return available[W][x]>available[W][y];});
    int planned_w[N]{}, commitments[N]{};
    bool tele_used = false;
    for (int src : warriors) {
        int remaining = available[W][src];
        for (int splits = 0; remaining && splits < 8; ++splits) {
            int gi = -1; double best = -1e20;
            for (int j = 0; j < int(goals.size()); ++j) {
                auto g = goals[j];
                int need = max(0,g.need-commitments[g.pos]);
                double v = g.value/(board.dist[src][g.pos]+2.0);
                if (!need) v *= .06;
                else v *= min(1.0, remaining/double(need)) * .5 + .5;
                if (v > best) {best = v; gi = j;}
            }
            auto g = goals[gi];
            int take = min(remaining,max(1,g.need-commitments[g.pos]));
            if (splits == 7) take = remaining;
            int dest = src; double best_step = -1e20; bool do_tele = false;
            vector<int> opts = board.adj[src]; opts.push_back(src);
            int src_b = board.at[src];
            bool can_tele = !tele_used && src_b >= 0 && board.type[src_b] == STATION && s.owner[src_b] == t;
            if (can_tele) for (int c : stations) if (c != src) opts.push_back(c);
            for (int c : opts) {
                bool tp = c != src && board.dist[src][c] > 1;
                int n = tp ? min(5,take) : take;
                double v = -3.0*board.dist[c][g.pos];
                int loss = max(0,danger[c] - planned_w[c] - n);
                if (loss) v -= min(16.0,2.0*loss) * (style == 2 ? .55 : 1.0);
                if (wanted[c]) v += 2;
                if (s.u[enemy][F][c] && n + planned_w[c] > s.u[enemy][W][c]) v += 1;
                v += .01*planned_w[c];
                if (v > best_step) {best_step=v; dest=c; do_tele=tp;}
            }
            if (do_tele) { take = min(take,5); tele_used = true; }
            planned_w[dest] += take; commitments[g.pos] += take;
            if (dest != src) a.moves.push_back({W,src,dest,take,do_tele});
            remaining -= take;
        }
    }
    int planned_f[N]{};
    for (auto [src,b] : flag_tasks) {
        int dest = src; double best = -1e20; bool do_tele = false;
        vector<int> opts = board.adj[src]; opts.push_back(src);
        int src_b = board.at[src];
        if (!tele_used && src_b >= 0 && board.type[src_b] == STATION && s.owner[src_b] == t)
            for (int c : stations) if (c != src) opts.push_back(c);
        for (int c : opts) {
            double v = -3.0*board.dist[c][board.pos[b]];
            if (danger[c] > planned_w[c]) v -= 100 + 3*(danger[c]-planned_w[c]);
            if (s.u[enemy][F][c] && planned_w[c] <= s.u[enemy][W][c]) v -= 8;
            v -= planned_f[c] * .25;
            if (v > best) {best=v; dest=c; do_tele=c != src && board.dist[src][c] > 1;}
        }
        if (do_tele) tele_used = true;
        if (dest != src) a.moves.push_back({F,src,dest,1,do_tele});
        ++planned_f[dest];
    }
    // Unassigned flags leave threatened owned buildings when an adjacent refuge exists.
    for (int src = 0; src < N; ++src) if (left[src] && danger[src] > planned_w[src]) {
        int dest = src, best = danger[src]-planned_w[src];
        for (int c : board.adj[src]) if (danger[c]-planned_w[c] < best) {
            dest=c; best=danger[c]-planned_w[c];
        }
        if (dest != src) a.moves.push_back({F,src,dest,left[src]});
    }
    a.priority.resize(board.nb); iota(a.priority.begin(),a.priority.end(),0);
    sort(a.priority.begin(),a.priority.end(),[&](int x,int y){return building_value(s,t,x,style)>building_value(s,t,y,style);});
    return a;
}

double evaluation(const State& s, int t) {
    double score[2] = {points(s,0),points(s,1)}, total = accumulate(s.score,s.score+board.nb,0.0);
    double a2_margin=s.turn>=160?clamp(20*(score[t]-score[1-t]),-1000.0,1000.0):0;
    if (score[1-t] == 0 && score[t]*2 > total) return 100000+a2_margin;
    if (score[t] == 0 && score[1-t]*2 > total) return -100000+a2_margin;
    double val[2]{};
    for (int team = 0; team < 2; ++team) {
        int nf = accumulate(s.u[team][F],s.u[team][F]+N,0);
        int nw = accumulate(s.u[team][W],s.u[team][W]+N,0);
        val[team] = 3*nw + 5*nf + 2*accumulate(s.u[team][S],s.u[team][S]+N,0);
    }
    if (s.turn >= 160) {
        if (score[t] != score[1-t]) return (score[t] > score[1-t] ? 100000 : -100000)+a2_margin;
        if (s.occupation[t] != s.occupation[1-t]) return s.occupation[t] > s.occupation[1-t] ? 90000 : -90000;
        return val[t] == val[1-t] ? 0 : val[t] > val[1-t] ? 80000 : -80000;
    }
    double future = min(1.0,(160-s.turn)/25.0);
    double margin = score[t]-score[1-t], attack = 1;
    // v9: with 1/0 scoring a spare point of lead is worth little and a deeper deficit costs little.
    if (s.turn >= V9_SWITCH && v9_mode == V9_LOCK) {
        if (margin > 3) margin = 3 + .3*(margin-3);
        attack = .5;
    } else if (s.turn >= V9_SWITCH && v9_mode == V9_ALLIN) {
        if (margin < -3) margin = -3 + .3*(margin+3);
    }
    double result = margin * (15 + (1-future)*45);
    result += 1.3*future*(val[t]-val[1-t]) + .35*future*(s.res[t]-s.res[1-t]);
    for (int team = 0; team < 2; ++team) {
        double bonus = 0;
        if (has(s,team,ENG)) bonus += 110;
        bonus += (income(s,team)-10)*35;
        if (has(s,team,HOSPITAL)) bonus += 25;
        result += (team == t ? 1 : -1)*future*bonus;
        for (int b = 0; b < board.nb; ++b) if (s.owner[b] != team) {
            int d = INF;
            for (int c = 0; c < N; ++c) if (s.u[team][F][c]) d = min(d,board.dist[c][board.pos[b]]);
            result += (team == t ? attack : -1)*building_value(s,team,b,0)/(d+3.0);
        }
    }
    return result;
}

int forced_policy = -1;
mt19937 rng(20260927);
bool initialized = false, depot_history[2][BMAX]{};
int occupation_history[2][BMAX]{};

constexpr int A_MIX=0, A_LOCAL=1, A_MEMORY=0;
constexpr int A_STAGE=0, A_UNCERTAIN=0, A_FREE=1;
using AClock=chrono::steady_clock;
bool a_previous=false;
State a_previous_state;
Action a_previous_action;
double a_error[4]{};

Action a_clean(const State& s,int t,const Action& input) {
    Action out; int available[3][N],budget=s.res[t]; bool tele=false;
    for(int k=0;k<3;++k) copy(s.u[t][k],s.u[t][k]+N,available[k]);
    for(auto p:input.spawn) {
        if(p.kind<0 || p.kind>=3 || p.pos<0 || p.pos>=N || p.count<=0) continue;
        int b=board.at[p.pos];
        if(p.pos!=board.base[t] && !(b>=0 && board.type[b]==HOSPITAL && s.owner[b]==t)) continue;
        p.count=min(p.count,budget/cost(s,t,p.kind));
        if(!p.count) continue;
        budget-=p.count*cost(s,t,p.kind); available[p.kind][p.pos]+=p.count; out.spawn.push_back(p);
    }
    for(auto m:input.moves) {
        if(m.kind<0 || m.kind>=3 || m.from<0 || m.from>=N || m.to<0 || m.to>=N || m.count<=0) continue;
        if(m.tele) {
            int x=board.at[m.from],y=board.at[m.to];
            if(tele || x<0 || y<0 || x==y || board.type[x]!=STATION || board.type[y]!=STATION || s.owner[x]!=t || s.owner[y]!=t) continue;
            m.count=min(m.count,5);
        } else if(find(board.adj[m.from].begin(),board.adj[m.from].end(),m.to)==board.adj[m.from].end()) continue;
        m.count=min(m.count,available[m.kind][m.from]);
        if(!m.count) continue;
        available[m.kind][m.from]-=m.count; out.moves.push_back(m);
        if(m.tele) tele=true;
    }
    bool used[BMAX]{};
    for(int b:input.priority) if(b>=0 && b<board.nb && !used[b]) {used[b]=true;out.priority.push_back(b);}
    return out;
}

Action a_mix(const State& s,int t,const Action& flag,const Action& warrior) {
    Action a=flag; a.moves.clear();
    for(auto m:warrior.moves) if(m.kind==W) a.moves.push_back(m);
    for(auto m:flag.moves) if(m.kind!=W) a.moves.push_back(m);
    return a_clean(s,t,a);
}

Action a_patch(const State& s,int t,Action current,const Action& alternative,int source) {
    current.moves.erase(remove_if(current.moves.begin(),current.moves.end(),[&](auto m){return m.from==source;}),current.moves.end());
    for(auto m:alternative.moves) if(m.from==source) current.moves.push_back(m);
    return a_clean(s,t,current);
}

bool a_equal(const Action& x,const Action& y) {
    if(x.spawn.size()!=y.spawn.size() || x.moves.size()!=y.moves.size() || x.priority!=y.priority) return false;
    for(int i=0;i<int(x.spawn.size());++i) {
        auto a=x.spawn[i],b=y.spawn[i]; if(a.kind!=b.kind || a.pos!=b.pos || a.count!=b.count) return false;
    }
    for(int i=0;i<int(x.moves.size());++i) {
        auto a=x.moves[i],b=y.moves[i];
        if(a.kind!=b.kind || a.from!=b.from || a.to!=b.to || a.count!=b.count || a.tele!=b.tele) return false;
    }
    return true;
}

double a_prediction_error(const State& predicted,const State& observed,int us) {
    double loss=0;
    for(int k=0;k<3;++k) for(int c=0;c<N;++c)
        loss+=(k==F?5.0:1.0)*abs(predicted.u[1-us][k][c]-observed.u[1-us][k][c]);
    for(int b=0;b<board.nb;++b) loss+=12*(predicted.owner[b]!=observed.owner[b]);
    return loss+.25*abs(predicted.res[1-us]-observed.res[1-us]);
}

void a_observe(const State& s,int us,double (&weights)[4]) {
    if(A_MEMORY && a_previous && s.turn==a_previous_state.turn+1) {
        for(int j=0;j<4;++j) {
            Action opp=policy(a_previous_state,1-us,j);
            State p=us==0?advance(a_previous_state,a_previous_action,opp):advance(a_previous_state,opp,a_previous_action);
            a_error[j]=.75*a_error[j]+.25*a_prediction_error(p,s,us);
        }
    }
    double low=*min_element(a_error,a_error+4),sum=0;
    for(int j=0;j<4;++j) {weights[j]=A_MEMORY?exp(-min(40.0,(a_error[j]-low)/8.0)):1;sum+=weights[j];}
    for(double& w:weights) w=.10+.60*w/sum;
}

State a_scenario(State s,int us,int scenario) {
    if(!A_UNCERTAIN) return s;
    for(int b=0;b<board.nb;++b) {
        int mirror=board.at[224-board.pos[b]];
        if(s.revealed[us][b] || (mirror>=0 && s.revealed[us][mirror])) continue;
        bool center=board.pos[b]%15>=5 && board.pos[b]%15<=9;
        s.score[b]=board.type[b]==PLAZA?3:center?(scenario?4:2):(scenario?2:1);
    }
    for(int t=0;t<2;++t) {
        s.occupation[t]=0;
        for(int b=0;b<board.nb;++b) s.occupation[t]+=occupation_history[t][b]*s.score[b];
    }
    return s;
}

// v9: risk attitude over the four opponent models. Leading: weight the worst reply (low variance).
// Trailing: weight the best reply (any line that can flip the result is worth trying).
double v9_combine(double mean,double worst,double best) {
    if(v9_mode==V9_LOCK) return .45*mean+.55*worst;
    if(v9_mode==V9_ALLIN) return .6*mean+.1*worst+.3*best;
    return .75*mean+.25*worst;
}

bool a_evaluate(const State& s,int us,const Action& first,int continuation,int horizon,
                const double (&weights)[4],AClock::time_point start,double limit,double& result) {
    double scenarios[2]{}; int count=A_UNCERTAIN?2:1;
    for(int scenario=0;scenario<count;++scenario) {
        double mean=0,worst=1e100,best=-1e100;
        for(int j=0;j<4;++j) {
            State trial=a_scenario(s,us,scenario);
            for(int d=0;d<horizon;++d) {
                if(chrono::duration<double,milli>(AClock::now()-start).count()>=limit) return false;
                Action own=d?policy(trial,us,continuation):first,opp=policy(trial,1-us,j);
                trial=us==0?advance(trial,own,opp):advance(trial,opp,own);
                if(abs(evaluation(trial,us))>=80000) break;
            }
            double score=evaluation(trial,us);
            mean+=weights[j]*score; worst=min(worst,score); best=max(best,score);
        }
        scenarios[scenario]=v9_combine(mean,worst,best);
    }
    result=count==1?scenarios[0]:min(scenarios[0],scenarios[1]);
    return true;
}

struct APlan {Action action;int continuation;double value;};

constexpr int S3_MODE=5;

constexpr int S3V2_MODE=1;
bool s3v2_accept(double trial,double incumbent,double guarded_gain=0) {
    if(v9_mode==V9_ALLIN) return trial>incumbent;   // v9: trailing, no per-opponent no-regret guard
    return trial>incumbent && ((S3V2_MODE!=1 && S3V2_MODE!=3) || guarded_gain>=0);
}
double s3v2_minimum_gain(const double (&seed)[4],const double (&trial)[4]) {
    double gain=1e100;
    for(int j=0;j<4;++j) gain=min(gain,trial[j]-seed[j]);
    return gain;
}
bool s3v2_values(const State& s,int us,const Action& first,int continuation,int depth,
                const double (&weights)[4],AClock::time_point start,double limit,
                double (&values)[4],double& result) {
    double mean=0,worst=1e100,best=-1e100;
    for(int opponent=0;opponent<4;++opponent) {
        State trial=s;
        for(int d=0;d<depth;++d) {
            if(chrono::duration<double,milli>(AClock::now()-start).count()>=limit) return false;
            Action own=d?policy(trial,us,continuation):first,enemy=policy(trial,1-us,opponent);
            trial=us==0?advance(trial,own,enemy):advance(trial,enemy,own);
            if(abs(evaluation(trial,us))>=80000) break;
        }
        values[opponent]=evaluation(trial,us);
        mean+=weights[opponent]*values[opponent];worst=min(worst,values[opponent]);best=max(best,values[opponent]);
    }
    result=v9_combine(mean,worst,best);return true;
}

int s3_base_continuation=0;
double s3_base_value=-1e100;

int s3_stock(const State& s,int us,const Action& a,int src,int kind) {
    int n=s.u[us][kind][src];
    for(auto p:a.spawn) if(p.pos==src && p.kind==kind) n+=p.count;
    return n;
}

Action s3_move(const State& s,int us,Action a,int src,int kind,int to,int count) {
    a.moves.erase(remove_if(a.moves.begin(),a.moves.end(),[&](auto m){return m.from==src && m.kind==kind;}),a.moves.end());
    if(to!=src && count>0) a.moves.push_back({kind,src,to,count});
    return a_clean(s,us,a);
}

void s3_add(vector<Action>& out,const Action& trial,const Action& current) {
    if(a_equal(trial,current)) return;
    if(none_of(out.begin(),out.end(),[&](const Action& old){return a_equal(old,trial);})) out.push_back(trial);
}

bool s3_contact(const State& s,int us,int c) {
    if(s.u[1-us][F][c] || s.u[1-us][W][c]) return true;
    for(int q:board.adj[c]) if(s.u[1-us][F][q] || s.u[1-us][W][q]) return true;
    int b=board.at[c];
    return b>=0 && s.u[us][F][c] && (s.owner[b]!=us || s.turn>=154);
}

vector<int> s3_groups(const State& s,int us,bool selective) {
    vector<pair<double,int>> rank;
    for(int c=0;c<N;++c) if(s.u[us][F][c] || s.u[us][W][c]) {
        if(selective && !s3_contact(s,us,c)) continue;
        double importance=8*s.u[us][F][c]+sqrt(double(s.u[us][W][c]))+(board.at[c]>=0?3:0);
        rank.push_back({-importance,c});
    }
    sort(rank.begin(),rank.end());
    vector<int> out;
    for(int i=0;i<min(4,int(rank.size()));++i) out.push_back(rank[i].second);
    return out;
}

vector<Action> s3_choices(const State& s,int us,const Action& current,int src,bool split) {
    vector<Action> out;
    vector<int> targets{src}; targets.insert(targets.end(),board.adj[src].begin(),board.adj[src].end());
    for(int to:targets) for(int mask=1;mask<=3;++mask) {
        Action trial=current;
        for(int kind=0;kind<2;++kind) if(mask&(1<<kind))
            trial=s3_move(s,us,trial,src,kind,to,s3_stock(s,us,current,src,kind));
        s3_add(out,trial,current);
    }
    if(split) for(int kind=0;kind<2;++kind) {
        int stock=s3_stock(s,us,current,src,kind);
        if(stock<2) continue;
        vector<int> counts{1,stock/2,stock-1};
        sort(counts.begin(),counts.end());counts.erase(unique(counts.begin(),counts.end()),counts.end());
        for(int to:board.adj[src]) for(int n:counts)
            s3_add(out,s3_move(s,us,current,src,kind,to,n),current);
        // Two destinations jointly spend one origin's stock; arrivals never fund departures.
        for(int i=0;i<int(board.adj[src].size());++i) for(int j=i+1;j<int(board.adj[src].size());++j) {
            Action trial=s3_move(s,us,current,src,kind,board.adj[src][i],stock/2);
            trial.moves.push_back({kind,src,board.adj[src][j],stock-stock/2});
            s3_add(out,a_clean(s,us,trial),current);
        }
    }
    return out;
}

vector<Action> s3_joint_choices(const State& s,int us,const Action& current,int left,int right) {
    vector<Action> out;
    vector<int> l{left},r{right};
    l.insert(l.end(),board.adj[left].begin(),board.adj[left].end());
    r.insert(r.end(),board.adj[right].begin(),board.adj[right].end());
    for(int x:l) for(int y:r) {
        // Convergence, a swap, and coordinated hold/advance are coupled before evaluation.
        if(x!=y && !(x==right && y==left) && x!=left && y!=right) continue;
        for(int mask=1;mask<=3;++mask) {
            Action trial=current;
            for(auto part:{pair{left,x},pair{right,y}}) for(int kind=0;kind<2;++kind)
                if(mask&(1<<kind)) trial=s3_move(s,us,trial,part.first,kind,part.second,s3_stock(s,us,current,part.first,kind));
            s3_add(out,trial,current);
        }
    }
    return out;
}

bool s3_try(const State& s,int us,const Action& action,int continuation,int depth,const double (&weights)[4],
            AClock::time_point start,double limit,APlan& best,double* score=nullptr) {
    double value;
    if(!a_evaluate(s,us,action,continuation,depth,weights,start,limit,value)) return false;
    if(score) *score=value;
    if(value>best.value) best={action,continuation,value};
    return true;
}


Action a_decide(const State& s,int us,AClock::time_point start,double limit=135.0) {
    Action scripts[4];
    for(int i=0;i<4;++i) scripts[i]=a_clean(s,us,policy(s,us,i));
    double weights[4]; a_observe(s,us,weights);
    vector<APlan> plans;
    for(int i=0;i<4;++i) plans.push_back({scripts[i],i,-1e100});
    // Evaluated first so a tight time budget cannot skip it.
    if(v9_mode==V9_ALLIN) {
        v9_randomize=true;
        Action allin=a_clean(s,us,policy(s,us,4));
        v9_randomize=false;
        for(const auto& note:v9_allin_notes) V9LOG("  [allin] " << note << "\n");
        plans.insert(plans.begin(),APlan{allin,4,-1e100});
    }
    if(A_MIX) for(auto pair:{std::pair{0,3},std::pair{3,0},std::pair{0,2},std::pair{2,0}})
        plans.push_back({a_mix(s,us,scripts[pair.first],scripts[pair.second]),pair.first,-1e100});
    int depth=min(A_STAGE?2:3,160-s.turn),best=0; bool any=false;
    for(int i=0;i<int(plans.size());++i) {
        double value;
        if(!a_evaluate(s,us,plans[i].action,plans[i].continuation,depth,weights,start,limit,value)) break;
        plans[i].value=value;
        if(!any || value>plans[best].value) best=i;
        any=true;
    }
    APlan incumbent=plans[best];
    if(v9_tracing) {
        static const char* names[5]={"s0-hold","s1-eco","s2-raid","s3-assign","s4-allin"};
        V9LOG("  [search] depth " << depth << ", script values:");
        for(auto& p:plans) {
            if(p.value<=-1e99) V9LOG(" " << names[p.continuation] << "=timeout");
            else V9LOG(" " << names[p.continuation] << "=" << long(p.value));
        }
        V9LOG("\n  [search] chosen " << (any?names[incumbent.continuation]:"none") << ": highest combined value"
              << " (" << (v9_mode==V9_LOCK?".45 mean+.55 worst":v9_mode==V9_ALLIN?".6 mean+.1 worst+.3 best":".75 mean+.25 worst")
              << " over 4 opponent models)\n");
    }
    const double v9_before_local=incumbent.value;
    if(A_STAGE && any) {
        vector<int> order;
        for(int i=0;i<int(plans.size());++i) if(plans[i].value>-1e99) order.push_back(i);
        stable_sort(order.begin(),order.end(),[&](int a,int b){return plans[a].value>plans[b].value;});
        int n=min(3,int(order.size())),deep=min(s.turn<80?6:4,160-s.turn); bool complete=true;
        vector<APlan> finalists;
        for(int k=0;k<n;++k) {
            APlan p=plans[order[k]];
            if(!a_evaluate(s,us,p.action,p.continuation,deep,weights,start,limit,p.value)) {complete=false;break;}
            finalists.push_back(p);
        }
        if(complete && !finalists.empty()) incumbent=*max_element(finalists.begin(),finalists.end(),[](auto a,auto b){return a.value<b.value;});
    }
    if(A_LOCAL && any) {
        vector<pair<double,int>> groups;
        for(int c=0;c<N;++c) if(s.u[us][F][c] || s.u[us][W][c]) {
            double importance=8*s.u[us][F][c]+sqrt(double(s.u[us][W][c]));
            int b=board.at[c]; if(b>=0) importance+=3;
            groups.push_back({-importance,c});
        }
        sort(groups.begin(),groups.end());
        for(int k=0;k<min(3,int(groups.size()));++k) {
            int src=groups[k].second;
            for(int j=0;j<4;++j) {
                Action trial=a_patch(s,us,incumbent.action,scripts[j],src); double value;
                if(a_equal(trial,incumbent.action)) continue;
                if(!a_evaluate(s,us,trial,incumbent.continuation,depth,weights,start,limit,value)) goto finished;
                if(value>incumbent.value) {incumbent.action=trial;incumbent.value=value;}
            }
            if(A_FREE) for(int target:board.adj[src]) {
                Action alternate;
                for(int kind=0;kind<2;++kind) if(s.u[us][kind][src]) alternate.moves.push_back({kind,src,target,s.u[us][kind][src]});
                Action trial=a_patch(s,us,incumbent.action,alternate,src); double value;
                if(a_equal(trial,incumbent.action)) continue;
                if(!a_evaluate(s,us,trial,incumbent.continuation,depth,weights,start,limit,value)) goto finished;
                if(value>incumbent.value) {incumbent.action=trial;incumbent.value=value;}
            }
        }
    }
finished:
    if(any && incumbent.value>v9_before_local)
        V9LOG("  [search] per-group patch improved value " << long(v9_before_local) << " -> " << long(incumbent.value) << "\n");
    if(A_MEMORY) {a_previous=true;a_previous_state=s;a_previous_action=incumbent.action;}
    s3_base_continuation=incumbent.continuation;s3_base_value=incumbent.value;
    return incumbent.action;
}

Action guard1_base_decide(const State& s,int us,AClock::time_point start,double limit=135.0) {
    auto groups=s3_groups(s,us,S3_MODE==6);
    if(groups.empty()) return a_decide(s,us,start,limit);
    Action seed=a_decide(s,us,start,min(limit,65.0));
    APlan best{seed,s3_base_continuation,s3_base_value};
    double weights[4];a_observe(s,us,weights);
    int depth=min(3,160-s.turn);
    if(S3_MODE==3) {
        for(int i=0;i<int(groups.size());++i) for(int j=i+1;j<int(groups.size());++j) {
            if(board.dist[groups[i]][groups[j]]>2) continue;
            Action anchor=best.action;
            for(const Action& trial:s3_joint_choices(s,us,anchor,groups[i],groups[j]))
                if(!s3_try(s,us,trial,best.continuation,depth,weights,start,limit,best)) return best.action;
        }
    } else if(S3_MODE==4) {
        vector<APlan> beam{best};
        for(int src:groups) {
            vector<APlan> next=beam;
            for(const APlan& parent:beam) for(const Action& trial:s3_choices(s,us,parent.action,src,false)) {
                double value;
                if(!s3_try(s,us,trial,parent.continuation,depth,weights,start,limit,best,&value)) return best.action;
                if(none_of(next.begin(),next.end(),[&](const APlan& old){return a_equal(old.action,trial);}))
                    next.push_back({trial,parent.continuation,value});
            }
            stable_sort(next.begin(),next.end(),[](const APlan& a,const APlan& b){return a.value>b.value;});
            if(next.size()>3) next.resize(3);
            beam=move(next);
        }
    } else if(S3_MODE==5) {

        vector<APlan> shortlist;
        vector<vector<Action>> choices;
        for(int src:groups) choices.push_back(s3_choices(s,us,seed,src,true));
        bool exhausted=false;
        if(S3V2_MODE==2) {
            for(size_t round=0;;++round) {
                bool any=false;
                for(const auto& group:choices) if(round<group.size()) {
                    any=true;double value;
                    if(!a_evaluate(s,us,group[round],best.continuation,1,weights,start,min(limit,85.0),value)) {
                        exhausted=true;break;
                    }
                    shortlist.push_back({group[round],best.continuation,value});
                }
                if(exhausted || !any) break;
            }
        } else {
            for(const auto& group:choices) {
                for(const Action& trial:group) {
                    double value;
                    if(!a_evaluate(s,us,trial,best.continuation,1,weights,start,min(limit,100.0),value)) {
                        exhausted=true;break;
                    }
                    shortlist.push_back({trial,best.continuation,value});
                }
                if(exhausted) break;
            }
        }
        stable_sort(shortlist.begin(),shortlist.end(),[](const APlan& a,const APlan& b){return a.value>b.value;});
        int alternate=best.continuation==3?0:3;
        double alternate_seed=s3_base_value;
        double seed_values[4]{};
        if(S3V2_MODE==1 && !shortlist.empty()) {
            double checked_seed;
            if(!s3v2_values(s,us,seed,best.continuation,depth,weights,start,limit,seed_values,checked_seed)) return seed;
        }
        if(S3V2_MODE==3 && depth>1 && !shortlist.empty())
            if(!a_evaluate(s,us,seed,alternate,depth,weights,start,limit,alternate_seed)) return seed;
        for(int i=0;i<min(8,int(shortlist.size()));++i) {
            double value,values[4]{};
            if(S3V2_MODE==1) {
                if(!s3v2_values(s,us,shortlist[i].action,best.continuation,depth,weights,start,limit,values,value)) break;
            } else if(!a_evaluate(s,us,shortlist[i].action,best.continuation,depth,weights,start,limit,value)) break;
            if(value<=best.value) continue;
            double alternate_gain=value-s3_base_value;
            if(S3V2_MODE==1) alternate_gain=s3v2_minimum_gain(seed_values,values);
            if(S3V2_MODE==3 && depth>1) {
                double alternative;
                if(!a_evaluate(s,us,shortlist[i].action,alternate,depth,weights,start,limit,alternative)) break;
                alternate_gain=alternative-alternate_seed;
            }
            if(s3v2_accept(value,best.value,alternate_gain))
                best={shortlist[i].action,best.continuation,value};
        }
    } else {
        for(int pass=0;pass<(S3_MODE==7?2:1);++pass) {
            bool improved=false;
            if(pass) reverse(groups.begin(),groups.end());
            for(int src:groups) {
                Action anchor=best.action;
                double before=best.value;
                for(const Action& trial:s3_choices(s,us,anchor,src,S3_MODE==2 || S3_MODE==7))
                    if(!s3_try(s,us,trial,best.continuation,depth,weights,start,limit,best)) return best.action;
                improved|=best.value>before;
            }
            if(!improved) break;
        }
    }
    if(!a_equal(best.action,seed))
        V9LOG("  [refine] local move search around " << groups.size() << " contact groups replaced the script plan"
              << " (value " << long(s3_base_value) << " -> " << long(best.value) << ")\n");
    else V9LOG("  [refine] no local alternative beat the script plan\n");
    return best.action;
}

Action deadline_guard(const State& s,int us,Action action) {
    if(s.turn>=150) return action;
    action=a_clean(s,us,action);
    int enemy=1-us,stock[N]{},locked[N]{},danger[N]{};
    copy(s.u[us][W],s.u[us][W]+N,stock);
    for(auto p:action.spawn) if(p.kind==W) stock[p.pos]+=p.count;
    vector<int> sources{board.base[us]},enemy_sources{board.base[enemy]};
    for(int b=0;b<board.nb;++b) if(board.type[b]==HOSPITAL && s.owner[b]>=0)
        (s.owner[b]==us?sources:enemy_sources).push_back(board.pos[b]);
    for(int c=0;c<N;++c) if(board.pass[c]) {
        danger[c]=s.u[enemy][W][c];
        for(int q:board.adj[c]) danger[c]+=s.u[enemy][W][q];
        for(int q:enemy_sources) if(board.dist[c][q]<=1) {
            danger[c]+=s.res[enemy]/cost(s,enemy,W);break;
        }
        int b=board.at[c];
        if(b>=0 && board.type[b]==STATION && s.owner[b]==enemy) {
            int remote=0;
            for(int j=0;j<board.nb;++j) if(j!=b && board.type[j]==STATION && s.owner[j]==enemy)
                remote=max(remote,min(5,s.u[enemy][W][board.pos[j]]));
            danger[c]+=remote;
        }
    }
    int seed_flags[N]{},seed_warriors[N]{};
    copy(s.u[us][F],s.u[us][F]+N,seed_flags);
    copy(stock,stock+N,seed_warriors);
    for(auto p:action.spawn) if(p.kind==F) seed_flags[p.pos]+=p.count;
    for(auto m:action.moves) {
        if(m.kind==F) {seed_flags[m.from]-=m.count;seed_flags[m.to]+=m.count;}
        if(m.kind==W) {seed_warriors[m.from]-=m.count;seed_warriors[m.to]+=m.count;}
    }
    // v9: station-aware enemy ETA (walk to any enemy station, teleport, walk on).
    vector<int> enemy_stations=v9_stations(s,enemy);
    auto enemy_eta=[&](int src,int target) {return v9_eta(enemy_stations,src,target);};
    struct Defense {int target,deadline,need;};
    vector<Defense> defenses;
    for(int b=0;b<board.nb;++b) {
        if(s.owner[b]!=us || (board.type[b]!=ENG && board.type[b]!=HALL)) continue;
        int target=board.pos[b];
        if(board.dist[board.base[us]][target]>=board.dist[board.base[enemy]][target]) continue;
        int flag_eta=INF,warrior_eta=INF;
        for(int c=0;c<N;++c) {
            if(s.u[enemy][F][c]) flag_eta=min(flag_eta,enemy_eta(c,target));
            if(s.u[enemy][W][c]) warrior_eta=min(warrior_eta,enemy_eta(c,target));
        }
        flag_eta=max(1,flag_eta);
        if(flag_eta>6) continue;
        if(s.res[enemy]>=cost(s,enemy,W)) for(int c:enemy_sources)
            warrior_eta=min(warrior_eta,max(1,board.dist[c][target]));
        int need=1;
        if(warrior_eta<=flag_eta) {
            // v9: an escorted raid needs one W more than the enemy W that can arrive with the flag.
            if(!V9_MID) continue;
            int escort=0;
            for(int c=0;c<N;++c) if(s.u[enemy][W][c] && enemy_eta(c,target)<=flag_eta) escort+=s.u[enemy][W][c];
            for(int c:enemy_sources) if(board.dist[c][target]<=flag_eta) {escort+=s.res[enemy]/cost(s,enemy,W);break;}
            need=escort+1;
            if(need>V9_MID_MAX) {
                V9LOG("  [mid-guard] " << v9_bname(b) << ": escorted raid, enemy F in " << flag_eta << " turns with "
                      << escort << " W -> need " << need << " > cap " << V9_MID_MAX << ", not answered\n");
                continue;
            }
        }
        V9LOG("  [mid-guard] " << v9_bname(b) << ": enemy F in " << flag_eta << " turns"
              << (need>1?", escorted":", unescorted") << " -> need " << need << " W\n");
        defenses.push_back({target,flag_eta,need});
    }
    stable_sort(defenses.begin(),defenses.end(),[](auto a,auto b){return a.deadline<b.deadline;});
    vector<Movement> reserved;
    int assignments=0;
    auto safe_step=[&](int src,int target) {
        if(src==target) return danger[src]? -1:src;
        int dest=-1;
        for(int q:board.adj[src]) if(board.dist[q][target]<board.dist[src][target] && !danger[q]) {
            dest=q;break;
        }
        return dest;
    };
    auto assemble=[&]() {
        Action result=action;
        vector<Movement> moves;
        int available[N];
        for(int c=0;c<N;++c) available[c]=stock[c]-locked[c];
        for(auto m:action.moves) {
            if(m.kind==W) {m.count=min(m.count,available[m.from]);available[m.from]-=m.count;}
            if(m.count>0) moves.push_back(m);
        }
        moves.insert(moves.end(),reserved.begin(),reserved.end());
        result.moves=move(moves);
        return a_clean(s,us,result);
    };
    auto safe_reservation=[&](int src,int dest) {
        ++locked[src];
        if(src!=dest) reserved.push_back({W,src,dest,1});
        Action trial=assemble();
        --locked[src];
        if(src!=dest) reserved.pop_back();
        int warriors[N];copy(s.u[us][W],s.u[us][W]+N,warriors);
        for(auto p:trial.spawn) if(p.kind==W) warriors[p.pos]+=p.count;
        for(auto m:trial.moves) if(m.kind==W) {warriors[m.from]-=m.count;warriors[m.to]+=m.count;}
        for(int c=0;c<N;++c) if(seed_flags[c] && warriors[c]<seed_warriors[c])
            return false;
        return true;
    };
    // v9: escorted raids expect enemy W next to the target, so they may stand on it and step
    // through the least dangerous cell instead of requiring a danger-free path.
    auto relaxed_step=[&](int src,int target) {
        if(src==target) return src;
        int dest=-1,low=INF;
        for(int q:board.adj[src]) if(board.dist[q][target]<board.dist[src][target] && danger[q]<low) {
            dest=q;low=danger[q];
        }
        return dest;
    };
    for(auto defense:defenses) {
        if(assignments>=2) {V9LOG("  [mid-guard]   " << v9_cell(defense.target) << ": skipped, 2-building cap reached\n"); break;}
        // Snapshot: a sized defence is all-or-nothing, a partial answer only feeds the enemy escort.
        int locked_before[N]; copy(locked,locked+N,locked_before);
        int stock_before[N]; copy(stock,stock+N,stock_before);
        auto reserved_before=reserved; auto spawn_before=action.spawn;
        auto step_for=[&](int src,int target) {
            return defense.need>1?relaxed_step(src,target):safe_step(src,target);
        };
        int placed=0;
        for(;placed<defense.need;++placed) {
        int source=-1,dest=-1,best=INF;
        for(int c=0;c<N;++c) if(stock[c]>locked[c] && board.dist[c][defense.target]<=defense.deadline) {
            int step=step_for(c,defense.target);
            if(step<0 || !safe_reservation(c,step)) continue;
            int rank=4*board.dist[c][defense.target];
            for(auto m:action.moves) if(m.kind==W && m.from==c && m.to==step && m.count>0) {--rank;break;}
            if(rank<best) {best=rank;source=c;dest=step;}
        }
        if(source<0) {
            vector<pair<int,int>> sites;
            for(int c:sources) if(board.dist[c][defense.target]<=defense.deadline && step_for(c,defense.target)>=0)
                sites.push_back({board.dist[c][defense.target],c});
            sort(sites.begin(),sites.end());
            for(auto [eta,site]:sites) {
                int step=step_for(site,defense.target);
                int original_size=int(action.spawn.size());
                for(int donor=0;donor<original_size;++donor) {
                    auto production=action.spawn[donor];
                    if(production.kind!=W || production.count<=0 || production.pos==site || stock[production.pos]<=locked[production.pos]) continue;
                    --action.spawn[donor].count;--stock[production.pos];
                    action.spawn.push_back({W,site,1});++stock[site];
                    if(safe_reservation(site,step)) {source=site;dest=step;break;}
                    action.spawn.pop_back();--stock[site];
                    ++action.spawn[donor].count;++stock[production.pos];
                }
                if(source>=0) break;
            }
            if(source<0) break;
        }
        ++locked[source];
        if(source!=dest) reserved.push_back({W,source,dest,1});
        }
        if(placed<defense.need) {
            copy(locked_before,locked_before+N,locked); copy(stock_before,stock_before+N,stock);
            reserved=reserved_before; action.spawn=spawn_before;
            V9LOG("  [mid-guard]   " << v9_cell(defense.target) << ": only " << placed << "/" << defense.need
                  << " W can arrive safely in time -> rolled back (partial defence only trades W)\n");
            continue;
        }
        V9LOG("  [mid-guard]   " << v9_cell(defense.target) << ": reserved " << placed << " W to arrive by turn +"
              << defense.deadline << "\n");
        ++assignments;
    }
    if(!assignments) return action;
    return assemble();
}

// ---- v9: endgame guard (LOCK / NORMAL from V9_SWITCH) -------------------------
// Conservative threat model (kept on purpose): every enemy F that can reach an owned building within
// the horizon threatens it, even if the same F threatens several buildings. Travel times on both sides
// are station-aware (walk, or walk to an owned station + teleport + walk). need = every enemy W able to
// be on the building by the flag's arrival te (teleport-borne W capped at 5 per turn, plus a fresh
// spawn) + 1.
// Allocation is all-or-nothing per building (a partial answer only trades W one for one, so trying to
// hold two buildings must not lose both). Several orders are tried (score, score per W, cheapest first,
// earliest first) and the one that holds the most score is kept, fewer locked W breaking ties: when two
// buildings can both be held, both are held.
// Defenders: walking W, W reaching an own station and teleporting (<=5 per turn, the current turn's
// teleport reserved before the search may use it, never emptying a threatened origin station), and W
// production moved to a source within reach (LOCK may convert a planned F spawn into defenders).
struct V9Alloc {
    int locked[N]{}, stock[N]{};
    vector<Production> spawn;
    vector<Movement> reserved;
    bool tele_now=false;
    int tele_later[24]{};
    int spent=0, used=0;
    double covered=0;
    vector<string> notes;
};
Action v9_endgame_guard(const State& s,int us,Action action) {
    action=a_clean(s,us,action);
    const int enemy=1-us, remaining=160-s.turn;
    if(remaining<=0) return action;
    const int horizon=min(remaining,V9_HORIZON);
    int stock0[N]{};
    copy(s.u[us][W],s.u[us][W]+N,stock0);
    for(auto p:action.spawn) if(p.kind==W) stock0[p.pos]+=p.count;
    auto sources=v9_sources(s,us), enemy_sources=v9_sources(s,enemy);
    auto ours=v9_stations(s,us), theirs=v9_stations(s,enemy);
    const int espawn=s.res[enemy]/cost(s,enemy,W);
    int danger[N]{};
    for(int c=0;c<N;++c) if(board.pass[c]) {
        danger[c]=s.u[enemy][W][c];
        for(int q:board.adj[c]) danger[c]+=s.u[enemy][W][q];
        for(int q:enemy_sources) if(board.dist[c][q]<=1) {danger[c]+=espawn;break;}
    }
    struct Threat {int b,te,need;};
    vector<Threat> threats;
    int threat_need[BMAX]{};
    for(int b=0;b<board.nb;++b) if(s.owner[b]==us) {
        int target=board.pos[b], te=INF, from=-1; bool spawned=false;
        for(int c=0;c<N;++c) if(s.u[enemy][F][c]) {
            int e=max(1,v9_eta(theirs,c,target));
            if(e<te) {te=e;from=c;}
        }
        if(s.res[enemy]>=5) for(int c:enemy_sources) if(max(1,board.dist[c][target])<te) {
            te=max(1,board.dist[c][target]);from=c;spawned=true;
        }
        if(te>horizon) continue;
        int walk_w=0,tele_w=0,spawn_w=0;
        for(int c=0;c<N;++c) if(s.u[enemy][W][c]) {
            if(board.dist[c][target]<=te) walk_w+=s.u[enemy][W][c];
            else if(v9_eta(theirs,c,target)<=te) tele_w+=s.u[enemy][W][c];
        }
        tele_w=min(tele_w,5*max(1,te-1));
        for(int c:enemy_sources) if(board.dist[c][target]<=te) {spawn_w=espawn;break;}
        int need=walk_w+tele_w+spawn_w+1;
        V9LOG("  [end-guard] threat " << v9_bname(b) << " score " << s.score[b] << ": enemy F "
              << (spawned?"spawnable at ":"from ") << v9_cell(from)
              << (!spawned && board.dist[from][target]>te?" via station":"") << " arrives in " << te
              << ", enemy W able to join " << walk_w << " walking"
              << (tele_w?" + "+to_string(tele_w)+" via station":"")
              << (spawn_w?" + "+to_string(spawn_w)+" spawnable":"") << " -> need " << need << "\n");
        threats.push_back({b,te,need});
        threat_need[b]=need;
    }
    if(threats.empty()) {V9LOG("  [end-guard] no owned building has an enemy F within " << horizon << " turns\n"); return action;}
    int spent0=0;
    for(auto p:action.spawn) spent0+=p.count*cost(s,us,p.kind);
    auto walk_step=[&](int c,int target) {
        if(c==target) return c;
        int dest=c,low=INF;
        for(int q:board.adj[c]) if(board.dist[q][target]<board.dist[c][target] && danger[q]<low) {dest=q;low=danger[q];}
        return dest;
    };
    auto run=[&](const vector<int>& order,V9Alloc& A) {
        copy(stock0,stock0+N,A.stock); fill(A.locked,A.locked+N,0);
        A.spawn=action.spawn; A.reserved.clear(); A.tele_now=false; fill(A.tele_later,A.tele_later+24,0);
        A.spent=spent0; A.used=0; A.covered=0; A.notes.clear();
        bool processed[BMAX]{};
        for(int idx:order) {
            const Threat& th=threats[idx];
            processed[th.b]=true;
            const int target=board.pos[th.b];
            auto keep=[&](int c) {   // W an unprocessed threatened building needs for itself
                int b=board.at[c];
                return (b>=0 && b!=th.b && threat_need[b] && !processed[b])?threat_need[b]:0;
            };
            // Candidates: (eta, via-station, cell). Walking first, W on another threatened building last.
            struct Cand {int eta,station,other,c;};
            vector<Cand> cands;
            for(int c=0;c<N;++c) if(A.stock[c]>A.locked[c]) {
                int walk=board.dist[c][target];
                V9Route r=v9_route(ours,c,target);
                if(walk<=th.te) cands.push_back({walk,0,keep(c)>0,c});
                else if(r.s1>=0 && r.eta<=th.te) cands.push_back({r.eta,1,keep(c)>0,c});
            }
            sort(cands.begin(),cands.end(),[](const Cand& x,const Cand& y){
                if(x.station!=y.station) return x.station<y.station;
                if(x.other!=y.other) return x.other<y.other;
                if(x.eta!=y.eta) return x.eta<y.eta;
                return x.c<y.c;
            });
            int got=0, tele_k=0, tele_src=-1, tele_dst=-1, later_used[24]{};
            vector<pair<int,int>> walk, via;   // (cell,count)
            for(const Cand& x:cands) {
                if(got>=th.need) break;
                int k=min(th.need-got,A.stock[x.c]-A.locked[x.c]);
                if(!x.station) {walk.push_back({x.c,k}); got+=k; continue;}
                V9Route r=v9_route(ours,x.c,target);
                if(r.d1==0) {   // teleport this turn: one per team, keep the origin's own defence
                    if(A.tele_now || tele_k) continue;
                    k=min({k,5,A.stock[x.c]-A.locked[x.c]-keep(x.c)});
                    if(k<=0) continue;
                    tele_k=k; tele_src=x.c; tele_dst=r.s2; got+=k;
                } else {
                    int d1=min(23,r.d1);
                    k=min(k,5-A.tele_later[d1]-later_used[d1]);
                    if(k<=0) continue;
                    later_used[d1]+=k; via.push_back({x.c,k}); got+=k;
                }
            }
            // Production at a source within reach.
            int site=-1, extra=0;
            vector<pair<int,int>> donors; vector<int> f_drop;
            if(got<th.need) {
                int best=INF;
                for(int c:sources) {int e=v9_eta(ours,c,target); if(e<=th.te && e<best) {best=e;site=c;}}
                if(site>=0) {
                    const int wc=cost(s,us,W);
                    int budget=s.res[us]-A.spent;
                    for(int i=0;i<int(A.spawn.size()) && got+extra<th.need;++i) {
                        auto p=A.spawn[i];
                        if(p.kind!=W || p.pos==site || p.count<=0) continue;
                        int k=min({p.count,A.stock[p.pos]-A.locked[p.pos],th.need-got-extra});
                        if(k>0) {donors.push_back({i,k});extra+=k;}
                    }
                    while(got+extra<th.need && budget>=wc) {budget-=wc;++extra;}
                    if(v9_mode==V9_LOCK) for(int i=0;i<int(A.spawn.size()) && got+extra<th.need;++i) {
                        if(A.spawn[i].kind!=F || A.spawn[i].count<=0) continue;
                        f_drop.push_back(i); budget+=A.spawn[i].count*5;
                        while(got+extra<th.need && budget>=wc) {budget-=wc;++extra;}
                    }
                }
            }
            if(got+extra<th.need) {
                A.notes.push_back(v9_bname(th.b)+": GIVE UP, only "+to_string(got+extra)+"/"+to_string(th.need)+
                                  " W can be there within "+to_string(th.te)+" turns; those W stay with the search plan");
                continue;
            }
            ostringstream note;
            note << v9_bname(th.b) << ": HOLD with " << th.need << " W =";
            for(auto [c,k]:walk) {
                A.locked[c]+=k;
                int dest=walk_step(c,target);
                if(dest!=c) A.reserved.push_back({W,c,dest,k});
                note << " " << k << " walk from " << v9_cell(c) << " (dist " << board.dist[c][target] << ")";
            }
            for(auto [c,k]:via) {
                A.locked[c]+=k;
                Movement m=v9_step(ours,W,c,target,k,false,danger);
                if(m.to!=c) A.reserved.push_back(m);
                V9Route r=v9_route(ours,c,target);
                note << " " << k << " from " << v9_cell(c) << " via station " << v9_cell(r.s1) << "->" << v9_cell(r.s2)
                     << " (eta " << r.eta << ")";
            }
            for(int d=0;d<24;++d) A.tele_later[d]+=later_used[d];
            if(tele_k) {
                A.locked[tele_src]+=tele_k; A.tele_now=true;
                A.reserved.push_back({W,tele_src,tele_dst,tele_k,true});
                note << " " << tele_k << " teleport now " << v9_cell(tele_src) << "->" << v9_cell(tele_dst);
            }
            if(extra) {
                int from_budget=extra;
                for(auto [i,k]:donors) {A.spawn[i].count-=k; A.stock[A.spawn[i].pos]-=k; from_budget-=k;}
                for(int i:f_drop) {A.spent-=A.spawn[i].count*5; A.spawn[i].count=0;}
                A.spent+=from_budget*cost(s,us,W);
                A.spawn.push_back({W,site,extra}); A.stock[site]+=extra; A.locked[site]+=extra;
                Movement m=v9_step(ours,W,site,target,extra,false,danger);
                if(m.to!=site) A.reserved.push_back(m);
                note << " " << extra << " spawned at " << v9_cell(site) << (donors.empty()?"":" (moved from other sites)")
                     << (f_drop.empty()?"":" (F spawn converted)");
            }
            A.notes.push_back(note.str());
            A.covered+=s.score[th.b]; A.used+=th.need;
        }
    };
    // Candidate orders; keep the allocation that holds the most score.
    vector<int> base(threats.size());
    iota(base.begin(),base.end(),0);
    auto ordered=[&](auto less) {vector<int> o=base; stable_sort(o.begin(),o.end(),less); return o;};
    const char* names[4]={"score","score/W","cheapest","earliest"};
    vector<vector<int>> orders{
        ordered([&](int x,int y){const auto&a=threats[x];const auto&b=threats[y];
            return s.score[a.b]!=s.score[b.b] ? s.score[a.b]>s.score[b.b] : a.te<b.te;}),
        ordered([&](int x,int y){const auto&a=threats[x];const auto&b=threats[y];
            return s.score[a.b]/a.need>s.score[b.b]/b.need;}),
        ordered([&](int x,int y){const auto&a=threats[x];const auto&b=threats[y];
            return a.need!=b.need ? a.need<b.need : s.score[a.b]>s.score[b.b];}),
        ordered([&](int x,int y){const auto&a=threats[x];const auto&b=threats[y];
            return a.te!=b.te ? a.te<b.te : s.score[a.b]>s.score[b.b];}),
    };
    static V9Alloc trial, best;
    int chosen=-1;
    for(int i=0;i<int(orders.size());++i) {
        run(orders[i],trial);
        V9LOG("  [end-guard] order " << names[i] << ": holds " << trial.covered << " points with " << trial.used << " W\n");
        if(chosen<0 || trial.covered>best.covered || (trial.covered==best.covered && trial.used<best.used)) {
            best=trial; chosen=i;
        }
    }
    V9LOG("  [end-guard] using order " << names[chosen] << " (most score held, fewer locked W on ties)\n");
    for(const auto& note:best.notes) V9LOG("  [end-guard]   " << note << "\n");
    if(best.reserved.empty() && none_of(best.locked,best.locked+N,[](int x){return x>0;})) return action;
    // Reserved moves first so the defensive teleport is the one the engine applies.
    Action result=action;
    result.spawn=best.spawn;
    result.spawn.erase(remove_if(result.spawn.begin(),result.spawn.end(),[](const Production& p){return p.count<=0;}),result.spawn.end());
    vector<Movement> moves=best.reserved;
    int available[N];
    for(int c=0;c<N;++c) available[c]=best.stock[c]-best.locked[c];
    for(auto m:action.moves) {
        if(best.tele_now && m.tele) {V9LOG("  [end-guard] search teleport " << v9_cell(m.from) << "->" << v9_cell(m.to)
                                            << " dropped: teleport reserved for defence\n"); continue;}
        if(m.kind==W) {
            int wanted=m.count;
            m.count=min(m.count,max(0,available[m.from]));available[m.from]-=m.count;
            if(m.count<wanted) V9LOG("  [end-guard] search move " << v9_cell(m.from) << "->" << v9_cell(m.to) << " W "
                                     << wanted << " cut to " << m.count << ": units locked for defence\n");
        }
        if(m.count>0) moves.push_back(m);
    }
    result.moves=move(moves);
    return a_clean(s,us,result);
}

// v9: our F on an owned building dies to a larger enemy W arrival and neutralises it; step off first.
Action v9_flag_safety(const State& s,int us,Action action) {
    const int enemy=1-us;
    auto enemy_sources=v9_sources(s,enemy);
    int espawn=s.res[enemy]/cost(s,enemy,W);
    int fw[N]; copy(s.u[us][W],s.u[us][W]+N,fw);
    int stay[N]; copy(s.u[us][F],s.u[us][F]+N,stay);
    for(auto p:action.spawn) if(p.kind==W) fw[p.pos]+=p.count;
    for(auto m:action.moves) {
        if(m.kind==W) {fw[m.from]-=m.count;fw[m.to]+=m.count;}
        if(m.kind==F) stay[m.from]-=m.count;
    }
    auto danger=[&](int c) {
        int r=s.u[enemy][W][c];
        for(int q:board.adj[c]) r+=s.u[enemy][W][q];
        for(int q:enemy_sources) if(board.dist[c][q]<=1) {r+=espawn;break;}
        return r;
    };
    bool changed=false;
    for(int c=0;c<N;++c) {
        int b=board.at[c];
        if(stay[c]<=0 || b<0 || s.owner[b]!=us || danger(c)<=fw[c]) continue;
        int dest=-1,low=INF;
        for(int q:board.adj[c]) {
            int v=danger(q)-fw[q];
            if(v<low) {low=v;dest=q;}
        }
        if(dest>=0) {
            V9LOG("  [flag-safety] F " << stay[c] << " on own " << v9_bname(b) << " steps to " << v9_cell(dest)
                  << ": enemy W reach " << danger(c) << " > our W " << fw[c] << " (its death would neutralise the building)\n");
            action.moves.push_back({F,c,dest,stay[c]});changed=true;
        }
    }
    return changed?a_clean(s,us,action):action;
}

Action s3_decide(const State& s,int us,AClock::time_point start,double limit=135.0) {
    Action a=guard1_base_decide(s,us,start,limit);
    if(s.turn<V9_SWITCH) return deadline_guard(s,us,a);
    if(v9_mode==V9_ALLIN) {V9LOG("  [end-guard] off: ALLIN abandons defensive reservations\n"); return a;}
    return v9_flag_safety(s,us,v9_endgame_guard(s,us,a));
}

vector<string> decide(const p::View& v, const p::Init& in) {
    auto start = chrono::steady_clock::now();
    if (!initialized) {board.init(in); initialized=true;}
    int us = in.team == "Y" ? 0 : 1;
    State s; s.turn=v.turn-1; s.res[us]=v.my_resource; s.res[1-us]=v.opp_resource;
    for (const auto& u : v.units) s.u[u.team=="Y"?0:1][kinds.find(u.kind[0])][u.x+15*u.y] += u.count;
    for (int b = 0; b < board.nb; ++b) {
        const auto& x = v.buildings[b];
        s.owner[b] = x.owner == "N" ? -1 : x.owner == "Y" ? 0 : 1; s.stage[b]=x.stage;
        s.score[b] = x.score;
        if (x.score >= 0) s.revealed[us][b] = true;
        if (s.owner[b] >= 0) {
            if (v.turn > 1) ++occupation_history[s.owner[b]][b];
            if (board.type[b] == DEPOT) depot_history[s.owner[b]][b] = true;
        }
    }
    for (int b = 0; b < board.nb; ++b) {
        int mirror = board.at[224-board.pos[b]];
        v9_known[b] = s.score[b] >= 0 || (mirror >= 0 && s.score[mirror] >= 0) || board.type[b] == PLAZA;
    }
    for (int b = 0; b < board.nb; ++b) if (s.score[b] < 0) {
        int mirror = board.at[224-board.pos[b]];
        if (mirror >= 0 && s.score[mirror] >= 0) s.score[b] = s.score[mirror];
        else s.score[b] = board.type[b] == PLAZA ? 3 : board.pos[b]%15>=5 && board.pos[b]%15<=9 ? 3 : 1.5;
    }
    for (int t = 0; t < 2; ++t) for (int b = 0; b < board.nb; ++b) {
        s.claimed[t][b] = depot_history[t][b]; s.occupation[t] += occupation_history[t][b]*s.score[b];
    }
    // v9: score margin from our view. Owned buildings are always revealed to their owner, so only
    // enemy buildings whose mirror we never saw are estimated (side 1-2, centre 2-4).
    {
        double mine = 0, theirs = 0, theirs_high = 0;
        for (int b = 0; b < board.nb; ++b) {
            if (s.owner[b] == us) mine += s.score[b];
            if (s.owner[b] != 1-us) continue;
            theirs += s.score[b];
            bool centre = board.type[b] == WATCH || board.type[b] == DEPOT ||
                          (board.type[b] == STATION && board.pos[b]%15>=5 && board.pos[b]%15<=9);
            theirs_high += v9_known[b] ? s.score[b] : centre ? 4 : 2;
        }
        v9_margin = mine - theirs; v9_margin_low = mine - theirs_high;
        if (s.turn < V9_SWITCH) v9_mode = V9_NORMAL;
        else if (v9_margin >= 1) v9_mode = V9_LOCK;
        else if (v9_margin <= -1) v9_mode = V9_ALLIN;
        else v9_mode = s.occupation[us] > s.occupation[1-us] ? V9_LOCK : V9_ALLIN;   // tie-break by occupation
        if (v9_tracing) {
            int unknown = 0, nw[2]{}, nf[2]{};
            for (int b = 0; b < board.nb; ++b) if (s.owner[b] == 1-us && !v9_known[b]) ++unknown;
            for (int t = 0; t < 2; ++t) for (int c = 0; c < N; ++c) {nw[t] += s.u[t][W][c]; nf[t] += s.u[t][F][c];}
            V9LOG("\n== turn " << v.turn << " (" << in.team << ") mode " << v9_mode_name(v9_mode)
                  << " | score us " << mine << " them ~" << theirs << " (worst " << theirs_high << ", "
                  << unknown << " enemy buildings estimated) margin " << v9_margin
                  << " | res " << s.res[us] << "/" << s.res[1-us] << " W " << nw[us] << "/" << nw[1-us]
                  << " F " << nf[us] << "/" << nf[1-us] << "\n");
            if (s.turn < V9_SWITCH) V9LOG("  [mode] NORMAL: before turn " << V9_SWITCH+1 << "\n");
            else if (v9_margin >= 1) V9LOG("  [mode] LOCK: estimated lead " << v9_margin << " >= 1 -> minimise variance, hold every point\n");
            else if (v9_margin <= -1) V9LOG("  [mode] ALLIN: estimated deficit " << v9_margin << " <= -1 -> maximise variance\n");
            else V9LOG("  [mode] " << v9_mode_name(v9_mode) << ": score tie region, occupation " << long(s.occupation[us])
                       << " vs " << long(s.occupation[1-us]) << " decides\n");
            if (s.turn > 145) V9LOG("  [flags] endgame F demand " << v9_flag_target(s,us,7)
                                    << " (targets reachable before 160 + threatened own buildings)\n");
        }
    }
    Action a=forced_policy>=0?policy(s,us,forced_policy):s3_decide(s,us,start);
    vector<string> out;
    for (auto x : a.spawn) {
        if (x.pos==board.base[us]) out.push_back(p::spawn(string(1,kinds[x.kind]),x.count));
        else out.push_back(p::spawn(string(1,kinds[x.kind]),x.count,x.pos%15,x.pos/15));
    }
    for (auto x : a.moves) {
        if (x.tele) out.push_back(p::tele(x.from%15,x.from/15,string(1,kinds[x.kind]),x.count,x.to%15,x.to/15));
        else {
            int delta=x.to-x.from; string dir=delta==1?"R":delta==-1?"L":delta==15?"D":"U";
            out.push_back(p::move(x.from%15,x.from/15,string(1,kinds[x.kind]),x.count,dir));
        }
    }
    vector<pair<int,int>> prio;
    for (int b : a.priority) prio.push_back({board.pos[b]%15,board.pos[b]/15});
    out.push_back(p::priority(prio));
    if (v9_tracing) {
        V9LOG("  [out] " << chrono::duration<double,milli>(chrono::steady_clock::now()-start).count() << " ms:");
        for (const auto& line : out) V9LOG(" | " << line);
        V9LOG("\n");
        v9_trace_file.flush();
    }
    return out;
}

int main(int argc,char** argv) {
    for (int i = 1; i < argc; ++i) {
        string arg = argv[i];
        if (arg.rfind("--trace=", 0) == 0) {
            v9_trace_file.open(arg.substr(8));
            v9_tracing = bool(v9_trace_file);
        } else forced_policy = clamp(atoi(argv[i]),0,3);
    }
    return p::run(decide);
}
