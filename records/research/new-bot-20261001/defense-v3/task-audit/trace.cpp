#define main mission_original_main
#include "source-v1/main.cpp"
#undef main
int main(){
    std::vector<std::string> lines;if(!p::read_block(std::cin,lines))return 0;
    auto init=p::parse_init(lines);mission::board.init(init);
    while(p::read_block(std::cin,lines)){
        auto view=p::parse_turn(lines,init);mission::World w(view,init);mission::Forecast f(w);
        auto tasks=mission::defenseTasks(w);mission::Plan seed;seed.money=w.money;
        std::copy(w.own[mission::W],w.own[mission::W]+mission::board.size,seed.availableW.begin());
        mission::reserveDefenders(seed,w,f,tasks);
        auto output=mission::decide(view,init);p::emit(output);
        if(view.turn<12||view.turn>20)continue;
        std::cerr<<"{\"turn\":"<<view.turn<<",\"flag_candidates\":[";bool comma=false;
        for(int src=0;src<mission::board.size;++src)if(w.enemy[mission::F][src]){
            if(comma)std::cerr<<",";comma=true;
            std::cerr<<"{\"cell\":"<<src<<",\"targets\":[";bool inner=false;
            for(int b=0;b<mission::board.count;++b)if(w.owner[b]==0){
                int d=mission::board.distance[src][mission::board.pos[b]];
                for(int s:w.enemyStations)for(int t:w.enemyStations)if(s!=t)d=std::min(d,mission::board.distance[src][s]+1+mission::board.distance[t][mission::board.pos[b]]);
                if(d>5)continue;if(inner)std::cerr<<",";inner=true;
                std::cerr<<"["<<b<<","<<mission::board.pos[b]<<","<<d<<","<<mission::value(w,b)<<","<<mission::value(w,b)/(d+2.)<<"]";
            }
            std::cerr<<"]}";
        }
        std::cerr<<"],\"tasks\":[";
        for(size_t i=0;i<tasks.size();++i){auto t=tasks[i];if(i)std::cerr<<",";std::cerr<<"["<<t.building<<","<<t.deadline<<","<<t.need<<","<<t.worth<<"]";}
        std::cerr<<"],\"reserved_moves\":[";
        for(size_t i=0;i<seed.moves.size();++i){auto m=seed.moves[i];if(i)std::cerr<<",";std::cerr<<"["<<m.from<<","<<m.to<<","<<m.count<<"]";}
        std::cerr<<"],\"goal_supply\":[";comma=false;
        for(int b=0;b<mission::board.count;++b)if(seed.goalSupply[b]){if(comma)std::cerr<<",";comma=true;std::cerr<<"["<<b<<","<<seed.goalSupply[b]<<"]";}
        std::cerr<<"],\"reserved_arrivals\":[";comma=false;
        for(int c=0;c<mission::board.size;++c)if(seed.arrivalW[c]){if(comma)std::cerr<<",";comma=true;std::cerr<<"["<<c<<","<<seed.arrivalW[c]<<"]";}
        std::cerr<<"]}\n";
    }
}
