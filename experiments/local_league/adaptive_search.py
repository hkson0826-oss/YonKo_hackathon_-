"""Bounded action recombination, local search, and observation-based opponent fit."""

START = "    constexpr int P=4;\n"
END = "    const auto& a=candidates[chosen];\n"

HELPERS = r'''
constexpr int A_MIX=@MIX@, A_LOCAL=@LOCAL@, A_MEMORY=@MEMORY@;
constexpr int A_STAGE=@STAGE@, A_UNCERTAIN=@UNCERTAIN@, A_FREE=@FREE@;
using AClock=chrono::steady_clock;
bool a_previous=false;
State a_previous_state;
Action a_previous_action;
double a_error[4]{};

Action a_clean(const State& s,int t,const Action& input) {
    Action out; int available[3][N],budget=s.res[t]; bool tele=false;
    for(int k=0;k<3;++k) copy(s.u[t][k],s.u[t][k]+N,available[k]);
    for(auto p:input.spawn) {
        if(p.kind<0 || p.kind>=3 || p.pos<0 || p.pos>=N || p.count<=0) continue;
        int b=board.at[p.pos];
        if(p.pos!=board.base[t] && !(b>=0 && board.type[b]==HOSPITAL && s.owner[b]==t)) continue;
        p.count=min(p.count,budget/cost(s,t,p.kind));
        if(!p.count) continue;
        budget-=p.count*cost(s,t,p.kind); available[p.kind][p.pos]+=p.count; out.spawn.push_back(p);
    }
    for(auto m:input.moves) {
        if(m.kind<0 || m.kind>=3 || m.from<0 || m.from>=N || m.to<0 || m.to>=N || m.count<=0) continue;
        if(m.tele) {
            int x=board.at[m.from],y=board.at[m.to];
            if(tele || x<0 || y<0 || x==y || board.type[x]!=STATION || board.type[y]!=STATION || s.owner[x]!=t || s.owner[y]!=t) continue;
            m.count=min(m.count,5);
        } else if(find(board.adj[m.from].begin(),board.adj[m.from].end(),m.to)==board.adj[m.from].end()) continue;
        m.count=min(m.count,available[m.kind][m.from]);
        if(!m.count) continue;
        available[m.kind][m.from]-=m.count; out.moves.push_back(m);
        if(m.tele) tele=true;
    }
    bool used[BMAX]{};
    for(int b:input.priority) if(b>=0 && b<board.nb && !used[b]) {used[b]=true;out.priority.push_back(b);}
    return out;
}

Action a_mix(const State& s,int t,const Action& flag,const Action& warrior) {
    Action a=flag; a.moves.clear();
    for(auto m:warrior.moves) if(m.kind==W) a.moves.push_back(m);
    for(auto m:flag.moves) if(m.kind!=W) a.moves.push_back(m);
    return a_clean(s,t,a);
}

Action a_patch(const State& s,int t,Action current,const Action& alternative,int source) {
    current.moves.erase(remove_if(current.moves.begin(),current.moves.end(),[&](auto m){return m.from==source;}),current.moves.end());
    for(auto m:alternative.moves) if(m.from==source) current.moves.push_back(m);
    return a_clean(s,t,current);
}

bool a_equal(const Action& x,const Action& y) {
    if(x.spawn.size()!=y.spawn.size() || x.moves.size()!=y.moves.size() || x.priority!=y.priority) return false;
    for(int i=0;i<int(x.spawn.size());++i) {
        auto a=x.spawn[i],b=y.spawn[i]; if(a.kind!=b.kind || a.pos!=b.pos || a.count!=b.count) return false;
    }
    for(int i=0;i<int(x.moves.size());++i) {
        auto a=x.moves[i],b=y.moves[i];
        if(a.kind!=b.kind || a.from!=b.from || a.to!=b.to || a.count!=b.count || a.tele!=b.tele) return false;
    }
    return true;
}

double a_prediction_error(const State& predicted,const State& observed,int us) {
    double loss=0;
    for(int k=0;k<3;++k) for(int c=0;c<N;++c)
        loss+=(k==F?5.0:1.0)*abs(predicted.u[1-us][k][c]-observed.u[1-us][k][c]);
    for(int b=0;b<board.nb;++b) loss+=12*(predicted.owner[b]!=observed.owner[b]);
    return loss+.25*abs(predicted.res[1-us]-observed.res[1-us]);
}

void a_observe(const State& s,int us,double (&weights)[4]) {
    if(A_MEMORY && a_previous && s.turn==a_previous_state.turn+1) {
        for(int j=0;j<4;++j) {
            Action opp=policy(a_previous_state,1-us,j);
            State p=us==0?advance(a_previous_state,a_previous_action,opp):advance(a_previous_state,opp,a_previous_action);
            a_error[j]=.75*a_error[j]+.25*a_prediction_error(p,s,us);
        }
    }
    double low=*min_element(a_error,a_error+4),sum=0;
    for(int j=0;j<4;++j) {weights[j]=A_MEMORY?exp(-min(40.0,(a_error[j]-low)/8.0)):1;sum+=weights[j];}
    for(double& w:weights) w=.10+.60*w/sum;
}

State a_scenario(State s,int us,int scenario) {
    if(!A_UNCERTAIN) return s;
    for(int b=0;b<board.nb;++b) {
        int mirror=board.at[224-board.pos[b]];
        if(s.revealed[us][b] || (mirror>=0 && s.revealed[us][mirror])) continue;
        bool center=board.pos[b]%15>=5 && board.pos[b]%15<=9;
        s.score[b]=board.type[b]==PLAZA?3:center?(scenario?4:2):(scenario?2:1);
    }
    for(int t=0;t<2;++t) {
        s.occupation[t]=0;
        for(int b=0;b<board.nb;++b) s.occupation[t]+=occupation_history[t][b]*s.score[b];
    }
    return s;
}

bool a_evaluate(const State& s,int us,const Action& first,int continuation,int horizon,
                const double (&weights)[4],AClock::time_point start,double limit,double& result) {
    double scenarios[2]{}; int count=A_UNCERTAIN?2:1;
    for(int scenario=0;scenario<count;++scenario) {
        double mean=0,worst=1e100;
        for(int j=0;j<4;++j) {
            State trial=a_scenario(s,us,scenario);
            for(int d=0;d<horizon;++d) {
                if(chrono::duration<double,milli>(AClock::now()-start).count()>=limit) return false;
                Action own=d?policy(trial,us,continuation):first,opp=policy(trial,1-us,j);
                trial=us==0?advance(trial,own,opp):advance(trial,opp,own);
                if(abs(evaluation(trial,us))>=80000) break;
            }
            double score=evaluation(trial,us);
            mean+=weights[j]*score; worst=min(worst,score);
        }
        scenarios[scenario]=.75*mean+.25*worst;
    }
    result=count==1?scenarios[0]:min(scenarios[0],scenarios[1]);
    return true;
}

struct APlan {Action action;int continuation;double value;};
Action a_decide(const State& s,int us,AClock::time_point start,double limit=135.0) {
    Action scripts[4];
    for(int i=0;i<4;++i) scripts[i]=a_clean(s,us,policy(s,us,i));
    double weights[4]; a_observe(s,us,weights);
    vector<APlan> plans;
    for(int i=0;i<4;++i) plans.push_back({scripts[i],i,-1e100});
    if(A_MIX) for(auto pair:{std::pair{0,3},std::pair{3,0},std::pair{0,2},std::pair{2,0}})
        plans.push_back({a_mix(s,us,scripts[pair.first],scripts[pair.second]),pair.first,-1e100});
    int depth=min(A_STAGE?2:3,160-s.turn),best=0; bool any=false;
    for(int i=0;i<int(plans.size());++i) {
        double value;
        if(!a_evaluate(s,us,plans[i].action,plans[i].continuation,depth,weights,start,limit,value)) break;
        plans[i].value=value;
        if(!any || value>plans[best].value) best=i;
        any=true;
    }
    APlan incumbent=plans[best];
    if(A_STAGE && any) {
        vector<int> order;
        for(int i=0;i<int(plans.size());++i) if(plans[i].value>-1e99) order.push_back(i);
        stable_sort(order.begin(),order.end(),[&](int a,int b){return plans[a].value>plans[b].value;});
        int n=min(3,int(order.size())),deep=min(s.turn<80?6:4,160-s.turn); bool complete=true;
        vector<APlan> finalists;
        for(int k=0;k<n;++k) {
            APlan p=plans[order[k]];
            if(!a_evaluate(s,us,p.action,p.continuation,deep,weights,start,limit,p.value)) {complete=false;break;}
            finalists.push_back(p);
        }
        if(complete && !finalists.empty()) incumbent=*max_element(finalists.begin(),finalists.end(),[](auto a,auto b){return a.value<b.value;});
    }
    if(A_LOCAL && any) {
        vector<pair<double,int>> groups;
        for(int c=0;c<N;++c) if(s.u[us][F][c] || s.u[us][W][c]) {
            double importance=8*s.u[us][F][c]+sqrt(double(s.u[us][W][c]));
            int b=board.at[c]; if(b>=0) importance+=3;
            groups.push_back({-importance,c});
        }
        sort(groups.begin(),groups.end());
        for(int k=0;k<min(3,int(groups.size()));++k) {
            int src=groups[k].second;
            for(int j=0;j<4;++j) {
                Action trial=a_patch(s,us,incumbent.action,scripts[j],src); double value;
                if(a_equal(trial,incumbent.action)) continue;
                if(!a_evaluate(s,us,trial,incumbent.continuation,depth,weights,start,limit,value)) goto finished;
                if(value>incumbent.value) {incumbent.action=trial;incumbent.value=value;}
            }
            if(A_FREE) for(int target:board.adj[src]) {
                Action alternate;
                for(int kind=0;kind<2;++kind) if(s.u[us][kind][src]) alternate.moves.push_back({kind,src,target,s.u[us][kind][src]});
                Action trial=a_patch(s,us,incumbent.action,alternate,src); double value;
                if(a_equal(trial,incumbent.action)) continue;
                if(!a_evaluate(s,us,trial,incumbent.continuation,depth,weights,start,limit,value)) goto finished;
                if(value>incumbent.value) {incumbent.action=trial;incumbent.value=value;}
            }
        }
    }
finished:
    if(A_MEMORY) {a_previous=true;a_previous_state=s;a_previous_action=incumbent.action;}
    return incumbent.action;
}
'''


def _build(source: str, **parameters) -> str:
    if source.count(START) != 1 or source.count(END) != 1:
        raise ValueError("v2 decision anchors changed")
    helpers = HELPERS
    for key in ("mix", "local", "memory", "stage", "uncertain", "free"):
        helpers = helpers.replace("@" + key.upper() + "@", str(int(parameters.get(key, False))))
    block = "    Action a=forced_policy>=0?policy(s,us,forced_policy):a_decide(s,us,start);\n"
    begin, end = source.index(START), source.index(END) + len(END)
    out = source[:begin] + block + source[end:]
    anchor = "vector<string> decide(const p::View& v, const p::Init& in) {"
    if out.count(anchor) != 1:
        raise ValueError("v2 function anchor changed")
    return out.replace(anchor, helpers + "\n" + anchor, 1)


def variants(source: str) -> list[dict]:
    specs = [
        ("a_asymmetric_mix", "script_recombination", {"mix": True},
         "F 이동·생산과 W 이동을 서로 다른 정책에서 결합해 원본 4개 밖의 행동을 만든다.",
         "F/W 협력이 깨질 수 있고 깊이 3 이후 혼합 역할이 유지되지 않는다."),
        ("a_pgs_local", "coordinate_action_search", {"local": True},
         "중요한 출발지 3곳의 명령만 순서대로 고쳐 제한 시간 내 완전 평가된 개선을 보존한다.",
         "탐색 순서와 국소 최적에 민감하며 새 생산 명령은 만들지 않는다."),
        ("a_pgs_hybrid", "coordinate_action_search", {"mix": True, "local": True},
         "혼합 정책을 초기점으로 삼아 주요 병력 묶음의 상충 명령을 국소 교정한다.",
         "후보 생성 비용으로 국소 수정 기회가 줄고 평가 함수 오류를 확대할 수 있다."),
        ("a_opponent_fit", "observed_opponent_fit", {"mix": True, "memory": True},
         "직전 합법 관측 전이의 재현 오차로 상대 스크립트 가중치를 조절한다.",
         "실제 상대가 네 스크립트 밖에 있거나 전략을 바꾸면 잘못 추정할 수 있다."),
        ("a_fit_pgs", "observed_opponent_fit", {"local": True, "memory": True},
         "최소 상대 가중치 0.10과 최악값 25%를 유지하며 상대 적합도와 국소 수정을 결합한다.",
         "예측 오차 최소화가 승률 개선을 뜻하지 않으며 계산 예산을 공유한다."),
        ("a_progressive", "progressive_refinement", {"mix": True, "stage": True},
         "얕은 평가로 후보 3개를 추린 뒤 더 깊이 평가하되 세 후보가 다 끝난 경우만 교체한다.",
         "얕은 평가에서 탈락한 장기 투자 행동은 복구하지 못한다."),
        ("a_score_scenarios", "hidden_score_scenarios", {"mix": True, "uncertain": True},
         "미공개 대칭 건물 점수를 합법 범위의 두 극단으로 평가해 점수 추정 취약성을 줄인다.",
         "모든 미공개 점수가 함께 낮거나 높은 두 경우뿐이며 전체 가능 맵의 최악값이 아니다."),
        ("a_local_unabstracted", "partial_unabstracted_moves", {"local": True, "free": True},
         "중요 출발지에서는 기존 스크립트에 없는 인접 칸 이동도 실제 전이로 비교한다.",
         "해당 출발지의 F/W 전량 동시 이동만 추가하므로 최적 분할이나 다턴 계획은 아니다."),
    ]
    return [{"id": name, "family": family, "parameters": params,
             "hypothesis": hypothesis, "weakness": weakness, "source": _build(source, **params)}
            for name, family, params, hypothesis, weakness in specs]


ITERATION2_HELPERS = r'''
double a2_importance(const State& s,int us,int c) {
    int enemy_w=s.u[1-us][W][c],enemy_f=s.u[1-us][F][c];
    for(int q:board.adj[c]) {enemy_w+=s.u[1-us][W][q];enemy_f+=s.u[1-us][F][q];}
    double importance=8*s.u[us][F][c]+sqrt(double(s.u[us][W][c]));
    int b=board.at[c];
    if(b>=0) {
        importance+=3;
        if(s.u[us][F][c] && (s.owner[b]!=us || enemy_f)) importance+=12+4*s.score[b];
        if(s.turn>=155 && s.u[us][F][c] && s.owner[b]!=us) importance+=60;
    }
    if(s.u[us][F][c] && enemy_w) importance+=min(30,enemy_w)+10;
    return importance;
}

vector<Action> a2_neighborhood(const State& s,int us,const Action& incumbent,int src) {
    vector<Action> choices; vector<int> destinations{src};
    destinations.insert(destinations.end(),board.adj[src].begin(),board.adj[src].end());
    for(int dest:destinations) for(int mask=1;mask<=3;++mask) {
        Action trial=incumbent;
        trial.moves.erase(remove_if(trial.moves.begin(),trial.moves.end(),[&](auto m) {
            return m.from==src && m.kind<2 && (mask&(1<<m.kind));
        }),trial.moves.end());
        if(dest!=src) for(int kind=0;kind<2;++kind) if(mask&(1<<kind)) {
            int stock=s.u[us][kind][src];
            for(auto p:incumbent.spawn) if(p.pos==src && p.kind==kind) stock+=p.count;
            if(stock) trial.moves.push_back({kind,src,dest,stock});
        }
        trial=a_clean(s,us,trial);
        if(a_equal(trial,incumbent)) continue;
        if(none_of(choices.begin(),choices.end(),[&](const Action& old){return a_equal(old,trial);})) choices.push_back(trial);
    }
    return choices;
}
'''


def _replace_required(source: str, old: str, new: str) -> str:
    if source.count(old) != 1:
        raise ValueError("Iteration-2 source anchor changed: " + old[:70])
    return source.replace(old, new, 1)


def _iteration2(source: str, *, tactical=False, memory=False, continuous=False) -> str:
    if continuous:
        out = _build(source, mix=True, memory=True)
        helper = r'''
Action a2_continuation(const State& s,int us,int code) {
    if(code<4) return policy(s,us,code);
    int flags=(code-4)/4,warriors=(code-4)%4;
    return a_mix(s,us,policy(s,us,flags),policy(s,us,warriors));
}
'''
        out = _replace_required(out, "bool a_evaluate(", helper + "\nbool a_evaluate(")
        out = _replace_required(out, "Action own=d?policy(trial,us,continuation):first,opp=policy(trial,1-us,j);",
                                "Action own=d?a2_continuation(trial,us,continuation):first,opp=policy(trial,1-us,j);")
        out = _replace_required(out, "scripts[pair.second]),pair.first,-1e100});",
                                "scripts[pair.second]),4+pair.first*4+pair.second,-1e100});")
        return out
    out = _build(source, local=True, free=True, memory=memory)
    anchor = "double score[2] = {points(s,0),points(s,1)}, total = accumulate(s.score,s.score+board.nb,0.0);"
    out = _replace_required(out, anchor, anchor + "\n    double a2_margin=s.turn>=160?clamp(20*(score[t]-score[1-t]),-1000.0,1000.0):0;")
    out = _replace_required(out, "if (score[1-t] == 0 && score[t]*2 > total) return 100000;",
                            "if (score[1-t] == 0 && score[t]*2 > total) return 100000+a2_margin;")
    out = _replace_required(out, "if (score[t] == 0 && score[1-t]*2 > total) return -100000;",
                            "if (score[t] == 0 && score[1-t]*2 > total) return -100000+a2_margin;")
    out = _replace_required(out, "if (score[t] != score[1-t]) return score[t] > score[1-t] ? 100000 : -100000;",
                            "if (score[t] != score[1-t]) return (score[t] > score[1-t] ? 100000 : -100000)+a2_margin;")
    if tactical:
        out = _replace_required(out, "struct APlan {", ITERATION2_HELPERS + "\nstruct APlan {")
        out = _replace_required(out,
                                "double importance=8*s.u[us][F][c]+sqrt(double(s.u[us][W][c]));\n            int b=board.at[c]; if(b>=0) importance+=3;",
                                "double importance=a2_importance(s,us,c);")
        old = """            if(A_FREE) for(int target:board.adj[src]) {
                Action alternate;
                for(int kind=0;kind<2;++kind) if(s.u[us][kind][src]) alternate.moves.push_back({kind,src,target,s.u[us][kind][src]});
                Action trial=a_patch(s,us,incumbent.action,alternate,src); double value;
                if(a_equal(trial,incumbent.action)) continue;
                if(!a_evaluate(s,us,trial,incumbent.continuation,depth,weights,start,limit,value)) goto finished;
                if(value>incumbent.value) {incumbent.action=trial;incumbent.value=value;}
            }"""
        new = """            if(A_FREE) for(const Action& trial:a2_neighborhood(s,us,incumbent.action,src)) {
                double value;
                if(!a_evaluate(s,us,trial,incumbent.continuation,depth,weights,start,limit,value)) goto finished;
                if(value>incumbent.value) {incumbent.action=trial;incumbent.value=value;}
            }"""
        out = _replace_required(out, old, new)
    return out


def variants_iteration2(source: str) -> list[dict]:
    specs = [
        ("a_v2_terminal_local", "terminal_local_revision", {},
         "7001 최종 턴에서 동가치 패배 때문에 재점령을 포기한 문제를 종반 점수차로 구분한다.",
         "확인된 한 턴에서 3점을 회복해도 패배는 그대로다. 승패 단계 간 순서는 보존한다."),
        ("a_v2_tactical_local", "tactical_neighborhood_revision", {"tactical": True},
         "위협·점령 중인 F의 출발지를 우선하고 F/W별 이동·대기를 별도 후보로 공식 전이 평가한다.",
         "대기를 강제하지 않는다. 7001 turn34처럼 F 대기는 오히려 적의 즉시 점령을 도울 수 있다."),
        ("a_v2_tactical_fit", "tactical_neighborhood_revision", {"tactical": True, "memory": True},
         "같은 전술 후보 집합에서 관측 기반 상대 적합도 사용 여부만 대조한다.",
         "모델 후보 밖의 상대를 잘못 추정하면 국소 개선의 기준도 왜곡된다."),
        ("a_v2_continuous_mix", "continuous_role_revision", {"continuous": True},
         "혼합한 F/W 역할을 rollout 후속 턴에도 유지해 첫 행동과 평가 계획의 불일치를 줄인다.",
         "7007 패배가 역할 단절 때문인지는 미확인이다. 실제 다음 턴에는 재계획하므로 영속 임무가 아니다."),
    ]
    return [{"id": name, "family": family, "parameters": params,
             "hypothesis": hypothesis, "weakness": weakness,
             "source": _iteration2(source, **params)}
            for name, family, params, hypothesis, weakness in specs]
