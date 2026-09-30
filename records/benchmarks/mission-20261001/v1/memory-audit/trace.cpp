#define main mission_original_main
#include "source-v1/main.cpp"
#undef main
int main(){
    std::vector<std::string> lines;if(!p::read_block(std::cin,lines))return 0;
    auto init=p::parse_init(lines);mission::board.init(init);
    while(p::read_block(std::cin,lines)){
        auto view=p::parse_turn(lines,init);
        mission::World world(view,init);auto before=mission::memories;auto tokens=mission::tokens(world);
        auto output=mission::decide(view,init);p::emit(output);
        std::cerr<<"{\"turn\":"<<view.turn<<",\"tokens\":[";
        for(size_t i=0;i<tokens.size();++i){auto t=tokens[i];if(i)std::cerr<<",";std::cerr<<"["<<t.pos<<","<<t.goal<<","<<t.age<<","<<t.stalled<<"]";}
        std::cerr<<"],\"before\":[";
        for(size_t i=0;i<before.size();++i){auto m=before[i];if(i)std::cerr<<",";std::cerr<<"["<<m.expected<<","<<m.goal<<","<<m.previousDistance<<","<<m.age<<","<<m.stalled<<"]";}
        std::cerr<<"],\"after\":[";
        for(size_t i=0;i<mission::memories.size();++i){auto m=mission::memories[i];if(i)std::cerr<<",";std::cerr<<"["<<m.expected<<","<<m.goal<<","<<m.previousDistance<<","<<m.age<<","<<m.stalled<<"]";}
        std::cerr<<"]}\n";
    }
}
