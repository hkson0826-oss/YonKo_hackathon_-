Action inspect_guard(const State& s,int us,Action action) {
    if(s.turn>=150) return action;
    action=a_clean(s,us,action);
    int enemy=1-us,stock[N]{},locked[N]{},danger[N]{};
    copy(s.u[us][W],s.u[us][W]+N,stock);
    for(auto p:action.spawn) if(p.kind==W) stock[p.pos]+=p.count;
    vector<int> sources{board.base[us]},enemy_sources{board.base[enemy]};
    for(int b=0;b<board.nb;++b) if(board.type[b]==HOSPITAL && s.owner[b]>=0)
        (s.owner[b]==us?sources:enemy_sources).push_back(board.pos[b]);
    for(int c=0;c<N;++c) if(board.pass[c]) {
        danger[c]=s.u[enemy][W][c];
        for(int q:board.adj[c]) danger[c]+=s.u[enemy][W][q];
        for(int q:enemy_sources) if(board.dist[c][q]<=1) {
            danger[c]+=s.res[enemy]/cost(s,enemy,W);break;
        }
        int b=board.at[c];
        if(b>=0 && board.type[b]==STATION && s.owner[b]==enemy) {
            int remote=0;
            for(int j=0;j<board.nb;++j) if(j!=b && board.type[j]==STATION && s.owner[j]==enemy)
                remote=max(remote,min(5,s.u[enemy][W][board.pos[j]]));
            danger[c]+=remote;
        }
    }
    int seed_flags[N]{},seed_warriors[N]{};
    copy(s.u[us][F],s.u[us][F]+N,seed_flags);
    copy(stock,stock+N,seed_warriors);
    for(auto p:action.spawn) if(p.kind==F) seed_flags[p.pos]+=p.count;
    for(auto m:action.moves) {
        if(m.kind==F) {seed_flags[m.from]-=m.count;seed_flags[m.to]+=m.count;}
        if(m.kind==W) {seed_warriors[m.from]-=m.count;seed_warriors[m.to]+=m.count;}
    }
    vector<int> enemy_stations;
    for(int b=0;b<board.nb;++b) if(board.type[b]==STATION && s.owner[b]==enemy)
        enemy_stations.push_back(board.pos[b]);
    auto enemy_eta=[&](int src,int target) {
        int eta=board.dist[src][target],b=board.at[src];
        if(b>=0 && board.type[b]==STATION && s.owner[b]==enemy)
            for(int dst:enemy_stations) if(dst!=src) eta=min(eta,1+board.dist[dst][target]);
        return eta;
    };
    struct Defense {int target,deadline;};
    vector<Defense> defenses;
    for(int b=0;b<board.nb;++b) {
        if(s.owner[b]!=us || (board.type[b]!=ENG && board.type[b]!=HALL)) continue;
        int target=board.pos[b];
        if(board.dist[board.base[us]][target]>=board.dist[board.base[enemy]][target]) continue;
        int flag_eta=INF,warrior_eta=INF;
        for(int c=0;c<N;++c) {
            if(s.u[enemy][F][c]) flag_eta=min(flag_eta,enemy_eta(c,target));
            if(s.u[enemy][W][c]) warrior_eta=min(warrior_eta,enemy_eta(c,target));
        }
        flag_eta=max(1,flag_eta);
        if(flag_eta>6) continue;
        if(s.res[enemy]>=cost(s,enemy,W)) for(int c:enemy_sources)
            warrior_eta=min(warrior_eta,max(1,board.dist[c][target]));
        if(warrior_eta<=flag_eta) continue;
        defenses.push_back({target,flag_eta});
    }
    stable_sort(defenses.begin(),defenses.end(),[](auto a,auto b){return a.deadline<b.deadline;});
    vector<Movement> reserved;
    constexpr int defense_limit=2;
    int assignments=0;
    auto safe_step=[&](int src,int target) {
        if(src==target) return danger[src]? -1:src;
        int dest=-1;
        for(int q:board.adj[src]) if(board.dist[q][target]<board.dist[src][target] && !danger[q]) {
            dest=q;break;
        }
        return dest;
    };
    auto assemble=[&]() {
        Action result=action;
        vector<Movement> moves;
        int available[N];
        for(int c=0;c<N;++c) available[c]=stock[c]-locked[c];
        for(auto m:action.moves) {
            if(m.kind==W) {m.count=min(m.count,available[m.from]);available[m.from]-=m.count;}
            if(m.count>0) moves.push_back(m);
        }
        moves.insert(moves.end(),reserved.begin(),reserved.end());
        result.moves=move(moves);
        return a_clean(s,us,result);
    };
    auto safe_reservation=[&](int src,int dest) {
        ++locked[src];
        if(src!=dest) reserved.push_back({W,src,dest,1});
        Action trial=assemble();
        --locked[src];
        if(src!=dest) reserved.pop_back();
        int warriors[N];copy(s.u[us][W],s.u[us][W]+N,warriors);
        for(auto p:trial.spawn) if(p.kind==W) warriors[p.pos]+=p.count;
        for(auto m:trial.moves) if(m.kind==W) {warriors[m.from]-=m.count;warriors[m.to]+=m.count;}
        for(int c=0;c<N;++c) if(seed_flags[c] && warriors[c]<seed_warriors[c])
            return false;
        return true;
    };
    for(auto defense:defenses) {
        if(assignments>=defense_limit) break;
        // Even two later reservations leave one of these arriving warriors.
        cout<<" defense_target="<<defense.target%15<<","<<defense.target/15<<" currentW="<<s.u[us][W][defense.target]<<" projectedW="<<seed_warriors[defense.target]<<" flag_eta="<<defense.deadline<<" danger="<<danger[defense.target]<<" skipped="<<(seed_warriors[defense.target]>defense_limit && !danger[defense.target])<<"\n";
        if(seed_warriors[defense.target]>defense_limit && !danger[defense.target]) continue;
        int source=-1,dest=-1,best=INF;
        for(int c=0;c<N;++c) if(stock[c]>locked[c] && board.dist[c][defense.target]<=defense.deadline) {
            int step=safe_step(c,defense.target);
            if(step<0 || !safe_reservation(c,step)) continue;
            int rank=4*board.dist[c][defense.target];
            for(auto m:action.moves) if(m.kind==W && m.from==c && m.to==step && m.count>0) {--rank;break;}
            if(rank<best) {best=rank;source=c;dest=step;}
        }
        if(source<0) {
            vector<pair<int,int>> sites;
            for(int c:sources) if(board.dist[c][defense.target]<=defense.deadline && safe_step(c,defense.target)>=0)
                sites.push_back({board.dist[c][defense.target],c});
            sort(sites.begin(),sites.end());
            for(auto [eta,site]:sites) {
                int step=safe_step(site,defense.target);
                int original_size=int(action.spawn.size());
                for(int donor=0;donor<original_size;++donor) {
                    auto production=action.spawn[donor];
                    if(production.kind!=W || production.count<=0 || production.pos==site || stock[production.pos]<=locked[production.pos]) continue;
                    --action.spawn[donor].count;--stock[production.pos];
                    action.spawn.push_back({W,site,1});++stock[site];
                    if(safe_reservation(site,step)) {source=site;dest=step;break;}
                    action.spawn.pop_back();--stock[site];
                    ++action.spawn[donor].count;++stock[production.pos];
                }
                if(source>=0) break;
            }
            if(source<0) continue;
        }
        ++locked[source];++assignments;
        if(source!=dest) reserved.push_back({W,source,dest,1});
    }
    if(!assignments) return action;
    return assemble();
}
