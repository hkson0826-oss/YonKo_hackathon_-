"""Own-policy interventions, with the v2 opponent model frozen for causal comparison."""


def _replace(source: str, old: str, new: str) -> str:
    if source.count(old) != 1:
        raise ValueError(f"Expected one v2 source anchor: {old[:90]!r}")
    return source.replace(old, new, 1)


_GUARD = r'''
// Reserve origin units before clipping the old plan: arrivals cannot move twice.
Action causal_guard(const State& s, int t, Action a, int scope, int limit,
                     int start_turn, int escort_limit) {
    if ((!scope || s.turn<start_turn) && !escort_limit) return a;
    int stock[3][N]{}, locked[3][N]{}, projected[3][N]{}, danger[N]{};
    for (int k=0;k<3;++k) copy(s.u[t][k],s.u[t][k]+N,stock[k]);
    int resource=s.res[t], enemy=1-t;
    for (auto x:a.spawn) {
        int b=board.at[x.pos];
        if (x.pos!=board.base[t] && !(b>=0 && board.type[b]==HOSPITAL && s.owner[b]==t)) continue;
        int n=min(max(0,x.count),resource/cost(s,t,x.kind));
        stock[x.kind][x.pos]+=n; resource-=n*cost(s,t,x.kind);
    }
    for (int k=0;k<3;++k) copy(stock[k],stock[k]+N,projected[k]);
    int departure[3][N]{};
    for (auto x:a.moves) {
        int n=min(x.count,stock[x.kind][x.from]-departure[x.kind][x.from]);
        departure[x.kind][x.from]+=n;
        projected[x.kind][x.from]-=n; projected[x.kind][x.to]+=n;
    }
    vector<int> enemy_sources{board.base[enemy]};
    for (int b=0;b<board.nb;++b)
        if (board.type[b]==HOSPITAL && s.owner[b]==enemy) enemy_sources.push_back(board.pos[b]);
    for (int c=0;c<N;++c) if (board.pass[c]) {
        danger[c]=s.u[enemy][W][c];
        for (int q:board.adj[c]) danger[c]+=s.u[enemy][W][q];
        for (int q:enemy_sources) if (board.dist[c][q]<=1) {
            danger[c]+=s.res[enemy]/cost(s,enemy,W); break;
        }
        int b=board.at[c];
        if (b>=0 && board.type[b]==STATION && s.owner[b]==enemy) {
            int remote=0;
            for (int j=0;j<board.nb;++j) if (j!=b && board.type[j]==STATION && s.owner[j]==enemy)
                remote=max(remote,min(5,s.u[enemy][W][board.pos[j]]));
            danger[c]+=remote;
        }
    }
    vector<Movement> reserved;
    auto reserve_pair=[&](int dest,int required_w,int forced_flag_src=-1) {
        vector<int> sources{dest};
        sources.insert(sources.end(),board.adj[dest].begin(),board.adj[dest].end());
        auto planned_to=[&](int kind,int src) {
            int n=src==dest?stock[kind][src]-departure[kind][src]:0;
            for (auto x:a.moves) if (x.kind==kind && x.from==src && x.to==dest && !x.tele) n+=x.count;
            return n;
        };
        stable_sort(sources.begin(),sources.end(),[&](int x,int y) {
            return planned_to(W,x)>planned_to(W,y);
        });
        int flag_src=forced_flag_src;
        if (flag_src<0) {
            int best=-1;
            for (int src:sources) if (stock[F][src]>locked[F][src]) {
                int merit=4*planned_to(F,src)+(src==dest);
                if (merit>best) {best=merit;flag_src=src;}
            }
        }
        if (flag_src<0 || board.dist[flag_src][dest]>1 || stock[F][flag_src]<=locked[F][flag_src]) return false;
        int supply=0;
        for (int src:sources) supply+=stock[W][src]-locked[W][src];
        if (supply<required_w) return false;
        ++locked[F][flag_src];
        if (flag_src!=dest) reserved.push_back({F,flag_src,dest,1});
        for (int src:sources) {
            int n=min(required_w,stock[W][src]-locked[W][src]);
            locked[W][src]+=n; required_w-=n;
            if (n && src!=dest) reserved.push_back({W,src,dest,n});
        }
        return true;
    };
    int owned_eng=0;
    for (int b=0;b<board.nb;++b) owned_eng+=s.owner[b]==t && board.type[b]==ENG;
    vector<pair<double,int>> threatened;
    if (scope && s.turn>=start_turn) for (int b=0;b<board.nb;++b) if (s.owner[b]==t) {
        if (scope==2 && (board.type[b]!=ENG || owned_eng!=1)) continue;
        int c=board.pos[b], flag_distance=INF;
        for (int q=0;q<N;++q) if (s.u[enemy][F][q]) flag_distance=min(flag_distance,board.dist[q][c]);
        if (flag_distance>1 && !(s.u[t][F][c] && danger[c])) continue;
        double value=7*s.score[b];
        if (board.type[b]==ENG && owned_eng==1) value+=45*min(1.0,(160-s.turn)/25.0);
        if (board.type[b]==HALL) value+=20*min(1.0,(160-s.turn)/25.0);
        threatened.push_back({value,b});
    }
    sort(threatened.rbegin(),threatened.rend());
    int count=0;
    for (auto [value,b]:threatened) {
        if (count>=limit) break;
        int c=board.pos[b];
        if (reserve_pair(c,danger[c])) ++count;
    }
    int escorted=0;
    for (auto x:a.moves) if (x.kind==F && !x.tele && x.count && escorted<escort_limit) {
        if (danger[x.to]<=projected[W][x.to]) continue;
        if (reserve_pair(x.to,danger[x.to],x.from)) ++escorted;
    }
    if (reserved.empty()) {
        bool any=false;
        for (int k=0;k<3;++k) for (int c=0;c<N;++c) any|=locked[k][c]>0;
        if (!any) return a;
    }
    vector<Movement> moves;
    int left[3][N]{};
    for (int k=0;k<3;++k) for (int c=0;c<N;++c) left[k][c]=stock[k][c]-locked[k][c];
    for (auto x:a.moves) {
        x.count=min(x.count,left[x.kind][x.from]);
        left[x.kind][x.from]-=x.count;
        if (x.count) moves.push_back(x);
    }
    moves.insert(moves.end(),reserved.begin(),reserved.end());
    a.moves=move(moves);
    return a;
}
'''


def _render(source: str, parameters: dict) -> str:
    begin = source.index("Action policy(const State& s, int t, int style) {")
    end = source.index("double evaluation(const State& s, int t) {")
    own = source[begin:end].replace("Action policy(", "Action causal_base_policy(", 1)
    if parameters.get("capacity"):
        own = _replace(own, "splits < 8", "splits < 24")
        own = _replace(own, "if (splits == 7) take = remaining;", "// Unassigned excess stays available for the next turn.")
    if parameters.get("threat_window"):
        own = _replace(own, "if (enemy_flag_dist[c] > 5 &&", "if (enemy_flag_dist[c] > 2 &&")
    if parameters.get("rendezvous"):
        own = _replace(own, "if (wanted[c] && danger[c]) goals.push_back({c,danger[c]+1,50.0});",
                       "if (wanted[c]) goals.push_back({c,max(1,danger[c]+1),50.0});")
    if parameters.get("deadline"):
        own = _replace(own, "if (d == 0) v += 10;",
                       "if (d == 0) v += 10;\n            if (s.owner[b]==enemy && max(1,d)+1>160-s.turn) v *= .5;")
    if parameters.get("balanced_front"):
        own = _replace(own, "int need = max(1, near_enemy[c] + 1);",
                       "int need = max(1, min(near_enemy[c] + 1, max(4, nw/3)));" )
        own = _replace(own, "need = max(1,danger[c]+1);",
                       "need = max(1,enemy_flag_dist[c]<=1 ? danger[c]+1 : min(4,danger[c]+1));")
    wrapper = """
Action causal_policy(const State& s, int t, int style) {
    return causal_guard(s,t,causal_base_policy(s,t,style),SCOPE,LIMIT,0,ESCORT);
}
"""
    wrapper = wrapper.replace("SCOPE", str(parameters.get("guard", 0)))
    wrapper = wrapper.replace("LIMIT", "1").replace("ESCORT", str(parameters.get("escort", 0)))
    result = _replace(source, "double evaluation(const State& s, int t) {",
                      _GUARD + "\n" + own + wrapper + "\ndouble evaluation(const State& s, int t) {")
    result = _replace(result, "candidates[i]=policy(s,us,i);", "candidates[i]=causal_policy(s,us,i);")
    result = _replace(result, "own=d==0?candidates[i]:policy(trial,us,i), opp=policy(trial,1-us,j);",
                      "own=d==0?candidates[i]:causal_policy(trial,us,i), opp=policy(trial,1-us,j);")
    return result


def variants(source: str) -> list[dict]:
    specs = [
        ("q_guard_own", "isolated_defense", {"guard": 1},
         "Reserve a one-step F/W defense pair only in our policy; keep the original opponent scripts fixed.",
         "Worst-case arrivals can still overdefend, and the unchanged opponent model may miss counterplay."),
        ("q_escort_own", "isolated_escort", {"escort": 2},
         "Repair unsafe flag destinations with same-turn warrior escorts without modifying opponent rollout actions.",
         "Escorts can abandon a more valuable position; the flag target choice remains the v2 heuristic."),
        ("q_capacity", "bounded_assignment", {"capacity": True},
         "Remove the eighth-split all-remaining dump and allow twenty-four capacity-limited assignments.",
         "Excess beyond twenty-four assignments remains still; incorrect demand estimates remain unchanged."),
        ("q_threat_window", "defense_arrival_window", {"threat_window": True},
         "Create owned-building defense tasks only against flags within two steps or threatened resident flags.",
         "A distant enemy can advance before reinforcements arrive; this intentionally reduces speculative defense."),
        ("q_rendezvous", "escort_rendezvous", {"rendezvous": True},
         "Give every planned next flag cell a warrior rendezvous task, including currently empty danger cells.",
         "One-step escort goals may compete with strategic targets and flags can choose a different safe step."),
        ("q_deadline", "capture_deadline", {"deadline": True},
         "Discount enemy-owned targets when only neutralization can finish, while keeping those denial actions legal candidates.",
         "The fixed half-value is approximate and can underweight decisive last-turn denial."),
        ("q_balanced_front", "distributed_pressure", {"balanced_front": True, "capacity": True},
         "Cap non-immediate local demand and split warriors across tasks instead of matching every nearby enemy at one spot.",
         "The enemy may concentrate and overwhelm a capped attack; immediate owned-building defense remains uncapped."),
        ("q_coordinated", "combined_own_interventions",
         {"guard": 1, "capacity": True, "threat_window": True, "rendezvous": True, "deadline": True},
         "Combine capacity assignment, near-term defense, escort rendezvous and capture-completion values with one owned defense pair.",
         "Interactions can shift policy selection and lose important denial attacks; compare every component separately."),
    ]
    return [{"id": name, "family": family, "parameters": {**parameters, "opponent_model": "unchanged_v2"},
             "hypothesis": hypothesis, "weakness": weakness, "source": _render(source, parameters)}
            for name, family, parameters, hypothesis, weakness in specs]
