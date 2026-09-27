"""Loss-driven structural candidates. Input and returned sources are immutable snapshots."""


def _replace(source: str, old: str, new: str) -> str:
    if source.count(old) != 1:
        raise ValueError(f"Expected one v2 source anchor: {old[:90]!r}")
    return source.replace(old, new, 1)


_HELPER = r'''
// Reserve origin units before clipping the old plan: arrivals cannot move twice.
Action repair_action(const State& s, int t, Action a, int scope, int limit,
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

Action policy(const State& s, int t, int style) {
    return repair_action(s,t,repair_base_policy(s,t,style),REPAIR_SCOPE,REPAIR_LIMIT,
                         REPAIR_START,REPAIR_ESCORT);
}
'''


def _render(source: str, parameters: dict) -> str:
    result = _replace(source, "Action policy(const State& s, int t, int style) {",
                      "Action repair_base_policy(const State& s, int t, int style) {")
    helper = _HELPER
    for name in ("scope", "limit", "start", "escort"):
        helper = helper.replace("REPAIR_" + name.upper(), str(parameters.get(name, 0)))
    result = _replace(result, "double evaluation(const State& s, int t) {", helper + "\ndouble evaluation(const State& s, int t) {")
    if parameters.get("terminal_margin"):
        declaration = "double score[2] = {points(s,0),points(s,1)}, total = accumulate(s.score,s.score+board.nb,0.0);"
        result = _replace(result, declaration, declaration +
                          "\n    double repair_margin=s.turn>=160?clamp(20*(score[t]-score[1-t]),-1000.0,1000.0):0;")
        result = _replace(result,
                          "if (score[1-t] == 0 && score[t]*2 > total) return 100000;",
                          "if (score[1-t] == 0 && score[t]*2 > total) return 100000 + repair_margin;")
        result = _replace(result,
                          "if (score[t] == 0 && score[1-t]*2 > total) return -100000;",
                          "if (score[t] == 0 && score[1-t]*2 > total) return -100000 + repair_margin;")
        result = _replace(result,
                          "if (score[t] != score[1-t]) return score[t] > score[1-t] ? 100000 : -100000;",
                          "if (score[t] != score[1-t]) return (score[t] > score[1-t] ? 100000 : -100000) + repair_margin;")
    if parameters.get("economic"):
        result = _replace(result, "if (has(s,team,ENG)) bonus += 110;",
                          "if (has(s,team,ENG)) bonus += 4.0*(income(s,team)/2-income(s,team)/3)*min(18.0,max(0.0,160.0-s.turn));")
    return result


def variants(source: str) -> list[dict]:
    """Return ten hypotheses; none is a claim of strength before the league."""
    specs = [
        ("r_guard_one", "paired_defense", {"scope": 1, "limit": 1},
         "Reserve a legal one-step F/W pair at the highest-value imminently threatened owned building.",
         "Independent worst-case enemy arrivals can overdefend and sacrifice expansion."),
        ("r_guard_two", "paired_defense", {"scope": 1, "limit": 2},
         "Cover two simultaneous losses without assigning the same origin units twice.",
         "Two pessimistic reservations may answer mutually incompatible attacks."),
        ("r_guard_late", "paired_defense", {"scope": 1, "limit": 2, "start": 120},
         "Keep v2 expansion early and add joint flag contest defense for the last 40 turns.",
         "An economy lost earlier may already be unrecoverable."),
        ("r_eng_guard", "engineering_retention", {"scope": 2, "limit": 1},
         "Defend the last owned engineering building with joint arrival rather than increasing its scalar value.",
         "Ignores central score threats and cannot defend when local reinforcements are insufficient."),
        ("r_eng_terminal", "engineering_retention", {"scope": 2, "limit": 1, "terminal_margin": True},
         "Combine sustained production discount with a final-score ordering within predicted wins/losses.",
         "Short rollout and estimated hidden scores can still select the wrong defense."),
        ("r_guard_terminal", "paired_defense", {"scope": 1, "limit": 2, "terminal_margin": True},
         "Retain important contested ownership when every terminal rollout predicts the same result.",
         "The secondary score preference does not itself improve actual win probability."),
        ("r_joint_escort", "joint_arrival", {"escort": 2},
         "Reserve warriors from reachable origins for unsafe flag destinations on the same turn.",
         "Worst-case danger may redirect warriors away from a better offensive task."),
        ("r_economic_value", "realizable_economy", {"economic": True},
         "Value engineering through integer warrior-production savings and a bounded remaining horizon.",
         "Assumes income can be spent on warriors and discounts neither recapture nor alternative spending."),
        ("r_terminal_margin", "terminal_order", {"terminal_margin": True},
         "Break otherwise equal terminal win/loss rollout values with a bounded score margin.",
         "Only changes endgame ties between rollout predictions; estimated scores remain uncertain."),
        ("r_combined", "combined_repairs", {"scope": 1, "limit": 2, "escort": 1,
                                              "economic": True, "terminal_margin": True},
         "Combine joint defense, shared-arrival escort, engineering savings, and terminal ordering.",
         "Interactions may overcommit scarce units; compare against individual repairs before adoption."),
    ]
    return [{"id": name, "family": family, "parameters": parameters,
             "hypothesis": hypothesis, "weakness": weakness, "source": _render(source, parameters)}
            for name, family, parameters, hypothesis, weakness in specs]
