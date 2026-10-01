#define main siphon_original_entry
#include "submissions/siphon/main.cpp"
#undef main

Action probe_decide(Ctx& ctx) {
    Planner p(ctx);
    p.setup();
    for(int b=0;b<B.nb;++b) if(ctx.s.owner[b]==ctx.op) {
        const int need=p.capNeed(b);
        const int available=p.totalW+p.budget/p.wc[p.me];
        const double rate=max(1.0,double(income(ctx.s,ctx.me))/p.wc[p.me]);
        const double wait=max(0,need-available)/rate;
        int closest=FAR;
        for(int c=0;c<N;++c) if(ctx.s.u[ctx.me][F][c]) closest=min(closest,int(B.dist[c][B.bpos[b]]));
        if(p.budget>=5) for(int c:p.src[p.me]) closest=min(closest,int(B.dist[c][B.bpos[b]]));
        std::cerr << "PROBE building="<<b<<" remaining="<<p.R<<" need="<<need
                  <<" available="<<available<<" closest="<<closest<<" wait="<<wait
                  <<" direct_value="<<p.capValue(b,max(1,closest),ctx.s.owner)
                  <<" waited_value="<<p.capValue(b,max(1,closest)+int(std::ceil(wait)),ctx.s.owner)<<"\n";
    }
    return decide(ctx);
}
int main(int argc,char** argv) { return yk::run(argc,argv,probe_decide); }
