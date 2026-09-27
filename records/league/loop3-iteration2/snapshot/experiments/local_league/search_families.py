"""Generate bounded search alternatives from the frozen v2 source."""

SEARCH_START = "    constexpr int P=4;\n"
SEARCH_END = "    const auto& a=candidates[chosen];\n"

SELECTOR = r"""
int league_select(const double (&payoff)[4][4], int mode) {
    constexpr int P=4;
    if (mode != 0) {
        int chosen=0;
        double best=-1e100;
        for (int i=0;i<P;++i) {
            double row[P]; copy(payoff[i],payoff[i]+P,row); sort(row,row+P);
            double mean=accumulate(row,row+P,0.0)/P;
            double score=mode==1?row[0]:mode==2?mean:mode==3?.5*(mean+row[0]):.5*(row[0]+row[1]);
            if (score>best) {best=score;chosen=i;}
        }
        return chosen;
    }
    double rr[P]{}, rc[P]{}, avg[P]{};
    for (int it=0;it<600;++it) {
        double x[P]{},y[P]{},sx=0,sy=0;
        for (int i=0;i<P;++i) {x[i]=max(0.0,rr[i]);y[i]=max(0.0,rc[i]);sx+=x[i];sy+=y[i];}
        for (int i=0;i<P;++i) {x[i]=sx?x[i]/sx:1.0/P;y[i]=sy?y[i]/sy:1.0/P;avg[i]+=x[i];}
        double rv[P]{},cv[P]{},value=0;
        for (int i=0;i<P;++i) for (int j=0;j<P;++j) {rv[i]+=payoff[i][j]*y[j];cv[j]+=payoff[i][j]*x[i];value+=x[i]*y[j]*payoff[i][j];}
        for (int i=0;i<P;++i) {rr[i]+=rv[i]-value;rc[i]+=value-cv[i];}
    }
    return discrete_distribution<int>(avg,avg+P)(rng);
}
"""

HOLD_HELPER = r"""
Action league_hold(const State& s, int t, Action a) {
    bool hold[N]{};
    for (int b=0;b<board.nb;++b) if (s.owner[b]==t) {
        int c=board.pos[b];
        for (int q=0;q<N;++q) if (s.u[1-t][F][q] && board.dist[q][c]<=1) hold[c]=true;
    }
    a.moves.erase(remove_if(a.moves.begin(),a.moves.end(),[&](const Movement& m) {
        return m.kind==W && hold[m.from];
    }),a.moves.end());
    return a;
}
"""


def replace_once(source: str, old: str, new: str) -> str:
    count = source.count(old)
    if count != 1:
        raise ValueError(f"Expected one source anchor; found {count}: {old[:72]!r}")
    return source.replace(old, new, 1)


def _search(source: str, *, mode: int, depth: int, switch: bool = False,
            hold: bool = False, assignment: bool = False) -> str:
    if source.count(SEARCH_START) != 1 or source.count(SEARCH_END) != 1:
        raise ValueError("v2 decision block anchors changed")
    start = source.index(SEARCH_START)
    end = source.index(SEARCH_END)
    if end <= start or "double rr[P]{}" not in source[start:end]:
        raise ValueError("v2 decision block has unexpected contents")
    if assignment:
        block = "    Action candidates[4];\n    int chosen=forced_policy<0?3:forced_policy;\n    candidates[chosen]=policy(s,us,chosen);\n"
    else:
        continuation = "d>=2?0:i" if switch else "i"
        own_initial = "i==3?league_hold(s,us,policy(s,us,0)):policy(s,us,i)" if hold else "policy(s,us,i)"
        own_later = "i==3?league_hold(trial,us,policy(trial,us,0)):policy(trial,us,i)" if hold else f"policy(trial,us,{continuation})"
        block = f"""    constexpr int P=4;
    Action candidates[P];
    for (int i=0;i<P;++i) candidates[i]={own_initial};
    int chosen=forced_policy;
    if (chosen<0) {{
        double payoff[P][P]{{}};
        bool complete=true;
        int horizon=min({depth},160-s.turn);
        for (int i=0;i<P && complete;++i) for (int j=0;j<P;++j) {{
            State trial=s;
            for (int d=0;d<horizon;++d) {{
                Action own=d==0?candidates[i]:({own_later}),opp=policy(trial,1-us,j);
                trial=us==0?advance(trial,own,opp):advance(trial,opp,own);
                double e=evaluation(trial,us);
                if (abs(e)>=80000) break;
                if (chrono::duration<double,milli>(chrono::steady_clock::now()-start).count()>160) {{complete=false;break;}}
            }}
            payoff[i][j]=evaluation(trial,us)/200.0;
            if (!complete) break;
        }}
        chosen=complete?league_select(payoff,{mode}):0;
    }}
"""
    out = source[:start] + block + source[end:]
    if not assignment:
        out = replace_once(out, "mt19937 rng(20260927);\n", "mt19937 rng(20260927);\n" + SELECTOR)
    if hold:
        out = replace_once(out, "int forced_policy = -1;\n", HOLD_HELPER + "\nint forced_policy = -1;\n")
    return out


def variants(source: str) -> list[dict]:
    specs = [
        ("s_maximin_d4", "robust_selection", {"mode": 1, "depth": 4},
         "내부 상대 4개 중 최악의 결과를 개선한다.", "상대 후보 밖의 공략에는 보장이 없고 공격 기회를 놓칠 수 있다."),
        ("s_mean_d4", "uniform_opponent", {"mode": 2, "depth": 4},
         "모든 상대를 같은 확률로 보고 평균 이득을 높인다.", "평균이 좋아도 특정 상대에게 크게 질 수 있다."),
        ("s_mean_min_d4", "risk_blend", {"mode": 3, "depth": 4},
         "평균과 최악값을 절반씩 반영해 안전과 기회를 절충한다.", "절반이라는 비율은 미검증이며 최악 상대가 비현실적일 수 있다."),
        ("s_tail2_d4", "lower_tail", {"mode": 4, "depth": 4},
         "하위 2개 결과의 평균으로 극단적인 한 상대의 과도한 영향을 줄인다.", "4개 동등가중 가상 상대의 하위 평균이며 실제 손실분포 추정은 아니다."),
        ("s_regret_d2", "short_horizon", {"mode": 0, "depth": 2},
         "짧은 예측으로 상대 모델 오류의 누적과 계산량을 줄인다.", "중립화 뒤 재점령과 먼 경제 투자 효과를 놓칠 수 있다."),
        ("s_regret_d6", "long_horizon", {"mode": 0, "depth": 6},
         "6턴 예측이 경제 거점 진입과 재점령의 결과를 더 잘 반영한다.", "계산량과 모델 오류가 늘고 160ms 초과 시 정책0으로 돌아간다."),
        ("s_switch_guard_d4", "sparse_role_plan", {"mode": 0, "depth": 4, "switch": True},
         "후보 정책을 2턴 수행하고 수비 정책0으로 전환하는 계획을 평가한다.", "매 턴 다시 계획하며 지속 임무 예약이나 진화적 RHEA는 구현하지 않았다."),
        ("s_assignment_only", "assignment_ablation", {"mode": 0, "depth": 0, "assignment": True},
         "팀원에서 유래한 거리 기반 임무 배정만 실행해 탐색의 순기여를 확인한다.", "전체 행동 상호작용과 상대 반응을 비교하는 탐색이 없다."),
        ("s_maximin_d1", "immediate_robust", {"mode": 1, "depth": 1},
         "동시 명령의 다음 한 턴 피해에 집중한다.", "두 턴이 필요한 적 건물 점령을 과소평가할 수 있다."),
        ("s_local_hold_d3", "partial_tactical_portfolio", {"mode": 1, "depth": 3, "hold": True},
         "적 F가 인접한 아군 건물에서 W 출발을 취소하는 후보를 원래 정책과 비교한다.", "할당 정책 슬롯을 대체하며 과잉 주둔할 수 있다. 완전한 PGS나 최적 병력 배정은 아니다."),
    ]
    return [{"id": name, "family": family, "parameters": params,
             "hypothesis": hypothesis, "weakness": weakness,
             "source": _search(source, **params)}
            for name, family, params, hypothesis, weakness in specs]
