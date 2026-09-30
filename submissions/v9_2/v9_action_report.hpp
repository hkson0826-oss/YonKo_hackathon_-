// Optional execution-time telemetry. Does not participate in policy selection.
#include <fstream>
ofstream v9_report_file;
ostream* v9_report_stream=nullptr;
struct V9ReportNote {Movement movement;const char* reason;int target,need,eta;bool spawn;};
vector<V9ReportNote> v9_report_notes;
struct V9ReportEvent {const char* reason;int target,need,eta,available;};
vector<V9ReportEvent> v9_report_events;
struct V9FlagScenario {int cell,count,target,eta;};
vector<V9FlagScenario> v9_flag_scenarios;
struct V9RandomChoice {int cell,target,candidates;double chosen,best;};
vector<V9RandomChoice> v9_random_choices;
void v9_report_flag_scenario(int cell,int count,int target,int eta) {
    if(v9_report_stream) v9_flag_scenarios.push_back({cell,count,target,eta});
}
void v9_report_random_choice(int cell,int target,double chosen,double best,int candidates) {
    if(v9_report_stream) v9_random_choices.push_back({cell,target,candidates,chosen,best});
}
void v9_report_event(const char* reason,int target,int need,int eta,int available) {
    if(v9_report_stream) v9_report_events.push_back({reason,target,need,eta,available});
}
void v9_report_note(Movement m,const char* reason,int target=-1,int need=-1,int eta=-1,bool spawn=false) {
    if(v9_report_stream) v9_report_notes.push_back({m,reason,target,need,eta,spawn});
}
string v9_json_string(const string& s) {
    string out="\"";
    for(unsigned char c:s) {
        if(c=='"' || c=='\\') {out+='\\';out+=c;}
        else if(c=='\n') out+="\\n";
        else if(c=='\r') out+="\\r";
        else if(c=='\t') out+="\\t";
        else if(c>=32) out+=c;
    }
    return out+'"';
}
void v9_write_report(const State& s,int us,const Action& a,const p::Init& in,double ms,
                     const char* mode,double margin,double lower) {
    if(!v9_report_stream) return;
    ostringstream o;
    o<<"{\"version\":\"v9_2\",\"turn\":"<<s.turn+1<<",\"team\":"<<v9_json_string(in.team)
     <<",\"mode\":"<<v9_json_string(mode)
     <<",\"estimated_margin\":"<<margin<<",\"lower_margin\":"<<lower
     <<",\"decision_ms\":"<<ms<<",\"resource\":"<<s.res[us]
     <<",\"attack_seed\":"<<v9_attack_seed<<",\"enemy_shared_spawn_budget_W\":"<<s.res[1-us]/cost(s,1-us,W)
     <<",\"guard_adds_hypothetical_production\":false,\"terrain\":[";
    for(int i=0;i<int(in.terrain.size());++i) {if(i)o<<',';o<<v9_json_string(in.terrain[i]);}
    o<<"],\"buildings\":[";
    for(int b=0;b<board.nb;++b) {
        if(b)o<<',';
        o<<"{\"id\":"<<board.id[b]<<",\"x\":"<<board.pos[b]%15<<",\"y\":"<<board.pos[b]/15
         <<",\"type\":"<<v9_json_string(types[board.type[b]])<<",\"owner\":"<<s.owner[b]
         <<",\"estimated_score\":"<<s.score[b]<<",\"score_known\":"<<
           (s.revealed[us][b] || board.type[b]==PLAZA ||
            (board.at[224-board.pos[b]]>=0 && s.revealed[us][board.at[224-board.pos[b]]])?"true":"false")<<'}';
    }
    o<<"],\"units\":[";bool comma=false;
    for(int team=0;team<2;++team) for(int kind=0;kind<3;++kind) for(int c=0;c<N;++c) if(s.u[team][kind][c]) {
        if(comma)o<<',';
        comma=true;
        o<<"{\"team\":"<<team<<",\"kind\":"<<v9_json_string(string(1,kinds[kind]))
         <<",\"x\":"<<c%15<<",\"y\":"<<c/15<<",\"count\":"<<s.u[team][kind][c]<<'}';
    }
    o<<"],\"enemy_flag_alternatives\":[";
    for(int i=0;i<int(v9_flag_scenarios.size());++i) {
        if(i)o<<',';
        const auto& f=v9_flag_scenarios[i];
        o<<"{\"source\":["<<f.cell%15<<','<<f.cell/15<<"],\"count\":"<<f.count
         <<",\"target_id\":"<<board.id[f.target]<<",\"eta\":"<<f.eta
         <<",\"simultaneous_targets_limit\":"<<f.count<<'}';
    }
    o<<"],\"attack_choices\":[";
    for(int i=0;i<int(v9_random_choices.size());++i) {
        if(i)o<<',';
        const auto& c=v9_random_choices[i];
        o<<"{\"source\":["<<c.cell%15<<','<<c.cell/15<<"],\"target_id\":"<<board.id[c.target]
         <<",\"near_best_candidates\":"<<c.candidates<<",\"chosen_value\":"<<c.chosen<<",\"best_value\":"<<c.best<<'}';
    }
    o<<"],\"decisions\":[";
    for(int i=0;i<int(v9_report_events.size());++i) {
        if(i)o<<',';
        const auto& e=v9_report_events[i];
        o<<"{\"reason\":"<<v9_json_string(e.reason)<<",\"target_id\":"<<board.id[e.target]
         <<",\"need\":"<<e.need<<",\"eta\":"<<e.eta<<",\"available\":"<<e.available<<'}';
    }
    o<<"],\"actions\":[";comma=false;
    auto emit=[&](const char* op,int kind,int from,int to,int count,const char* fallback) {
        if(comma)o<<',';
        comma=true;
        const V9ReportNote* note=nullptr;
        for(const auto& n:v9_report_notes)
            if(n.movement.kind==kind && n.movement.from==from && n.movement.to==to &&
               n.movement.tele==(string(op)=="TELE") && n.spawn==(string(op)=="SPAWN")) {note=&n;break;}
        int enemy_here=0,enemy_near=0,our_here=0;
        if(to>=0) {
            enemy_here=s.u[1-us][W][to];our_here=s.u[us][W][to];enemy_near=enemy_here;
            for(int q:board.adj[to]) enemy_near+=s.u[1-us][W][q];
        }
        o<<"{\"op\":"<<v9_json_string(op)<<",\"kind\":"<<v9_json_string(string(1,kinds[kind]))
         <<",\"from\":["<<from%15<<','<<from/15<<"],\"to\":["<<to%15<<','<<to/15
         <<"],\"count\":"<<count<<",\"reason\":"<<v9_json_string(note?note->reason:fallback)
         <<",\"reason_scope\":"<<v9_json_string(note?"recorded_assignment":"selected_plan")
         <<",\"target_id\":"<<(note && note->target>=0?board.id[note->target]:-1)
         <<",\"need\":"<<(note?note->need:-1)<<",\"eta\":"<<(note?note->eta:-1)
         <<",\"reserved_count\":"<<(note?min(count,note->movement.count):0)
         <<",\"walk_distance_to_target\":"<<(note && note->target>=0?board.dist[from][board.pos[note->target]]:-1)
         <<",\"effective_distance_to_target\":"<<(note && note->target>=0?v9_distance(s,us,from,board.pos[note->target],count):-1)
         <<",\"enemy_W_here\":"<<enemy_here<<",\"enemy_W_near\":"<<enemy_near
         <<",\"our_W_here\":"<<our_here<<'}';
    };
    int outgoing[3][N]{},spawned[3][N]{};
    for(auto p:a.spawn) {
        spawned[p.kind][p.pos]+=p.count;
        emit("SPAWN",p.kind,p.pos,p.pos,p.count,"production_in_selected_plan");
    }
    for(auto m:a.moves) {
        outgoing[m.kind][m.from]+=m.count;
        emit(m.tele?"TELE":"MOVE",m.kind,m.from,m.to,m.count,"move_in_selected_evaluated_plan");
    }
    for(int kind=0;kind<3;++kind) for(int c=0;c<N;++c) {
        int staying=s.u[us][kind][c]+spawned[kind][c]-outgoing[kind][c];
        if(staying>0) emit("HOLD",kind,c,c,staying,"no_outgoing_order_in_selected_plan");
    }
    o<<"],\"capture_priority\":[";
    for(int i=0;i<int(a.priority.size());++i) {if(i)o<<',';o<<board.id[a.priority[i]];}
    o<<"]}";
    *v9_report_stream<<o.str()<<'\n';v9_report_stream->flush();
}
