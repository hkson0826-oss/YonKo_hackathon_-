import sys
import unittest
from pathlib import Path
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'yk-development-tools'))
from engine.config import load_config
from engine.state import Building, new_game
from engine.commands import Move, Move2, Spawn, Tele, Priority
from engine.pipeline import run_turn, step_victory, step_spawn, step_move, step_income, step_capture, step_combat, step_reveal
from runner.protocol import parse_commands, serialize_turn

def b(i,x,y,kind='HALL',owner='N',score=2):
    return Building(i,x,y,kind,score,owner,0 if owner == 'N' else 2)
def s(bs=(),resource=10):
    return new_game(load_config(),buildings=list(bs),resources={'Y':resource,'K':resource})

class NewBotRuleCounterexamples(unittest.TestCase):
    def test_last_turn_neutralization_changes_final_score_without_capture(self):
        st=s([b(0,5,5,owner='K',score=4),b(1,8,5,owner='Y',score=3),b(2,9,5,owner='K',score=2)])
        st.turn=159;st.add_unit(5,5,'Y','F',1)
        out,res=run_turn(st,[],[])
        self.assertEqual(out.buildings[0].owner,'N');self.assertEqual(res['winner'],'Y');self.assertEqual(res['score'],{'Y':3,'K':2})
    def test_owner_warrior_is_safe_garrison_against_warrior_only_raid(self):
        st=s([b(0,5,5,owner='Y')]);st.add_unit(5,5,'Y','W',1);st.add_unit(5,5,'K','W',2)
        step_combat(st);self.assertEqual(st.buildings[0].owner,'Y')
    def test_exact_equal_warriors_protect_flag_but_do_not_clear_enemy_flag(self):
        st=s([b(0,5,5)])
        for t in 'YK':st.add_unit(5,5,t,'W',4);st.add_unit(5,5,t,'F',1)
        out,_=run_turn(st,[],[])
        self.assertEqual(out.buildings[0].owner,'N');self.assertEqual(out.get_unit(5,5,'Y','F'),1);self.assertEqual(out.get_unit(5,5,'K','F'),1)
    def test_one_surplus_warrior_clears_all_enemy_flags(self):
        st=s([b(0,5,5)]);st.add_unit(5,5,'Y','W',5);st.add_unit(5,5,'K','W',4);st.add_unit(5,5,'K','F',7);st.add_unit(5,5,'Y','F',1)
        out,_=run_turn(st,[],[])
        self.assertEqual(out.get_unit(5,5,'K','F'),0);self.assertEqual(out.buildings[0].owner,'Y')
    def test_global_spawn_budget_not_repeated_per_hospital(self):
        st=s([b(0,5,5,'HOSPITAL','Y'),b(1,9,5,'HOSPITAL','Y'),b(2,8,8,'ENG','Y')],10)
        step_spawn(st,{'Y':[Spawn('W',5,5,5),Spawn('W',5,9,5)],'K':[]})
        self.assertEqual(sum(v for (x,y,t,k),v in st.units.items() if t=='Y'),5)
    def test_one_unit_cannot_defend_two_destinations(self):
        st=s();st.add_unit(5,5,'Y','W',3)
        step_move(st,{'Y':[Move(5,5,'W',3,'L'),Move(5,5,'W',3,'R')],'K':[]})
        self.assertEqual(st.get_unit(4,5,'Y','W'),3);self.assertEqual(st.get_unit(6,5,'Y','W'),0)
    def test_only_one_tele_can_carry_one_kind(self):
        st=s([b(0,5,5,'STATION','Y'),b(1,9,5,'STATION','Y')]);st.add_unit(5,5,'Y','F',1);st.add_unit(5,5,'Y','W',6)
        step_move(st,{'Y':[Tele(5,5,'F',1,9,5),Tele(5,5,'W',5,9,5)],'K':[]})
        self.assertEqual(st.get_unit(9,5,'Y','F'),1);self.assertEqual(st.get_unit(9,5,'Y','W'),0)
    def test_new_station_cannot_tele_until_next_turn(self):
        st=s([b(0,5,5,'STATION','Y'),b(1,9,5,'STATION')]);st.add_unit(5,5,'Y','W',5);st.add_unit(9,5,'Y','F',1)
        out,_=run_turn(st,[Tele(5,5,'W',5,9,5)],[])
        self.assertEqual(out.buildings[1].owner,'Y');self.assertEqual(out.get_unit(5,5,'Y','W'),5)
    def test_capture_library_loss_preserves_discount_both_teams(self):
        st=s([b(0,5,5,'LIBRARY','Y'),b(1,9,5,'WATCH')],0);st.add_unit(5,5,'K','F',1);st.add_unit(9,5,'Y','F',1)
        out,_=run_turn(st,[],[])
        self.assertEqual(out.buildings[0].owner,'N');self.assertEqual(out.resources['Y'],9)
    def test_combat_library_loss_removes_discount(self):
        st=s([b(0,5,5,'LIBRARY','Y'),b(1,9,5,'WATCH')],0);st.add_unit(5,5,'Y','F',1);st.add_unit(5,5,'K','W',1);st.add_unit(9,5,'Y','F',1)
        out,_=run_turn(st,[],[])
        self.assertEqual(out.buildings[0].owner,'N');self.assertEqual(out.resources['Y'],8)
    def test_combat_hall_loss_removes_income_same_turn(self):
        st=s([b(0,5,5,owner='Y')],0);st.add_unit(5,5,'Y','F',1);st.add_unit(5,5,'K','W',1)
        out,_=run_turn(st,[],[]);self.assertEqual(out.resources['Y'],10)
    def test_capture_hall_loss_still_receives_income_this_turn(self):
        st=s([b(0,5,5,owner='Y')],0);st.add_unit(5,5,'K','F',1)
        out,_=run_turn(st,[],[]);self.assertEqual(out.resources['Y'],12)
    def test_hidden_actual_score_does_not_get_default_priority(self):
        st=s([b(0,6,5,'WATCH',score=4),b(1,4,5,'WATCH',score=1)],2)
        for bd in st.sorted_buildings():st.add_unit(bd.x,bd.y,'Y','F',1)
        step_capture(st,{'Y':[],'K':[]})
        self.assertEqual(st.buildings[1].owner,'Y');self.assertEqual(st.buildings[0].owner,'N')
    def test_priority_can_override_hidden_default(self):
        st=s([b(0,6,5,'WATCH',score=4),b(1,4,5,'WATCH',score=1)],2)
        for bd in st.sorted_buildings():st.add_unit(bd.x,bd.y,'Y','F',1)
        step_capture(st,{'Y':[(6,5)],'K':[]})
        self.assertEqual(st.buildings[0].owner,'Y')
    def test_scout_move2_midpoint_cannot_reveal_far_building(self):
        st=s([b(0,3,1,'WATCH')]);st.add_unit(3,3,'Y','S',1)
        # Midpoint (3,4) is within 2 of target (3,6); start/end are outside 2.
        st.buildings[0].x=3;st.buildings[0].y=6
        out,_=run_turn(st,[Move2(3,3,1,'D','U')],[])
        self.assertNotIn(0,out.revealed['Y'])
    def test_dead_units_do_not_reveal(self):
        st=s([b(0,5,5,'WATCH')]);st.add_unit(5,5,'Y','S',1);st.add_unit(5,5,'K','W',1)
        out,_=run_turn(st,[],[]);self.assertNotIn(0,out.revealed['Y'])
    def test_both_owned_engs_do_not_reduce_w_cost_below_two(self):
        st=s([b(0,5,5,'ENG','Y'),b(1,8,5,'ENG','Y')],10)
        step_spawn(st,{'Y':[Spawn('W',10)],'K':[]});self.assertEqual(st.get_unit(0,7,'Y','W'),5)
    def test_named_base_spawn_is_ignored(self):
        st=s();step_spawn(st,{'Y':[Spawn('F',1,0,7)],'K':[]});self.assertEqual(st.get_unit(0,7,'Y','F'),0)
    def test_n1_expires_and_has_no_claimant_rights(self):
        st=s([b(0,5,5)]);st.buildings[0].stage=1;st.add_unit(5,5,'K','F',1)
        out,_=run_turn(st,[],[]);self.assertEqual(out.buildings[0].owner,'K')
    def test_total_odd_does_not_prevent_draw_with_neutral_plaza(self):
        st=s([b(0,7,7,'PLAZA',score=3),b(1,3,5,owner='Y',score=1),b(2,11,9,owner='K',score=1)])
        st.turn=160;self.assertEqual(step_victory(st)['winner'],'DRAW')
    def test_depot_reclaim_gives_no_second_bonus(self):
        st=s([b(0,5,5,'DEPOT')],0);st.depot_claimed={0:{'Y'}};st.add_unit(5,5,'Y','F',1)
        out,_=run_turn(st,[],[]);self.assertEqual(out.resources['Y'],8)
    def test_resource_cap_before_capture_loses_overflow(self):
        st=s([b(0,5,5,'WATCH')],39);st.add_unit(5,5,'Y','F',1)
        out,_=run_turn(st,[],[]);self.assertEqual(out.resources['Y'],38)
    def test_turn_160_includes_current_capture_in_tiebreak(self):
        st=s([b(0,5,5,'WATCH',score=2),b(1,10,5,'WATCH','K',score=2),b(2,7,7,'PLAZA',score=3)])
        st.turn=159;st.add_unit(5,5,'Y','F',1);st.occupation_score_turns={'Y':30,'K':30}
        out,res=run_turn(st,[],[]);self.assertEqual(out.occupation_score_turns,{'Y':32,'K':32});self.assertEqual(res['reason'],'units')
    def test_protocol_filters_points_per_team(self):
        st=s([b(0,5,5,'WATCH',score=4)]);st.revealed['Y'].add(0)
        self.assertIn('0 5 5 WATCH N 0 4',serialize_turn(st,'Y',1));self.assertIn('0 5 5 WATCH N 0 -1',serialize_turn(st,'K',1))

if __name__=='__main__':unittest.main(verbosity=2)
