"""Bounded action-space extensions of the frozen iterative-v3 decision rule."""

HELPERS = r'''
constexpr int S3_MODE=@MODE@;
int s3_base_continuation=0;
double s3_base_value=-1e100;

int s3_stock(const State& s,int us,const Action& a,int src,int kind) {
    int n=s.u[us][kind][src];
    for(auto p:a.spawn) if(p.pos==src && p.kind==kind) n+=p.count;
    return n;
}

Action s3_move(const State& s,int us,Action a,int src,int kind,int to,int count) {
    a.moves.erase(remove_if(a.moves.begin(),a.moves.end(),[&](auto m){return m.from==src && m.kind==kind;}),a.moves.end());
    if(to!=src && count>0) a.moves.push_back({kind,src,to,count});
    return a_clean(s,us,a);
}

void s3_add(vector<Action>& out,const Action& trial,const Action& current) {
    if(a_equal(trial,current)) return;
    if(none_of(out.begin(),out.end(),[&](const Action& old){return a_equal(old,trial);})) out.push_back(trial);
}

bool s3_contact(const State& s,int us,int c) {
    if(s.u[1-us][F][c] || s.u[1-us][W][c]) return true;
    for(int q:board.adj[c]) if(s.u[1-us][F][q] || s.u[1-us][W][q]) return true;
    int b=board.at[c];
    return b>=0 && s.u[us][F][c] && (s.owner[b]!=us || s.turn>=154);
}

vector<int> s3_groups(const State& s,int us,bool selective) {
    vector<pair<double,int>> rank;
    for(int c=0;c<N;++c) if(s.u[us][F][c] || s.u[us][W][c]) {
        if(selective && !s3_contact(s,us,c)) continue;
        double importance=8*s.u[us][F][c]+sqrt(double(s.u[us][W][c]))+(board.at[c]>=0?3:0);
        rank.push_back({-importance,c});
    }
    sort(rank.begin(),rank.end());
    vector<int> out;
    for(int i=0;i<min(4,int(rank.size()));++i) out.push_back(rank[i].second);
    return out;
}

vector<Action> s3_choices(const State& s,int us,const Action& current,int src,bool split) {
    vector<Action> out;
    vector<int> targets{src}; targets.insert(targets.end(),board.adj[src].begin(),board.adj[src].end());
    for(int to:targets) for(int mask=1;mask<=3;++mask) {
        Action trial=current;
        for(int kind=0;kind<2;++kind) if(mask&(1<<kind))
            trial=s3_move(s,us,trial,src,kind,to,s3_stock(s,us,current,src,kind));
        s3_add(out,trial,current);
    }
    if(split) for(int kind=0;kind<2;++kind) {
        int stock=s3_stock(s,us,current,src,kind);
        if(stock<2) continue;
        vector<int> counts{1,stock/2,stock-1};
        sort(counts.begin(),counts.end());counts.erase(unique(counts.begin(),counts.end()),counts.end());
        for(int to:board.adj[src]) for(int n:counts)
            s3_add(out,s3_move(s,us,current,src,kind,to,n),current);
        // Two destinations jointly spend one origin's stock; arrivals never fund departures.
        for(int i=0;i<int(board.adj[src].size());++i) for(int j=i+1;j<int(board.adj[src].size());++j) {
            Action trial=s3_move(s,us,current,src,kind,board.adj[src][i],stock/2);
            trial.moves.push_back({kind,src,board.adj[src][j],stock-stock/2});
            s3_add(out,a_clean(s,us,trial),current);
        }
    }
    return out;
}

vector<Action> s3_joint_choices(const State& s,int us,const Action& current,int left,int right) {
    vector<Action> out;
    vector<int> l{left},r{right};
    l.insert(l.end(),board.adj[left].begin(),board.adj[left].end());
    r.insert(r.end(),board.adj[right].begin(),board.adj[right].end());
    for(int x:l) for(int y:r) {
        // Convergence, a swap, and coordinated hold/advance are coupled before evaluation.
        if(x!=y && !(x==right && y==left) && x!=left && y!=right) continue;
        for(int mask=1;mask<=3;++mask) {
            Action trial=current;
            for(auto part:{pair{left,x},pair{right,y}}) for(int kind=0;kind<2;++kind)
                if(mask&(1<<kind)) trial=s3_move(s,us,trial,part.first,kind,part.second,s3_stock(s,us,current,part.first,kind));
            s3_add(out,trial,current);
        }
    }
    return out;
}

bool s3_try(const State& s,int us,const Action& action,int continuation,int depth,const double (&weights)[4],
            AClock::time_point start,double limit,APlan& best,double* score=nullptr) {
    double value;
    if(!a_evaluate(s,us,action,continuation,depth,weights,start,limit,value)) return false;
    if(score) *score=value;
    if(value>best.value) best={action,continuation,value};
    return true;
}

Action s3_decide(const State& s,int us,AClock::time_point start,double limit=135.0) {
    auto groups=s3_groups(s,us,S3_MODE==6);
    if(groups.empty()) return a_decide(s,us,start,limit);
    Action seed=a_decide(s,us,start,min(limit,65.0));
    APlan best{seed,s3_base_continuation,s3_base_value};
    double weights[4];a_observe(s,us,weights);
    int depth=min(3,160-s.turn);
    if(S3_MODE==3) {
        for(int i=0;i<int(groups.size());++i) for(int j=i+1;j<int(groups.size());++j) {
            if(board.dist[groups[i]][groups[j]]>2) continue;
            Action anchor=best.action;
            for(const Action& trial:s3_joint_choices(s,us,anchor,groups[i],groups[j]))
                if(!s3_try(s,us,trial,best.continuation,depth,weights,start,limit,best)) return best.action;
        }
    } else if(S3_MODE==4) {
        vector<APlan> beam{best};
        for(int src:groups) {
            vector<APlan> next=beam;
            for(const APlan& parent:beam) for(const Action& trial:s3_choices(s,us,parent.action,src,false)) {
                double value;
                if(!s3_try(s,us,trial,parent.continuation,depth,weights,start,limit,best,&value)) return best.action;
                if(none_of(next.begin(),next.end(),[&](const APlan& old){return a_equal(old.action,trial);}))
                    next.push_back({trial,parent.continuation,value});
            }
            stable_sort(next.begin(),next.end(),[](const APlan& a,const APlan& b){return a.value>b.value;});
            if(next.size()>3) next.resize(3);
            beam=move(next);
        }
    } else if(S3_MODE==5) {
        vector<APlan> shortlist;
        bool exhausted=false;
        for(int src:groups) {
            for(const Action& trial:s3_choices(s,us,seed,src,true)) {
                double value;
                if(!a_evaluate(s,us,trial,best.continuation,1,weights,start,min(limit,100.0),value)) {exhausted=true;break;}
                shortlist.push_back({trial,best.continuation,value});
            }
            if(exhausted) break;
        }
        stable_sort(shortlist.begin(),shortlist.end(),[](const APlan& a,const APlan& b){return a.value>b.value;});
        // Shallow scores never compete with the fully evaluated incumbent.
        for(int i=0;i<min(8,int(shortlist.size()));++i)
            if(!s3_try(s,us,shortlist[i].action,shortlist[i].continuation,depth,weights,start,limit,best)) break;
    } else {
        for(int pass=0;pass<(S3_MODE==7?2:1);++pass) {
            bool improved=false;
            if(pass) reverse(groups.begin(),groups.end());
            for(int src:groups) {
                Action anchor=best.action;
                double before=best.value;
                for(const Action& trial:s3_choices(s,us,anchor,src,S3_MODE==2 || S3_MODE==7))
                    if(!s3_try(s,us,trial,best.continuation,depth,weights,start,limit,best)) return best.action;
                improved|=best.value>before;
            }
            if(!improved) break;
        }
    }
    return best.action;
}
'''


def _replace(source: str, old: str, new: str) -> str:
    if source.count(old) != 1:
        raise ValueError('Frozen v3 anchor changed: ' + old[:80])
    return source.replace(old, new, 1)


def _build(source: str, mode: int) -> str:
    _replace(source, 'constexpr int A_MIX=0, A_LOCAL=1, A_MEMORY=0;',
             'constexpr int A_MIX=0, A_LOCAL=1, A_MEMORY=0;')
    helper = HELPERS.replace('@MODE@', str(mode))
    before, after = helper.split('Action s3_decide(', 1)
    source = _replace(source, 'Action a_decide(', before + '\nAction a_decide(')
    source = _replace(source, '    return incumbent.action;\n}',
                      '    s3_base_continuation=incumbent.continuation;s3_base_value=incumbent.value;\n    return incumbent.action;\n}')
    source = _replace(source, 'vector<string> decide(const p::View& v, const p::Init& in) {',
                      'Action s3_decide(' + after + '\nvector<string> decide(const p::View& v, const p::Init& in) {')
    return _replace(source, 'Action a=forced_policy>=0?policy(s,us,forced_policy):a_decide(s,us,start);',
                    'Action a=forced_policy>=0?policy(s,us,forced_policy):s3_decide(s,us,start);')


def variants(source: str) -> list[dict]:
    specs = [
        ('s3_role_wait', 'independent_role_moves', 1,
         'v3의 F/W 동시 전량 이동 밖에 있는 한 종류만 이동·잔류하는 행동을 평가한다.',
         '추가 후보가 틀린 rollout 평가를 더 많이 활용할 수 있다. v3의 기본 탐색 시간을 65ms로 나눈다.'),
        ('s3_split_reserve', 'partial_force_allocation', 2,
         '1개·절반·1개 잔류 및 두 목적지 분할로 전량 이동과 전량 대기 사이의 행동을 연다.',
         '분할 수는 근사 후보이며 모든 병력 수 조합을 탐색하지 않는다. 적 합류를 과소평가하면 각개격파된다.'),
        ('s3_joint_origins', 'coupled_origin_search', 3,
         '가까운 두 출발지를 함께 바꿔 단독 수정으로는 이득이 없는 합류·호위·교대를 비교한다.',
         '상위 4개 출발지와 제한된 공동 이동 형식만 탐색하며 서로 다른 F/W 교차 역할을 모두 열지는 않는다.'),
        ('s3_beam_actions', 'action_assignment_beam', 4,
         '출발지별 최선 하나 대신 완전히 평가된 상위 3개 행동을 유지해 뒤쪽 공동 수정의 기회를 남긴다.',
         '폭 3에서 탈락한 전제 행동은 복구하지 못하고 계산 예산 때문에 후반 출발지는 못 볼 수 있다.'),
        ('s3_screen_refine', 'successive_action_refinement', 5,
         '넓은 행동 후보를 1턴으로 선별하고 상위 8개만 기존 3턴 평가로 확인한다.',
         '즉각 손해를 감수하는 장기 행동은 얕은 선별에서 탈락한다. 1턴 점수는 기존 최선과 직접 비교하지 않는다.'),
        ('s3_selective_contact', 'state_conditioned_abstraction', 6,
         '적 접촉·미점령 건물·종반 점령에 관련된 출발지에서만 F/W 독립 행동을 연다.',
         '접촉하지 않은 전략적 이동의 세밀한 개선은 제외된다. 선택 기준은 학습된 최적 기준이 아니다.'),
        ('s3_revisit_search', 'revisited_coordinate_search', 7,
         '분할과 독립 이동으로 뒤쪽 출발지가 바뀐 후 앞쪽 출발지를 역순으로 재평가한다.',
         '최대 2회 국소 탐색이며 지역 최적이나 잘못된 상대 모델을 탈출한다고 보장하지 않는다.'),
    ]
    return [{'id': name, 'family': family, 'parameters': {'mode': mode, 'base_ms': 65, 'total_ms': 135},
             'hypothesis': hypothesis, 'weakness': weakness, 'source': _build(source, mode)}
            for name, family, mode, hypothesis, weakness in specs]
