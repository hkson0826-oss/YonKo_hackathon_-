// Ownership-aware travel time. Walking wins ties; stations get no strategic bonus.
struct V9Travel {int eta,to;bool tele;int first_slot=0;};
V9Travel v9_travel(const State& s,int team,int from,int target,int count=1,bool tele_free=true,
                   const bool* booked=nullptr) {
    V9Travel best{board.dist[from][target],from,false};
    auto walking_step=[&](int goal) {
        int next=from,risk=INF;
        for(int q:board.adj[from]) if(board.dist[q][goal]+1==board.dist[from][goal]) {
            int r=s.u[1-team][W][q];
            if(r<risk) {risk=r;next=q;}
        }
        return next;
    };
    best.to=walking_step(target);
    int stations[BMAX],ns=0;
    for(int b=0;b<board.nb;++b) if(s.owner[b]==team && board.type[b]==STATION)
        stations[ns++]=board.pos[b];
    // Sending an entire stack needs ceil(count/5) distinct turns. For one unit this is 1.
    int waves=(max(1,count)+4)/5;
    for(int i=0;i<ns;++i) for(int j=0;j<ns;++j) if(i!=j) {
        int src=stations[i],dst=stations[j],entry=board.dist[from][src];
        int slot=entry+1,first=0;
        if(entry==0 && !tele_free) ++slot;
        for(int wave=0;wave<waves && slot<=160;++wave) {
            while(slot<=160 && booked && booked[slot]) ++slot;
            if(!first) first=slot;
            if(wave+1<waves) ++slot;
        }
        int eta=slot>160?INF:slot+board.dist[dst][target];
        if(eta>=best.eta) continue;
        if(from==src) best={eta,first==1?dst:from,first==1,first};
        else best={eta,walking_step(src),false,first};
    }
    return best;
}
int v9_distance(const State& s,int team,int from,int target,int count=1,bool tele_free=true) {
    return v9_travel(s,team,from,target,count,tele_free).eta;
}

// Attack exploration is stochastic by default; a recorded --attack-seed makes it reproducible.
mt19937 v9_attack_rng;
unsigned int v9_attack_seed=0;
bool v9_attack_custom_seed=false;
