import importlib.util
import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"experiments"))
import local_league as league
import league_campaign as campaign
sys.path.insert(0,str(ROOT/"yk-development-tools"))
from engine.config import load_config
from runner.bots import InProcessBot
from runner.match import run_match


class LeagueTests(unittest.TestCase):
    def test_pairs_and_cartesian_jobs_are_identical_and_unique(self):
        common={"map_seeds":[1,2],"replays":"none"}
        a=league.make_jobs({**common,"candidates":["a"],"opponents":["b"]},{"a":{},"b":{}})
        b=league.make_jobs({**common,"pairs":[["a","b"]]},{"a":{},"b":{}})
        self.assertEqual(a,b)
        self.assertEqual(len(a),4)
        with self.assertRaises(ValueError):
            league.make_jobs({**common,"pairs":[["a","b"],["a","b"]]},{"a":{},"b":{}})

    def test_actual_spawn_diagnostics_match_official_state_with_clipped_requests(self):
        def spawn(view,init):
            return ["SPAWN W 100", "SPAWN F 100"]
        replay,result=run_match(5911,load_config(),InProcessBot(spawn),InProcessBot(lambda v,i:[]),max_turns=8)
        data=league.diagnostics(replay)
        final_w=sum(n for t,k,x,y,n in replay["turns"][-1]["state"]["units"] if t=="Y" and k=="W")
        self.assertGreater(final_w,0)
        self.assertEqual(data["Y"]["production"]["W"],final_w)
        self.assertEqual(data["Y"]["production"]["F"],0)
        self.assertEqual(data["Y"]["deaths"]["W"],0)
        self.assertEqual(data["Y"]["engineering_turns"],0)
        self.assertEqual(data["K"]["production"]["W"],0)

    def test_bootstrap_clusters_opponents_by_map_and_does_not_pool_sides(self):
        rows=[]
        for seed in range(4):
            for opponent in ("x","y"):
                for name in ("v2","new"):
                    rows.append({"candidate":name,"map_seed":seed,"team":"Y","opponent":opponent,
                                 "status":"complete","win":name=="new","draw":False})
                    rows.append({**rows[-1],"team":"K","win":False})
        result=campaign.paired_interval(rows,"new")
        self.assertEqual(result["maps"],4)
        self.assertEqual(result["point_rate_difference"],1)
        self.assertEqual(result["map_cluster_bootstrap_95pct"],[1,1])
        self.assertEqual(campaign.paired_interval(rows,"new","K")["point_rate_difference"],0)

    def test_crossplay_counts_both_sides_but_not_double_games(self):
        table=campaign.crossplay_table([{"candidate":"a","opponent":"b","team":"K","status":"complete","win":True,"draw":False}])
        self.assertEqual(table["unique_matches"],1)
        self.assertEqual(table["totals"]["a"]["wins"],1)
        self.assertEqual(table["totals"]["b"]["losses"],1)
        self.assertEqual(table["totals"]["b"]["Y_games"],1)


if __name__=="__main__":
    unittest.main()
