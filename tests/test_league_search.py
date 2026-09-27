import importlib.util
import pathlib
import subprocess
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("search_families", ROOT / "experiments/local_league/search_families.py")
families = importlib.util.module_from_spec(spec)
spec.loader.exec_module(families)


class SearchFamiliesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = (ROOT / "submissions/tuned/main.cpp").read_text()
        cls.variants = families.variants(cls.original)

    def test_unique_sources_and_unchanged_transition_observation(self):
        self.assertEqual(len(self.variants), 10)
        self.assertEqual(len({v["id"] for v in self.variants}), 10)
        self.assertEqual(len({v["source"] for v in self.variants}), 10)
        transition = self.original.split("State advance(", 1)[1].split("double building_value(", 1)[0]
        observation = self.original.split("    State s; s.turn=v.turn-1;", 1)[1].split(families.SEARCH_START, 1)[0]
        for item in self.variants:
            self.assertIn(transition, item["source"], item["id"])
            self.assertIn(observation, item["source"], item["id"])

    def test_changed_anchor_rejected(self):
        with self.assertRaises(ValueError):
            families.variants(self.original.replace("    constexpr int P=4;", "    constexpr int P=5;"))
        with self.assertRaises(ValueError):
            families.replace_once("same same", "same", "new")

    def test_all_candidates_compile(self):
        with tempfile.TemporaryDirectory(prefix="yk-search-compile-") as directory:
            root = pathlib.Path(directory)
            for item in self.variants:
                source = root / (item["id"] + ".cpp")
                source.write_text(item["source"])
                result = subprocess.run(["g++", "-std=c++20", "-O2", "-I", str(ROOT / "submissions/tuned"),
                                         str(source), "-o", str(root / item["id"])],
                                        capture_output=True, text=True, timeout=60)
                self.assertEqual(result.returncode, 0, item["id"] + "\n" + result.stderr)

    def test_cpp_selection_and_tactical_subset(self):
        candidate = next(v for v in self.variants if v["id"] == "s_local_hold_d3")
        harness = r'''
#define main bot_entry
''' + candidate["source"] + r'''
#undef main
#include <cassert>
int main() {
    double payoff[4][4]={{5,5,5,5},{-20,50,50,50},{4,7,42.5,42.5},{-5,40,40,40}};
    assert(league_select(payoff,1)==0);
    assert(league_select(payoff,2)==1);
    assert(league_select(payoff,3)==2);
    assert(league_select(payoff,4)==3);
    double ties[4][4]{};
    for(int mode=1;mode<=4;++mode) assert(league_select(ties,mode)==0);
    double dominant[4][4]={{9,9,9,9},{-1,-1,-1,-1},{-1,-1,-1,-1},{-1,-1,-1,-1}};
    int selected=0;
    for(int k=0;k<100;++k) selected+=league_select(dominant,0)==0;
    assert(selected>=95);
    board.nb=1;board.pos[0]=10;
    for(int x=0;x<N;++x) for(int y=0;y<N;++y) board.dist[x][y]=x==y?0:INF;
    board.dist[11][10]=1;
    State s;s.owner[0]=0;s.u[1][F][11]=1;
    Action a;a.spawn.push_back({W,0,3});a.priority.push_back(0);
    a.moves={{W,10,9,3},{F,10,9,1},{W,20,19,2}};
    auto hold=league_hold(s,0,a);
    assert(hold.moves.size()==2 && hold.moves[0].kind==F && hold.moves[1].from==20);
    assert(hold.spawn.size()==1 && hold.spawn[0].count==3 && hold.priority==a.priority);
    s.owner[0]=1;
    assert(league_hold(s,0,a).moves.size()==3);
    return 0;
}
'''
        with tempfile.TemporaryDirectory(prefix="yk-search-logic-") as directory:
            source = pathlib.Path(directory) / "logic.cpp"
            binary = pathlib.Path(directory) / "logic"
            source.write_text(harness)
            subprocess.run(["g++", "-std=c++20", "-O2", "-I", str(ROOT / "submissions/tuned"),
                            str(source), "-o", str(binary)], check=True, capture_output=True, timeout=60)
            subprocess.run([str(binary)], check=True, capture_output=True, timeout=10)


if __name__ == "__main__":
    unittest.main()
