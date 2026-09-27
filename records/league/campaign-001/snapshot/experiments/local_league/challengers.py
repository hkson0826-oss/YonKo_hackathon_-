"""Independent action generators and their v2 search-portfolio variants."""

from __future__ import annotations


CPP = r'''
struct ChallengePlan {
    const State& s;
    int t, enemy, budget, left[2][N]{}, landed_w[N]{}, threat[N]{};
    int flag_distance[N], outgoing[2][N][N]{};
    vector<int> sources;
    Action action;
    ChallengePlan(const State& state, int team):s(state),t(team),enemy(1-team),budget(state.res[team]) {
        for (int k=0;k<2;++k) copy(s.u[t][k],s.u[t][k]+N,left[k]);
        fill(flag_distance,flag_distance+N,INF);
        sources.push_back(board.base[t]);
        vector<int> enemy_sources{board.base[enemy]};
        for (int b=0;b<board.nb;++b) if (board.type[b]==HOSPITAL) {
            if (s.owner[b]==t) sources.push_back(board.pos[b]);
            if (s.owner[b]==enemy) enemy_sources.push_back(board.pos[b]);
        }
        for (int c=0;c<N;++c) if (board.pass[c]) {
            threat[c]=s.u[enemy][W][c];
            for (int q:board.adj[c]) threat[c]+=s.u[enemy][W][q];
            for (int q:enemy_sources) if (board.dist[c][q]<=1) {
                threat[c]+=s.res[enemy]/cost(s,enemy,W); break;
            }
            for (int q=0;q<N;++q) if (s.u[enemy][F][q])
                flag_distance[c]=min(flag_distance[c],board.dist[c][q]);
            int b=board.at[c];
            if (b>=0 && board.type[b]==STATION && s.owner[b]==enemy) {
                int remote=0;
                for (int j=0;j<board.nb;++j) if (j!=b && board.type[j]==STATION && s.owner[j]==enemy)
                    remote=max(remote,min(5,s.u[enemy][W][board.pos[j]]));
                threat[c]+=remote;
            }
        }
        int capture_cost=0;
        for (int b=0;b<board.nb;++b) if (s.owner[b]!=t) {
            bool near=left[F][board.pos[b]]>0;
            for (int q:board.adj[board.pos[b]]) near|=left[F][q]>0;
            if (near) capture_cost+=(board.type[b]==PLAZA?4:2)-has(s,t,LIBRARY);
        }
        budget=max(0,budget-max(0,capture_cost-income(s,t)));
    }
    int count(int kind) const { return accumulate(left[kind],left[kind]+N,0); }
    double worth(int b) const {
        double future=max(0.0,min(1.0,(160-s.turn)/55.0));
        double v=s.score[b]*(s.owner[b]==enemy?2:1);
        if (board.type[b]==ENG && !has(s,t,ENG)) v+=18*future;
        if (board.type[b]==HALL) v+=12*future;
        if (board.type[b]==HOSPITAL) v+=8*future;
        if (board.type[b]==DEPOT && !s.claimed[t][b]) v+=5*future;
        return v;
    }
    int site(int target, int kind) const {
        int best=sources.front(); double bv=1e20;
        for (int c:sources) {
            double v=board.dist[c][target];
            if (kind==F && threat[c]>left[W][c]) v+=100;
            if (v<bv) {best=c;bv=v;}
        }
        return best;
    }
    bool produce(int kind, int target, int n=1) {
        int c=site(target,kind), price=cost(s,t,kind);
        n=min(n,budget/price);
        if (n<=0 || board.dist[c][target]>160-s.turn) return false;
        action.spawn.push_back({kind,c,n}); left[kind][c]+=n; budget-=n*price; return true;
    }
    void send(int kind,int src,int dest,int n) {
        n=min(n,left[kind][src]); if (n<=0) return;
        left[kind][src]-=n;
        if (kind==W) landed_w[dest]+=n;
        if (src!=dest) outgoing[kind][src][dest]+=n;
    }
    vector<int> options(int src) const {
        vector<int> q{src}; q.insert(q.end(),board.adj[src].begin(),board.adj[src].end());
        return q;
    }
    int step(int src,int dest,int kind,int n,bool force=false) const {
        int next=src; double bv=1e20;
        for (int q:options(src)) {
            double v=3.0*board.dist[q][dest];
            int support=landed_w[q]+(kind==W?n:0);
            int deficit=max(0,threat[q]-support);
            if (kind==F && deficit) v+=1000+5*deficit;
            if (kind==W && !force) v+=min(12,2*deficit);
            if (kind==W) v-=.02*landed_w[q];
            if (v<bv) {bv=v;next=q;}
        }
        return next;
    }
    void flag_to(int src,int target) { send(F,src,step(src,target,F,1),1); }
    void evacuate_unused_flags() {
        for (int c=0;c<N;++c) if (left[F][c]) {
            int q=step(c,c,F,1);
            send(F,c,q,left[F][c]);
        }
    }
    Action finish() {
        evacuate_unused_flags();
        for (int k=0;k<2;++k) for (int c=0;c<N;++c) for (int q:board.adj[c])
            if (outgoing[k][c][q]) action.moves.push_back({k,c,q,outgoing[k][c][q]});
        action.priority.resize(board.nb);iota(action.priority.begin(),action.priority.end(),0);
        stable_sort(action.priority.begin(),action.priority.end(),[&](int a,int b){return worth(a)>worth(b);});
        return action;
    }
};

// A globally greedy auction pairs flags with marginal economic value per travel turn.
Action challenge_economy(const State& s,int t) {
    ChallengePlan p(s,t);
    vector<int> targets;
    for (int b=0;b<board.nb;++b) if (s.owner[b]!=t) targets.push_back(b);
    int preferred=-1; double best=-1;
    for (int b:targets) {
        int d=board.dist[p.site(board.pos[b],F)][board.pos[b]];
        double v=p.worth(b)/(d+2.0);
        if (v>best) {best=v;preferred=b;}
    }
    int target=preferred<0?board.base[t]:board.pos[preferred];
    int desired=min(7,int(targets.size())), nf=p.count(F);
    if (nf<desired && (nf<2 || p.count(W)>=nf)) p.produce(F,target,nf<2?min(2-nf,desired-nf):1);
    p.produce(W,target,p.budget/cost(s,t,W));
    int flags[N];copy(p.left[F],p.left[F]+N,flags);bool used[BMAX]{};
    vector<pair<int,int>> missions;
    for (int i=0;i<board.nb;++i) {
        int src=-1,goal=-1;double bv=-1e20;
        for (int c=0;c<N;++c) if (flags[c]) for (int b:targets) if (!used[b]) {
            int d=board.dist[c][board.pos[b]];
            if (d+(s.owner[b]==p.enemy)>160-s.turn) continue;
            double v=p.worth(b)/(d+1.5)-.08*p.threat[board.pos[b]];
            if (d==0) v+=25;
            if (v>bv) {bv=v;src=c;goal=b;}
        }
        if (src<0) break;
        --flags[src];used[goal]=true;missions.push_back({src,goal});
    }
    vector<Goal> goals;
    for (auto [c,b]:missions) {
        int q=c;
        for (int n:board.adj[c]) if (board.dist[n][board.pos[b]]<board.dist[q][board.pos[b]]) q=n;
        if (p.threat[q]) goals.push_back({q,p.threat[q]+1,35+p.worth(b)});
        goals.push_back({board.pos[b],max(1,p.threat[board.pos[b]]+1),p.worth(b)});
    }
    for (int b=0;b<board.nb;++b) if (s.owner[b]==t && p.flag_distance[board.pos[b]]<=2)
        goals.push_back({board.pos[b],max(1,p.threat[board.pos[b]]+1),2*p.worth(b)+10});
    int assigned[N]{};
    for (int c=0;c<N;++c) while (p.left[W][c] && !goals.empty()) {
        int gi=0;double bv=-1e20;
        for (int j=0;j<int(goals.size());++j) {
            auto g=goals[j]; double v=g.value/(board.dist[c][g.pos]+2.0);
            if (assigned[g.pos]>=g.need) v*=.03;
            if (v>bv) {bv=v;gi=j;}
        }
        auto g=goals[gi];int n=min(p.left[W][c],max(1,g.need-assigned[g.pos]));
        assigned[g.pos]+=n;p.send(W,c,p.step(c,g.pos,W,n),n);
    }
    for (int c=0;c<N;++c) if (p.left[W][c]) p.send(W,c,c,p.left[W][c]);
    for (auto [c,b]:missions) p.flag_to(c,board.pos[b]);
    return p.finish();
}

// Reserve contested ownership first, then send surplus to the nearest recapture.
Action challenge_territory(const State& s,int t) {
    ChallengePlan p(s,t);
    vector<int> owned,targets;
    for (int b=0;b<board.nb;++b) (s.owner[b]==t?owned:targets).push_back(b);
    stable_sort(owned.begin(),owned.end(),[&](int a,int b){
        return (p.flag_distance[board.pos[a]]<=2)*100+p.worth(a)>
               (p.flag_distance[board.pos[b]]<=2)*100+p.worth(b);
    });
    int focus=-1;double bv=-1e20;
    for (int b=0;b<board.nb;++b) {
        if (s.owner[b]==t && p.flag_distance[board.pos[b]]>3) continue;
        double v=p.worth(b)/(board.dist[p.site(board.pos[b],W)][board.pos[b]]+2.0);
        if (s.owner[b]==t) v*=2;
        if (v>bv) {bv=v;focus=b;}
    }
    int target=focus<0?board.base[t]:board.pos[focus];
    int desired=min(8,max(2,int(targets.size())+int(owned.size())/3));
    if (p.count(F)<desired && (p.count(F)<2 || p.count(W)>p.count(F))) p.produce(F,target);
    p.produce(W,target,p.budget/cost(s,t,W));
    vector<pair<int,int>> flag_missions;
    int flag_pool[N];copy(p.left[F],p.left[F]+N,flag_pool);
    for (int b:owned) {
        int c=board.pos[b];
        if (p.flag_distance[c]>3) continue;
        int src=-1,nearest=INF;
        for (int q=0;q<N;++q) if (flag_pool[q] && board.dist[q][c]<nearest) {src=q;nearest=board.dist[q][c];}
        if (src>=0 && nearest<=max(1,p.flag_distance[c])) {--flag_pool[src];flag_missions.push_back({src,b});}
        int need=max(1,p.threat[c]+1);
        while (need>0) {
            int wsrc=-1,d=INF;
            for (int q=0;q<N;++q) if (p.left[W][q] && board.dist[q][c]<d) {wsrc=q;d=board.dist[q][c];}
            if (wsrc<0 || d>3) break;
            int n=min(need,p.left[W][wsrc]);need-=n;p.send(W,wsrc,p.step(wsrc,c,W,n,true),n);
        }
    }
    bool assigned[BMAX]{};
    for (int c=0;c<N;++c) while (flag_pool[c]) {
        int goal=-1;double score=-1e20;
        for (int b:targets) if (!assigned[b]) {
            int d=board.dist[c][board.pos[b]];
            if (d+(s.owner[b]==p.enemy)>160-s.turn) continue;
            double v=p.worth(b)/(d+1.0);
            if (s.stage[b]==1) v+=8;
            if (v>score) {score=v;goal=b;}
        }
        if (goal<0) break;
        --flag_pool[c];assigned[goal]=true;flag_missions.push_back({c,goal});
    }
    for (int c=0;c<N;++c) if (p.left[W][c]) {
        int dest=c;double score=-1e20;
        for (auto [f,b]:flag_missions) {
            int q=board.pos[b];double v=(p.worth(b)+8)/(board.dist[c][q]+1.0);
            v/=1+.3*p.landed_w[q];
            if (v>score) {score=v;dest=q;}
        }
        int n=p.left[W][c];p.send(W,c,p.step(c,dest,W,n),n);
    }
    for (auto [c,b]:flag_missions) p.flag_to(c,board.pos[b]);
    return p.finish();
}

// Select one breach and keep surplus warriors together; flags exploit safe flanks.
Action challenge_spearhead(const State& s,int t) {
    ChallengePlan p(s,t);
    int focal=-1;double bv=-1e20;
    for (int b=0;b<board.nb;++b) if (s.owner[b]!=t) {
        int c=board.pos[b],d=board.dist[board.base[t]][c];
        for (int q=0;q<N;++q) if (p.left[W][q]) d=min(d,board.dist[q][c]);
        double v=p.worth(b)/(d+2.0)-.15*p.threat[c];
        if (s.owner[b]==p.enemy) v+=3;
        if (v>bv) {bv=v;focal=b;}
    }
    int target=focal<0?board.base[p.enemy]:board.pos[focal];
    if (p.count(F)<min(4,max(2,board.nb/4)) && (p.count(F)<2 || p.count(W)>=4)) p.produce(F,target);
    p.produce(W,target,p.budget/cost(s,t,W));
    for (int b=0;b<board.nb;++b) if (s.owner[b]==t && p.flag_distance[board.pos[b]]<=1) {
        int c=board.pos[b];p.send(W,c,c,min(p.left[W][c],p.threat[c]+1));
    }
    vector<int> warriors;
    for (int c=0;c<N;++c) if (p.left[W][c]) warriors.push_back(c);
    stable_sort(warriors.begin(),warriors.end(),[&](int a,int b){return p.left[W][a]>p.left[W][b];});
    for (int c:warriors) {int n=p.left[W][c];p.send(W,c,p.step(c,target,W,n,true),n);}
    bool assigned[BMAX]{};
    for (int c=0;c<N;++c) while (p.left[F][c]) {
        int goal=-1;double score=-1e20;
        for (int b=0;b<board.nb;++b) if (!assigned[b] && s.owner[b]!=t) {
            int q=board.pos[b],d=board.dist[c][q];
            if (d+(s.owner[b]==p.enemy)>160-s.turn) continue;
            double v=p.worth(b)/(d+1.0)-.1*p.threat[q];
            if (b==focal) v+=2;
            if (v>score) {score=v;goal=b;}
        }
        if (goal<0) break;
        assigned[goal]=true;p.flag_to(c,board.pos[goal]);
    }
    return p.finish();
}
'''


def variants(source: str) -> list[dict]:
    """Return self-contained C++ sources without modifying the submitted bot."""
    anchor = "Action policy(const State& s, int t, int style) {"
    if source.count(anchor) != 1 or source.count("int forced_policy = -1;") != 1:
        raise ValueError("challengers require the frozen v2 policy layout")
    designs = [
        ("economy", "challenge_economy", "economic_auction",
         "이동 거리당 경제 가치를 전체 기수-거점 쌍에서 경매해 ENG/HALL의 조기 확보를 우선한다.",
         "경제 미래 가치가 고정되어 상대의 집중 돌파와 종반 점령 역전을 과소평가할 수 있다."),
        ("territory", "challenge_territory", "contested_territory",
         "소유 거점에 접근하는 적 F에 아군 F의 동시 경합과 W 주둔을 예약하고 여유 병력으로 재점령한다.",
         "상대 F의 위협에 지나치게 주둔하여 비어 있는 경제 거점 확보를 놓칠 수 있다."),
        ("spearhead", "challenge_spearhead", "focused_breach",
         "W를 한 돌파 거점으로 집중시키고 F는 호위받는 정면과 안전한 측면을 점령한다.",
         "거리 변화에 따른 목표 변경으로 왕복과 수비 부족이 발생하며 다방면 기습에 취약하다."),
    ]
    rows = []
    for name, function, family, hypothesis, weakness in designs:
        for mode in ("direct", "portfolio"):
            guard = "true" if mode == "direct" else "style==2"
            edited = source.replace(anchor, CPP + "\n" + anchor + f"\n    if ({guard}) return {function}(s,t);", 1)
            if mode == "direct":
                edited = edited.replace("int forced_policy = -1;", "int forced_policy = 0;", 1)
            rows.append({
                "id": f"c_{name}_{mode}", "family": family,
                "parameters": {"mode": mode, "replacement_style": None if mode == "direct" else 2},
                "hypothesis": hypothesis, "weakness": weakness, "source": edited,
            })
    return rows
