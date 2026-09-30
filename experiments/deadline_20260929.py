"""Small frozen leagues for the 2026-09-29 deadline; no automatic promotion."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import random
import re
import shlex
import shutil
import sys

sys.dont_write_bytecode = True
import local_league as league
import v3_campaign
from cross_family_audit import submission_address_space

V4 = 's3_v2_screen_paired_guard'
V4_SHA = '1703701340ede10b652b0aa024e29c3fd411e2809ae34de1e3d0b39620d496df'
OPPONENTS = ['v3', 'teammate', 'j_balanced_portfolio', 's3_selective_contact']


def csv(value):
    names = value.split(',')
    if not names or any(not name for name in names) or len(names) != len(set(names)):
        raise ValueError('Expected distinct nonempty comma-separated names')
    return names


def prepare(args):
    arena = args.arena.resolve()
    runtime_args = {}
    supplied_names = {value.partition('=')[0] for value in args.candidate}
    for supplied in args.candidate_arg:
        name, separator, argument = supplied.partition('=')
        if not separator or name not in supplied_names or not argument or '\x00' in argument:
            raise ValueError('Candidate argument must be CANDIDATE_ID=ONE_ARGUMENT: ' + supplied)
        runtime_args.setdefault(name, []).append(argument)
    challenge = ['s3_selective_contact', 'r3_opponent_league', 'f3_v2_warrior_reserve']
    league.prepare(arena, v3_campaign.population_spec(2, [V4], challenge))
    manifest = json.loads((arena / 'manifest.json').read_text())
    if manifest['bots'][V4]['source_sha256'] != V4_SHA:
        raise ValueError('Recreated v4 differs from the existing submitted local v4')
    manifest['status'] = 'adding_external_candidates'
    league.write(arena / 'manifest.json', manifest)
    manifest['bots']['v4'] = {**manifest['bots'].pop(V4), 'id': 'v4', 'equivalent_original_id': V4}
    for supplied in args.candidate:
        name, separator, source_arg = supplied.partition('=')
        if not separator or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', name) or name in manifest['bots']:
            raise ValueError('Candidate must be NEW_ID=CPP_SOURCE_DIRECTORY: ' + supplied)
        source = Path(source_arg).resolve()
        if not (source / 'main.cpp').is_file():
            raise ValueError('Missing main.cpp in ' + str(source))
        frozen = arena / 'snapshot/candidates' / name
        frozen.mkdir(parents=True)
        copied = [source / 'main.cpp', *sorted(source.glob('*.hpp'))]
        if (source / 'submission.json').is_file():
            copied.append(source / 'submission.json')
        for path in copied:
            shutil.copyfile(path, frozen / path.name)
        builds = []
        command = league.sweep._compile(arena, frozen / 'main.cpp', name, shutil.which('g++'), builds, frozen)
        arguments = runtime_args.get(name, [])
        command = shlex.join([*shlex.split(command), *arguments])
        manifest['bots'][name] = {
            'id': name, 'family': 'deadline_external', 'source_directory': str(source),
            'source': str((frozen / 'main.cpp').relative_to(arena)),
            'source_sha256': league.sha(frozen / 'main.cpp'),
            'input_files_sha256': {path.name: league.sha(frozen / path.name) for path in copied},
            'command': command, 'binary_sha256': league.sha(shlex.split(command)[0]), 'builds': builds,
            'runtime_args': arguments,
        }
    manifest['frozen_sha256'] = {
        str(path.relative_to(arena)): league.sha(path)
        for folder in (arena / 'snapshot', arena / 'bin')
        for path in sorted(folder.rglob('*')) if path.is_file()
    }
    manifest.update(status='ready', finished_utc=league.stamp())
    league.write(arena / 'manifest.json', manifest)
    print(json.dumps({'arena': str(arena), 'bots': list(manifest['bots']), 'status': 'ready'}), flush=True)


def compare(rows, baseline, candidates):
    index = {(r['candidate'], r['map_seed'], r['team'], r['opponent']): r for r in rows}
    result = {}
    for candidate in candidates:
        if candidate == baseline:
            continue
        result[candidate] = {}
        for team in 'YK':
            by_map, by_opponent = {}, {}
            for key, row in index.items():
                name, seed, side, opponent = key
                if name != candidate or side != team or row['status'] != 'complete':
                    continue
                reference = index.get((baseline, seed, side, opponent))
                if reference is None or reference['status'] != 'complete':
                    continue
                diff = (int(row['win']) + .5 * int(row['draw']) - int(reference['win']) - .5 * int(reference['draw']))
                by_map.setdefault(seed, []).append(diff)
                by_opponent.setdefault(opponent, []).append(diff)
            values = [sum(v) / len(v) for _, v in sorted(by_map.items())]
            rng = random.Random(20260929)
            samples = sorted(sum(rng.choices(values, k=len(values))) / len(values) for _ in range(2000)) if values else []
            result[candidate][team] = {
                'paired_maps': len(values), 'paired_games': sum(map(len, by_map.values())),
                'point_rate_difference': sum(values) / len(values) if values else None,
                'map_cluster_bootstrap_95pct': [samples[50], samples[1949]] if samples else None,
                'opponent_point_rate_difference': {name: sum(v) / len(v) for name, v in by_opponent.items()},
            }
    return {'baseline': baseline, 'comparisons': result,
            'interpretation': 'Small local fixed-opponent samples; no automatic promotion or leaderboard-score claim.'}


def run(args):
    arena = args.arena.resolve()
    candidates, opponents = csv(args.candidates), csv(args.opponents)
    if args.baseline not in candidates:
        raise ValueError('Baseline must be one of the candidates for matched comparisons')
    if args.maps < 1 or args.workers < 1 or args.seed_start < 0:
        raise ValueError('Invalid map range or worker count')
    if not re.fullmatch(r'[A-Za-z0-9_-]+', args.run_id):
        raise ValueError('Invalid run ID')
    manifest = json.loads((arena / 'manifest.json').read_text())
    plan = {'candidates': candidates, 'opponents': opponents,
            'map_seeds': list(range(args.seed_start, args.seed_start + args.maps)),
            'replays': 'all', 'order_seed': 20260929}
    jobs = league.make_jobs(plan, manifest['bots'])
    plans = arena / 'plans'
    plans.mkdir(exist_ok=True)
    plan_path = plans / (args.run_id + '.json')
    policy_path = plans / (args.run_id + '-policy.json')
    policy = {'created_utc': league.stamp(), 'stage': args.stage, 'baseline': args.baseline,
              'hypothesis': args.hypothesis, 'source_commit': manifest['source_commit'],
              'source_sha256': {name: manifest['bots'][name]['source_sha256'] for name in set(candidates + opponents)},
              'map_seeds': plan['map_seeds'], 'policy_rng_seed': manifest['policy_rng_seed'],
              'candidate_runtime_args': {name: manifest['bots'][name]['runtime_args']
                                         for name in sorted(set(candidates + opponents))
                                         if manifest['bots'][name].get('runtime_args')},
              'scheduled_jobs': len(jobs), 'workers': args.workers,
              'resource_policy': 'Official engine turn timeout; inherited 384MiB RLIMIT_AS after compilation',
              'stop_policy': 'Any error/forfeit blocks promotion; deadline decisions and candidate locking belong to the operator.'}
    if args.resume:
        if not plan_path.is_file() or json.loads(plan_path.read_text()) != plan:
            raise ValueError('Resume plan mismatch')
        previous = json.loads(policy_path.read_text())
        for key in ('stage', 'baseline', 'hypothesis', 'source_sha256', 'policy_rng_seed'):
            if previous.get(key) != policy[key]:
                raise ValueError('Resume policy mismatch: ' + key)
        if previous.get('candidate_runtime_args', {}) != policy['candidate_runtime_args']:
            raise ValueError('Resume policy mismatch: candidate_runtime_args')
    else:
        if plan_path.exists() or policy_path.exists():
            raise ValueError('Run ID already used; use --resume or a new ID')
        league.write(plan_path, plan)
        league.write(policy_path, policy)
    print(json.dumps({'event': 'start', 'jobs': len(jobs), 'run_id': args.run_id, 'workers': args.workers}), flush=True)
    with submission_address_space() as limit:
        league.write(arena / (args.run_id + '-resource-limit.json'), limit)
        league.run(arena, plan_path, args.run_id, args.workers, args.resume)
    rows = [json.loads(line) for line in (arena / 'runs' / args.run_id / 'results.jsonl').read_text().splitlines()]
    report = compare(rows, args.baseline, candidates)
    report.update(complete=len(rows) == len(jobs), errors=sum(r['status'] != 'complete' for r in rows),
                  forfeits=sum(bool(r.get('forfeit')) for r in rows))
    league.write(arena / 'runs' / args.run_id / 'paired-comparison.json', report)
    print(json.dumps(report), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    prep = sub.add_parser('prepare')
    prep.add_argument('--arena', type=Path, required=True)
    prep.add_argument('--candidate', action='append', default=[], help='NEW_ID=CPP_SOURCE_DIRECTORY; copied before freezing')
    prep.add_argument('--candidate-arg', action='append', default=[], help='CANDIDATE_ID=ONE_ARGUMENT; repeat for multiple arguments')
    play = sub.add_parser('run')
    play.add_argument('--arena', type=Path, required=True)
    play.add_argument('--run-id', required=True)
    play.add_argument('--baseline', default='v4')
    play.add_argument('--candidates', default='v4,v3')
    play.add_argument('--opponents', default=','.join(OPPONENTS))
    play.add_argument('--seed-start', type=int, required=True)
    play.add_argument('--maps', type=int, required=True)
    play.add_argument('--workers', type=int, default=6)
    play.add_argument('--stage', choices=['smoke', 'development', 'selection', 'final'], required=True)
    play.add_argument('--hypothesis', default='Current version and matched frozen opponents, both sides')
    play.add_argument('--resume', action='store_true')
    args = parser.parse_args()
    (prepare if args.action == 'prepare' else run)(args)


if __name__ == '__main__':
    main()
