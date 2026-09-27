"""Joint flag/escort missions with bounded warrior commitments."""
from __future__ import annotations

CPP = r'''
struct JointMission {
    int flag, building, next;
    double value;
};
struct JointAllocator {
    const State& s;
    int t, enemy, profile, budget, left[2][N]{}, landed[N]{}, threat[N]{}, far[N]{}, fd[N];
    int assigned[BMAX]{}, committed[BMAX]{};
    vector<int> sources;
    vector<JointMission> missions;
    Action action;
    JointAllocator(const State& state,int team,int variant):s(state),t(team),enemy(1-team),profile(variant),budget(s.res[t]) {
        for(int k=0;k<2;++k) copy(s.u[t][k],s.u[t][k]+N,left[k]);
        fill(fd,fd+N,INF);sources.push_back(board.base[t]);
        vector<int> enemy_sources{board.base[enemy]};
        for(int b=0;b<board.nb;++b) if(board.type[b]==HOSPITAL) {
            if(s.owner[b]==t) sources.push_back(board.pos[b]);
            if(s.owner[b]==enemy) enemy_sources.push_back(board.pos[b]);
        }
        for(int c=0;c<N;++c) if(board.pass[c]) {
            for(int q=0;q<N;++q) {
                if(board.dist[c][q]<=1) threat[c]+=s.u[enemy][W][q];
                if(board.dist[c][q]<=3) far[c]+=s.u[enemy][W][q];
                if(s.u[enemy][F][q]) fd[c]=min(fd[c],board.dist[c][q]);
            }
            for(int q:enemy_sources) if(board.dist[c][q]<=1) {threat[c]+=s.res[enemy]/cost(s,enemy,W);break;}
            int b=board.at[c];
            if(b>=0 && board.type[b]==STATION && s.owner[b]==enemy) {
                int extra=0;
                for(int j=0;j<board.nb;++j) if(j!=b && board.type[j]==STATION && s.owner[j]==enemy)
                    extra=max(extra,min(5,s.u[enemy][W][board.pos[j]]));
                threat[c]+=extra;
                for(int j=0;j<board.nb;++j) if(j!=b && board.type[j]==STATION && s.owner[j]==enemy && s.u[enemy][F][board.pos[j]]) fd[c]=min(fd[c],1);
            }
        }
        int cap=0;
        for(int b=0;b<board.nb;++b) if(s.owner[b]!=t) {
            int c=board.pos[b];bool reachable=left[F][c]>0;
            for(int q:board.adj[c]) reachable|=left[F][q]>0;
            if(reachable) cap+=(board.type[b]==PLAZA?4:2)-has(s,t,LIBRARY);
        }
        budget=max(0,budget-max(0,cap-income(s,t)));
    }
    int count(int kind) const {return accumulate(left[kind],left[kind]+N,0);}
    double worth(int b) const {
        double future=min(1.0,max(0.0,(160-s.turn)/45.0));
        double value=7*s.score[b]*(s.owner[b]==enemy?1.7:1.0);
        if(board.type[b]==ENG && !has(s,t,ENG)) value+=50*future;
        if(board.type[b]==HALL) value+=40*future;
        if(board.type[b]==HOSPITAL) value+=30*future;
        if(board.type[b]==DEPOT && !s.claimed[t][b]) value+=18*future;
        if(s.owner[b]==t && fd[board.pos[b]]<=2) value*=profile==2?2.5:1.8;
        if(profile==3 && s.stage[b]==1) value+=20;
        return value;
    }
    bool useful(int b,int distance=0) const {
        if(s.owner[b]==t) return fd[board.pos[b]]<=2 && distance<=max(1,fd[board.pos[b]]);
        // One final phase can still neutralize enemy ownership.
        return max(1,distance)<=160-s.turn;
    }
    double arrival_worth(int b,int distance) const {
        double value=worth(b);
        if(s.owner[b]==enemy && max(1,distance)+1>160-s.turn) value*=.5;
        return value;
    }
    vector<int> options(int c) const {
        vector<int> result{c};result.insert(result.end(),board.adj[c].begin(),board.adj[c].end());return result;
    }
    int support(int c) const {
        int n=landed[c]+left[W][c];for(int q:board.adj[c]) n+=left[W][q];return n;
    }
    void send(int kind,int from,int to,int n) {
        n=min(n,left[kind][from]);if(n<=0)return;
        left[kind][from]-=n;
        if(kind==W) landed[to]+=n;
        if(from!=to) action.moves.push_back({kind,from,to,n});
    }
    void escort(int cell,int need) {
        need=max(0,need-landed[cell]);
        vector<int> order=options(cell);
        stable_sort(order.begin(),order.end(),[&](int a,int b) {
            if(a==cell || b==cell) return a==cell && b!=cell;
            return left[W][a]>left[W][b];
        });
        for(int q:order) {int n=min(need,left[W][q]);send(W,q,cell,n);need-=n;}
    }
    int flag_step(int from,int building) const {
        int target=board.pos[building],best=from;double score=-1e20;
        for(int q:options(from)) {
            int deficit=max(0,threat[q]-support(q));
            double value=-4.0*board.dist[q][target]-100*double(deficit>0)-2*deficit;
            if(q==target && s.owner[building]==t && fd[q]<=1) value+=5;
            if(q==target && s.u[enemy][F][q] && support(q)<=threat[q]) value-=5;
            value-=.002*threat[q];
            if(value>score) {score=value;best=q;}
        }
        return best;
    }
    void produce() {
        int targets=0;for(int b=0;b<board.nb;++b) targets+=s.owner[b]!=t;
        int desired=min(profile==1?5:8,max(2,targets));
        if(s.turn<3) desired=4;
        if(s.turn>145) desired=min(desired,4);
        int nf=count(F),nw=count(W),make=min(max(0,desired-nf),budget/5);
        if(nf>=2 && s.turn>=2) make=min(make,nw>=2?1:0);
        for(int k=0;k<make;++k) {
            int site=-1;double score=-1e20;
            for(int q:sources) for(int b=0;b<board.nb;++b) if(useful(b,board.dist[q][board.pos[b]])) {
                double value=arrival_worth(b,board.dist[q][board.pos[b]])/(board.dist[q][board.pos[b]]+2.0);
                value-=3*max(0,threat[q]-support(q));
                value-=.5*left[F][q];
                if(value>score){score=value;site=q;}
            }
            if(site<0)break;
            action.spawn.push_back({F,site,1});++left[F][site];budget-=5;
        }
        int n=budget/cost(s,t,W);
        if(n<=0)return;
        int site=-1;double score=-1e20;
        for(int q:sources) for(int b=0;b<board.nb;++b) if(useful(b,board.dist[q][board.pos[b]])) {
            int c=board.pos[b];
            double value=worth(b)/(board.dist[q][c]+2.0);
            if(s.owner[b]==t && fd[c]<=1 && board.dist[q][c]<=1 && support(c)<threat[c]+1) value+=40;
            if(value>score){score=value;site=q;}
        }
        if(site<0)return;
        action.spawn.push_back({W,site,n});left[W][site]+=n;budget-=n*cost(s,t,W);
    }
    void assign_flags() {
        int pool[N];copy(left[F],left[F]+N,pool);
        for(int round=0;round<board.nb;++round) {
            int source=-1,goal=-1,next=-1;double best=-1e20;
            for(int c=0;c<N;++c) if(pool[c]) for(int b=0;b<board.nb;++b) if(!assigned[b]) {
                int target=board.pos[b],d=board.dist[c][target];
                if(!useful(b,d))continue;
                if(s.owner[b]==t && d>max(1,fd[target]))continue;
                int q=flag_step(c,b),deficit=max(0,threat[q]-support(q));
                double v=arrival_worth(b,d)/(d+1.7)-4*deficit;
                if(c==target)v+=12;
                if(s.owner[b]==t && fd[target]<=1 && d<=1)v+=40;
                if(profile==1 && s.owner[b]==enemy)v+=4;
                if(v>best){best=v;source=c;goal=b;next=q;}
            }
            if(source<0)break;
            --pool[source];assigned[goal]=1;missions.push_back({source,goal,next,best});
        }
        stable_sort(missions.begin(),missions.end(),[&](const JointMission& a,const JointMission& b) {
            bool da=s.owner[a.building]==t && fd[board.pos[a.building]]<=1;
            bool db=s.owner[b.building]==t && fd[board.pos[b.building]]<=1;
            return da!=db?da:a.value>b.value;
        });
    }
    void defend_and_escort() {
        // Only units already within one move can satisfy this turn's defense.
        for(const auto& m:missions) {
            int c=board.pos[m.building];
            if(s.owner[m.building]!=t || fd[c]>1 || board.dist[m.flag][c]>1)continue;
            if(support(c)>=threat[c]) escort(c,threat[c]);
        }
        for(int b=0;b<board.nb;++b) {
            int c=board.pos[b];
            if(s.owner[b]!=t || fd[c]>1 || assigned[b])continue;
            if(support(c)>=threat[c]+1)escort(c,threat[c]+1);
        }
        for(auto& m:missions) {
            m.next=flag_step(m.flag,m.building);
            int need=threat[m.next];
            if(s.u[enemy][F][m.next] && s.owner[m.building]!=t)++need;
            if(support(m.next)>=need)escort(m.next,need);
            // A worst-case tie kills both warriors and leaves our flag alive.
            if(landed[m.next]<threat[m.next]) {
                int safest=m.flag,deficit=threat[safest]-landed[safest];
                for(int q:options(m.flag)) if(threat[q]-landed[q]<deficit) {safest=q;deficit=threat[q]-landed[q];}
                m.next=safest;
            }
            send(F,m.flag,m.next,1);
        }
    }
    int warrior_step(int source,int target,int n) const {
        int next=source;double best=-1e20;
        for(int q:options(source)) {
            int deficit=max(0,threat[q]-landed[q]-n);
            double value=-4.0*board.dist[q][target]-min(14.0,2.0*deficit);
            if(profile==1)value+=min(8.0,1.2*deficit);
            if(value>best){best=value;next=q;}
        }
        return next;
    }
    void distribute_warriors() {
        int need[BMAX]{};
        for(int b=0;b<board.nb;++b) {
            int c=board.pos[b];
            if(s.owner[b]!=t) need[b]=max(1,far[c]+1);
            else if(fd[c]<=3)need[b]=threat[c]+1;
            committed[b]=landed[c];
        }
        vector<int> order;
        for(int c=0;c<N;++c)if(left[W][c])order.push_back(c);
        stable_sort(order.begin(),order.end(),[&](int a,int b){return left[W][a]>left[W][b];});
        for(int src:order) {
            int attacks=0;
            for(int b=0;b<board.nb;++b) if(s.owner[b]!=t && useful(b,board.dist[src][board.pos[b]]))++attacks;
            int surplus_chunk=max(1,(left[W][src]+max(1,attacks)-1)/max(1,attacks));
            for(int split=0;left[W][src] && split<2*BMAX;++split) {
            int goal=-1;double best=-1e20;bool surplus=false;
            for(int b=0;b<board.nb;++b) {
                int c=board.pos[b],remaining=need[b]-committed[b];
                if(remaining<=0 || !useful(b,board.dist[src][c]))continue;
                double value=worth(b)/(board.dist[src][c]+2.0);
                if(assigned[b])value*=1.4;
                if(s.owner[b]==t && fd[c]>1)value*=.65;
                if(value>best){best=value;goal=b;}
            }
            if(goal<0) {
                surplus=true;
                // A filled defensive mission cannot absorb the entire surplus.
                for(int b=0;b<board.nb;++b) if(s.owner[b]!=t && useful(b,board.dist[src][board.pos[b]])) {
                    double value=worth(b)/(board.dist[src][board.pos[b]]+2.0)/(1+committed[b]/20.0);
                    if(value>best){best=value;goal=b;}
                }
            }
            if(goal<0){send(W,src,src,left[W][src]);break;}
            int n=min(left[W][src],max(1,need[goal]-committed[goal]));
            if(surplus)n=min(left[W][src],surplus_chunk);
            int dest=warrior_step(src,board.pos[goal],n);
            committed[goal]+=n;send(W,src,dest,n);
            }
        }
    }
    Action finish() {
        for(int c=0;c<N;++c) if(left[F][c]) {
            int next=c,deficit=threat[c]-landed[c];
            for(int q:board.adj[c]) if(threat[q]-landed[q]<deficit){next=q;deficit=threat[q]-landed[q];}
            send(F,c,next,left[F][c]);
        }
        action.priority.resize(board.nb);iota(action.priority.begin(),action.priority.end(),0);
        stable_sort(action.priority.begin(),action.priority.end(),[&](int a,int b){return worth(a)>worth(b);});
        return action;
    }
};
Action joint_policy(const State& s,int t,int profile) {
    JointAllocator p(s,t,profile);
    p.produce();p.assign_flags();p.defend_and_escort();p.distribute_warriors();return p.finish();
}
'''


def variants(source: str) -> list[dict]:
    anchor = "Action policy(const State& s, int t, int style) {"
    if source.count(anchor) != 1 or source.count("int forced_policy = -1;") != 1:
        raise ValueError("joint allocator requires the frozen v2 policy layout")
    designs = [
        ("balanced", 0, "한 턴 내 실제 도착 W와 F를 공동 배정하고 충족된 수비 임무에서 잉여 병력을 뺀다.",
         "적 인접 W를 모두 한 목표에 가정하는 보수성과 매 턴 탐욕 재배정이 장기 우회·진동을 만들 수 있다."),
        ("pressure", 1, "F 수요를 줄여 전투력을 확보하고 적 소유 목표 및 돌파 이동에 더 적극적으로 투자한다.",
         "약한 묶음의 전진과 F 감소가 다방면 재점령 및 기습 수비를 악화시킬 수 있다."),
        ("defensive", 2, "F가 실제 접근하는 소유 거점의 임무 가치를 높이되 필요한 W 이상은 이동시킨다.",
         "예상 F 경로와 과대 위협 때문에 실제 공격하지 않는 거점에 수비를 배정할 수 있다."),
        ("reclaim", 3, "직전 중립화된 1단계 거점의 재점령을 우선하고 남은 턴에 점유 가능 여부를 구분한다.",
         "중립화 상태는 직전 목표의 중요도를 보장하지 않아 가치가 낮은 반복 경합에 매몰될 수 있다."),
    ]
    result = []
    for name, profile, hypothesis, weakness in designs:
        for mode in ("direct", "portfolio"):
            edited = source.replace(anchor, CPP + "\n" + anchor, 1)
            guard = "true" if mode == "direct" else "style==2"
            wrapper = f"""
Action joint_own_policy(const State& s,int t,int style) {{
    if ({guard}) return joint_policy(s,t,{profile});
    return policy(s,t,style);
}}
"""
            evaluation_anchor = "double evaluation(const State& s, int t) {"
            candidate_anchor = "candidates[i]=policy(s,us,i);"
            rollout_anchor = "own=d==0?candidates[i]:policy(trial,us,i), opp=policy(trial,1-us,j);"
            for value in (evaluation_anchor, candidate_anchor, rollout_anchor):
                if edited.count(value) != 1:
                    raise ValueError("joint allocator requires frozen evaluation and rollout anchors")
            edited = edited.replace(evaluation_anchor, wrapper + "\n" + evaluation_anchor, 1)
            edited = edited.replace(candidate_anchor, "candidates[i]=joint_own_policy(s,us,i);", 1)
            edited = edited.replace(rollout_anchor, "own=d==0?candidates[i]:joint_own_policy(trial,us,i), opp=policy(trial,1-us,j);", 1)
            if mode == "direct":
                edited = edited.replace("int forced_policy = -1;", "int forced_policy = 0;", 1)
            result.append({"id": f"j_{name}_{mode}", "family": "joint_mission_allocation",
                           "parameters": {"profile": profile, "mode": mode, "replacement_style": None if mode == "direct" else 2,
                                          "opponent_model": "unchanged_v2", "own_only": True},
                           "hypothesis": hypothesis, "weakness": weakness, "source": edited})
    return result


def variants_iteration2(source: str) -> list[dict]:
    """New IDs only: the first iteration renderer and its eight sources stay frozen."""
    original = {row["id"]: row for row in variants(source)}
    specifications = [
        ("j_v2_defensive_delayed", "j_defensive_portfolio", {"start_turn": 30},
         "7003 첫 턴부터 확장 경로가 갈라진 회귀에 대해 초반 30턴의 원래 정책을 보존하고 이후 공동 배정만 추가한다.",
         "초반 공동 호위의 잠재 이득도 버리며 30턴의 정책 전환이 새로운 역할 진동을 만들 수 있다."),
        ("j_v2_reclaim_flags7", "j_reclaim_portfolio", {"flag_cap": 7},
         "7005의 10턴부터 F8명 유지·W3명 감소와 종반 중복 F를 근거로 기수 상한을 v2의 7명으로 제한한다.",
         "F1명의 비용 절약은 작은 효과이며 실제 패배 원인은 목표 배정과 전투 경로일 수 있다."),
        ("j_v2_reclaim_relay", "j_reclaim_portfolio", {"blocked_flag_relay": True},
         "위험 때문에 진전하지 못한 F에는 최종 건물 대신 다음 진전 칸을 W 집결 임무로 만들어 유휴 F와 호위 단절을 줄인다.",
         "막힌 F가 가치 낮은 전선에 있으면 큰 W 집단을 끌어들여 다른 전선을 약하게 만들 수 있다."),
        ("j_v2_reclaim_relay_delayed", "j_reclaim_portfolio", {"blocked_flag_relay": True, "start_turn": 30},
         "초반 v2 확장을 보존한 뒤 막힌 F의 경유점 호위만 추가해 첫 회귀의 초기 분기와 종반 유휴를 함께 대조한다.",
         "두 요소 결합이므로 단일 요인의 인과 효과는 분리 후보와 비교해야 하며 상대별 회귀 가능성이 남는다."),
    ]
    results = []
    for name, parent, parameters, hypothesis, weakness in specifications:
        edited = original[parent]["source"]
        if parameters.get("start_turn"):
            anchor = "if (style==2) return joint_policy(s,t,"
            if edited.count(anchor) != 1:
                raise ValueError("joint own-policy wrapper changed")
            edited = edited.replace(anchor, f"if (style==2 && s.turn>={parameters['start_turn']}) return joint_policy(s,t,", 1)
        if parameters.get("flag_cap"):
            anchor = "int desired=min(profile==1?5:8,max(2,targets));"
            if edited.count(anchor) != 1:
                raise ValueError("joint flag capacity changed")
            edited = edited.replace(anchor, f"int desired=min(profile==1?5:{parameters['flag_cap']},max(2,targets));", 1)
        if parameters.get("blocked_flag_relay"):
            start = edited.index("    void distribute_warriors() {")
            end = edited.index("    Action finish() {", start)
            block = edited[start:end]
            block = block.replace("int need[BMAX]{};", "int need[BMAX]{}, destination[BMAX];\n        copy(board.pos,board.pos+board.nb,destination);", 1)
            anchor = "        vector<int> order;"
            relay = r'''        for(const auto& m:missions) {
            int target=board.pos[m.building],distance=board.dist[m.flag][target];
            if(s.owner[m.building]==t || distance==0 || board.dist[m.next][target]<distance)continue;
            int waypoint=m.flag;
            for(int q:board.adj[m.flag]) if(board.dist[q][target]<board.dist[waypoint][target])waypoint=q;
            if(waypoint==m.flag || threat[waypoint]<=landed[waypoint])continue;
            destination[m.building]=waypoint;
            need[m.building]=threat[waypoint]+1;
            committed[m.building]=landed[waypoint];
        }
'''
            if block.count(anchor) != 1:
                raise ValueError("joint warrior assignment layout changed")
            block = block.replace(anchor, relay + anchor, 1)
            block = block.replace("int c=board.pos[b],remaining=need[b]-committed[b];", "int c=destination[b],remaining=need[b]-committed[b];", 1)
            block = block.replace("int dest=warrior_step(src,board.pos[goal],n);", "int dest=warrior_step(src,surplus?board.pos[goal]:destination[goal],n);", 1)
            edited = edited[:start] + block + edited[end:]
        results.append({"id": name, "family": "joint_mission_revision2", "parameters": {
            **parameters, "parent_candidate": parent, "iteration": 2, "own_only": True,
            "opponent_model": "unchanged_v2", "mode": "portfolio", "replacement_style": 2},
            "hypothesis": hypothesis, "weakness": weakness, "source": edited})
    return results
