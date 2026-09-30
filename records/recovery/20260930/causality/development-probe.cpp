#define main submission_main
#include "main.cpp"
#undef main
#include "development-old-guard.inc"
#include "development-inspect-guard.inc"
bool equal(const Action&a,const Action&b) {
    if(a.spawn.size()!=b.spawn.size()||a.moves.size()!=b.moves.size()||a.priority!=b.priority)return false;
    for(size_t i=0;i<a.spawn.size();++i) {auto x=a.spawn[i],y=b.spawn[i];if(x.kind!=y.kind||x.pos!=y.pos||x.count!=y.count)return false;}
    for(size_t i=0;i<a.moves.size();++i) {auto x=a.moves[i],y=b.moves[i];if(x.kind!=y.kind||x.from!=y.from||x.to!=y.to||x.count!=y.count||x.tele!=y.tele)return false;}
    return true;
}
int main(){
#include "development-fixtures.inc"
}
