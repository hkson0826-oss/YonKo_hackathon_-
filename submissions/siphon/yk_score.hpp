// yk_score.hpp - in-bot score estimator built on the map's 180-degree symmetry.
//
// What is hidden: only building point values. Owners, units and resources are public, so
//   opponent score = sum of scores of the buildings the opponent owns.
// What we know:
//   * every revealed score (-1 otherwise; reveals are permanent),
//   * mirror pairs share one score: revealing either building fixes both,
//   * PLAZA is always 3,
//   * domains: home pairs (x 0-4 / 10-14) score 1..2, centre pairs (x 5-9) score 2..4, uniform prior,
//   * every TURN input proves no instant win happened on the previous turn: if one team owned nothing,
//     the other team's score was <= total/2 (total = 3 + 2 * sum of pair scores).
// The book keeps every pair-score assignment consistent with that evidence (at most 2^5 * 3^3 = 864)
// and answers questions exactly over that set: score bounds, posterior means, P(ahead), and P(win) for any
// hypothetical final ownership including the occupation-turn and unit-value tie-breaks.
// Pairs split one-each between the teams cancel out of the margin automatically.
#pragma once
#include "yk_core.hpp"
#include <cstdio>

namespace yk {

struct Outlook {
    int n = 0;                          // consistent assignments
    double p_win = 0, p_draw = 0, p_lose = 0;
    double p_ahead = 0, p_tie = 0, p_behind = 0;   // current-score comparison only
    double my_mean = 0, opp_mean = 0, margin_mean = 0;
    int my_lo = 0, my_hi = 0, opp_lo = 0, opp_hi = 0, margin_lo = 0, margin_hi = 0;
};

struct ScoreBook {
    int known[NB];                      // exact score or -1
    int pair_of[NB];                    // pair index, -1 for PLAZA
    int npairs = 0;
    int pair_rep[NB]{};                 // first building of each pair
    bool pair_center[NB]{};
    long owned_turns[2][NB]{};          // completed turns each team owned each building (observed)
    vector<std::pair<int, uint32_t>> zero_cons;   // (team, owned mask): 2*score(mask) <= total
    vector<array<int8_t, NB>> cand;     // consistent assignments, score per building
    double mean[NB]{};
    int lo[NB]{}, hi[NB]{};
    bool dirty = true, fallback = false;
    int last_turn = -1;

    void init() {
        npairs = 0;
        for (int b = 0; b < NB; ++b) { known[b] = -1; pair_of[b] = -1; }
        for (int b = 0; b < B.nb; ++b) {
            if (B.btype[b] == PLAZA || B.partner[b] == b) { known[b] = 3; continue; }
            if (pair_of[b] >= 0) continue;
            pair_rep[npairs] = b;
            pair_center[npairs] = B.center[b];
            pair_of[b] = pair_of[B.partner[b]] = npairs++;
        }
        dirty = true;
        rebuild();
    }
    void learn(int b, int value) {
        if (b < 0 || b >= B.nb || value < 0) return;
        if (known[b] != value) { known[b] = value; dirty = true; }
        int q = B.partner[b];
        if (known[q] != value) { known[q] = value; dirty = true; }
    }
    // Call once per TURN input, before deciding.
    void observe(const p::View& v, const State& s) {
        for (const auto& b : v.buildings) if (b.id >= 0 && b.id < B.nb && b.score >= 0) learn(b.id, b.score);
        if (v.turn >= 2 && v.turn != last_turn) {
            for (int b = 0; b < B.nb; ++b) if (s.owner[b] >= 0) ++owned_turns[s.owner[b]][b];
            for (int t = 0; t < 2; ++t) {
                uint32_t mask = 0;
                for (int b = 0; b < B.nb; ++b) if (s.owner[b] == t) mask |= 1u << b;
                if (mask && owned_count(s, 1 - t) == 0) {
                    std::pair<int, uint32_t> c{t, mask};
                    if (std::find(zero_cons.begin(), zero_cons.end(), c) == zero_cons.end()) { zero_cons.push_back(c); dirty = true; }
                }
            }
        }
        last_turn = v.turn;
        if (dirty) rebuild();
    }
    void rebuild() {
        dirty = false;
        vector<int> unknown;
        for (int p = 0; p < npairs; ++p) if (known[pair_rep[p]] < 0) unknown.push_back(p);
        auto enumerate = [&](bool constrained) {
            cand.clear();
            vector<int> digit(unknown.size(), 0);
            while (true) {
                array<int8_t, NB> a{};
                for (int b = 0; b < B.nb; ++b) a[b] = (int8_t)max(0, known[b]);
                for (size_t i = 0; i < unknown.size(); ++i) {
                    int p = unknown[i], v = (pair_center[p] ? 2 : 1) + digit[i];
                    a[pair_rep[p]] = a[B.partner[pair_rep[p]]] = (int8_t)v;
                }
                bool ok = true;
                if (constrained) {
                    int total = 0;
                    for (int b = 0; b < B.nb; ++b) total += a[b];
                    for (auto [t, mask] : zero_cons) {
                        int sc = 0;
                        for (int b = 0; b < B.nb; ++b) if (mask >> b & 1) sc += a[b];
                        if (2 * sc > total) { ok = false; break; }
                    }
                }
                if (ok) cand.push_back(a);
                size_t i = 0;
                for (; i < unknown.size(); ++i) {
                    int size = pair_center[unknown[i]] ? 3 : 2;
                    if (++digit[i] < size) break;
                    digit[i] = 0;
                }
                if (i == unknown.size()) break;
            }
        };
        enumerate(true);
        fallback = cand.empty();
        if (fallback) enumerate(false);
        for (int b = 0; b < B.nb; ++b) {
            double sum = 0;
            int l = 99, h = -1;
            for (auto& a : cand) { sum += a[b]; l = min(l, (int)a[b]); h = max(h, (int)a[b]); }
            mean[b] = cand.empty() ? 0 : sum / cand.size();
            lo[b] = l;
            hi[b] = h;
        }
    }

    bool exact(int b) const { return lo[b] == hi[b]; }
    int guess(int b) const { return (int)std::lround(mean[b]); }
    // Integer score vector for the simulator (posterior mean rounded; exact where known).
    void guess_all(int* out) const { for (int b = 0; b < NB; ++b) out[b] = b < B.nb ? guess(b) : 0; }
    int unknown_pairs() const {
        int n = 0;
        for (int p = 0; p < npairs; ++p) n += lo[pair_rep[p]] != hi[pair_rep[p]];
        return n;
    }
    // Expected total map score.
    double total_mean() const {
        double t = 0;
        for (int b = 0; b < B.nb; ++b) t += mean[b];
        return t;
    }

    // Outcome distribution if the game ended with owner_final, for team `me`.
    // Occupation projection: observed turns + (remaining-1) turns of owner_now + the final turn of owner_final.
    // remaining = LAST_TURN - s.turn (turns still to be played, including the final one).
    Outlook evaluate(int me, const int* owner_final, const int* owner_now, int remaining, int uv_me, int uv_op) const {
        Outlook o;
        o.n = (int)cand.size();
        if (!o.n) return o;
        const int op = 1 - me;
        o.my_lo = o.opp_lo = o.margin_lo = INF;
        o.my_hi = o.opp_hi = o.margin_hi = -INF;
        for (auto& a : cand) {
            int my = 0, opp = 0;
            long occ_me = 0, occ_op = 0;
            for (int b = 0; b < B.nb; ++b) {
                int v = a[b];
                if (owner_final[b] == me) my += v;
                else if (owner_final[b] == op) opp += v;
                occ_me += owned_turns[me][b] * v;
                occ_op += owned_turns[op][b] * v;
                if (remaining > 1) {
                    if (owner_now[b] == me) occ_me += (long)(remaining - 1) * v;
                    else if (owner_now[b] == op) occ_op += (long)(remaining - 1) * v;
                }
                if (remaining >= 1) {
                    if (owner_final[b] == me) occ_me += v;
                    else if (owner_final[b] == op) occ_op += v;
                }
            }
            o.my_mean += my;
            o.opp_mean += opp;
            o.my_lo = min(o.my_lo, my); o.my_hi = max(o.my_hi, my);
            o.opp_lo = min(o.opp_lo, opp); o.opp_hi = max(o.opp_hi, opp);
            o.margin_lo = min(o.margin_lo, my - opp); o.margin_hi = max(o.margin_hi, my - opp);
            if (my > opp) o.p_ahead += 1; else if (my == opp) o.p_tie += 1; else o.p_behind += 1;
            int res;
            if (my != opp) res = my > opp ? 1 : -1;
            else if (occ_me != occ_op) res = occ_me > occ_op ? 1 : -1;
            else res = uv_me == uv_op ? 0 : uv_me > uv_op ? 1 : -1;
            if (res > 0) o.p_win += 1; else if (res < 0) o.p_lose += 1; else o.p_draw += 1;
        }
        double n = o.n;
        o.my_mean /= n; o.opp_mean /= n; o.margin_mean = o.my_mean - o.opp_mean;
        o.p_ahead /= n; o.p_tie /= n; o.p_behind /= n;
        o.p_win /= n; o.p_draw /= n; o.p_lose /= n;
        return o;
    }
    // Outcome if the current ownership held to the end.
    Outlook now(const State& s, int me) const {
        return evaluate(me, s.owner, s.owner, LAST_TURN - s.turn, unit_value(s, me), unit_value(s, 1 - me));
    }
    // P(win) if the game ended with owner_final (occupation projected from the current owners).
    double p_win_with(const State& s, int me, const int* owner_final) const {
        Outlook o = evaluate(me, owner_final, s.owner, LAST_TURN - s.turn, unit_value(s, me), unit_value(s, 1 - me));
        return o.p_win + 0.5 * o.p_draw;
    }
    // Observed occupation totals (posterior mean).
    double occupation_mean(int t) const {
        double o = 0;
        for (int b = 0; b < B.nb; ++b) o += owned_turns[t][b] * mean[b];
        return o;
    }
    // Naive estimate used by v8/v9 (mirror or plaza, else centre 3 / home 1.5); diagnostics only.
    double naive_points(const State& s, int t) const {
        double sum = 0;
        for (int b = 0; b < B.nb; ++b) if (s.owner[b] == t)
            sum += known[b] >= 0 ? known[b] : (B.center[b] ? 3.0 : 1.5);
        return sum;
    }
    // One diagnostics line for stderr (local --debug runs only).
    string debug_line(const State& s, int me) const {
        Outlook o = now(s, me);
        char buf[256];
        std::snprintf(buf, sizeof(buf), "EST %d my %.2f opp %.2f lo %d hi %d p_ahead %.3f p_tie %.3f p_win %.3f n %d unknown %d naive %.2f fb %d",
                      s.turn + 1, o.my_mean, o.opp_mean, o.opp_lo, o.opp_hi, o.p_ahead, o.p_tie, o.p_win + 0.5 * o.p_draw, o.n,
                      unknown_pairs(), naive_points(s, 1 - me), fallback ? 1 : 0);
        return buf;
    }
};

}  // namespace yk
