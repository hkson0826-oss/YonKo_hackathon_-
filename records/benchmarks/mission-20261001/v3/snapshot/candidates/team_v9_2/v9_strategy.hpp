// v9_2: outcome-aware terminal planning. Uses only observed/mirrored scores.
enum class V9Mode { Early, Lock, Chase, Uncertain };
pair<double,double> v9_score_bounds(const State& s,int us) {
    double lo=0,hi=0;
    for(int b=0;b<board.nb;++b) if(s.owner[b]>=0) {
        int mirror=board.at[224-board.pos[b]];
        bool known=s.revealed[us][b] || (mirror>=0 && s.revealed[us][mirror]) || board.type[b]==PLAZA;
        double a=known?s.score[b]:1, z=known?s.score[b]:4;
        if(s.owner[b]==us) {lo+=a;hi+=z;} else {lo-=z;hi-=a;}
    }
    return {lo,hi};
}
V9Mode v9_mode(const State& s,int us) {
    if(s.turn+1<140) return V9Mode::Early;
    auto [lo,hi]=v9_score_bounds(s,us);
    if(lo>=1) return V9Mode::Lock;
    if(hi<0) return V9Mode::Chase;
    return V9Mode::Uncertain;
}

Action v9_plan(const State& s,int us,Action base) {
    const int enemy=1-us, left=160-s.turn;
    V9Mode mode=v9_mode(s,us);
    bool late=mode!=V9Mode::Early, lock=mode==V9Mode::Lock, chase=mode==V9Mode::Chase;
    Action a=late?Action{}:a_clean(s,us,base);
    int stock[2][N]{}, used[2][N]{}, arrived[N]{};
    for(int k=0;k<2;++k) copy(s.u[us][k],s.u[us][k]+N,stock[k]);
    vector<int> sites{board.base[us]}, enemy_stations;
    for(int b=0;b<board.nb;++b) {
        if(s.owner[b]==enemy && board.type[b]==STATION) enemy_stations.push_back(board.pos[b]);
        if(s.owner[b]==us && board.type[b]==HOSPITAL) sites.push_back(board.pos[b]);
    }
    auto enemy_eta=[&](int c,int p) {
        return max(1,v9_distance(s,enemy,c,p));
    };
    struct Threat {int b,eta,need;};
    vector<Threat> threats;
    if(!chase) for(int b=0;b<board.nb;++b) if(s.owner[b]==us) {
        if(!late && board.type[b]!=HALL && board.type[b]!=ENG) continue;
        int p=board.pos[b],eta=INF;
        for(int c=0;c<N;++c) if(s.u[enemy][F][c]) {
            int d=enemy_eta(c,p);eta=min(eta,d);
            if(d<=min(left,late?left:6))
                v9_report_flag_scenario(c,s.u[enemy][F][c],b,d);
        }
        if(eta>min(left,late?left:6)) continue;
        int escort=0,remote=0;
        // Reserve against local escorts, not every army that could eventually cross the map.
        for(int c=0;c<N;++c) if(s.u[enemy][W][c] && enemy_eta(c,p)<=eta) {
            bool nearby=board.dist[c][p]<=min(eta,3);
            for(int f=0;f<N && !nearby;++f) if(s.u[enemy][F][f] &&
                board.dist[c][f]<=1 && enemy_eta(f,p)<=eta) nearby=true;
            if(!nearby) continue;
            if(board.dist[c][p]<=eta) escort+=s.u[enemy][W][c];
            else {
                int capacity=0;
                for(int x:enemy_stations) for(int y:enemy_stations) if(x!=y) {
                    int waves=eta-board.dist[c][x]-board.dist[y][p];
                    capacity=max(capacity,5*max(0,waves));
                }
                remote+=min(s.u[enemy][W][c],capacity);
            }
        }
        // Each observed W is counted once; all teleported W share at most 5 slots per turn.
        escort+=min(remote,5*eta);
        threats.push_back({b,eta,escort+1});
    }
    stable_sort(threats.begin(),threats.end(),[&](auto x,auto y) {
        return s.score[x.b]/(x.eta+1.0)>s.score[y.b]/(y.eta+1.0);
    });
    int budget=s.res[us];
    if(!late) for(auto p:a.spawn) {budget-=p.count*cost(s,us,p.kind);if(p.kind<2) stock[p.kind][p.pos]+=p.count;}
    auto buy=[&](int kind,int site,int n) {
        n=min(n,max(0,budget)/cost(s,us,kind));
        if(n>0) {
            a.spawn.push_back({kind,site,n});stock[kind][site]+=n;budget-=n*cost(s,us,kind);
            v9_report_note({kind,site,site,n},kind==F?"replacement_flag_production":"warrior_production",-1,-1,-1,true);
        }
        return n;
    };
    // Keep resources needed after income for simultaneous captures/neutralizations.
    if(late) {
        int capture_budget=0;
        for(int b=0;b<board.nb;++b) if(s.owner[b]!=us) {
            int p=board.pos[b];bool close=stock[F][p]>0;
            for(int q:board.adj[p]) close|=stock[F][q]>0;
            if(close) capture_budget+=max(1,(board.type[b]==PLAZA?4:2)-int(has(s,us,LIBRARY)));
        }
        budget=max(0,budget-max(0,capture_budget-income(s,us)));
        int nf=accumulate(stock[F],stock[F]+N,0);
        // Buy replacement F only when a spawn site can reach an actual mission in time.
        int desired=lock?min(6,max(2,int(threats.size()))):6;
        for(int i=nf;i<desired && budget>=5;++i) {
            int best=-1;double value=-1;
            for(int site:sites) for(int b=0;b<board.nb;++b) {
                bool mission=lock?false:s.owner[b]!=us;
                if(lock) for(auto t:threats) if(t.b==b) mission=true;
                int d=v9_distance(s,us,site,board.pos[b]);
                if(lock) {
                    d=INF;for(int q:board.adj[board.pos[b]]) d=min(d,v9_distance(s,us,site,q)+1);
                }
                if(!mission || max(1,d)+(s.owner[b]==enemy?1:0)>left) continue;
                double v=s.score[b]/(d+2.0);
                if(v>value) {value=v;best=site;}
            }
            if(best<0) break;
            buy(F,best,1);
        }
        int site=sites.front();double best=-1;
        for(int c:sites) for(int b=0;b<board.nb;++b) {
            if(lock && s.owner[b]!=us) continue;
            if(chase && s.owner[b]==us) continue;
            double v=s.score[b]/(v9_distance(s,us,c,board.pos[b])+2.0);
            if(v>best) {best=v;site=c;}
        }
        buy(W,site,budget/cost(s,us,W));
    }
    vector<Movement> reserved;
    bool tele_used=false;
    bool tele_booked[161]{};
    using Route=V9Travel;
    auto route=[&](int c,int p,int count=1) {
        return v9_travel(s,us,c,p,count,!tele_used,tele_booked);
    };
    auto book_route=[&](Route r,int count) {
        if(!r.first_slot) return;
        int slot=r.first_slot;
        for(int wave=0;wave<(count+4)/5;++wave) {
            while(slot<=160 && tele_booked[slot]) ++slot;
            if(slot<=160) tele_booked[slot++]=true;
        }
    };
    auto send=[&](int kind,int c,Route r,int n,const char* reason="planned_route",int target=-1,int need=-1,int eta=-1) {
        n=min(n,stock[kind][c]-used[kind][c]);
        if(r.tele) {n=min(n,5);tele_used=true;}
        book_route(r,n);
        used[kind][c]+=n;
        if(n) v9_report_note({kind,c,r.to,n,r.tele},reason,target,need,eta);
        if(c!=r.to && n) reserved.push_back({kind,c,r.to,n,r.tele});
        if(kind==W && n) arrived[r.to]+=n;
        return n;
    };
    for(auto t:threats) {
        int p=board.pos[t.b],missing=t.need;
        // Protect donors' own threatened buildings before exporting their garrison.
        vector<pair<int,int>> donors;
        for(int c=0;c<N;++c) if(stock[W][c]>used[W][c]) {
            auto r=route(c,p);if(r.eta<=t.eta) donors.push_back({r.eta,c});
        }
        sort(donors.begin(),donors.end());
        auto spare=[&](int c) {
            int keep=0;
            if(c!=p) for(auto other:threats) if(board.pos[other.b]==c) keep=max(keep,other.need);
            return max(0,stock[W][c]-used[W][c]-keep);
        };
        bool saved_tele=tele_used;
        bool saved_booked[161];copy(tele_booked,tele_booked+161,saved_booked);
        vector<pair<int,int>> plan;
        for(auto [d,c]:donors) {
            if(!missing) break;
            int n=min(missing,spare(c));
            if(route(c,p).tele) n=min(n,5);
            auto r=route(c,p,n);if(r.eta>t.eta) continue;
            if(r.tele) {
                // At the arrival turn, wait waves do not put more than 5 at the exit now.
                n=min(n,5);r=route(c,p,n);
            }
            if(!n) continue;
            plan.push_back({c,n});missing-=n;book_route(r,n);if(r.tele) tele_used=true;
        }
        tele_used=saved_tele;
        copy(saved_booked,saved_booked+161,tele_booked);
        if(missing) {
            v9_report_event("defense_skipped_insufficient_arrivals",t.b,t.need,t.eta,t.need-missing);
            continue;
        }
        v9_report_event("defense_committed",t.b,t.need,t.eta,t.need);
        for(auto [c,n]:plan) send(W,c,route(c,p,n),n,"defense_deadline_reservation",t.b,t.need,t.eta);
    }
    if(late) {
        int assigned[BMAX]{};
        for(int c=0;c<N;++c) while(stock[F][c]>used[F][c]) {
            int target=-1;double best=-1e100;
            struct Candidate {int b;double value;bool escorted;};
            vector<Candidate> candidates;
            for(int b=0;b<board.nb;++b) {
                int p=board.pos[b];auto r=route(c,p);
                if(lock) {
                    if(s.owner[b]!=us || assigned[b]) continue;
                    int danger=0;for(auto t:threats) if(t.b==b) danger=t.need;
                    double v=(danger?s.score[b]*3:s.score[b])/(r.eta+2.0);
                    if(v>best) {best=v;target=b;}
                } else {
                    if(s.owner[b]==us || assigned[b] || max(1,r.eta)>left) continue;
                    int defenders=s.u[enemy][W][p];
                    for(int q:board.adj[p]) defenders+=s.u[enemy][W][q];
                    double swing=s.score[b]*(s.owner[b]==enemy && r.eta+1<=left?2:1);
                    double v=swing/(r.eta+1.0)-.15*defenders;
                    // Check escorts with the F's own transit slot reserved; do not count one
                    // future TELE for several donors when forming the random candidate pool.
                    bool prior_tele=tele_used,prior_booked[161];
                    copy(tele_booked,tele_booked+161,prior_booked);
                    book_route(r,1);if(r.tele)tele_used=true;
                    int missing=max(0,defenders+1-arrived[p]);
                    vector<pair<int,int>> donors;
                    for(int q=0;q<N;++q) if(stock[W][q]>used[W][q]) donors.push_back({route(q,p).eta,q});
                    sort(donors.begin(),donors.end());
                    for(auto [d,q]:donors) {
                        if(!missing)break;
                        int n=min(missing,stock[W][q]-used[W][q]);
                        if(route(q,p).tele)n=min(n,5);
                        auto wr=route(q,p,n);if(wr.eta>max(1,r.eta))continue;
                        missing-=n;book_route(wr,n);if(wr.tele)tele_used=true;
                    }
                    tele_used=prior_tele;copy(prior_booked,prior_booked+161,tele_booked);
                    candidates.push_back({b,v,missing==0});
                    if(v>best) {best=v;target=b;}
                }
            }
            if(!lock && !candidates.empty()) {
                bool safe=any_of(candidates.begin(),candidates.end(),[](auto x){return x.escorted;});
                double baseline=-1e100;
                for(auto x:candidates) if(!safe || x.escorted) baseline=max(baseline,x.value);
                double band=max(.15,abs(baseline)*.15),temperature=max(.05,band/2);
                vector<Candidate> near;vector<double> weights;
                for(auto x:candidates) if((!safe || x.escorted) && x.value>=baseline-band) {
                    near.push_back(x);weights.push_back(exp((x.value-baseline)/temperature));
                }
                if(!near.empty()) {
                    auto chosen=near[discrete_distribution<int>(weights.begin(),weights.end())(v9_attack_rng)];
                    target=chosen.b;
                    v9_report_random_choice(c,target,chosen.value,baseline,int(near.size()));
                }
            }
            if(target<0) {used[F][c]=stock[F][c];break;}
            int p=board.pos[target];
            if(lock) {
                // Recapture flags wait beside the building; avoid flag-pull exposure.
                int safe=-1,d=INF;
                for(int q:board.adj[p]) {
                    int danger=s.u[enemy][W][q];for(int v:board.adj[q]) danger+=s.u[enemy][W][v];
                    if(!danger && route(c,q).eta<d) {safe=q;d=route(c,q).eta;}
                }
                if(safe>=0) p=safe;
                else {used[F][c]++;++assigned[target];continue;}
            }
            auto fr=route(c,p);
            if(!lock) {
                int need=s.u[enemy][W][p]+1;
                for(int q:board.adj[p]) need+=s.u[enemy][W][q];
                int missing=max(0,need-arrived[p]);
                vector<pair<int,int>> escorts;
                for(int q=0;q<N;++q) if(stock[W][q]>used[W][q] && route(q,p).eta<=max(1,fr.eta))
                    escorts.push_back({route(q,p).eta,q});
                sort(escorts.begin(),escorts.end());
                for(auto [eta,q]:escorts) {
                    if(!missing) break;
                    auto wr=route(q,p);if(wr.eta>max(1,fr.eta)) continue;
                    int n=min(missing,stock[W][q]-used[W][q]);
                    if(wr.tele)n=min(n,5);
                    wr=route(q,p,n);if(wr.eta>max(1,fr.eta))continue;
                    missing-=send(W,q,wr,n,"flag_mission_escort",target,need,max(1,fr.eta));
                }
                // A preceding W teleport may consume the F's planned teleport.
                fr=route(c,p);
                if(fr.eta>left) {used[F][c]=stock[F][c];break;}
            }
            // At a safe launch cell, time vulnerable neutralizations for the final turn.
            // Secure captures are taken immediately; never wait in enemy W contact.
            if(chase && s.owner[target]==enemy && left<=4 && fr.eta<left &&
               !s.u[enemy][W][c] && arrived[p]<=s.u[enemy][W][p]) {
                bool contact=false;
                for(int q:board.adj[c]) contact|=s.u[enemy][W][q]>0;
                if(!contact) fr={0,c,false};
            }
            if(lock && fr.to!=c) {
                int danger=s.u[enemy][W][fr.to];
                for(int q:board.adj[fr.to]) danger+=s.u[enemy][W][q];
                if(danger>=max(1,arrived[fr.to])) fr={0,c,false};
            }
            send(F,c,fr,1,lock?"recapture_flag_position":(fr.to==c && p!=c)?"timed_neutralization_wait":"randomized_offensive_flag_mission",target,-1,fr.eta);++assigned[target];
            a.priority.push_back(target);
        }
        // Remaining W defend in lock mode; in chase mode escort offensive F missions.
        for(int c=0;c<N;++c) while(stock[W][c]>used[W][c]) {
            int target=-1;double best=-1e100;
            for(int b=0;b<board.nb;++b) {
                int p=board.pos[b];
                if(lock && s.owner[b]!=us) continue;
                if(!lock && s.owner[b]==us) continue;
                int n=stock[W][c]-used[W][c];
                if(route(c,p).tele)n=min(n,5);
                auto r=route(c,p,n);if(r.eta>left) continue;
                int need=s.u[enemy][W][p]+1;
                for(int q:board.adj[p]) need+=s.u[enemy][W][q];
                for(auto t:threats) if(t.b==b) need=max(need,t.need);
                double v=s.score[b]*(lock?1:(assigned[b]?3:1))/(r.eta+2.0);
                v*=double(need)/(need+arrived[p]);
                if(v>best) {best=v;target=b;}
            }
            if(target<0) break;
            int p=board.pos[target],n=stock[W][c]-used[W][c];
            if(route(c,p).tele)n=min(n,5);
            auto r=route(c,p,n);
            send(W,c,r,n,lock?"remaining_defense_distribution":"remaining_attack_support",target,-1,r.eta);
        }
        a.moves=reserved;
    } else {
        // Override only reserved early economic defense, preserving other v8 orders.
        int available[2][N];
        for(int k=0;k<2;++k) for(int c=0;c<N;++c) available[k][c]=stock[k][c]-used[k][c];
        vector<Movement> rest;
        for(auto m:a.moves) {
            if(tele_used && m.tele) continue;
            if(m.kind<2) {m.count=min(m.count,available[m.kind][m.from]);available[m.kind][m.from]-=m.count;}
            if(m.count>0) rest.push_back(m);
        }
        a.moves=reserved;a.moves.insert(a.moves.end(),rest.begin(),rest.end());
    }
    return a_clean(s,us,a);
}
