#pragma once

#ifdef __CUDACC__
#define GP_HD __host__ __device__
#else
#define GP_HD
#endif

namespace probe {
constexpr int CELLS = 225, BUILDINGS = 17, UNREACHABLE = 10000;
enum { PLAZA, HALL, STATION, LIBRARY, ENG, HOSPITAL, WATCH, DEPOT };

struct Position {
    int turn, nb, team;
    int resource[2], army_value[2], flags[2][CELLS];
    int owner[BUILDINGS], type[BUILDINGS], claimed[2][BUILDINGS];
    int building_position[BUILDINGS], base_position[2];
    int distance[CELLS][BUILDINGS], base_distance[2][BUILDINGS];
    int building_distance[BUILDINGS][BUILDINGS];
    double score[BUILDINGS], occupation[2];
};

struct Parameters { double engineering, hall_income, army; };

GP_HD inline double lower(double a, double b) { return a < b ? a : b; }
GP_HD inline int lesser(int a, int b) { return a < b ? a : b; }
GP_HD inline int greater(int a, int b) { return a > b ? a : b; }

GP_HD inline bool owns(const Position& s, int team, int type) {
    for (int b = 0; b < s.nb; ++b)
        if (s.owner[b] == team && s.type[b] == type) return true;
    return false;
}

GP_HD inline double building_value(const Position& s, int team, int b) {
    double future = lower(1.0, (160.0 - s.turn) / 35.0);
    double value = 7 * s.score[b];
    if (s.owner[b] == 1 - team) value *= 1.55;
    if (s.type[b] == ENG && (!owns(s, team, ENG) || s.owner[b] == team)) value += 48 * future;
    if (s.type[b] == HALL) value += 55 * future;
    if (s.type[b] == HOSPITAL) {
        double saving = 0;
        for (int j = 0; j < s.nb; ++j) if (s.owner[j] != team)
            saving += greater(0, s.base_distance[team][j] - s.building_distance[b][j]);
        value += lower(40.0, 6 + saving * .55) * future;
    }
    if (s.type[b] == DEPOT && !s.claimed[team][b]) value += 18 * future;
    if (s.type[b] == LIBRARY && !owns(s, team, LIBRARY)) value += 7 * future;
    if (s.type[b] == STATION) value += 6 * future;
    return value;
}

GP_HD inline double evaluate(const Position& s, const Parameters& p) {
    const int team = s.team, enemy = 1 - team;
    double score[2] = {0, 0}, total = 0;
    for (int b = 0; b < s.nb; ++b) {
        total += s.score[b];
        if (s.owner[b] >= 0) score[s.owner[b]] += s.score[b];
    }
    if (score[enemy] == 0 && score[team] * 2 > total) return 100000;
    if (score[team] == 0 && score[enemy] * 2 > total) return -100000;
    if (s.turn >= 160) {
        if (score[team] != score[enemy]) return score[team] > score[enemy] ? 100000 : -100000;
        if (s.occupation[team] != s.occupation[enemy]) return s.occupation[team] > s.occupation[enemy] ? 90000 : -90000;
        return s.army_value[team] == s.army_value[enemy] ? 0 : s.army_value[team] > s.army_value[enemy] ? 80000 : -80000;
    }
    double future = lower(1.0, (160 - s.turn) / 25.0);
    double result = (score[team] - score[enemy]) * (15 + (1 - future) * 45);
    result += p.army * future * (s.army_value[team] - s.army_value[enemy])
        + .35 * future * (s.resource[team] - s.resource[enemy]);
    for (int t = 0; t < 2; ++t) {
        double bonus = 0;
        if (owns(s, t, ENG)) bonus += p.engineering;
        int extra_income = 0;
        for (int b = 0; b < s.nb; ++b) if (s.owner[b] == t && s.type[b] == HALL) extra_income += 2;
        bonus += extra_income * p.hall_income;
        if (owns(s, t, HOSPITAL)) bonus += 25;
        result += (t == team ? 1 : -1) * future * bonus;
        for (int b = 0; b < s.nb; ++b) if (s.owner[b] != t) {
            int distance = UNREACHABLE;
            for (int cell = 0; cell < CELLS; ++cell)
                if (s.flags[t][cell]) distance = lesser(distance, s.distance[cell][b]);
            result += (t == team ? 1 : -1) * building_value(s, t, b) / (distance + 3.0);
        }
    }
    return result;
}
}
