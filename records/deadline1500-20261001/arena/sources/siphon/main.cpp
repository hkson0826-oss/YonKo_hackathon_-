// siphon - "economic strangler".
//
// Idea: the final W difference equals the W production difference, so the bot fights the production war:
// it takes the opponent's economy (ENG, HALL, HOSPITAL) with one escorted strike group, garrisons what it
// took, forward-spawns from a captured hospital and closes out with an instant win when the enemy is down
// to a few buildings. Everything is re-planned from the observed state each turn (fed states need not follow
// from our commands); cross-turn memory is only used for target hysteresis and staging-wait counters.
//
// Turn plan
//   1. valuation   value(b) = (our W-rate - their W-rate) gain x remaining turns + points x wpts (+ depot,
//                  closeout bonus, final-phase p_win_with delta). W-rate = income / W cost (+ small extras).
//   2. threats     arrival-time threat on every own building: min enemy flag ETA (units on board or fresh
//                  spawns near their sources) and the W needed on the cell by then (their escort + 1).
//   3. flags       greedy (flag, target) assignment by value / (eta + escort wait + 3); fresh flags may be
//                  spawned; at most `strikeCap` raids on enemy-owned buildings (one strike group early).
//                  Undefendable own economy buildings get a sentinel flag parked next to (not on) them.
//   4. spawns      every resource is spent: W for defence deficits at the nearest source in time, the rest
//                  at the source closest to the strike group (captured hospital = forward spawn).
//   5. warriors    all-or-nothing defence / flag-kill tasks and partial escorts, greedy by value per W.
//   6. movement    a flag steps only onto cells where its escort covers every enemy W that can get there
//                  this turn; entering the 2-cell zone around an enemy-owned target waits for the full escort.
#include "yk_bot.hpp"
using namespace yk;

namespace {

constexpr int DEF_HORIZON = 7;     // enemy flag ETA considered a threat to an own building
constexpr int SPAWN_THREAT = 5;    // own buildings this close to an enemy source face spawned flags
constexpr int ZONE = 2;            // commit zone around an enemy-owned target
constexpr int MIN_RAID = 4;        // V9 answers escorted raids only if its need <= 4 -> escort >= 4
constexpr double ENEMY_ECON = 1.25;

struct SiphonMemory {
    int tgt[N];                    // flag cell after our move -> mission building
    int wait[NB];                  // turns a strike group waited at the zone edge
    SiphonMemory() { std::fill(tgt, tgt + N, -1); std::fill(wait, wait + NB, 0); }
} MEM;

enum MKind { CAP = 0, SENT = 1 };
enum TKind { DEFEND = 0, KILL = 1, ESCORT = 2 };

struct FMission {
    int kind = CAP, b = -1, goal = -1, fcell = -1;
    double value = 0;
    int need = 0, assigned = 0;
    vector<std::pair<int, int>> w;  // assigned W (cell, count)
};

struct WTask {
    int kind, b, goal, need, maxd, mi;
    double value;
    bool fallback;
};

struct Planner {
    Ctx& ctx;
    const State& s;
    const ScoreBook& book;
    int me, op, R;
    int sc[NB];
    int wc[2];
    double wpts = 8;
    int dng[N];
    vector<int> src[2], sta[2];
    int budget = 0, totalW = 0;
    int pool[N], stay[N];
    Action act;
    bool closeout = false, finalPhase = false;
    double cbonus[NB]{}, fgain[NB]{}, fneu[NB]{}, floss[NB]{};
    int needCache[NB];
    int thTe[NB], thNeed[NB];
    double sentVal[NB]{};
    int sentCell[NB];
    vector<FMission> ms;
    vector<int> idleF;
    int newWait[NB]{};
    int newTgt[N];

    explicit Planner(Ctx& c) : ctx(c), s(c.s), book(c.book), me(c.me), op(c.op) {}

    // ---------------------------------------------------------------- helpers
    int etaT(int t, int from, int to) const {
        int d = B.dist[from][to];
        if (sta[t].size() >= 2)
            for (int x : sta[t]) for (int y : sta[t])
                if (x != y) d = min(d, (int)B.dist[from][x] + 1 + (int)B.dist[y][to]);
        return d;
    }
    int oppW(int c) const { return s.u[op][W][c]; }
    int oppWNear(int c) const {  // enemy W on c and its neighbours
        int n = oppW(c);
        for (int q : B.adj[c]) n += oppW(q);
        return n;
    }
    bool ownBuildingCell(int c) const { int b = B.at[c]; return b >= 0 && s.owner[b] == me; }

    double econ(int t, const int* own) const {
        int halls = 0, engs = 0;
        double extra = 0;
        for (int b = 0; b < B.nb; ++b) {
            if (own[b] != t) continue;
            switch (B.btype[b]) {
                case HALL: ++halls; break;
                case ENG: ++engs; break;
                case HOSPITAL: {
                    const int c = B.bpos[b];
                    extra += B.dist[c][B.base[1 - t]] < B.dist[c][B.base[t]] ? 0.35 : 0.15;
                    break;
                }
                case LIBRARY: extra += 0.12; break;
                case STATION: extra += 0.05; break;
                case WATCH: extra += 0.03; break;
                default: break;
            }
        }
        const double inc = 10 + 2 * halls;
        return inc / (engs ? 2.0 : 3.0) + extra;
    }
    double econDiff(const int* own) const { return econ(me, own) - econ(op, own); }
    double deltaIf(int b, int newOwner, const int* own) const {
        int h[NB];
        std::copy(own, own + NB, h);
        h[b] = newOwner;
        return econDiff(h) - econDiff(own);
    }

    // Escort needed to raid b: enemy W able to reach it within 3 turns (+ spawns), +1 to kill defenders.
    int capNeed(int b) {
        if (needCache[b] >= 0) return needCache[b];
        const int g = B.bpos[b];
        const int r = reach_w(s, op, g, 3, true, false);
        bool enemyF = false;
        for (int c = 0; c < N && !enemyF; ++c) if (s.u[op][F][c] && B.dist[c][g] <= 2) enemyF = true;
        int need;
        if (s.owner[b] == op) need = closeout ? r + 1 : max(MIN_RAID, r + 1);
        else need = r + (enemyF ? 1 : 0);
        return needCache[b] = min(need, 30);
    }

    // Value (W equivalents) of our flag capturing b with first capture phase tArr turns from now.
    double capValue(int b, int tArr, const int* own) const {
        const int o = own[b];
        if (o == me || tArr > R) return -1;
        const int phases = o == op ? 2 : 1;
        const int tDone = tArr + phases - 1;
        double v = 0;
        if (tDone <= R) {
            double d = max(0.0, deltaIf(b, me, own));
            v += d * (R - tDone) * (o == op ? ENEMY_ECON : 1.0);
            v += wpts * sc[b] * (o == op ? 2 : 1);
            if (B.btype[b] == DEPOT && !s.claimed[me][b] && tDone < R) v += 15.0 / wc[me];
            if (finalPhase) v += 300.0 * fgain[b];
        } else {  // only the neutralisation fits before the end
            double d = max(0.0, deltaIf(b, -1, own));
            v += d * (R - tArr) + wpts * sc[b];
            if (finalPhase) v += 300.0 * fneu[b];
        }
        if (closeout && o == op) v += cbonus[b];
        return v;
    }
    // Value of keeping own building b if the enemy could take it te turns from now.
    double defValue(int b, int te) const {
        double d = max(0.0, -deltaIf(b, op, s.owner));
        double v = d * max(0, R - te) + wpts * sc[b] * 2;
        if (finalPhase) v += 300.0 * floss[b];
        if (closeout) v += 60;
        return v;
    }

    // ---------------------------------------------------------------- setup
    void setup() {
        R = max(1, ctx.remaining());
        book.guess_all(sc);
        for (int t = 0; t < 2; ++t) {
            wc[t] = unit_cost(s, t, W);
            src[t] = sources(s, t);
            sta[t] = stations(s, t);
        }
        budget = s.res[me];
        for (int c = 0; c < N; ++c) {
            pool[c] = s.u[me][W][c];
            stay[c] = 0;
            totalW += pool[c];
            newTgt[c] = -1;
        }
        danger_map(s, op, dng);
        if (sta[op].size() >= 2)  // up to 5 W can teleport onto another enemy station
            for (int x : sta[op]) {
                int best = 0;
                for (int y : sta[op]) if (y != x) best = max(best, min(5, oppW(y)));
                dng[x] += best;
            }
        for (int b = 0; b < NB; ++b) { needCache[b] = -1; thTe[b] = FAR; thNeed[b] = 0; sentCell[b] = -1; }
        finalPhase = s.turn >= 144;
        wpts = finalPhase ? 14 : 8;

        // Closeout: neutralising every enemy building must leave us > total/2 under (almost) all hypotheses.
        const int ne = owned_count(s, op);
        if (ne >= 1 && ne <= 4 && !book.cand.empty()) {
            int h[NB];
            for (int b = 0; b < NB; ++b) h[b] = b < B.nb && s.owner[b] == op ? -1 : s.owner[b];
            size_t ok = 0;
            for (const auto& a : book.cand) {
                int tot = 0, my = 0;
                for (int b = 0; b < B.nb; ++b) { tot += a[b]; if (h[b] == me) my += a[b]; }
                if (2 * my > tot) ++ok;
            }
            if (ok * 20 >= book.cand.size() * 19) {
                closeout = true;
                for (int b = 0; b < B.nb; ++b) if (s.owner[b] == op) cbonus[b] = 400;
            }
        }
        // Final phase: marginal P(win) of flipping each building under the score posterior.
        if (finalPhase && !book.cand.empty()) {
            const double p0 = book.p_win_with(s, me, s.owner);
            int h[NB];
            for (int b = 0; b < B.nb; ++b) {
                std::copy(s.owner, s.owner + NB, h);
                if (s.owner[b] != me) {
                    h[b] = me;
                    fgain[b] = max(0.0, book.p_win_with(s, me, h) - p0);
                    if (s.owner[b] == op) {
                        h[b] = -1;
                        fneu[b] = max(0.0, book.p_win_with(s, me, h) - p0);
                    }
                } else {
                    h[b] = op;
                    floss[b] = max(0.0, p0 - book.p_win_with(s, me, h));
                }
            }
        }
    }

    // ---------------------------------------------------------------- threats
    void computeThreats() {
        vector<int> ef;
        for (int c = 0; c < N; ++c) if (s.u[op][F][c]) ef.push_back(c);
        for (int b = 0; b < B.nb; ++b) {
            if (s.owner[b] != me) continue;
            const int g = B.bpos[b];
            int te = FAR, need = 0;
            for (int f : ef) {
                int d = etaT(op, f, g);
                if (d > DEF_HORIZON) continue;
                int e = oppWNear(f);
                te = min(te, max(1, d));
                need = max(need, e + 1);
            }
            if (s.res[op] >= 5)
                for (int c : src[op]) {
                    int d = B.dist[c][g];
                    if (d > SPAWN_THREAT) continue;
                    int e = (s.res[op] - 5) / wc[op] + oppWNear(c);
                    te = min(te, max(1, d));
                    need = max(need, e + 1);
                }
            if (te < FAR) need = max(need, oppWNear(g) + 1);
            thTe[b] = te;
            thNeed[b] = min(need, 40);
        }
    }
    // W of the pool (plus spawnable) able to be on g within maxd turns.
    int reachable(int g, int maxd, bool withSpawn) const {
        int n = 0;
        for (int c = 0; c < N; ++c) if (pool[c] && B.dist[c][g] <= maxd) n += pool[c];
        if (withSpawn) {
            bool srcOk = false;
            for (int c : src[me]) if (B.dist[c][g] <= maxd) srcOk = true;
            if (srcOk) n += budget / wc[me];
        }
        return n;
    }
    void computeSentinels() {
        for (int b = 0; b < B.nb; ++b) {
            if (s.owner[b] != me || thTe[b] >= FAR) continue;
            const int t = B.btype[b];
            if (t != HALL && t != ENG && t != HOSPITAL && sc[b] < 3) continue;
            if (reachable(B.bpos[b], thTe[b] + 1, true) >= thNeed[b]) continue;
            int best = -1, bv = INF;
            for (int q : B.adj[B.bpos[b]]) {
                int v = dng[q] * 4 + (ownBuildingCell(q) ? 3 : 0);
                if (v < bv) { bv = v; best = q; }
            }
            if (best < 0) continue;
            sentCell[b] = best;
            sentVal[b] = 0.4 * defValue(b, thTe[b]);
        }
    }

    // ---------------------------------------------------------------- flags
    void assignFlags() {
        vector<int> fl;
        for (int c = 0; c < N; ++c) for (int k = 0; k < s.u[me][F][c]; ++k) fl.push_back(c);
        const int nF = (int)fl.size();
        const int fcap = closeout ? 8 : (s.turn >= 144 ? 5 : 4);
        const int maxNew = s.turn == 0 ? 2 : (closeout ? 2 : 1);
        const double vth = closeout ? 5 : (s.turn < 40 ? 50 : 20);
        const int strikeCap = closeout ? 99 : 1 + (totalW >= 14) + (totalW >= 28);
        const double prod = max(1.0, (double)income(s, me) / wc[me]);
        const int wAvail = totalW + budget / wc[me];
        int hyp[NB];
        std::copy(s.owner, s.owner + NB, hyp);
        bool taken[NB]{}, sentTaken[NB]{};
        vector<bool> used(nF, false);
        int strikes = 0, newF = 0;
        while (true) {
            double best = 0;
            int bf = -1, bsrc = -1, bb = -1, bkind = CAP, bneed = 0;
            double bval = 0;
            auto consider = [&](int fi, int cell, int srcCell) {
                const bool virt = fi < 0;
                const double pen = virt ? 5.0 / wc[me] + 3 : 0;
                for (int b = 0; b < B.nb; ++b) {
                    if (hyp[b] == me) {
                        if (sentVal[b] <= 0 || sentTaken[b] || sentCell[b] < 0) continue;
                        int d = B.dist[cell][sentCell[b]];
                        if (d >= FAR) continue;
                        double v = sentVal[b];
                        if (virt && v - pen < vth) continue;
                        double score = (v - pen) / (d + 3);
                        if (score > best) { best = score; bf = fi; bsrc = srcCell; bb = b; bkind = SENT; bval = v; bneed = 0; }
                        continue;
                    }
                    if (taken[b]) continue;
                    const int g = B.bpos[b];
                    const int d = B.dist[cell][g];
                    if (d >= FAR) continue;
                    const bool strike = s.owner[b] == op;
                    if (strike && strikes >= strikeCap) continue;
                    const int tArr = max(1, d);
                    const int need = capNeed(b);
                    const double tw = max(0, need - wAvail) / prod;
                    double v = capValue(b, tArr + (int)std::ceil(tw), hyp);
                    if (v <= 0) continue;
                    if (virt && v - pen < vth) continue;
                    double score = (v - pen) / (tArr + tw + 3);
                    if (!virt && MEM.tgt[cell] == b) score *= 1.3;
                    if (score > best) { best = score; bf = fi; bsrc = srcCell; bb = b; bkind = CAP; bval = v; bneed = need; }
                }
            };
            for (int i = 0; i < nF; ++i) if (!used[i]) consider(i, fl[i], -1);
            if (newF < maxNew && nF + newF < fcap && budget >= 5)
                for (int c : src[me]) consider(-1, c, c);
            if (bb < 0) break;
            FMission m;
            m.kind = bkind;
            m.b = bb;
            m.value = bval;
            m.need = bkind == CAP ? bneed : 0;
            m.goal = bkind == CAP ? B.bpos[bb] : sentCell[bb];
            if (bf >= 0) {
                used[bf] = true;
                m.fcell = fl[bf];
            } else {
                act.add_spawn(F, bsrc, 1);
                budget -= 5;
                ++newF;
                m.fcell = bsrc;
            }
            if (bkind == CAP) {
                taken[bb] = true;
                if (s.owner[bb] == op) ++strikes;
                hyp[bb] = me;
            } else {
                sentTaken[bb] = true;
            }
            ms.push_back(m);
        }
        for (int i = 0; i < nF; ++i) if (!used[i]) idleF.push_back(fl[i]);
    }

    // ---------------------------------------------------------------- warriors
    vector<WTask> buildTasks() {
        vector<WTask> tasks;
        for (int b = 0; b < B.nb; ++b) {
            if (s.owner[b] != me || thTe[b] >= FAR) continue;
            double v = defValue(b, thTe[b]);
            tasks.push_back({DEFEND, b, B.bpos[b], thNeed[b], thTe[b], -1, v, false});
            tasks.push_back({DEFEND, b, B.bpos[b], thNeed[b], thTe[b] + 1, -1, 0.6 * v, true});
        }
        for (int c = 0; c < N; ++c) {
            if (!s.u[op][F][c]) continue;
            const int b = B.at[c];
            if (b < 0 || s.owner[b] == me) continue;   // own buildings are covered by DEFEND
            double v = 5.0 / wc[me] + wpts * sc[b];
            double d = s.owner[b] == op ? deltaIf(b, -1, s.owner) : -deltaIf(b, op, s.owner);
            v += 0.5 * max(0.0, d) * R;
            if (closeout) v += 100;
            tasks.push_back({KILL, b, c, oppWNear(c) + 1, 1, -1, v, false});
        }
        for (int i = 0; i < (int)ms.size(); ++i)
            if (ms[i].kind == CAP && ms[i].need > 0)
                tasks.push_back({ESCORT, ms[i].b, ms[i].fcell, ms[i].need, FAR, i, ms[i].value, false});
        std::stable_sort(tasks.begin(), tasks.end(), [](const WTask& x, const WTask& y) {
            return x.value / max(1, x.need) > y.value / max(1, y.need);
        });
        return tasks;
    }
    // Take up to `need` W from the pool nearest to `anchor` within maxd; commit=false only counts.
    int gather(int anchor, int maxd, int need, vector<std::pair<int, int>>* out) {
        static int order[N];
        int n = 0;
        for (int c = 0; c < N; ++c) if (pool[c] && B.dist[c][anchor] <= maxd) order[n++] = c;
        std::sort(order, order + n, [&](int x, int y) { return B.dist[x][anchor] < B.dist[y][anchor]; });
        int got = 0;
        for (int i = 0; i < n && got < need; ++i) {
            int c = order[i], k = min(pool[c], need - got);
            got += k;
            if (out) { pool[c] -= k; out->push_back({c, k}); }
        }
        return got;
    }

    void spawnWarriors(const vector<WTask>& tasks) {
        int n = budget / wc[me];
        if (n <= 0) return;
        int spawnAt[N]{};
        // Defence deficits first (dry run on a pool copy).
        int saved[N];
        std::copy(pool, pool + N, saved);
        bool done[NB]{};
        for (const auto& t : tasks) {
            if (t.kind != DEFEND || done[t.b] || n <= 0) continue;
            int got = gather(t.goal, t.maxd, t.need, nullptr);
            if (got >= t.need) { vector<std::pair<int, int>> tmp; gather(t.goal, t.maxd, t.need, &tmp); done[t.b] = true; continue; }
            int bs = -1;
            for (int c : src[me]) if (B.dist[c][t.goal] <= t.maxd && (bs < 0 || B.dist[c][t.goal] < B.dist[bs][t.goal])) bs = c;
            if (bs < 0 || got + n < t.need) continue;
            int k = t.need - got;
            vector<std::pair<int, int>> tmp;
            gather(t.goal, t.maxd, t.need, &tmp);
            spawnAt[bs] += k;
            n -= k;
            done[t.b] = true;
        }
        std::copy(saved, saved + N, pool);
        // The rest joins the strike group (or the most exposed own building).
        if (n > 0) {
            int rally = -1, rgoal = -1;
            double bv = -1;
            for (const auto& m : ms)
                if (m.kind == CAP && m.need > 0 && m.value > bv) { bv = m.value; rally = m.fcell; rgoal = m.goal; }
            if (rally < 0) {
                double bd = -1;
                for (int b = 0; b < B.nb; ++b)
                    if (s.owner[b] == me && thTe[b] < FAR && defValue(b, thTe[b]) > bd) { bd = defValue(b, thTe[b]); rally = rgoal = B.bpos[b]; }
            }
            if (rally < 0 && !ms.empty()) { rally = ms[0].fcell; rgoal = ms[0].goal; }
            int bs = B.base[me];
            if (rally >= 0) {
                int bd = INF;
                for (int c : src[me]) {
                    int d = 2 * B.dist[c][rally] + B.dist[c][rgoal];
                    if (d < bd) { bd = d; bs = c; }
                }
            }
            spawnAt[bs] += n;
        }
        for (int c : src[me]) if (spawnAt[c] > 0) {
            act.add_spawn(W, c, spawnAt[c]);
            pool[c] += spawnAt[c];
            budget -= spawnAt[c] * wc[me];
            totalW += spawnAt[c];
        }
    }

    void assignWarriors(const vector<WTask>& tasks) {
        bool defended[NB]{};
        for (const auto& t : tasks) {
            if (t.kind == ESCORT) {
                FMission& m = ms[t.mi];
                m.assigned += gather(m.fcell, FAR, t.need - m.assigned, &m.w);
                continue;
            }
            if (t.kind == DEFEND && defended[t.b]) continue;
            if (gather(t.goal, t.maxd, t.need, nullptr) < t.need) continue;
            vector<std::pair<int, int>> got;
            gather(t.goal, t.maxd, t.need, &got);
            if (t.kind == DEFEND) defended[t.b] = true;
            for (auto [c, k] : got) {
                if (c == t.goal) stay[c] += k;
                else act.add_move(W, c, B.step_toward(c, t.goal), k);
            }
        }
        // Leftovers reinforce the capture missions (raids first), else guard the most valuable own building.
        for (int c = 0; c < N; ++c) {
            if (!pool[c]) continue;
            int bi = -1;
            double bv = 0;
            for (int i = 0; i < (int)ms.size(); ++i) {
                if (ms[i].kind != CAP) continue;
                double v = ms[i].value * (ms[i].need > 0 ? 2.0 : 1.0) / (B.dist[c][ms[i].fcell] + 5);
                if (v > bv) { bv = v; bi = i; }
            }
            if (bi >= 0) {
                ms[bi].w.push_back({c, pool[c]});
                ms[bi].assigned += pool[c];
                pool[c] = 0;
                continue;
            }
            int bg = -1;
            double gv = 0;
            for (int b = 0; b < B.nb; ++b) {
                if (s.owner[b] != me) continue;
                double v = defValue(b, 0) / (B.dist[c][B.bpos[b]] + 3);
                if (v > gv) { gv = v; bg = B.bpos[b]; }
            }
            if (bg >= 0 && bg != c) act.add_move(W, c, B.step_toward(c, bg), pool[c]);
            else stay[c] += pool[c];
            pool[c] = 0;
        }
    }

    // ---------------------------------------------------------------- movement
    int availAt(const FMission& m, int q) const {
        int n = stay[q];
        for (auto [c, k] : m.w) if (B.dist[c][q] <= 1) n += k;
        return n;
    }
    void moveGroup(FMission& m) {
        const int f = m.fcell, g = m.goal;
        const int dfg = B.dist[f][g];
        int nxt = f;
        if (f != g) {
            int bv = INF;
            for (int q : B.adj[f]) {
                if (B.dist[q][g] >= dfg) continue;
                int v = dng[q] - availAt(m, q);
                if (v < bv) { bv = v; nxt = q; }
            }
        }
        const bool relaxed = MEM.wait[m.b] >= 12 || (m.assigned < m.need && MEM.wait[m.b] >= 6);
        bool commitWait = false;
        if (m.kind == CAP && nxt != f && m.need > 0 && dfg > ZONE && B.dist[nxt][g] <= ZONE && !relaxed &&
            s.owner[m.b] == op && availAt(m, nxt) < m.need)
            commitWait = true;
        int dest;
        if (!commitWait && availAt(m, nxt) >= dng[nxt]) {
            dest = nxt;
        } else if (availAt(m, f) >= dng[f]) {
            dest = f;
        } else {
            dest = f;
            int bv = availAt(m, f) - dng[f];
            for (int q : B.adj[f]) {
                int v = availAt(m, q) - dng[q];
                if (v > bv) { bv = v; dest = q; }
            }
        }
        if (m.kind == CAP) {
            if (commitWait && dest == f) newWait[m.b] = MEM.wait[m.b] + 1;
            else if (B.dist[dest][g] <= ZONE + 1) newWait[m.b] = MEM.wait[m.b];
        }
        if (dest != f) act.add_move(F, f, dest, 1);
        newTgt[dest] = m.b;
        const int dg = B.dist[dest][g];
        for (auto [c, k] : m.w) {
            if (c == dest) continue;
            if (B.dist[c][dest] <= 1) { act.add_move(W, c, dest, k); continue; }
            if (B.dist[c][g] < dg && B.dist[c][dest] <= 2) continue;   // ahead of the flag: hold
            act.add_move(W, c, B.step_toward(c, dest), k);
        }
    }
    void moveIdle(int f) {
        const bool onOwn = ownBuildingCell(f);
        if (stay[f] >= dng[f] && !(onOwn && dng[f] > 0)) return;
        int best = f, bv = INF;
        for (int q : B.adj[f]) {
            int v = (dng[q] - stay[q]) * 4 + (ownBuildingCell(q) ? 2 : 0);
            if (v < bv) { bv = v; best = q; }
        }
        int cur = (dng[f] - stay[f]) * 4 + (onOwn ? 2 : 0);
        if (best != f && bv < cur) act.add_move(F, f, best, 1);
    }

    void setPriority() {
        vector<int> order;
        for (int b = 0; b < B.nb; ++b) order.push_back(b);
        auto key = [&](int b) {
            const int t = B.btype[b];
            const bool econ = t == HALL || t == ENG || t == HOSPITAL;
            if (closeout && s.owner[b] == op) return 0;
            if (s.owner[b] == op && econ) return 1;
            if (t == HALL || t == ENG) return 2;
            return 3;
        };
        std::stable_sort(order.begin(), order.end(), [&](int x, int y) {
            int kx = key(x), ky = key(y);
            if (kx != ky) return kx < ky;
            return sc[x] > sc[y];
        });
        act.priority = order;
    }

    Action run() {
        setup();
        computeThreats();
        computeSentinels();
        assignFlags();
        vector<WTask> tasks = buildTasks();
        spawnWarriors(tasks);
        assignWarriors(tasks);
        for (auto& m : ms) moveGroup(m);
        for (int f : idleF) moveIdle(f);
        setPriority();
        std::copy(newTgt, newTgt + N, MEM.tgt);
        std::copy(newWait, newWait + NB, MEM.wait);
        if (ctx.debug) {
            string line = "siphon R " + std::to_string(R) + (closeout ? " CLOSEOUT" : "") + (finalPhase ? " FINAL" : "");
            for (auto& m : ms)
                line += string(" ") + (m.kind == CAP ? "C" : "S") + std::to_string(m.b) + "@" + cell_str(m.fcell) +
                        " n" + std::to_string(m.need) + " a" + std::to_string(m.assigned) + " v" + std::to_string((int)m.value);
            ctx.log(line);
        }
        return act;
    }
};

}  // namespace

Action decide(Ctx& ctx) {
    Planner p(ctx);
    return p.run();
}

int main(int argc, char** argv) { return run(argc, argv, decide); }
