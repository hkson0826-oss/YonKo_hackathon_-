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


_REVISION_GUARDS = r'''
void f3_v2_landing(const State& s,int t,const Action& a,int (&land)[3][N]) {
    for(int k=0;k<3;++k) copy(s.u[t][k],s.u[t][k]+N,land[k]);
    for(auto p:a.spawn) land[p.kind][p.pos]+=p.count;
    for(auto m:a.moves) {land[m.kind][m.from]-=m.count;land[m.kind][m.to]+=m.count;}
}
pair<int,bool> f3_v2_threat(const State& s,int t,int c) {
    int enemy=1-t,w=s.u[enemy][W][c];bool flag=s.u[enemy][F][c]>0;
    for(int q:board.adj[c]) {w+=s.u[enemy][W][q];flag|=s.u[enemy][F][q]>0;}
    bool spawn=board.dist[board.base[enemy]][c]<=1;
    for(int b=0;b<board.nb;++b) if(board.type[b]==HOSPITAL && s.owner[b]==enemy && board.dist[board.pos[b]][c]<=1) spawn=true;
    if(spawn) {w+=s.res[enemy]/cost(s,enemy,W);flag|=s.res[enemy]>=cost(s,enemy,F);}
    int here=board.at[c];
    if(here>=0 && board.type[here]==STATION && s.owner[here]==enemy) {
        int remote=0;
        for(int b=0;b<board.nb;++b) if(b!=here && board.type[b]==STATION && s.owner[b]==enemy) {
            remote=max(remote,min(5,s.u[enemy][W][board.pos[b]]));flag|=s.u[enemy][F][board.pos[b]]>0;
        }
        w+=remote;
    }
    return {w,flag};
}
bool f3_v2_safe_mission(const State& s,int t,const Action& input,int b,Action& out) {
    if(!f3_mission(s,t,input,b,out)) return false;
    int before[3][N]{},after[3][N]{};
    f3_v2_landing(s,t,a_clean(s,t,input),before);f3_v2_landing(s,t,out,after);
    for(int j=0;j<board.nb;++j) if(j!=b && s.owner[j]==t) {
        int c=board.pos[j];auto [danger,flag]=f3_v2_threat(s,t,c);
        if(!flag && !(danger && before[F][c])) continue;
        int old_need=danger+int(flag && !before[F][c]),new_need=danger+int(flag && !after[F][c]);
        if(before[W][c]>=old_need && after[W][c]<new_need) return false;
    }
    return true;
}
bool f3_v2_warrior_reserve(const State& s,int t,const Action& input,int b,Action& out) {
    if(b<0 || b>=board.nb || s.owner[b]!=t) return false;
    int c=board.pos[b],land[3][N]{};Action clean=a_clean(s,t,input);
    f3_v2_landing(s,t,clean,land);auto [danger,flag]=f3_v2_threat(s,t,c);
    if(!flag && !(danger && land[F][c])) return false;
    int need=danger+int(flag && !land[F][c]);
    int extra=need-land[W][c],outgoing=0;
    for(auto m:clean.moves) if(m.kind==W && m.from==c) outgoing+=m.count;
    if(extra<=0 || extra>outgoing) return false;
    int allowed=outgoing-extra;out=clean;out.moves.clear();
    for(auto m:clean.moves) {
        if(m.kind==W && m.from==c) {m.count=min(m.count,allowed);allowed-=m.count;}
        if(m.count>0) out.moves.push_back(m);
    }
    return true;
}
vector<int> f3_v2_owned_targets(const State& s,int t) {
    vector<pair<double,int>> ranked;
    for(int b=0;b<board.nb;++b) if(s.owner[b]==t) ranked.push_back({-building_value(s,t,b,1),b});
    sort(ranked.begin(),ranked.end());vector<int> out;
    for(auto [_,b]:ranked) out.push_back(b);
    return out;
}
'''


def _render_iteration2(source: str, mode: str) -> str:
    result = _render(source, mode in ("soft", "movement"), False, mode == "safe_mission")
    result = _replace(result, "double evaluation(const State& s,int t) {", "bool f3_v2_local_phase=false;\n\ndouble evaluation(const State& s,int t) {")
    result = _replace(result, "struct APlan {Action action;int continuation;double value;};", _REVISION_GUARDS + "\nstruct APlan {Action action;int continuation;double value;};")
    if mode == "soft":
        old = "if(F3_MATCH) base+=f3_access(s,t,true)-f3_access(s,t,false)-f3_access(s,1-t,true)+f3_access(s,1-t,false);"
        result = _replace(result, old, "if(F3_MATCH) base+=.4*(f3_access(s,t,true)-f3_access(s,t,false)-f3_access(s,1-t,true)+f3_access(s,1-t,false));")
    elif mode == "movement":
        result = _replace(result, "    if(F3_MATCH) base+=", "    if(!f3_v2_local_phase) return base;\n    if(F3_MATCH) base+=")
        result = _replace(result, "    Action scripts[4];", "    f3_v2_local_phase=false;\n    Action scripts[4];")
        result = _replace(result, "    if(A_LOCAL && any) {", r'''
    if(any) {
        f3_v2_local_phase=true;double local_value;
        if(!a_evaluate(s,us,incumbent.action,incumbent.continuation,depth,weights,start,limit,local_value)) goto finished;
        incumbent.value=local_value;
    }
    if(A_LOCAL && any) {''')
    elif mode == "safe_mission":
        result = _replace(result, "if(!f3_mission(s,us,scripts[i],b,repaired)) continue;", "if(!f3_v2_safe_mission(s,us,scripts[i],b,repaired)) continue;")
    elif mode == "warrior":
        anchor = "    for(int i=0;i<4;++i) plans.push_back({scripts[i],i,-1e100});"
        result = _replace(result, anchor, anchor + r'''
    for(int i=0;i<4;++i) {
        int added=0;
        for(int b:f3_v2_owned_targets(s,us)) {
            Action protected_action;
            if(!f3_v2_warrior_reserve(s,us,scripts[i],b,protected_action)) continue;
            bool duplicate=false;
            for(const auto& p:plans) if(a_equal(p.action,protected_action)) {duplicate=true;break;}
            if(!duplicate) {plans.push_back({protected_action,i,-1e100});if(++added==2) break;}
        }
    }
''')
    else:
        raise ValueError(f"Unknown revision-2 repair: {mode}")
    return result


def variants_iteration2(source: str) -> list[dict]:
    specs = (
        ("f3_v2_soft_matching", "soft", "원래 접근 평가 60%·일대일 보정 40%로, 관측된 초기 계획 순위 편향을 줄이며 분산 효과를 남긴다.", "40%도 다른 상태의 생산 순위를 바꿀 수 있고, 좋은 이동 신호까지 약해질 수 있다."),
        ("f3_v2_movement_matching", "movement", "생산·초기 스크립트는 원래 평가로 고르고 국소 이동만 일대일 평가로 비교한다. 경계에서 incumbent를 새 척도로 다시 평가한다.", "생산과 이동의 결합 개선을 놓칠 수 있고 재평가가 탐색 시간을 사용한다."),
        ("f3_v2_safe_econ_mission", "safe_mission", "경제 거점 공동 임무가 다른 보유 거점의 원래 안전한 F/W 방어를 새로 깨면 그 추가 임무를 제외한다.", "가치가 낮은 거점을 포기하는 유리한 교환도 막을 수 있으며, 원래 네 정책의 위험 행동은 제거하지 않는다."),
        ("f3_v2_warrior_reserve", "warrior", "적 F 진입이나 아군 F 사망이 가능한 보유 거점에서 필요한 W만 남기는 새 후보를 비교한다. F 이동·생산은 보존한다.", "인접 적의 최대 집중을 가정해 과도하게 묶일 수 있고, 원거리 호위나 다음 턴 재배치는 해결하지 못한다."),
    )
    return [dict(id=name,family="v3_revised_repair",parameters=dict(mode=mode,revision=2),hypothesis=hypothesis,weakness=weakness,
                 source=_render_iteration2(source,mode)) for name,mode,hypothesis,weakness in specs]
