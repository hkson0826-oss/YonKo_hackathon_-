#define main submission_main
#include "../submissions/first/main.cpp"
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
    s=advance(s,a[0],a[1]);
    cout<<s.turn<<' '<<s.res[0]<<' '<<s.res[1]<<' '<<s.occupation[0]<<' '<<s.occupation[1]<<'\n';
    for (int b=0;b<board.nb;++b)
        cout<<s.owner[b]<<' '<<s.stage[b]<<' '<<s.claimed[0][b]<<' '<<s.claimed[1][b]
            <<' '<<s.revealed[0][b]<<' '<<s.revealed[1][b]<<'\n';
    for (int t=0;t<2;++t) for (int k=0;k<3;++k) for (int c=0;c<N;++c)
        if (s.u[t][k][c]) cout<<t<<' '<<k<<' '<<c<<' '<<s.u[t][k][c]<<'\n';
}
