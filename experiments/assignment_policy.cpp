// Distance-based assignment, adapted from teammate delineate-v1 (351c32e).
Action assignment_policy(const State& s, int t) {
    Action a;
    int enemy = 1-t, remaining_turns = 160-s.turn;
    int own[2][N]{}, danger[N]{}, local[N]{};
    for (int k=0;k<2;++k) copy(s.u[t][k],s.u[t][k]+N,own[k]);
    vector<int> sources{board.base[t]}, enemy_sources{board.base[enemy]}, targets;
    for (int b=0;b<board.nb;++b) {
        if (s.owner[b]!=t) targets.push_back(b);
        if (board.type[b]==HOSPITAL && s.owner[b]>=0)
            (s.owner[b]==t?sources:enemy_sources).push_back(board.pos[b]);
    }
    for (int c=0;c<N;++c) if (board.pass[c]) {
        danger[c]=s.u[enemy][W][c];
        for (int q:board.adj[c]) danger[c]+=s.u[enemy][W][q];
        for (int q=0;q<N;++q) if (board.dist[c][q]<=3) local[c]+=s.u[enemy][W][q];
        for (int q:enemy_sources) if (board.dist[c][q]<=1) {danger[c]+=s.res[enemy]/cost(s,enemy,W);break;}
    }
    bool engineering=has(s,t,ENG);
    auto value=[&](int b) {
        double bonus=0;
        if (board.type[b]==HALL) bonus=5;
        if (board.type[b]==ENG && !engineering) bonus=5;
        if (board.type[b]==HOSPITAL) bonus=4;
        if (board.type[b]==DEPOT) bonus=2;
        if (board.type[b]==LIBRARY) bonus=1;
        if (board.type[b]==STATION) bonus=.5;
        return 1.4*s.score[b]+bonus*min(1.0,remaining_turns/60.0);
    };
    int capture_cost=0;
    for (int b:targets) {
        bool near=own[F][board.pos[b]]>0;
        for (int c:board.adj[board.pos[b]]) near|=own[F][c]>0;
        if (near) capture_cost+=(board.type[b]==PLAZA?4:2)-has(s,t,LIBRARY);
    }
    int budget=max(0,s.res[t]-max(0,capture_cost-10));
    auto produce=[&](int kind) {
        if (budget<cost(s,t,kind)) return false;
        double best=1e20;int site=sources.front();
        for (int c:sources) for (int b=0;b<board.nb;++b) if (targets.empty() || s.owner[b]!=t) {
            double v=board.dist[c][board.pos[b]]-value(b);
            if (v<best) {best=v;site=c;}
        }
        int distance=INF;
        for (int b=0;b<board.nb;++b) if (targets.empty() || s.owner[b]!=t)
            distance=min(distance,board.dist[site][board.pos[b]]);
        if (distance>remaining_turns) return false;
        ++own[kind][site];budget-=cost(s,t,kind);a.spawn.push_back({kind,site,1});
        return true;
    };
    int nf=accumulate(own[F],own[F]+N,0), desired=targets.empty()?0:min(6,max(2,int(targets.size())));
    for (int i=0;i<(nf<2?2:1) && nf<desired;++i) if (produce(F)) ++nf;
    while (produce(W)) {}
    int flags[N];copy(own[F],own[F]+N,flags);
    int assigned[BMAX]{};
    vector<pair<int,int>> missions;
    for (int f=0;f<nf && !targets.empty();++f) {
        int src=-1,target=-1;double best=1e20;
        for (int c=0;c<N;++c) if (flags[c]) for (int b:targets) {
            int distance=board.dist[c][board.pos[b]];
            if (distance+(s.owner[b]==enemy)>remaining_turns) continue;
            double v=distance-value(b)+18*assigned[b]+min(10,s.u[enemy][W][board.pos[b]])*.7;
            if (v<best) {best=v;src=c;target=b;}
        }
        if (src<0) break;
        --flags[src];++assigned[target];missions.push_back({src,target});
    }
    vector<Goal> tasks;
    for (int b=0;b<board.nb;++b) {
        int c=board.pos[b];
        if (s.owner[b]==t) {
            bool nearby=false;
            for (int q=0;q<N;++q) if (s.u[enemy][F][q] && board.dist[q][c]<=2) nearby=true;
            if (local[c] || nearby) tasks.push_back({c,max(1,local[c]+1),value(b)+7});
        } else if (assigned[b] || s.u[enemy][F][c]) {
            tasks.push_back({c,max(1,local[c]+1),value(b)+2});
        }
    }
    if (tasks.empty()) for (int b:targets) tasks.push_back({board.pos[b],1,value(b)});
    int planned[N]{},allocated[N]{},moving[2][N][4]{};
    vector<int> warriors;
    for (int c=0;c<N;++c) if (own[W][c]) warriors.push_back(c);
    sort(warriors.begin(),warriors.end(),[&](int x,int y){return own[W][x]>own[W][y];});
    auto route=[&](int src,int dest,int kind,int n) {
        if (src==dest) return;
        int d=dest-src,dir=d==-15?0:d==15?1:d==-1?2:3;
        moving[kind][src][dir]+=n;
    };
    auto options=[&](int c) {
        vector<int> out{c};
        if (t==0) out.insert(out.end(),board.adj[c].begin(),board.adj[c].end());
        else for (int delta:{15,-15,1,-1}) {
            int q=c+delta;
            if (find(board.adj[c].begin(),board.adj[c].end(),q)!=board.adj[c].end()) out.push_back(q);
        }
        return out;
    };
    for (int c:warriors) for (int i=0;i<own[W][c];++i) {
        if (tasks.empty()) {++planned[c];continue;}
        int target=c;double best=1e20;
        for (auto task:tasks) {
            double v=board.dist[c][task.pos]-task.value+4*max(0,allocated[task.pos]-task.need+1);
            if (v<best) {best=v;target=task.pos;}
        }
        ++allocated[target];int dest=c;
        for (int q:options(c)) if (board.dist[q][target]<board.dist[dest][target]) dest=q;
        ++planned[dest];route(c,dest,W,1);
    }
    for (auto [c,b]:missions) {
        int dest=c;double best=1e20;
        for (int q:options(c)) {
            double v=1000*(danger[q]>planned[q])+board.dist[q][board.pos[b]]+.01*danger[q];
            if (v<best) {best=v;dest=q;}
        }
        route(c,dest,F,1);
    }
    for (int c=0;c<N;++c) if (flags[c] && danger[c]>planned[c]) {
        for (int q:options(c)) if (danger[q]<=planned[q]) {route(c,q,F,flags[c]);break;}
    }
    int delta[4]={-15,15,-1,1};
    for (int k=0;k<2;++k) for (int c=0;c<N;++c) for (int d=0;d<4;++d)
        if (moving[k][c][d]) a.moves.push_back({k,c,c+delta[d],moving[k][c][d]});
    a.priority=targets;
    stable_sort(a.priority.begin(),a.priority.end(),[&](int x,int y){return value(x)>value(y);});
    return a;
}
