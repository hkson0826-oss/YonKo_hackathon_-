#include "evaluation_shared.hpp"
#define main submission_main
#include "../../submissions/tuned/main.cpp"
#undef main
#include <cstddef>

extern "C" size_t probe_position_size() { return sizeof(probe::Position); }
extern "C" size_t probe_parameter_size() { return sizeof(probe::Parameters); }

extern "C" void probe_cpu(const probe::Position* positions, int states,
                          const probe::Parameters* parameters, int params,
                          double* output, int count, int workers) {
    #pragma omp parallel for num_threads(workers) if(workers > 1)
    for (int i = 0; i < count; ++i)
        output[i] = probe::evaluate(positions[(i / params) % states], parameters[i % params]);
}

// The submission's unmodified evaluator is the baseline oracle.
extern "C" void probe_original(const probe::Position* positions, int count, double* output) {
    for (int i = 0; i < count; ++i) {
        const auto& x = positions[i];
        board.nb = x.nb;
        board.base[0] = x.base_position[0]; board.base[1] = x.base_position[1];
        State s;
        s.turn = x.turn;
        for (int b = 0; b < x.nb; ++b) {
            board.pos[b] = x.building_position[b];
            board.type[b] = x.type[b];
            s.owner[b] = x.owner[b]; s.score[b] = x.score[b];
            for (int t = 0; t < 2; ++t) s.claimed[t][b] = x.claimed[t][b];
            for (int cell = 0; cell < N; ++cell) board.dist[cell][board.pos[b]] = x.distance[cell][b];
        }
        for (int t = 0; t < 2; ++t) {
            s.res[t] = x.resource[t]; s.occupation[t] = x.occupation[t];
            int flag_total = 0;
            for (int cell = 0; cell < N; ++cell) if (x.flags[t][cell]) {
                s.u[t][F][cell] = x.flags[t][cell];
                flag_total += x.flags[t][cell];
            }
            // Only total 5F+3W+2S is used by evaluation; represent its remainder exactly.
            int remainder = x.army_value[t] - 5 * flag_total;
            s.u[t][W][0] = remainder % 2 ? 1 : 0;
            s.u[t][S][0] = (remainder - 3 * s.u[t][W][0]) / 2;
        }
        output[i] = evaluation(s, x.team);
    }
}
