#define main submission_main
#include "main.cpp"
#undef main

int main() {
    vector<string> lines;
    if (!p::read_block(cin,lines)) return 1;
    board.init(p::parse_init(lines));
    State s;
    cin >> s.turn >> s.res[0] >> s.res[1] >> s.occupation[0] >> s.occupation[1];
    for (int b=0;b<board.nb;++b)
        cin >> s.owner[b] >> s.stage[b] >> s.score[b] >> s.claimed[0][b] >> s.claimed[1][b]
            >> s.revealed[0][b] >> s.revealed[1][b];
    int n; cin >> n;
    for (int i=0;i<n;++i) {int t,k,c,count;cin>>t>>k>>c>>count;s.u[t][k][c]=count;}
    Action a[2];
    for (int t=0;t<2;++t) {
        int ns,nm,np;cin>>ns>>nm>>np;
        for (int j=0;j<ns;++j) {Production x;cin>>x.kind>>x.pos>>x.count;a[t].spawn.push_back(x);}
        for (int j=0;j<nm;++j) {Movement x;cin>>x.kind>>x.from>>x.to>>x.count>>x.tele;a[t].moves.push_back(x);}
        for (int j=0;j<np;++j) {int b;cin>>b;a[t].priority.push_back(b);}
    }

    cout << "[";
    for(int model=-1;model<4;++model) {
        if(model!=-1) cout << ",";
        Action enemy=model<0?Action{}:policy(s,1,model);
        State after=advance(s,a[0],enemy);
        cout << "{\"model\":" << model << ",\"own_total_f_after\":" << accumulate(after.u[0][F],after.u[0][F]+N,0);
        cout << ",\"own_target_f_after\":" << after.u[0][F][12+15*6] << ",\"enemy_target_w_after\":" << after.u[1][W][12+15*6] << ",\"enemy_moves\":[";
        bool comma=false;
        for(auto m:enemy.moves) {if(comma)cout<<",";comma=true;cout<<"["<<m.kind<<","<<m.from%15<<","<<m.from/15<<","<<m.to%15<<","<<m.to/15<<","<<m.count<<","<<m.tele<<"]";}
        cout << "]}";
    }
    cout << "]\n";
}
