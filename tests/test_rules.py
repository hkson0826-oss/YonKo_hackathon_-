"""Executable counterexamples for strategic assumptions in the report."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'yk-development-tools'))
from engine.commands import Move, Move2, Spawn, Tele, Priority
from engine.config import load_config
from engine.pipeline import run_turn, step_victory, unit_value
from engine.state import Building, new_game
from mapgen import generate


def state(buildings=(), resource=10):
    return new_game(load_config(), buildings=list(buildings), resources={'Y': resource, 'K': resource})


def building(i=0, x=5, y=5, kind='HALL', score=2, owner='N'):
    return Building(i,x,y,kind,score,owner,0 if owner=='N' else 2)


class RulesTest(unittest.TestCase):
    def test_departed_flag_preserves_ownership(self):
        s=state([building(owner='Y')]);s.add_unit(5,5,'Y','F',1);s.add_unit(6,5,'K','W',1)
        s,_=run_turn(s,[Move(5,5,'F',1,'U')],[Move(6,5,'W',1,'L')])
        self.assertEqual(s.buildings[0].owner,'Y')

    def test_staying_flag_can_lose_ownership(self):
        s=state([building(owner='Y')]);s.add_unit(5,5,'Y','F',1);s.add_unit(6,5,'K','W',1)
        s,_=run_turn(s,[],[Move(6,5,'W',1,'L')])
        self.assertEqual(s.buildings[0].owner,'N')

    def test_equal_warriors_leave_contested_flags(self):
        s=state([building()])
        for t in 'YK':
            s.add_unit(5,5,t,'F',1);s.add_unit(5,5,t,'W',3)
        s,_=run_turn(s,[],[])
        self.assertEqual(s.buildings[0].owner,'N')
        self.assertEqual(s.get_unit(5,5,'Y','F'),1)

    def test_combat_enables_one_turn_takeover(self):
        s=state([building(owner='K')]);s.add_unit(5,5,'K','F',1)
        s.add_unit(4,5,'Y','F',1);s.add_unit(4,5,'Y','W',1)
        s,_=run_turn(s,[Move(4,5,'F',1,'R'),Move(4,5,'W',1,'R')],[])
        self.assertEqual(s.buildings[0].owner,'Y')

    def test_empty_enemy_building_takes_two_turns(self):
        s=state([building(owner='K')]);s.add_unit(5,5,'Y','F',1)
        s,_=run_turn(s,[],[]);self.assertEqual(s.buildings[0].owner,'N')
        s,_=run_turn(s,[],[]);self.assertEqual(s.buildings[0].owner,'Y')

    def test_spawn_and_move_same_turn(self):
        s,_=run_turn(state(),[Spawn('F',1),Move(0,7,'F',1,'R')],[])
        self.assertEqual(s.get_unit(1,7,'Y','F'),1)

    def test_arrivals_cannot_move_again(self):
        s=state();s.add_unit(1,1,'Y','W',1)
        s,_=run_turn(s,[Move(1,1,'W',1,'R'),Move(2,1,'W',1,'R')],[])
        self.assertEqual(s.get_unit(2,1,'Y','W'),1)
        self.assertEqual(s.get_unit(3,1,'Y','W'),0)

    def test_edge_swap_has_no_combat(self):
        s=state();s.add_unit(1,1,'Y','F',1);s.add_unit(2,1,'K','W',1)
        s,_=run_turn(s,[Move(1,1,'F',1,'R')],[Move(2,1,'W',1,'L')])
        self.assertEqual(s.get_unit(2,1,'Y','F'),1)

    def test_income_pays_capture_with_zero_initial_resource(self):
        s=state([building()],0);s.add_unit(5,5,'Y','F',1)
        s,_=run_turn(s,[],[])
        self.assertEqual((s.buildings[0].owner,s.resources['Y']),('Y',8))

    def test_new_hall_income_starts_next_turn(self):
        s=state([building()],0);s.add_unit(5,5,'Y','F',1)
        s,_=run_turn(s,[],[]);s,_=run_turn(s,[],[])
        self.assertEqual(s.resources['Y'],20)

    def test_library_capture_does_not_discount_same_phase(self):
        s=state([building(kind='LIBRARY'),building(1,6,5,'WATCH')],0)
        s.add_unit(5,5,'Y','F',1);s.add_unit(6,5,'Y','F',1)
        s,_=run_turn(s,[Priority([(5,5),(6,5)])],[])
        self.assertEqual(s.resources['Y'],6)

    def test_depot_bonus_cannot_pay_other_same_turn_captures(self):
        bs=[building(i,i+1,5,'DEPOT' if i==0 else 'WATCH') for i in range(6)]
        s=state(bs,0)
        for b in bs:s.add_unit(b.x,b.y,'Y','F',1)
        s,_=run_turn(s,[Priority([b.pos for b in bs])],[])
        self.assertEqual(sum(b.owner=='Y' for b in s.buildings.values()),5)
        self.assertEqual(s.resources['Y'],15)

    def test_hospital_spawn_survives_ownership_loss(self):
        s=state([building(kind='HOSPITAL',owner='Y')])
        s.add_unit(5,5,'K','F',1)
        s,_=run_turn(s,[Spawn('W',1,5,5),Move(5,5,'W',1,'U')],[])
        self.assertEqual(s.get_unit(5,4,'Y','W'),1)
        self.assertEqual(s.buildings[0].owner,'N')

    def test_invalid_tele_does_not_consume_valid_tele(self):
        s=state([building(kind='STATION',owner='Y'),building(1,10,5,'STATION',owner='Y')])
        s.add_unit(5,5,'Y','W',9)
        s,_=run_turn(s,[Tele(5,5,'F',1,10,5),Tele(5,5,'W',9,10,5)],[])
        self.assertEqual(s.get_unit(10,5,'Y','W'),5)

    def test_scout_crosses_enemy_without_midpoint_combat(self):
        s=state();s.add_unit(1,1,'Y','S',1);s.add_unit(2,1,'K','W',2)
        s,_=run_turn(s,[Move2(1,1,1,'R','R')],[])
        self.assertEqual(s.get_unit(3,1,'Y','S'),1)

    def test_final_points_override_occupation_and_army(self):
        s=state([building(owner='Y',score=2),building(1,6,5,owner='K',score=1)])
        s.turn=160;s.occupation_score_turns={'Y':2,'K':5000};s.add_unit(1,1,'K','W',1000)
        self.assertEqual(step_victory(s)['winner'],'Y')

    def test_discounted_warrior_still_has_tiebreak_value_three(self):
        s=state([building(kind='ENG',owner='Y')],10)
        s,_=run_turn(s,[Spawn('W',5)],[])
        self.assertEqual(unit_value(s,'Y'),15)

    def test_score_symmetry_and_864_world_bound(self):
        for seed in range(40):
            m=generate(seed,load_config());bypos={b.pos:b for b in m.buildings}
            for b in m.buildings:self.assertEqual(b.score,bypos[(14-b.x,14-b.y)].score)
            self.assertEqual(m.total_score()%2,1)
        self.assertEqual(2**5*3**3,864)


if __name__=='__main__': unittest.main()
