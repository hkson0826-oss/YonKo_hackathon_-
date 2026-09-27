"""Campus Conquest v1: distance-based assignment with diminishing target value.

Inspired by delineate's Movement write-up (not copied winner source):
https://github.com/delineate/cg-2022-fall-challenge-strategy#movement
"""
from collections import Counter, deque
from protocol import DIRS, spawn, move, priority, run


class Strategy:
    def __init__(self):
        self.init = None

    def prepare(self, init):
        self.init = init
        self.edges = {}
        order = list(DIRS) if init.team == "Y" else ["D", "U", "R", "L"]
        for y in range(init.height):
            for x in range(init.width):
                if init.passable(x, y):
                    self.edges[x, y] = [(d, (x + DIRS[d][0], y + DIRS[d][1]))
                                        for d in order
                                        if init.passable(x + DIRS[d][0], y + DIRS[d][1])]
        self.dist = {}
        for start in self.edges:
            distances = {start: 0}
            queue = deque([start])
            while queue:
                p = queue.popleft()
                for _, q in self.edges[p]:
                    if q not in distances:
                        distances[q] = distances[p] + 1
                        queue.append(q)
            self.dist[start] = distances

    def distance(self, a, b):
        return self.dist[a].get(b, 999)

    def decide(self, view, init):
        if self.init is not init:
            self.prepare(init)
        pos = lambda u: (u["x"], u["y"])
        buildings = {pos(b): b for b in view.buildings}
        targets = [p for p, b in buildings.items() if b["owner"] != view.team]
        remaining = max(0, 160 - view.turn + 1)
        enemies = [u for u in view.units if u["team"] == view.opp]
        enemy_w = Counter({})
        enemy_f = Counter({})
        for u in enemies:
            if u["kind"] == "W":
                enemy_w[pos(u)] += u["count"]
            elif u["kind"] == "F":
                enemy_f[pos(u)] += u["count"]
        own = {kind: Counter() for kind in ("F", "W")}
        for u in view.my_units():
            if u["kind"] in own:
                own[u["kind"]][pos(u)] += u["count"]
        engineering = any(b["type"] == "ENG" and b["owner"] == view.team for b in buildings.values())
        warrior_cost = 2 if engineering else 3

        def value(p):
            b = buildings[p]
            score = b["score"]
            if score < 0:
                mirror = buildings.get((14-p[0], 14-p[1]))
                score = mirror["score"] if mirror and mirror["score"] >= 0 else (3 if 5 <= p[0] <= 9 else 1.5)
            bonuses = {"HALL": 5, "ENG": 5 if not engineering else 0,
                       "HOSPITAL": 4, "DEPOT": 2, "LIBRARY": 1, "STATION": 0.5}
            return 1.4 * score + bonuses.get(b["type"], 0) * min(1, remaining / 60)

        # Upper bound on enemy warriors reaching each cell this turn.
        threat = Counter()
        for p, n in enemy_w.items():
            for q in [p] + [q for _, q in self.edges[p]]:
                threat[q] += n
        enemy_cost = 2 if any(b["type"] == "ENG" and b["owner"] == view.opp for b in buildings.values()) else 3
        enemy_sites = [init.bases[view.opp]] + [p for p, b in buildings.items() if b["type"] == "HOSPITAL" and b["owner"] == view.opp]
        spawn_reach = set()
        for p in enemy_sites:
            spawn_reach.update([p] + [q for _, q in self.edges[p]])
        for p in spawn_reach:
            threat[p] += view.opp_resource // enemy_cost

        commands = []
        sites = [init.bases[view.team]] + [p for p, b in buildings.items() if b["type"] == "HOSPITAL" and b["owner"] == view.team]
        # Income precedes capture: reserve only capture demand exceeding guaranteed income.
        library = any(b["type"] == "LIBRARY" and b["owner"] == view.team for b in buildings.values())
        near = [p for p in targets if any(self.distance(f, p) <= 1 for f in own["F"])]
        capture_cost = sum(max(1, (4 if buildings[p]["type"] == "PLAZA" else 2) - library) for p in near)
        budget = max(0, view.my_resource - max(0, capture_cost - 10))
        desired_flags = min(6, max(2, len(targets))) if targets else 0

        def produce(kind):
            nonlocal budget
            goals = targets or list(buildings)
            site = min(sites, key=lambda s: min(self.distance(s, p) - value(p) for p in goals))
            if min(self.distance(site, p) for p in goals) > remaining:
                return False
            cost = 5 if kind == "F" else warrior_cost
            if budget < cost:
                return False
            commands.append(spawn(kind, 1) if site == init.bases[view.team] else spawn(kind, 1, *site))
            own[kind][site] += 1
            budget -= cost
            return True

        # Grow expansion crew gradually; keep investing the rest in combat units.
        nf = sum(own["F"].values())
        if nf < desired_flags:
            for _ in range(2 if nf < 2 else 1):
                if sum(own["F"].values()) < desired_flags:
                    produce("F")
        while produce("W"):
            pass

        # Globally pick the cheapest remaining (flag, building) pair.
        flags = [p for p, n in own["F"].items() for _ in range(n)]
        assigned = Counter()
        missions = []
        while flags and targets:
            options = [(self.distance(f, t) - value(t) + 18 * assigned[t]
                        + min(10, enemy_w[t]) * 0.7, i, t)
                       for i, f in enumerate(flags) for t in targets
                       if self.distance(f, t) + (buildings[t]["owner"] == view.opp) <= remaining]
            if not options:
                break
            _, i, target = min(options)
            start = flags.pop(i)
            missions.append((start, target))
            assigned[target] += 1

        # Defense and escort tasks have a required force, unlike flag assignments.
        tasks = {}
        for p, b in buildings.items():
            local = sum(n for e, n in enemy_w.items() if self.distance(e, p) <= 3)
            if b["owner"] == view.team:
                if local or any(self.distance(e, p) <= 2 for e in enemy_f):
                    tasks[p] = (max(1, local + 1), value(p) + 7)
            elif assigned[p] or enemy_f[p]:
                tasks[p] = (max(1, local + 1), value(p) + 2)
        if not tasks:
            tasks = {p: (1, value(p)) for p in targets}
        planned_w = Counter()
        allocated = Counter()
        moves = Counter()
        # Send stacks together until target demand is filled; surplus spreads out.
        for start, count in sorted(own["W"].items(), key=lambda item: -item[1]):
            for _ in range(count):
                if not tasks:
                    planned_w[start] += 1
                    continue
                target = min(tasks, key=lambda t: self.distance(start, t) - tasks[t][1]
                             + 4 * max(0, allocated[t] - tasks[t][0] + 1))
                allocated[target] += 1
                choices = [(None, start)] + self.edges[start]
                direction, end = min(choices, key=lambda dq: self.distance(dq[1], target))
                planned_w[end] += 1
                if direction:
                    moves[start, "W", direction] += 1
        for start, target in missions:
            choices = [(None, start)] + self.edges[start]
            def flag_cost(dq):
                _, end = dq
                lethal = threat[end] > planned_w[end]
                return 1000 * lethal + self.distance(end, target) + 0.01 * threat[end]
            direction, end = min(choices, key=flag_cost)
            if direction:
                moves[start, "F", direction] += 1
        # Unassigned flags leave threatened owned buildings when a safe escape exists.
        for start in flags:
            if threat[start] > planned_w[start]:
                safe = [(d, p) for d, p in self.edges[start] if threat[p] <= planned_w[p]]
                if safe:
                    moves[start, "F", safe[0][0]] += 1
        for (start, kind, direction), count in moves.items():
            commands.append(move(*start, kind, count, direction))
        commands.append(priority(sorted(targets, key=lambda p: -value(p))))
        return commands


BOT = Strategy()
def decide(view, init):
    return BOT.decide(view, init)


if __name__ == "__main__":
    run(decide)
