"""v3-only opponent uncertainty and restricted simultaneous-game candidates."""

EVALUATE_START = "bool a_evaluate("
EVALUATE_END = "struct APlan {"
ENTRY = "a_decide(s,us,start);"

HELPERS = r'''
constexpr int R3_MODE=@MODE@;
double r3_weights[6]={1./6,1./6,1./6,1./6,1./6,1./6},r3_error[6]{};
bool r3_previous=false;
State r3_previous_state;
Action r3_previous_action;
bool r3_expired(AClock::time_point start,double limit) {
    return chrono::duration<double,milli>(AClock::now()-start).count()>=limit;
}
State r3_step(const State& s,int us,const Action& own,const Action& opp) {
    return us==0?advance(s,own,opp):advance(s,opp,own);
}
Action r3_redirect(const State& s,int t,Action a,int src,int dst,bool flags) {
    a.moves.erase(remove_if(a.moves.begin(),a.moves.end(),[&](auto m){
        return m.from==src && (m.kind==W || (flags && m.kind==F));
    }),a.moves.end());
    if(src!=dst) for(int k=0;k<2;++k) if((k==W || flags) && s.u[t][k][src])
        a.moves.push_back({k,src,dst,s.u[t][k][src]});
    return a_clean(s,t,a);
}
vector<int> r3_threat_origins(const State& s,int t) {
    vector<pair<double,int>> ranked;
    for(int c=0;c<N;++c) if(s.u[t][W][c]) {
        double threat=0;
        for(int q=0;q<N;++q) if(s.u[1-t][F][q] && board.dist[c][q]<=2)
            threat+=s.u[1-t][F][q]*10.0/(1+board.dist[c][q]);
        for(int b=0;b<board.nb;++b) if(s.owner[b]==1-t && board.dist[c][board.pos[b]]<=2)
            threat+=5.0/(1+board.dist[c][board.pos[b]]);
        if(threat) ranked.push_back({-(threat+sqrt(double(s.u[t][W][c]))),c});
    }
    sort(ranked.begin(),ranked.end()); vector<int> result;
    for(auto item:ranked) result.push_back(item.second);
    return result;
}
Action r3_fixed(const State& s,int t,int model) {
    if(model<4) return a_clean(s,t,policy(s,t,model));
    if(model==4) return a_mix(s,t,policy(s,t,0),policy(s,t,3));
    Action a=policy(s,t,1); auto origins=r3_threat_origins(s,t);
    for(int n=0;n<min(2,int(origins.size()));++n) {
        int src=origins[n],dst=src; double best=-1e100;
        vector<int> next=board.adj[src];next.push_back(src);
        for(int c:next) {
            double value=-1e100;
            for(int q=0;q<N;++q) if(s.u[1-t][F][q])
                value=max(value,20.0*s.u[1-t][F][q]/(1+board.dist[c][q]));
            value-=2*s.u[1-t][W][c];
            if(value>best) {best=value;dst=c;}
        }
        a=r3_redirect(s,t,a,src,dst,false);
    }
    return a_clean(s,t,a);
}
bool r3_response(const State& s,int us,const Action& own,Action& opponent,int groups,
                 AClock::time_point start,double limit) {
    auto origins=r3_threat_origins(s,1-us);
    for(int n=0;n<min(groups,int(origins.size()));++n) {
        if(r3_expired(start,limit)) return false;
        double worst=evaluation(r3_step(s,us,own,opponent),us);
        Action incumbent=opponent;
        vector<int> next=board.adj[origins[n]];next.push_back(origins[n]);
        for(int dst:next) {
            if(r3_expired(start,limit)) return false;
            auto trial=r3_redirect(s,1-us,incumbent,origins[n],dst,groups>1);
            double value=evaluation(r3_step(s,us,own,trial),us);
            if(value<worst) {worst=value;opponent=trial;}
        }
    }
    return !r3_expired(start,limit);
}
void r3_observe(const State& s,int us,AClock::time_point start,double limit) {
    if(R3_MODE!=5) return;
    double next_error[6];copy(r3_error,r3_error+6,next_error);
    if(r3_previous && s.turn==r3_previous_state.turn+1) {
        for(int j=0;j<6;++j) {
            if(r3_expired(start,limit)) return;
            Action opp=r3_fixed(r3_previous_state,1-us,j);
            State predicted=r3_step(r3_previous_state,us,r3_previous_action,opp);
            next_error[j]=.8*r3_error[j]+.2*a_prediction_error(predicted,s,us);
        }
        if(r3_expired(start,limit)) return;
        copy(next_error,next_error+6,r3_error);
    }
    double low=*min_element(r3_error,r3_error+6),sum=0;
    for(int j=0;j<6;++j) {r3_weights[j]=exp(-min(40.0,(r3_error[j]-low)/10));sum+=r3_weights[j];}
    for(double& w:r3_weights) w=.1+.4*w/sum;
}

double r3_aggregate(vector<double> values) {
    double mean=accumulate(values.begin(),values.end(),0.0)/values.size();
    sort(values.begin(),values.end());
    if(R3_MODE==0) return .5*mean+.25*(values[0]+values[1]);
    return .75*mean+.25*values.front();
}

bool a_evaluate(const State& s,int us,const Action& first,int continuation,int horizon,
                const double (&weights)[4],AClock::time_point start,double limit,double& result) {
    if(R3_MODE==2) {
        State trial=s;
        for(int d=0;d<horizon;++d) {
            if(r3_expired(start,limit)) return false;
            Action own=d?policy(trial,us,continuation):first;
            State chosen;double worst=1e100;
            for(int j=0;j<4;++j) {
                if(r3_expired(start,limit)) return false;
                State next=r3_step(trial,us,own,r3_fixed(trial,1-us,j));
                double value=evaluation(next,us);
                if(value<worst) {worst=value;chosen=next;}
            }
            trial=chosen;if(abs(worst)>=80000) break;
        }
        if(r3_expired(start,limit)) return false;
        result=evaluation(trial,us);return true;
    }
    int models=(R3_MODE==1 || R3_MODE==5)?6:4;
    int depth=models==6 || R3_MODE==3 || R3_MODE==4?min(horizon,2):horizon;
    vector<double> values; double weighted=0;
    for(int j=0;j<models;++j) {
        State trial=s;
        for(int d=0;d<depth;++d) {
            if(r3_expired(start,limit)) return false;
            Action own=d?policy(trial,us,continuation):first;
            Action opp=r3_fixed(trial,1-us,j);
            if(d==0 && (R3_MODE==3 || R3_MODE==4) &&
               !r3_response(trial,us,own,opp,R3_MODE==4?2:1,start,limit)) return false;
            trial=r3_step(trial,us,own,opp);
            if(abs(evaluation(trial,us))>=80000) break;
        }
        double value=evaluation(trial,us);values.push_back(value);
        weighted+=R3_MODE==5?r3_weights[j]*value:0;
    }
    if(r3_expired(start,limit)) return false;
    result=R3_MODE==5?.75*weighted+.25*(*min_element(values.begin(),values.end())):r3_aggregate(values);
    return true;
}
'''

TAIL = r'''
int r3_regret_choice(const vector<vector<double>>& a) {
    vector<double> column(a[0].size(),-1e100);
    for(auto& row:a) for(int j=0;j<int(row.size());++j) column[j]=max(column[j],row[j]);
    int best=0;double least=1e100;
    for(int i=0;i<int(a.size());++i) {
        double regret=0;for(int j=0;j<int(column.size());++j) regret=max(regret,column[j]-a[i][j]);
        if(regret<least) {least=regret;best=i;}
    }
    return best;
}
vector<double> r3_mixture(const vector<vector<double>>& a) {
    int n=a.size(),m=a[0].size();vector<double> rr(n),cr(m),average(n);
    double scale=1;for(auto& row:a) for(double x:row) scale=max(scale,abs(x));
    for(int iteration=0;iteration<256;++iteration) {
        vector<double> p(n),q(m),rv(n),cv(m);double rp=0,rq=0;
        for(int i=0;i<n;++i) {p[i]=max(0.0,rr[i]);rp+=p[i];}
        for(int j=0;j<m;++j) {q[j]=max(0.0,cr[j]);rq+=q[j];}
        for(double& x:p) x=rp?x/rp:1.0/n;
        for(double& x:q) x=rq?x/rq:1.0/m;
        double value=0;
        for(int i=0;i<n;++i) for(int j=0;j<m;++j) {
            rv[i]+=q[j]*a[i][j]/scale;cv[j]-=p[i]*a[i][j]/scale;
            value+=p[i]*q[j]*a[i][j]/scale;
        }
        for(int i=0;i<n;++i) {rr[i]+=rv[i]-value;average[i]+=p[i]/256;}
        for(int j=0;j<m;++j) cr[j]+=cv[j]+value;
    }
    return average;
}
Action r3_decide(const State& s,int us,AClock::time_point start) {
    constexpr double limit=135;
    r3_observe(s,us,start,limit);
    if(R3_MODE<6) {
        Action a=a_decide(s,us,start,limit);
        if(R3_MODE==5) {r3_previous=true;r3_previous_state=s;r3_previous_action=a;}
        return a;
    }
    Action baseline=a_decide(s,us,start,65);
    vector<Action> choices{baseline};vector<int> styles{0};
    for(int j=0;j<4;++j) {
        if(r3_expired(start,limit)) return baseline;
        Action a=a_clean(s,us,policy(s,us,j));
        if(none_of(choices.begin(),choices.end(),[&](auto& b){return a_equal(a,b);})) {choices.push_back(a);styles.push_back(j);}
    }
    vector<vector<double>> matrix(choices.size(),vector<double>(6));
    for(int i=0;i<int(choices.size());++i) for(int j=0;j<6;++j) {
        State trial=s;
        for(int d=0;d<min(2,160-s.turn);++d) {
            if(r3_expired(start,limit)) return baseline;
            Action own=d?policy(trial,us,styles[i]):choices[i];
            trial=r3_step(trial,us,own,r3_fixed(trial,1-us,j));
            if(abs(evaluation(trial,us))>=80000) break;
        }
        matrix[i][j]=evaluation(trial,us);
    }
    if(r3_expired(start,limit)) return baseline;
    int selected=r3_regret_choice(matrix);
    if(R3_MODE==7) {
        auto mixture=r3_mixture(matrix);
        if(r3_expired(start,limit)) return baseline;
        selected=discrete_distribution<int>(mixture.begin(),mixture.end())(rng);
    }
    return choices[selected];
}
'''


def _build(source: str, mode: int) -> str:
    if source.count(EVALUATE_START) != 1 or source.count(EVALUATE_END) != 1 or source.count(ENTRY) != 1:
        raise ValueError("expected frozen v3 search anchors")
    begin, end = source.index(EVALUATE_START), source.index(EVALUATE_END)
    helpers = HELPERS.replace("@MODE@", str(mode))
    if mode >= 6:
        helpers = helpers[:helpers.index(EVALUATE_START)] + source[begin:end]
    out = source[:begin] + helpers + "\n" + source[end:]
    anchor = "vector<string> decide(const p::View& v, const p::Init& in) {"
    if out.count(anchor) != 1:
        raise ValueError("expected v3 observation entry")
    return out.replace(anchor, TAIL + "\n" + anchor, 1).replace(ENTRY, "r3_decide(s,us,start);", 1)


def variants(source: str) -> list[dict]:
    specs = [
        ("r3_lower_tail", "downside_risk", 0, "평균과 하위 두 상대 평균을 반씩 반영해 특정 응답에 취약한 행동을 줄인다.", "네 기존 상대 밖의 공략은 여전히 보지 못하며 공격 기회를 과소평가할 수 있다."),
        ("r3_opponent_league", "diverse_opponent_actions", 1, "F/W 혼합 및 깃발 사냥 응답을 추가한 6상대 평가로 행동 다양성을 높인다.", "깊이가 3에서 2로 줄고 고정 여섯 휴리스틱 밖으로 일반화가 보장되지 않는다."),
        ("r3_switching_adversary", "dynamic_script_response", 2, "매 예상 턴에 우리 평가를 가장 낮추는 상대 스크립트로 바꾸어 대응 전환을 검사한다.", "우리 행동에 반응하는 비현실적으로 강한 상대를 가정하며 탐욕적 한 턴 선택이지 전체 최악 경로는 아니다."),
        ("r3_local_counter", "local_adversarial_response", 3, "접촉한 상대 W 출발지 한 곳의 대기와 이동을 탐색해 기존 스크립트의 공략 누락을 찾는다.", "상대가 가까운 W를 가진 경우에만 동작하고 복수 출발지 협공과 먼 접근을 놓친다."),
        ("r3_joint_counter", "joint_adversarial_response", 4, "상대 두 출발지 F/W 공동 이동과 대기를 순서대로 최적화해 교차 공격을 가정한다.", "순차 국소 최소와 전량 이동만 검사하며 더 큰 계산량으로 우리 행동 탐색이 줄 수 있다."),
        ("r3_population_fit", "observed_population_fit", 5, "직전 공개 전이를 잘 설명하는 6상대 모델에 가중하되 각 10%를 남긴다.", "관측 오차에 전투와 숨은 점수 추정 오차가 섞이고 상대 전략 변화에 뒤처질 수 있다."),
        ("r3_minimax_regret", "restricted_matrix_regret", 6, "v3 국소 행동과 네 정책의 완성된 6상대 행렬에서 최대 기회손실이 작은 행동을 고른다.", "최악 절대 승률을 최적화하는 것이 아니고 깊이 2 행렬이 미완성되면 65ms 기준 행동으로 복귀한다."),
        ("r3_mixed_matrix", "restricted_matrix_mixture", 7, "완성된 작은 동시행동 행렬에 256회 regret matching 후 평균 혼합전략을 표본화한다.", "제한된 행렬의 근사 혼합일 뿐 게임 전체 Nash나 exploitability 보장이 없고 표본 분산이 생긴다."),
    ]
    return [{"id": name, "family": family, "parameters": {"mode": mode, "deadline_ms": 135, "base": "v3", "opponent_scope": "internal_only"},
             "hypothesis": hypothesis, "weakness": weakness, "source": _build(source, mode)}
            for name, family, mode, hypothesis, weakness in specs]
