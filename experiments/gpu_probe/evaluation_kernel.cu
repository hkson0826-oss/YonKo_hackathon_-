#include "evaluation_shared.hpp"
extern "C" __global__ void evaluate_batch(const probe::Position* positions, int states,
                                          const probe::Parameters* parameters, int params,
                                          double* output, int count) {
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i < count) output[i] = probe::evaluate(positions[(i / params) % states], parameters[i % params]);
}
