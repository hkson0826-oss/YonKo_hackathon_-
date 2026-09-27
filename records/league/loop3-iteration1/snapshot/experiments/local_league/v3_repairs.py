"""Economic and flag-allocation repairs for the frozen iterative-v3 source."""
from __future__ import annotations


_EVALUATION = r'''
double f3_access(const State& s,int t,bool matched) {
    vector<int> targets,flags;
    for(int b=0;b<board.nb;++b) if(s.owner[b]!=t) targets.push_back(b);
    if(!matched) {
        double value=0;
        for(int b:targets) {
            int d=INF;
            for(int c=0;c<N;++c) if(s.u[t][F][c]) d=min(d,board.dist[c][board.pos[b]]);
            value+=building_value(s,t,b,0)/(d+3.0);
        }
        return value;
    }
    for(int c=0;c<N;++c) for(int n=0;n<min(s.u[t][F][c],board.nb);++n) flags.push_back(c);
    int n=int(targets.size()),m=int(flags.size())+n;
    if(!n || flags.empty()) return 0;
    // Rectangular Hungarian assignment. Dummy columns leave targets unassigned.
    vector<vector<double>> a(n+1,vector<double>(m+1));
    for(int i=1;i<=n;++i) for(int j=1;j<=int(flags.size());++j) {
        int b=targets[i-1],d=board.dist[flags[j-1]][board.pos[b]];
        if(d<=160-s.turn) a[i][j]=-building_value(s,t,b,0)/(d+3.0);
    }
    vector<double> u(n+1),v(m+1);vector<int> p(m+1),way(m+1);
    for(int i=1;i<=n;++i) {
        p[0]=i;int j0=0;vector<double> low(m+1,1e100);vector<bool> used(m+1);
        do {
            used[j0]=true;int i0=p[j0],j1=0;double delta=1e100;
            for(int j=1;j<=m;++j) if(!used[j]) {
                double cur=a[i0][j]-u[i0]-v[j];
                if(cur<low[j]) {low[j]=cur;way[j]=j0;}
                if(low[j]<delta) {delta=low[j];j1=j;}
            }
            for(int j=0;j<=m;++j) if(used[j]) {u[p[j]]+=delta;v[j]-=delta;} else low[j]-=delta;
            j0=j1;
        } while(p[j0]);
        do {int j1=way[j0];p[j0]=p[j1];j0=j1;} while(j0);
    }
    return v[0];
}

double f3_supply(const State& s,int t) {
    int horizon=min(24,160-s.turn);
    if(horizon<=0) return 0;
    vector<int> sources{board.base[t]};
    for(int b=0;b<board.nb;++b) if(board.type[b]==HOSPITAL && s.owner[b]==t) sources.push_back(board.pos[b]);
    double weighted=0,weight=0;
    for(int b=0;b<board.nb;++b) {
        int c=board.pos[b];bool active=s.owner[b]!=t;
        if(!active) for(int q=0;q<N;++q) if(s.u[1-t][F][q] && board.dist[q][c]<=3) {active=true;break;}
        if(!active) continue;
        int delay=INF;for(int src:sources) delay=min(delay,board.dist[src][c]);
        double w=1+s.score[b];
        weighted+=w*max(0,horizon-delay);weight+=w;
    }
    return weight ? 3.9*income(s,t)/cost(s,t,W)*weighted/weight : 0;
}

double evaluation(const State& s,int t) {
    double base=f3_base_evaluation(s,t);
    if(abs(base)>=80000 || s.turn>=160) return base;
    if(F3_MATCH) base+=f3_access(s,t,true)-f3_access(s,t,false)-f3_access(s,1-t,true)+f3_access(s,1-t,false);
    if(F3_FLOW) {
        double future=min(1.0,(160-s.turn)/25.0),old[2]{};
        for(int side=0;side<2;++side) old[side]=(has(s,side,ENG)?110:0)+(income(s,side)-10)*35+(has(s,side,HOSPITAL)?25:0);
        base+=f3_supply(s,t)-f3_supply(s,1-t)-future*(old[t]-old[1-t]);
    }
    return base;
}
'''


_MISSION = r'''
bool f3_mission(const State& s,int t,const Action& input,int b,Action& out) {
    if(b<0 || b>=board.nb || s.owner[b]==t) return false;
    int target=board.pos[b],enemy=1-t,stock[3][N]{},reserved[3][N]{};
    Action clean=a_clean(s,t,input);
    for(int k=0;k<3;++k) copy(s.u[t][k],s.u[t][k]+N,stock[k]);
    for(auto p:clean.spawn) stock[p.kind][p.pos]+=p.count;
    vector<int> origins{target};origins.insert(origins.end(),board.adj[target].begin(),board.adj[target].end());
    int flag=-1;
    for(int src:origins) if(stock[F][src]) {
        int own=board.at[src];bool abandon=false;
        if(src!=target && own>=0 && s.owner[own]==t && stock[F][src]==1)
            for(int q=0;q<N;++q) if(s.u[enemy][F][q] && board.dist[q][src]<=1) {abandon=true;break;}
        if(!abandon) {flag=src;break;}
    }
    if(flag<0) return false;
    int danger=0;bool flag_threat=false,spawn_threat=board.dist[board.base[enemy]][target]<=1;
    for(int src:origins) {danger+=s.u[enemy][W][src];flag_threat|=s.u[enemy][F][src]>0;}
    for(int j=0;j<board.nb;++j) if(board.type[j]==HOSPITAL && s.owner[j]==enemy && board.dist[board.pos[j]][target]<=1) spawn_threat=true;
    if(spawn_threat) danger+=s.res[enemy]/cost(s,enemy,W);
    if(board.type[b]==STATION && s.owner[b]==enemy) {
        int remote=0;
        for(int j=0;j<board.nb;++j) if(j!=b && board.type[j]==STATION && s.owner[j]==enemy) remote=max(remote,min(5,s.u[enemy][W][board.pos[j]]));
        danger+=remote;
    }
    int need=danger+int(flag_threat),total=0;
    for(int src:origins) total+=stock[W][src];
    if(total<need) return false;
    reserved[F][flag]=1;
    vector<Movement> escort;
    if(flag!=target) escort.push_back({F,flag,target,1});
    for(int src:origins) {
        int n=min(need,stock[W][src]);reserved[W][src]=n;need-=n;
        if(n && src!=target) escort.push_back({W,src,target,n});
    }
    out=clean;out.moves.clear();
    for(auto move:clean.moves) {
        move.count=min(move.count,stock[move.kind][move.from]-reserved[move.kind][move.from]);
        if(move.count>0) {out.moves.push_back(move);stock[move.kind][move.from]-=move.count;}
    }
    out.moves.insert(out.moves.end(),escort.begin(),escort.end());
    out.priority.erase(remove(out.priority.begin(),out.priority.end(),b),out.priority.end());
    out.priority.insert(out.priority.begin(),b);
    out=a_clean(s,t,out);
    return !a_equal(clean,out);
}

vector<int> f3_targets(const State& s,int t) {
    vector<pair<double,int>> ranked;
    for(int b=0;b<board.nb;++b) if(s.owner[b]!=t && (board.type[b]==ENG || board.type[b]==HALL || board.type[b]==HOSPITAL)) {
        double value=building_value(s,t,b,1);
        if(board.type[b]==ENG && has(s,t,ENG)) value*=.25;
        ranked.push_back({-value,b});
    }
    sort(ranked.begin(),ranked.end());vector<int> result;
    for(auto [_,b]:ranked) result.push_back(b);
    return result;
}
'''


def _replace(source: str, old: str, new: str) -> str:
    if source.count(old) != 1:
        raise ValueError(f"Expected one v3 insertion point: {old[:70]!r}")
    return source.replace(old, new, 1)


def _render(source: str, matching: bool, flow: bool, mission: bool) -> str:
    source = _replace(source, "double evaluation(const State& s, int t) {", "double f3_base_evaluation(const State& s, int t) {")
    definitions = f"constexpr bool F3_MATCH={str(matching).lower()}, F3_FLOW={str(flow).lower()};\n"
    source = _replace(source, "int forced_policy = -1;", definitions + _EVALUATION + "\nint forced_policy = -1;")
    source = _replace(source, "struct APlan {Action action;int continuation;double value;};", _MISSION + "\nstruct APlan {Action action;int continuation;double value;};")
    if mission:
        anchor = "    for(int i=0;i<4;++i) plans.push_back({scripts[i],i,-1e100});"
        addition = r'''
    for(int i=0;i<4;++i) {
        int added=0;
        for(int b:f3_targets(s,us)) {
            Action repaired;
            if(!f3_mission(s,us,scripts[i],b,repaired)) continue;
            bool duplicate=false;for(const auto& p:plans) if(a_equal(p.action,repaired)) {duplicate=true;break;}
            if(!duplicate) {plans.push_back({repaired,i,-1e100});if(++added==2) break;}
        }
    }
'''
        source = _replace(source, anchor, anchor + addition)
    return source


def variants(source: str) -> list[dict]:
    specs = (
        ("f3_matching", True, False, False, "한 F를 여러 목표에 중복 계산하던 접근 잠재력을 일대일 최대 가중치 할당으로 바꾼다.", "후속 재사용·거점 연쇄 점령 가치를 낮게 평가할 수 있다."),
        ("f3_supply_flow", False, True, False, "ENG·HALL·HOSPITAL의 고정 보너스를 생산 속도, 생산지부터 목표까지 거리, 남은 턴의 도착 가능 병력으로 대체한다.", "지금의 소유권과 생산 거점이 유지된다는 근사이며 전선 이동·경로 전투를 계산하지 않는다."),
        ("f3_econ_mission", False, False, True, "인접 경제 거점에 F와 필요한 호위를 함께 배치하는 새 행동을 기존 4개 계획과 비교한다.", "인접 임무만 생성하고 모든 인접 적 W의 집중을 가정하여 기회를 놓칠 수 있다."),
        ("f3_matching_mission", True, False, True, "경제 거점 공동 임무와 일대일 F 접근 평가를 결합한다.", "임무 후보가 늘어 기존 국소 탐색의 예산이 줄며 각 요소의 기여는 단독 후보와 비교해야 한다."),
        ("f3_flow_mission", False, True, True, "새 경제 임무를 실제 전선 도착 가능 생산량으로 평가한다.", "경제 추정이 틀리면 임무 생성과 평가가 같은 편향을 증폭한다."),
        ("f3_econ_portfolio", True, True, True, "거점 접근 중복 제거·경제 흐름·공동 임무를 함께 평가한다.", "세 변경의 결합으로 회귀 원인 분리가 어렵고 단독 후보보다 느릴 수 있다."),
    )
    return [dict(id=name, family="v3_economic_repair", parameters=dict(matching=matching, supply_flow=flow, economic_mission=mission),
                 hypothesis=hypothesis, weakness=weakness, source=_render(source, matching, flow, mission))
            for name, matching, flow, mission, hypothesis, weakness in specs]
