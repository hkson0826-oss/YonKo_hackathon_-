"""Read-only local-league replay analysis; full replay information is for analysis only."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict, deque
import gzip
import hashlib
import json
import math
from pathlib import Path
import random
import statistics
import sys

CHECKPOINTS = (10, 20, 40, 80, 120)
TYPES = ('PLAZA', 'HALL', 'ENG', 'HOSPITAL', 'LIBRARY', 'STATION', 'WATCH', 'DEPOT')
KINDS = 'FWS'


def read_json(path):
    data = path.read_bytes()
    return json.loads(gzip.decompress(data) if path.suffix == '.gz' else data)


def distances(terrain, source):
    height, width = len(terrain), len(terrain[0])
    found, queue = {tuple(source): 0}, deque([tuple(source)])
    while queue:
        x, y = queue.popleft()
        for u, v in ((x-1,y), (x+1,y), (x,y-1), (x,y+1)):
            if 0 <= u < width and 0 <= v < height and terrain[v][u] != '#' and (u,v) not in found:
                found[u,v] = found[x,y] + 1
                queue.append((u,v))
    return found


def map_features(replay):
    board = replay['map']
    terrain, bases = board['terrain'], board['bases']
    width, height = board['width'], board['height']
    graph = {tuple((b['x'],b['y'])): distances(terrain,(b['x'],b['y'])) for b in board['buildings']}
    home = {t: distances(terrain,bases[t]) for t in 'YK'}
    plaza = next(b for b in board['buildings'] if b['type'] == 'PLAZA')
    p = (plaza['x'],plaza['y'])
    center = replay['config']['regions']['center']
    seams = [sum(terrain[y][x] != '#' and terrain[y][x+1] != '#' for y in range(height)) for x in range(center[0],center[1])]
    shared = {
        'base_to_base_walk_distance': home['Y'][tuple(bases['K'])],
        'center_min_horizontal_seam_width': min(seams),
        'plaza_adjacent_passable_cells': sum(0 <= x < width and 0 <= y < height and terrain[y][x] != '#' for x,y in ((p[0]-1,p[1]),(p[0]+1,p[1]),(p[0],p[1]-1),(p[0],p[1]+1))),
        'obstacle_cells': sum(row.count('#') for row in terrain),
        'rotational_terrain_symmetry': all((terrain[y][x] == '#') == (terrain[height-1-y][width-1-x] == '#') for y in range(height) for x in range(width)),
    }
    output = {}
    for t in 'YK':
        lo,hi = replay['config']['regions']['sinchon' if t == 'Y' else 'anam']
        econ = [b for b in board['buildings'] if b['type'] in ('ENG','HALL') and lo <= b['x'] <= hi]
        epos = [(b['x'],b['y']) for b in econ]
        output[t] = {
            **shared, 'base_to_plaza_walk_distance': home[t][p],
            'base_to_plaza_obstacle_detour': home[t][p] - abs(bases[t][0]-p[0]) - abs(bases[t][1]-p[1]),
            'home_economy_mean_walk_distance': statistics.mean(home[t][q] for q in epos),
            'home_economy_max_walk_distance': max(home[t][q] for q in epos),
            'home_economy_spread': max((graph[a][b] for a in epos for b in epos), default=0),
        }
    return output, graph


def percentile(values, fraction):
    if not values:
        return None
    values = sorted(values)
    return values[min(len(values)-1, math.ceil(fraction*len(values))-1)]


def interval(values):
    if not values:
        return None
    rng = random.Random(20261001)
    samples = sorted(statistics.mean(rng.choices(values,k=len(values))) for _ in range(4000))
    return [samples[99],samples[3899]]


def outcome_summary(rows):
    if not rows:
        return {'games':0}
    maps = defaultdict(list)
    for row in rows:
        maps[row['map_seed']].append(row['point'])
    map_values = [statistics.mean(v) for v in maps.values()]
    times = [v for r in rows for v in r['response_ms']]
    return {
        'games':len(rows), 'distinct_maps':len(maps),
        'wins':sum(r['win'] for r in rows), 'draws':sum(r['draw'] for r in rows),
        'losses':sum(not r['win'] and not r['draw'] for r in rows),
        'point_rate':statistics.mean(r['point'] for r in rows),
        'map_cluster_bootstrap_95pct':interval(map_values),
        'mean_score_margin':statistics.mean(r['score_margin'] for r in rows),
        'mean_game_turns':statistics.mean(r['turns'] for r in rows),
        'forfeits':sum(r['forfeit'] for r in rows),
        'first_turn_max_ms':max((r['response_ms'][0] for r in rows if r['response_ms']),default=None),
        'after_first_turn_max_ms':max((v for r in rows for v in r['response_ms'][1:]),default=None),
        'response_ms':{'count':len(times),'mean':statistics.mean(times) if times else None,
                       'p50':percentile(times,.5),'p95':percentile(times,.95),'max':max(times,default=None)},
    }


def checkpoints_summary(rows):
    output = {}
    for turn in (*map(str,CHECKPOINTS),'final'):
        snapshots = [r['checkpoints'][turn] for r in rows if turn in r['checkpoints']]
        if not snapshots:
            continue
        output[turn] = {'games_observed':len(snapshots),
                        'means':{key:statistics.mean(s[key] for s in snapshots) for key in snapshots[0]}}
    return output


def replay_players(row, replay, run_name):
    from engine.commands import Spawn
    from engine.pipeline import step_spawn
    from engine.state import Building, new_game

    board = replay['map']
    features, graphs = map_features(replay)
    state = new_game(replay['config'], terrain=[list(r) for r in board['terrain']],
                     buildings=[Building(b['id'],b['x'],b['y'],b['type'],b['score']) for b in board['buildings']],
                     bases={t:tuple(pos) for t,pos in board['bases'].items()})
    buildings = {b['id']:b for b in board['buildings']}
    positions = {(b['x'],b['y']):b['id'] for b in board['buildings']}
    home_econ = {}
    for t in 'YK':
        lo,hi = replay['config']['regions']['sinchon' if t == 'Y' else 'anam']
        home_econ[t] = [b['id'] for b in board['buildings'] if b['type'] in ('ENG','HALL') and lo <= b['x'] <= hi]
    cumulative = {t:{'production':Counter(),'losses':Counter(),'building_turns':Counter(),
                     'first_capture':{},'home_losses':[], 'home_enemy_F_first':None,
                     'home_enemy_F_turns':0, 'home_enemy_F_near2_turns':0,
                     'first_enemy_side_F':None, 'command_counts':Counter(), 'early_command_counts':Counter(),
                     'losses_by_phase':defaultdict(Counter), 'building_turns_by_phase':defaultdict(Counter), 'production_by_phase':defaultdict(Counter)} for t in 'YK'}
    checkpoints = {t:{} for t in 'YK'}
    ownership_events = []
    trajectory = []
    for frame in replay['turns']:
        turn = frame['turn']
        before = {t:Counter() for t in 'YK'}
        for (x,y,t,k),n in state.units.items():
            before[t][k] += n
        previous = {bid:b.owner for bid,b in state.buildings.items()}
        spawns = {t:[Spawn(**{k:v for k,v in c.items() if k != 'cmd'}) for c in frame['applied'][t] if c['cmd'] == 'Spawn'] for t in 'YK'}
        step_spawn(state,spawns)
        spawned = {t:Counter() for t in 'YK'}
        for (x,y,t,k),n in state.units.items():
            spawned[t][k] += n
        snap = frame['state']
        state.units = {(x,y,t,k):n for t,k,x,y,n in snap['units']}
        state.resources = dict(snap['resources'])
        for b in snap['buildings']:
            state.buildings[b['id']].owner = b['owner']
            state.buildings[b['id']].stage = b['stage']
            if b['owner'] != previous[b['id']]:
                ownership_events.append({'turn':turn,'building_id':b['id'],'type':buildings[b['id']]['type'],
                                         'from':previous[b['id']],'to':b['owner'], 'x':buildings[b['id']]['x'],'y':buildings[b['id']]['y']})
        turn_summary = {'turn':turn}
        for t in 'YK':
            enemy = 'K' if t == 'Y' else 'Y'
            values = cumulative[t]
            owned = [b for b in snap['buildings'] if b['owner'] == t]
            ownership = Counter(buildings[b['id']]['type'] for b in owned)
            units = Counter()
            for side,k,x,y,n in snap['units']:
                if side == t:
                    units[k] += n
            for kind in KINDS:
                production = spawned[t][kind] - before[t][kind]
                losses = spawned[t][kind] - units[kind]
                if production < 0 or losses < 0:
                    raise ValueError('Invalid unit accounting in '+row['job_id'])
                values['production'][kind] += production
                values['losses'][kind] += losses
                phase = '1-20' if turn <= 20 else '21-80' if turn <= 80 else '81-120' if turn <= 120 else '121-final'
                values['losses_by_phase'][phase][kind] += losses
                values['production_by_phase'][phase][kind] += production
            values['building_turns'].update(ownership)
            values['building_turns_by_phase'][phase].update(ownership)
            for b in owned:
                values['first_capture'].setdefault(str(b['id']),turn)
            for b in home_econ[t]:
                if previous[b] == t and state.buildings[b].owner != t:
                    values['home_losses'].append({'turn':turn,'building_id':b,'type':buildings[b]['type'],'new_owner':state.buildings[b].owner})
            intruding = any(side == enemy and k == 'F' and n > 0 and positions.get((x,y)) in home_econ[t] for side,k,x,y,n in snap['units'])
            near = any(side == enemy and k == 'F' and n > 0 and any(graphs[(buildings[b]['x'],buildings[b]['y'])].get((x,y),1000) <= 2 for b in home_econ[t]) for side,k,x,y,n in snap['units'])
            if intruding:
                values['home_enemy_F_first'] = values['home_enemy_F_first'] or turn
                values['home_enemy_F_turns'] += 1
            values['home_enemy_F_near2_turns'] += near
            elo,ehi = replay['config']['regions']['anam' if t == 'Y' else 'sinchon']
            if values['first_enemy_side_F'] is None and any(side == t and k == 'F' and n > 0 and elo <= x <= ehi for side,k,x,y,n in snap['units']):
                values['first_enemy_side_F'] = turn
            for c in frame['applied'][t]:
                key = c['cmd'] + ('_'+c['kind'] if 'kind' in c else '')
                values['command_counts'][key] += 1
                if turn <= 20:
                    values['early_command_counts'][key] += 1
            score = sum(buildings[b['id']]['score'] for b in owned)
            snapshot = {
                'score_full_replay':score, 'owned_buildings':len(owned), 'resources':snap['resources'][t],
                'revealed_buildings':len(snap.get('revealed',{}).get(t,[])),
                **{'owned_'+bt:ownership[bt] for bt in TYPES},
                **{'stock_'+k:units[k] for k in KINDS},
                **{'produced_'+k:values['production'][k] for k in KINDS},
                **{'lost_'+k:values['losses'][k] for k in KINDS},
                'home_economy_losses':len(values['home_losses']),
            }
            if turn in CHECKPOINTS:
                checkpoints[t][str(turn)] = snapshot
            checkpoints[t]['final'] = snapshot
            turn_summary[t] = {'score':score, 'F':units['F'],'W':units['W'],
                               'owned_ENG':ownership['ENG'],'owned_HALL':ownership['HALL'],
                               'owned_HOSPITAL':ownership['HOSPITAL']}
        trajectory.append(turn_summary)
    players = []
    for t in 'YK':
        enemy = 'K' if t == 'Y' else 'Y'
        name = row['candidate'] if t == row['team'] else row['opponent']
        values = cumulative[t]
        diag = row.get('diagnostics',{}).get(t,{})
        for key,new_key in (('production','production'),('deaths','losses')):
            if key in diag and any(diag[key].get(k,0) != values[new_key][k] for k in KINDS):
                raise ValueError('Stored diagnostics accounting disagreement: '+row['job_id']+' '+t+' '+key)
        result = row['result']
        win,draw = result['winner'] == t,result['winner'] == 'DRAW'
        players.append({
            'run':run_name,'job_id':row['job_id'],'map_seed':row['map_seed'],'bot':name,'team':t,
            'opponent':row['opponent'] if t == row['team'] else row['candidate'],
            'is_candidate':t == row['team'],'win':win,'draw':draw,'point':int(win)+.5*int(draw),
            'score_margin':result['score'][t]-result['score'][enemy],
            'turns':result['turns'],'reason':result['reason'],'forfeit':bool(row.get('forfeit')),
            'response_ms':row.get('response_ms' if t == row['team'] else 'opponent_response_ms',[]),
            'map_features':features[t], 'checkpoints':checkpoints[t],
            'production':dict(values['production']),'losses':dict(values['losses']),
            'losses_by_phase':{p:dict(v) for p,v in values['losses_by_phase'].items()},
            'production_by_phase':{p:dict(v) for p,v in values['production_by_phase'].items()},
            'building_turns_by_phase':{p:dict(v) for p,v in values['building_turns_by_phase'].items()},
            'building_turns':dict(values['building_turns']),
            'first_capture_turn_by_building':values['first_capture'],
            'home_economy_loss_events':values['home_losses'],
            'home_economy_enemy_F_first_turn':values['home_enemy_F_first'],
            'home_economy_enemy_F_turns':values['home_enemy_F_turns'],
            'home_economy_enemy_F_within2_walk_turns':values['home_enemy_F_near2_turns'],
            'first_enemy_region_F_turn':values['first_enemy_side_F'],
            'command_counts':dict(values['command_counts']),
            'first20_command_counts':dict(values['early_command_counts']),
            'replay':row['replay'],
        })
    return players,{'run':run_name,'job_id':row['job_id'],'map_seed':row['map_seed'],
                    'candidate':row['candidate'],'opponent':row['opponent'],'team':row['team'],
                    'ownership_events':ownership_events,'trajectory':trajectory}


def behavior_summary(rows):
    output = {'checkpoints':checkpoints_summary(rows)}
    for key in ('production','losses','building_turns','command_counts','first20_command_counts'):
        names = sorted({n for r in rows for n in r[key]})
        output['mean_'+key] = {n:statistics.mean(r[key].get(n,0) for r in rows) for n in names}
    output['phase_means'] = {}
    for field in ('production_by_phase','losses_by_phase','building_turns_by_phase'):
        output['phase_means'][field] = {}
        for phase in ('1-20','21-80','81-120','121-final'):
            selected = [r[field][phase] for r in rows if phase in r[field]]
            if selected:
                names = sorted({k for r in selected for k in r})
                output['phase_means'][field][phase] = {'games_observed':len(selected), 'means':{k:statistics.mean(r.get(k,0) for r in selected) for k in names}}
    output['home_economy'] = {
        'games_losing_a_home_economy_building':sum(bool(r['home_economy_loss_events']) for r in rows),
        'mean_loss_events':statistics.mean(len(r['home_economy_loss_events']) for r in rows),
        'games_with_enemy_F_on_home_economy':sum(r['home_economy_enemy_F_first_turn'] is not None for r in rows),
        'mean_enemy_F_on_home_economy_turns':statistics.mean(r['home_economy_enemy_F_turns'] for r in rows),
    }
    return output


def side_pairing(rows):
    index = {(r['map_seed'],r['opponent'],r['team']):r for r in rows}
    by_map, outcomes = defaultdict(list), {}
    for (seed,opponent,team), row in index.items():
        other = index.get((seed,opponent,'K'))
        if team == 'Y' and other is not None:
            by_map[seed].append(row['point']-other['point'])
            if len({r['opponent'] for r in rows}) == 1:
                label = 'both_wins' if row['win'] and other['win'] else 'both_losses' if row['point']==0 and other['point']==0 else 'split_win_loss' if {row['point'],other['point']} == {0,1} else 'includes_draw'
                outcomes[str(seed)] = {'category':label, 'Y_point':row['point'],'K_point':other['point'],
                                       'Y_score_margin':row['score_margin'],'K_score_margin':other['score_margin']}
    values = [statistics.mean(v) for v in by_map.values()]
    result = {'difference':'Y minus K', 'paired_maps':len(values),
              'paired_opponent_map_pairs':sum(map(len,by_map.values())),
              'point_rate_difference':statistics.mean(values) if values else None,
              'map_cluster_bootstrap_95pct':interval(values)}
    if outcomes:
        result['map_outcome_counts'] = dict(Counter(v['category'] for v in outcomes.values()))
        result['map_outcomes'] = outcomes
    return result


def aggregate(players, focus):
    result = {}
    for bot in focus:
        selected = [r for r in players if r['bot'] == bot]
        if not selected:
            continue
        entry = {'overall':outcome_summary(selected),'behavior':behavior_summary(selected)}
        entry['by_side'] = {t:{'outcome':outcome_summary([r for r in selected if r['team']==t]),
                              'behavior':behavior_summary([r for r in selected if r['team']==t])} for t in 'YK' if any(r['team']==t for r in selected)}
        entry['by_opponent'] = {op:{'overall':outcome_summary([r for r in selected if r['opponent']==op]), 'by_side':{t:outcome_summary([r for r in selected if r['opponent']==op and r['team']==t]) for t in 'YK'}} for op in sorted({r['opponent'] for r in selected})}
        entry['paired_side_comparison'] = side_pairing(selected)
        result[bot] = entry
    return result


def paired_common(players, focus):
    if len(focus) != 2:
        return {}
    left,right = focus
    index = {(r['bot'],r['team'],r['map_seed'],r['opponent']):r for r in players if r['is_candidate']}
    report = {}
    for team in ('Y','K','both'):
        differences = defaultdict(list)
        for key, row in index.items():
            bot,side,seed,opponent = key
            other = index.get((right,side,seed,opponent))
            if bot != left or other is None or team not in ('both',side):
                continue
            differences[seed].append(row['point']-other['point'])
        values = [statistics.mean(v) for v in differences.values()]
        report[team] = {'paired_maps':len(values),'paired_games':sum(map(len,differences.values())),
                        'point_rate_difference':statistics.mean(values) if values else None,
                        'map_cluster_bootstrap_95pct':interval(values)}
    return {'difference':left+' minus '+right, 'by_side':report}


def exploratory_strata(players, focus):
    report = {}
    keys = ('base_to_plaza_walk_distance','home_economy_max_walk_distance','home_economy_spread',
            'base_to_plaza_obstacle_detour','center_min_horizontal_seam_width','plaza_adjacent_passable_cells')
    for key in keys:
        unique = {(r['map_seed'],r['team']):r['map_features'][key] for r in players}
        if len(set(unique.values())) < 2:
            continue
        threshold = statistics.median(unique.values())
        bins = {'below_median':lambda v:v<threshold,'at_or_above_median':lambda v:v>=threshold}
        report[key] = {'median_threshold':threshold,'bins':{}}
        for label,predicate in bins.items():
            report[key]['bins'][label] = {bot:{'overall':outcome_summary([r for r in players if r['bot']==bot and predicate(r['map_features'][key])]), 'by_side':{side:outcome_summary([r for r in players if r['bot']==bot and r['team']==side and predicate(r['map_features'][key])]) for side in 'YK'}} for bot in focus}
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sdk',type=Path,required=True)
    parser.add_argument('--run-dir',type=Path,action='append',required=True)
    parser.add_argument('--focus',default='v8,teammate')
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    sys.path.insert(0,str(args.sdk.resolve()))
    all_players,trajectories,errors,input_files = [],[],[],{}
    seen_jobs = set()
    for run in args.run_dir:
        source = run/'results.jsonl'
        input_files[str(source)] = hashlib.sha256(source.read_bytes()).hexdigest()
        for line in source.read_text().splitlines():
            row = json.loads(line)
            if row['job_id'] in seen_jobs:
                raise ValueError('Duplicate match across input runs: '+row['job_id'])
            seen_jobs.add(row['job_id'])
            if row['status'] != 'complete':
                errors.append(row)
                continue
            replay_path = run/row['replay']
            input_files[str(replay_path)] = hashlib.sha256(replay_path.read_bytes()).hexdigest()
            replay = read_json(replay_path)
            if replay['seed'] != row['map_seed'] or replay['result'] != row['result']:
                raise ValueError('Replay/result mismatch: '+row['job_id'])
            players,trajectory = replay_players(row,replay,run.name)
            all_players.extend(players)
            trajectories.append(trajectory)
    focus = args.focus.split(',')
    output = {
        'method':{'checkpoints':'Post-turn exact snapshots; games ending before checkpoint omitted and denominator shown. Final always actual terminal state.',
                  'units':'Exact accepted production reconstructed by official step_spawn; losses = previous stock + accepted production - end-turn stock, checked against stored league diagnostics.',
                  'home_economy':'ENG and HALL within own home x-region; loss event is own -> neutral/opponent ownership.',
                  'map_features':'Static four-neighbor shortest walking paths without TELE; seam width and plaza degree are descriptive bottleneck proxies, not minimum cuts.',
                  'uncertainty':'4000 bootstrap draws resampling map clusters; a degenerate all-wins/all-losses interval does not prove certain future performance.',
                  'limitations':['Full replay score/hidden information used only for offline analysis.','Exploratory map strata are post-hoc associations, not causal effects or independent tests.','Early-terminal games excluded from later checkpoints; compare denominators.','Common-opponent difference uses matching candidate/opponent/map/side; direct games appear once per player perspective.']},
        'games':len(trajectories),'distinct_maps':len({r['map_seed'] for r in all_players}),
        'errors':errors,'input_sha256':input_files,
        'by_bot':aggregate(all_players,focus),
        'paired_common_opponents':paired_common(all_players,focus),
        'exploratory_map_strata':exploratory_strata(all_players,focus),
        'players':all_players,
    }
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n')
    trace_path=args.output.with_name(args.output.stem+'-trajectories.json.gz')
    trace_path.write_bytes(gzip.compress(json.dumps(trajectories,ensure_ascii=False,separators=(',',':')).encode(),mtime=0))
    print(json.dumps({'games':output['games'],'maps':output['distinct_maps'],'errors':len(errors),
                      'outcome':{bot:v['overall'] for bot,v in output['by_bot'].items()},
                      'output':str(args.output),'trajectories':str(trace_path)},ensure_ascii=False))


if __name__ == '__main__':
    main()
