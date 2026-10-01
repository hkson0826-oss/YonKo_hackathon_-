// yk_core.hpp - shared game core for the new bot family (not derived from v1-v9 code).
//
// Contents
//   Board      static map data: passability, adjacency, all-pairs BFS distance, buildings, mirror partner
//   State      full observable state (units, resources, owners, stages, depot claims, occupation)
//   Action     spawn / move / move2 / tele / priority, plus legalize() and to_lines()
//   advance()  faithful re-implementation of the engine turn pipeline (spawn, move, combat, income,
//              capture with library snapshot and PRIORITY order, depot bonus, occupation)
//   helpers    unit/capture cost, income, sources, stations, tele-aware ETA, threat counts, danger map
//
// Rules digest (yk-development-tools/engine/pipeline.py is authoritative)
//   15x15, 160 turns, 180-degree point symmetry (x,y)<->(14-x,14-y). Team 0 = Y, team 1 = K.
//   F cost 5 (only capturer), W cost 3 (2 if any ENG owned), S cost 2 (MOVE2, reveals Chebyshev 2).
//   Income 10 + 2 per HALL, cap 40 on every gain. Capture 2 (PLAZA 4), -1 with LIBRARY, min 1.
//   Pipeline: spawn(Y then K) -> simultaneous moves -> combat (W cancel 1:1, the side with W left wipes
//   the other side's F and S; an owner F wiped on its building pulls the flag -> N stage 1) -> income ->
//   capture (neutral -> owned, enemy -> neutral; contested if both F) -> depot +15 -> occupation -> reveal
//   -> victory (instant: opponent score 0 and my score > total/2; at 160: score, occupation, unit value).
//   TURN n input = state after engine turn n-1. The state after turn 160 is never sent.
#pragma once
#include "protocol.hpp"
#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <map>
#include <numeric>
#include <string>
#include <vector>

namespace yk {
using std::array;
using std::max;
using std::min;
using std::string;
using std::vector;

constexpr int GW = 15, GH = 15, N = GW * GH, NB = 17, INF = 1000000, FAR = 999, LAST_TURN = 160;
enum Kind { F = 0, W = 1, S = 2 };
constexpr const char* KIND_CHAR = "FWS";
enum BType { PLAZA = 0, HALL, LIBRARY, ENG, HOSPITAL, STATION, WATCH, DEPOT, NTYPE };
inline const char* TYPE_NAME[NTYPE] = {"PLAZA", "HALL", "LIBRARY", "ENG", "HOSPITAL", "STATION", "WATCH", "DEPOT"};
inline int type_code(const string& s) {
    for (int i = 0; i < NTYPE; ++i) if (s == TYPE_NAME[i]) return i;
    return -1;
}
inline int cx(int c) { return c % GW; }
inline int cy(int c) { return c / GW; }
inline int cell(int x, int y) { return x + GW * y; }
inline int mirror_cell(int c) { return N - 1 - c; }
inline int cheb(int a, int b) { return max(std::abs(cx(a) - cx(b)), std::abs(cy(a) - cy(b))); }
inline int manhattan(int a, int b) { return std::abs(cx(a) - cx(b)) + std::abs(cy(a) - cy(b)); }
inline string cell_str(int c) { return "(" + std::to_string(cx(c)) + "," + std::to_string(cy(c)) + ")"; }

// ------------------------------------------------------------------ Board
struct Board {
    bool pass[N]{};
    vector<int> adj[N];          // passable 4-neighbours, order U D L R
    short dist[N][N];            // BFS steps, FAR when unreachable
    int nb = 0;
    int bpos[NB]{}, btype[NB]{}, partner[NB]{};
    bool center[NB]{};           // x in 5..9 (score 2..4 region); PLAZA excluded
    int at[N];                   // building id at cell or -1
    int base[2]{};
    int me = 0, op = 1;

    void init(const p::Init& in) {
        me = in.team == "Y" ? 0 : 1;
        op = 1 - me;
        for (int c = 0; c < N; ++c) {
            pass[c] = in.terrain[cy(c)][cx(c)] != '#';
            at[c] = -1;
            adj[c].clear();
        }
        for (int c = 0; c < N; ++c) {
            const int x = cx(c), y = cy(c);
            const int nx[4] = {x, x, x - 1, x + 1}, ny[4] = {y - 1, y + 1, y, y};
            for (int d = 0; d < 4; ++d)
                if (nx[d] >= 0 && nx[d] < GW && ny[d] >= 0 && ny[d] < GH && pass[cell(nx[d], ny[d])])
                    adj[c].push_back(cell(nx[d], ny[d]));
        }
        nb = 0;
        for (const auto& b : in.buildings) {
            if (b.id < 0 || b.id >= NB) continue;
            bpos[b.id] = cell(b.x, b.y);
            btype[b.id] = max(0, type_code(b.type));
            at[bpos[b.id]] = b.id;
            nb = max(nb, b.id + 1);
        }
        for (int b = 0; b < nb; ++b) {
            int q = at[mirror_cell(bpos[b])];
            partner[b] = q >= 0 ? q : b;
            center[b] = btype[b] != PLAZA && cx(bpos[b]) >= 5 && cx(bpos[b]) <= 9;
        }
        base[0] = cell(in.bases[0].first, in.bases[0].second);
        base[1] = cell(in.bases[1].first, in.bases[1].second);
        static int queue_[N];
        for (int s = 0; s < N; ++s) {
            for (int c = 0; c < N; ++c) dist[s][c] = FAR;
            if (!pass[s]) continue;
            int head = 0, tail = 0;
            dist[s][s] = 0;
            queue_[tail++] = s;
            while (head < tail) {
                int c = queue_[head++];
                for (int q : adj[c]) if (dist[s][q] == FAR) {
                    dist[s][q] = dist[s][c] + 1;
                    queue_[tail++] = q;
                }
            }
        }
    }
    bool adjacent(int a, int b) const {
        for (int q : adj[a]) if (q == b) return true;
        return false;
    }
    // Neighbour of `from` on a shortest path to `to` minimising cost[] (nullptr = first found). from if from==to.
    int step_toward(int from, int to, const int* cost = nullptr) const {
        if (from == to) return from;
        int best = -1, low = INF;
        for (int q : adj[from]) if (dist[q][to] < dist[from][to]) {
            int v = cost ? cost[q] : 0;
            if (v < low) { low = v; best = q; }
        }
        return best < 0 ? from : best;
    }
};
inline Board B;

// ------------------------------------------------------------------ State
struct State {
    int turn = 0;                 // completed engine turns (TURN n input -> n-1)
    int res[2]{};
    int u[2][3][N]{};             // [team][kind][cell]
    int owner[NB];                // -1 neutral, 0 Y, 1 K
    int stage[NB]{};
    bool claimed[2][NB]{};        // depot bonus already received
    long occ[2]{};                // occupation accumulated inside advance() (simulation only)
    State() { for (int b = 0; b < NB; ++b) owner[b] = -1; }
};

inline int count_type(const State& s, int t, int type) {
    int n = 0;
    for (int b = 0; b < B.nb; ++b) if (s.owner[b] == t && B.btype[b] == type) ++n;
    return n;
}
inline bool owns_type(const State& s, int t, int type) { return count_type(s, t, type) > 0; }
inline int unit_cost(const State& s, int t, int kind) {
    if (kind == F) return 5;
    if (kind == S) return 2;
    return max(3 - count_type(s, t, ENG), 2);
}
inline int capture_cost(const State& s, int t, int b) {
    int c = B.btype[b] == PLAZA ? 4 : 2;
    if (owns_type(s, t, LIBRARY)) c -= 1;
    return max(c, 1);
}
inline int income(const State& s, int t) { return 10 + 2 * count_type(s, t, HALL); }
inline int total_units(const State& s, int t, int kind) {
    int n = 0;
    for (int c = 0; c < N; ++c) n += s.u[t][kind][c];
    return n;
}
inline int unit_value(const State& s, int t) {
    return 5 * total_units(s, t, F) + 3 * total_units(s, t, W) + 2 * total_units(s, t, S);
}
inline int points(const State& s, int t, const int* sc) {
    int p = 0;
    for (int b = 0; b < B.nb; ++b) if (s.owner[b] == t) p += sc[b];
    return p;
}
inline int owned_count(const State& s, int t) {
    int n = 0;
    for (int b = 0; b < B.nb; ++b) n += s.owner[b] == t;
    return n;
}
inline bool has_units(const State& s, int t, int c) { return s.u[t][F][c] || s.u[t][W][c] || s.u[t][S][c]; }
// Spawn sites: base first, then owned hospitals.
inline vector<int> sources(const State& s, int t) {
    vector<int> out{B.base[t]};
    for (int b = 0; b < B.nb; ++b) if (B.btype[b] == HOSPITAL && s.owner[b] == t) out.push_back(B.bpos[b]);
    return out;
}
inline vector<int> stations(const State& s, int t) {
    vector<int> out;
    for (int b = 0; b < B.nb; ++b) if (B.btype[b] == STATION && s.owner[b] == t) out.push_back(B.bpos[b]);
    return out;
}
// Turns for a unit of team t to walk from -> to, using one teleport between two owned stations if shorter.
inline int eta(const State& s, int t, int from, int to) {
    int d = B.dist[from][to];
    auto st = stations(s, t);
    if (st.size() >= 2)
        for (int a : st) for (int b : st) if (a != b) d = min(d, B.dist[from][a] + 1 + B.dist[b][to]);
    return d;
}
inline int source_dist(const State& s, int t, int target) {
    int d = FAR;
    for (int c : sources(s, t)) d = min(d, (int)B.dist[c][target]);
    return d;
}
// Enemy (team att) W that can stand on `target` within `turns` turns: walking/teleporting units plus units
// spawned now at a source in reach; with_income also counts future income spent on W while still in time.
inline int reach_w(const State& s, int att, int target, int turns, bool with_spawn = true, bool with_income = false) {
    int n = 0;
    for (int c = 0; c < N; ++c) if (s.u[att][W][c] && eta(s, att, c, target) <= turns) n += s.u[att][W][c];
    if (with_spawn) {
        int d = source_dist(s, att, target);
        if (d <= turns) {
            int cost = unit_cost(s, att, W), budget = s.res[att];
            if (with_income) budget += income(s, att) * (turns - d);
            n += budget / cost;
        }
    }
    return n;
}
// Earliest turn count in which a team-att F can stand on target (existing F, or a fresh F from a source).
inline int flag_eta(const State& s, int att, int target, bool with_spawn = true) {
    int best = FAR;
    for (int c = 0; c < N; ++c) if (s.u[att][F][c]) best = min(best, eta(s, att, c, target));
    if (with_spawn && s.res[att] >= 5) best = min(best, max(1, source_dist(s, att, target)));
    return best;
}
// Enemy W pressure per cell: W on the cell and neighbours, plus spawnable W next to their sources.
inline void danger_map(const State& s, int att, int* out) {
    const int spawn = s.res[att] / unit_cost(s, att, W);
    auto src = sources(s, att);
    for (int c = 0; c < N; ++c) {
        out[c] = 0;
        if (!B.pass[c]) continue;
        out[c] = s.u[att][W][c];
        for (int q : B.adj[c]) out[c] += s.u[att][W][q];
        for (int q : src) if (B.dist[c][q] <= 1) { out[c] += spawn; break; }
    }
}

// ------------------------------------------------------------------ Action
struct Spawn { int kind, pos, count; };
struct Move {
    int kind, from, to, count;
    bool tele = false;
    int via = -1;                 // MOVE2 (scouts only): from -> via -> to
};
struct Action {
    vector<Spawn> spawn;
    vector<Move> moves;
    vector<int> priority;         // building ids, highest first
    void add_spawn(int kind, int pos, int n) { if (n > 0) spawn.push_back({kind, pos, n}); }
    void add_move(int kind, int from, int to, int n) { if (n > 0 && from != to) moves.push_back({kind, from, to, n}); }
    void add_tele(int kind, int from, int to, int n) { if (n > 0 && from != to) moves.push_back({kind, from, to, n, true}); }
    void add_move2(int from, int via, int to, int n) { if (n > 0) moves.push_back({S, from, to, n, false, via}); }
};

// Clips an action to exactly what the engine will execute for team t (affordability in order, spawn sites,
// movable pools including fresh spawns, adjacency, one teleport, MOVE2 legality) and merges duplicate lines.
inline Action legalize(const State& s, int t, const Action& in) {
    Action out;
    int budget = s.res[t];
    static int pool[3][N];
    for (int k = 0; k < 3; ++k) std::copy(s.u[t][k], s.u[t][k] + N, pool[k]);
    for (auto sp : in.spawn) {
        if (sp.kind < 0 || sp.kind > 2 || sp.pos < 0 || sp.pos >= N || sp.count <= 0) continue;
        int b = B.at[sp.pos];
        if (sp.pos != B.base[t] && !(b >= 0 && B.btype[b] == HOSPITAL && s.owner[b] == t)) continue;
        int c = unit_cost(s, t, sp.kind), n = min(sp.count, budget / c);
        if (n <= 0) continue;
        budget -= n * c;
        pool[sp.kind][sp.pos] += n;
        bool merged = false;
        for (auto& o : out.spawn) if (o.kind == sp.kind && o.pos == sp.pos) { o.count += n; merged = true; break; }
        if (!merged) out.spawn.push_back({sp.kind, sp.pos, n});
    }
    const int own_stations = (int)stations(s, t).size();
    bool tele_done = false;
    std::map<long, int> index;
    for (auto m : in.moves) {
        if (m.kind < 0 || m.kind > 2 || m.from < 0 || m.from >= N || m.to < 0 || m.to >= N || m.count <= 0) continue;
        if (m.from == m.to) continue;
        int n = min(m.count, pool[m.kind][m.from]);
        if (n <= 0) continue;
        if (m.tele) {
            int a = B.at[m.from], b = B.at[m.to];
            if (tele_done || a < 0 || b < 0 || B.btype[a] != STATION || B.btype[b] != STATION ||
                s.owner[a] != t || s.owner[b] != t || own_stations < 2) continue;
            n = min(n, 5);
            tele_done = true;
            m.via = -1;
        } else if (m.via >= 0) {
            if (m.kind != S || m.via >= N || !B.adjacent(m.from, m.via) || !B.adjacent(m.via, m.to)) continue;
        } else if (!B.adjacent(m.from, m.to)) {
            continue;
        }
        pool[m.kind][m.from] -= n;
        long key = ((((long)m.kind * N + m.from) * N + m.to) * 2 + (m.tele ? 1 : 0)) * (N + 1) + (m.via + 1);
        auto it = index.find(key);
        if (it != index.end() && !m.tele) out.moves[it->second].count += n;
        else {
            index[key] = (int)out.moves.size();
            m.count = n;
            out.moves.push_back(m);
        }
    }
    bool used[NB]{};
    for (int b : in.priority) if (b >= 0 && b < B.nb && !used[b]) { used[b] = true; out.priority.push_back(b); }
    return out;
}

inline char dir_char(int from, int to) {
    int d = to - from;
    return d == -GW ? 'U' : d == GW ? 'D' : d == -1 ? 'L' : 'R';
}
// Protocol lines for team t (END is added by the runner). Output stays far below the 4096-line cap.
inline vector<string> to_lines(const Action& a, int t) {
    vector<string> out;
    for (auto& sp : a.spawn) {
        string k(1, KIND_CHAR[sp.kind]);
        if (sp.pos == B.base[t]) out.push_back(p::spawn(k, sp.count));
        else out.push_back(p::spawn(k, sp.count, cx(sp.pos), cy(sp.pos)));
    }
    for (auto& m : a.moves) {
        string k(1, KIND_CHAR[m.kind]);
        if (m.tele) out.push_back(p::tele(cx(m.from), cy(m.from), k, m.count, cx(m.to), cy(m.to)));
        else if (m.via >= 0)
            out.push_back(p::move2(cx(m.from), cy(m.from), m.count, string(1, dir_char(m.from, m.via)), string(1, dir_char(m.via, m.to))));
        else out.push_back(p::move(cx(m.from), cy(m.from), k, m.count, string(1, dir_char(m.from, m.to))));
        if (out.size() >= 4000) break;
    }
    if (!a.priority.empty()) {
        vector<std::pair<int, int>> xy;
        for (int b : a.priority) xy.push_back({cx(B.bpos[b]), cy(B.bpos[b])});
        out.push_back(p::priority(xy));
    }
    return out;
}

// ------------------------------------------------------------------ Simulator
// Home-normalised (y,x) key used by the engine's default capture order.
inline int home_key(int t, int b) {
    int c = B.bpos[b];
    if (cx(B.base[t]) * 2 > GW - 1) c = mirror_cell(c);
    return cy(c) * GW + cx(c);
}
// One engine turn. a0 is team 0 (Y), a1 team 1 (K). sc = building scores used for points, occupation and the
// default capture order (the engine orders by scores revealed to each team; an estimate is used here).
inline State advance(const State& s0, const Action& a0, const Action& a1, const int* sc) {
    State s = s0;
    const Action* act[2] = {&a0, &a1};
    ++s.turn;
    for (int b = 0; b < B.nb; ++b) if (s.owner[b] < 0 && s.stage[b] == 1) s.stage[b] = 0;
    // 1. spawn (Y first)
    for (int t = 0; t < 2; ++t) for (const auto& sp : act[t]->spawn) {
        if (sp.kind < 0 || sp.kind > 2 || sp.count <= 0 || sp.pos < 0 || sp.pos >= N) continue;
        int b = B.at[sp.pos];
        if (sp.pos != B.base[t] && !(b >= 0 && B.btype[b] == HOSPITAL && s.owner[b] == t)) continue;
        int c = unit_cost(s, t, sp.kind), n = min(sp.count, s.res[t] / c);
        if (n <= 0) continue;
        s.res[t] -= n * c;
        s.u[t][sp.kind][sp.pos] += n;
    }
    // 2. moves from the pre-move pool, arrivals merged afterwards
    static int arrive[2][3][N];
    std::memset(arrive, 0, sizeof(arrive));
    for (int t = 0; t < 2; ++t) {
        bool tele_used = false;
        int nst = (int)stations(s, t).size();
        for (auto m : act[t]->moves) {
            if (m.kind < 0 || m.kind > 2 || m.from < 0 || m.from >= N || m.to < 0 || m.to >= N || m.count <= 0) continue;
            if (m.tele) {
                int a = B.at[m.from], b = B.at[m.to];
                if (tele_used || m.from == m.to || a < 0 || b < 0 || B.btype[a] != STATION || B.btype[b] != STATION ||
                    s.owner[a] != t || s.owner[b] != t || nst < 2) continue;
                m.count = min(m.count, 5);
            } else if (m.via >= 0) {
                if (m.kind != S || !B.adjacent(m.from, m.via) || !B.adjacent(m.via, m.to)) continue;
            } else if (!B.adjacent(m.from, m.to)) continue;
            int n = min(m.count, s.u[t][m.kind][m.from]);
            if (n <= 0) continue;
            s.u[t][m.kind][m.from] -= n;
            arrive[t][m.kind][m.to] += n;
            if (m.tele) tele_used = true;
        }
    }
    for (int t = 0; t < 2; ++t) for (int k = 0; k < 3; ++k) for (int c = 0; c < N; ++c) s.u[t][k][c] += arrive[t][k][c];
    // 3. combat
    for (int c = 0; c < N; ++c) {
        if (!has_units(s, 0, c) || !has_units(s, 1, c)) continue;
        int m = min(s.u[0][W][c], s.u[1][W][c]);
        s.u[0][W][c] -= m;
        s.u[1][W][c] -= m;
        for (int t = 0; t < 2; ++t) if (s.u[1 - t][W][c] > 0 && s.u[t][W][c] == 0) {
            int b = B.at[c];
            if (b >= 0 && s.owner[b] == t && s.u[t][F][c] > 0) { s.owner[b] = -1; s.stage[b] = 1; }
            s.u[t][F][c] = 0;
            s.u[t][S][c] = 0;
        }
    }
    // 4-5. income after combat
    for (int t = 0; t < 2; ++t) s.res[t] = min(40, s.res[t] + income(s, t));
    // 6. capture (library snapshot, PRIORITY then score then home key), Y then K
    bool library[2] = {owns_type(s, 0, LIBRARY), owns_type(s, 1, LIBRARY)};
    int bonus[2]{};
    for (int t = 0; t < 2; ++t) {
        vector<int> cand;
        for (int b = 0; b < B.nb; ++b) {
            int c = B.bpos[b];
            if (s.u[t][F][c] <= 0 || s.u[1 - t][F][c] > 0) continue;
            if (s.owner[b] == t && s.stage[b] >= 2) continue;
            cand.push_back(b);
        }
        vector<int> order;
        bool used[NB]{};
        for (int b : act[t]->priority)
            if (b >= 0 && b < B.nb && !used[b] && std::find(cand.begin(), cand.end(), b) != cand.end()) { used[b] = true; order.push_back(b); }
        vector<int> rest;
        for (int b : cand) if (!used[b]) rest.push_back(b);
        std::sort(rest.begin(), rest.end(), [&](int x, int y) {
            if (sc[x] != sc[y]) return sc[x] > sc[y];
            return home_key(t, x) < home_key(t, y);
        });
        order.insert(order.end(), rest.begin(), rest.end());
        for (int b : order) {
            int cost = max((B.btype[b] == PLAZA ? 4 : 2) - (library[t] ? 1 : 0), 1);
            if (s.res[t] < cost) continue;
            s.res[t] -= cost;
            if (s.owner[b] < 0) {
                s.owner[b] = t;
                s.stage[b] = 2;
                if (B.btype[b] == DEPOT && !s.claimed[t][b]) { s.claimed[t][b] = true; bonus[t] += 15; }
            } else {
                s.owner[b] = -1;
                s.stage[b] = 1;
            }
        }
    }
    for (int t = 0; t < 2; ++t) {
        if (bonus[t]) s.res[t] = min(40, s.res[t] + bonus[t]);
        s.occ[t] += points(s, t, sc);
    }
    return s;
}
// Team that wins instantly in state s (-1 if none).
inline int instant_winner(const State& s, const int* sc) {
    int total = 0;
    for (int b = 0; b < B.nb; ++b) total += sc[b];
    for (int t = 0; t < 2; ++t)
        if (owned_count(s, 1 - t) == 0 && 2 * points(s, t, sc) > total) return t;
    return -1;
}

// ------------------------------------------------------------------ Parsing
inline State state_from_view(const p::View& v) {
    State s;
    s.turn = v.turn - 1;
    s.res[B.me] = v.my_resource;
    s.res[B.op] = v.opp_resource;
    for (const auto& u : v.units) {
        int t = u.team == "Y" ? 0 : u.team == "K" ? 1 : -1;
        int k = u.kind == "F" ? F : u.kind == "W" ? W : u.kind == "S" ? S : -1;
        if (t < 0 || k < 0 || u.x < 0 || u.x >= GW || u.y < 0 || u.y >= GH || u.count <= 0) continue;
        s.u[t][k][cell(u.x, u.y)] += u.count;
    }
    for (const auto& b : v.buildings) {
        if (b.id < 0 || b.id >= NB) continue;
        s.owner[b.id] = b.owner == "Y" ? 0 : b.owner == "K" ? 1 : -1;
        s.stage[b.id] = b.stage;
    }
    return s;
}

}  // namespace yk
