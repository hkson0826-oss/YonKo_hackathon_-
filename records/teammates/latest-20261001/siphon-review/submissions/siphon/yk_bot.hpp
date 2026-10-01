// yk_bot.hpp - turn loop shared by every bot of the new family.
//
// A bot provides   yk::Action decide(yk::Ctx& ctx)   and calls   return yk::run(argc, argv, decide);
// The runner parses INIT/TURN, keeps cross-turn memory and the ScoreBook, calls decide(), legalizes the
// result, prints it with END, and never lets an exception kill the process (it answers END instead).
// Local diagnostics: start the bot with --debug to get one "EST ..." line per turn on stderr.
#pragma once
#include "yk_core.hpp"
#include "yk_score.hpp"

namespace yk {

struct Memory {
    bool claimed[2][NB]{};        // depot bonus received (owning a depot once implies it)
    State prev;                   // previous observed state
    Action last;                  // our previous legalized action
    bool has_prev = false;
    int opp_f_lost = 0, my_f_lost = 0;

    void observe(State& s) {
        for (int b = 0; b < B.nb; ++b)
            if (s.owner[b] >= 0 && B.btype[b] == DEPOT) claimed[s.owner[b]][b] = true;
        for (int t = 0; t < 2; ++t) for (int b = 0; b < B.nb; ++b) s.claimed[t][b] = claimed[t][b];
    }
    void after(const State& s, const Action& a) { prev = s; last = a; has_prev = true; }
};

struct Ctx {
    const State& s;
    const ScoreBook& book;
    const Memory& mem;
    int me, op;
    std::chrono::steady_clock::time_point start;
    bool debug;
    int remaining() const { return LAST_TURN - s.turn; }   // turns left including the one being decided
    double elapsed_ms() const {
        return std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - start).count();
    }
    void log(const string& msg) const { if (debug) std::cerr << "T" << s.turn + 1 << " " << msg << "\n"; }
};

using DecideFn = Action (*)(Ctx&);

inline int run(int argc, char** argv, DecideFn decide) {
    bool debug = false;
    for (int i = 1; i < argc; ++i) if (string(argv[i]) == "--debug") debug = true;
    vector<string> lines;
    if (!p::read_block(std::cin, lines)) return 0;
    p::Init init;
    bool ok = true;
    try {
        init = p::parse_init(lines);
        B.init(init);
    } catch (...) {
        ok = false;
    }
    static ScoreBook book;
    static Memory mem;
    if (ok) book.init();
    while (p::read_block(std::cin, lines)) {
        auto start = std::chrono::steady_clock::now();
        vector<string> out;
        if (ok) {
            try {
                p::View v = p::parse_turn(lines, init);
                State s = state_from_view(v);
                mem.observe(s);
                book.observe(v, s);
                Ctx ctx{s, book, mem, B.me, B.op, start, debug};
                Action a = legalize(s, B.me, decide(ctx));
                out = to_lines(a, B.me);
                if (debug) std::cerr << book.debug_line(s, B.me) << "\n";
                mem.after(s, a);
            } catch (const std::exception& e) {
                if (debug) std::cerr << "ERROR " << e.what() << "\n";
                out.clear();
            } catch (...) {
                out.clear();
            }
        }
        p::emit(out);
    }
    return 0;
}

}  // namespace yk
