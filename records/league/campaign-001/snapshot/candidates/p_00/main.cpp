#include "protocol.hpp"
#include <chrono>
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

Action policy(const State& s, int t, int style) {
    if (style==3) return assignment_policy(s,t);
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
    if (s.turn > 145) desired_flags = min(desired_flags,3);
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
    if (score[1-t] == 0 && score[t]*2 > total) return 100000;
    if (score[t] == 0 && score[1-t]*2 > total) return -100000;
    double val[2]{};
    for (int team = 0; team < 2; ++team) {
        int nf = accumulate(s.u[team][F],s.u[team][F]+N,0);
        int nw = accumulate(s.u[team][W],s.u[team][W]+N,0);
        val[team] = 3*nw + 5*nf + 2*accumulate(s.u[team][S],s.u[team][S]+N,0);
    }
    if (s.turn >= 160) {
        if (score[t] != score[1-t]) return score[t] > score[1-t] ? 100000 : -100000;
        if (s.occupation[t] != s.occupation[1-t]) return s.occupation[t] > s.occupation[1-t] ? 90000 : -90000;
        return val[t] == val[1-t] ? 0 : val[t] > val[1-t] ? 80000 : -80000;
    }
    double future = min(1.0,(160-s.turn)/25.0);
    double result = (score[t]-score[1-t]) * (15 + (1-future)*45);
    result += 1.3*future*(val[t]-val[1-t]) + .35*future*(s.res[t]-s.res[1-t]);
    for (int team = 0; team < 2; ++team) {
        double bonus = 0;
        if (has(s,team,ENG)) bonus += 70;
        bonus += (income(s,team)-10)*35;
        if (has(s,team,HOSPITAL)) bonus += 25;
        result += (team == t ? 1 : -1)*future*bonus;
        for (int b = 0; b < board.nb; ++b) if (s.owner[b] != team) {
            int d = INF;
            for (int c = 0; c < N; ++c) if (s.u[team][F][c]) d = min(d,board.dist[c][board.pos[b]]);
            result += (team == t ? 1 : -1)*building_value(s,team,b,0)/(d+3.0);
        }
    }
    return result;
}

int forced_policy = -1;
mt19937 rng(20260927);
bool initialized = false, depot_history[2][BMAX]{};
int occupation_history[2][BMAX]{};
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
    for (int b = 0; b < board.nb; ++b) if (s.score[b] < 0) {
        int mirror = board.at[224-board.pos[b]];
        if (mirror >= 0 && s.score[mirror] >= 0) s.score[b] = s.score[mirror];
        else s.score[b] = board.type[b] == PLAZA ? 3 : board.pos[b]%15>=5 && board.pos[b]%15<=9 ? 3 : 1.5;
    }
    for (int t = 0; t < 2; ++t) for (int b = 0; b < board.nb; ++b) {
        s.claimed[t][b] = depot_history[t][b]; s.occupation[t] += occupation_history[t][b]*s.score[b];
    }
    constexpr int P=4;
    Action candidates[P];
    for (int i = 0; i < P; ++i) candidates[i]=policy(s,us,i);
    int chosen = forced_policy;
    if (chosen < 0) {
        double payoff[P][P]{};
        bool complete = true;
        int horizon = min(4,160-s.turn);
        for (int i = 0; i < P && complete; ++i) for (int j = 0; j < P; ++j) {
            State trial=s;
            for (int d = 0; d < horizon; ++d) {
                Action own=d==0?candidates[i]:policy(trial,us,i), opp=policy(trial,1-us,j);
                trial=us==0?advance(trial,own,opp):advance(trial,opp,own);
                double e=evaluation(trial,us);
                if (abs(e)>=80000) break;
                if (chrono::duration<double,milli>(chrono::steady_clock::now()-start).count()>160) {complete=false;break;}
            }
            payoff[i][j]=evaluation(trial,us)/200.0;
            if (!complete) break;
        }
        chosen=0;
        if (complete) {
            double rr[P]{}, rc[P]{}, avg[P]{};
            for (int it = 0; it < 600; ++it) {
                double x[P]{}, y[P]{}, sx=0,sy=0;
                for (int i = 0; i < P; ++i) {x[i]=max(0.0,rr[i]);y[i]=max(0.0,rc[i]);sx+=x[i];sy+=y[i];}
                for (int i = 0; i < P; ++i) {x[i]=sx?x[i]/sx:1.0/P;y[i]=sy?y[i]/sy:1.0/P;avg[i]+=x[i];}
                double rv[P]{}, cv[P]{}, value=0;
                for (int i = 0; i < P; ++i) for (int j = 0; j < P; ++j) {rv[i]+=payoff[i][j]*y[j];cv[j]+=payoff[i][j]*x[i];value+=x[i]*y[j]*payoff[i][j];}
                for (int i = 0; i < P; ++i) {rr[i]+=rv[i]-value;rc[i]+=value-cv[i];}
            }
            chosen=discrete_distribution<int>(avg,avg+P)(rng);
        }
    }
    const auto& a=candidates[chosen];
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
    return out;
}

int main(int argc,char** argv) {
    if (argc>1) forced_policy=clamp(atoi(argv[1]),0,3);
    return p::run(decide);
}
