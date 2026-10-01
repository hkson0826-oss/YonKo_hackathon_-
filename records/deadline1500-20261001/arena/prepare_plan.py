import concurrent.futures as cf
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import time
HERE=Path(__file__).resolve().parent
ARENA=Path('/tmp/yk-latest-teammates-arena-20261001')
OLD=json.loads(Path('/tmp/yk-quarter-cpu-20261001/plan.json').read_text())
MAN=json.loads((ARENA/'manifest.json').read_text())
COMPILER='/tmp/yk-gcc12-2bjbhm3o/gcc12-wrapper'
NAMES=['v8','mission4','v9_lock','v8_flagguard','s3_selective_contact','r3_opponent_league','j_balanced_portfolio','siphon']
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def build(name):
    source=Path('/tmp/yk-new-bot-20261001/submissions/deadline1500-flagguard-20261001') if name=='v8_flagguard' else ARENA/'snapshot/candidates'/name
    target=HERE/'sources'/name
    target.mkdir()
    for path in source.iterdir():
        if path.is_file() and (path.suffix in ('.cpp', '.hpp', '.h') or path.name == 'submission.json'):
            shutil.copy2(path, target/path.name)
    binary=HERE/'bin'/name
    command=[COMPILER,'-std=c++20','-O2','-DNDEBUG','-I',str(target),str(target/'main.cpp'),'-o',str(binary)]
    started=time.time()
    result=subprocess.run(command,capture_output=True,text=True,timeout=120)
    build={'command':command,'returncode':result.returncode,'stdout':result.stdout,'stderr':result.stderr,'elapsed_seconds':time.time()-started}
    (HERE/'builds'/f'{name}.json').write_text(json.dumps(build,indent=2)+'\n')
    assert result.returncode==0,build
    return name,{'command':str(binary),'binary_sha256':sha(binary),'source_directory':str(target),
                 'source_sha256':sha(target/'main.cpp'),'input_files_sha256':{str(p.relative_to(target)):sha(p) for p in sorted(target.rglob('*')) if p.is_file()},'build':build}
for directory in ['bin','builds','sources']: (HERE/directory).mkdir(exist_ok=True)
with cf.ThreadPoolExecutor(max_workers=4) as pool: bots=dict(pool.map(build,NAMES))
sources={str(ARENA/rel): value for rel,value in OLD['source_sha256'].items() if '/yk-development-tools/' in rel or '/experiments/' in rel}
for item in bots.values():
    for rel,value in item['input_files_sha256'].items(): sources[str(Path(item['source_directory'])/rel)]=value
plan={key:OLD[key] for key in ['conditions','server_cpu_quota_period','official_notice','first_turn_includes','whole_match_wall_seconds']}
plan.update(status='prepared_awaiting_root_commit_signal',arena=str(ARENA),bots=bots,source_sha256=sources,
    compiler={'path':COMPILER,'version':subprocess.run([COMPILER,'--version'],capture_output=True,text=True).stdout,'wrapper_sha256':sha(COMPILER)},
    candidates=NAMES[:4],opponents=NAMES[4:],hard_cutoff='2026-10-01T14:43:00+09:00',stop_scheduling_seconds_before_cutoff=40,
    max_workers=8,scope='Each game has a separate SDK worker and two independent transient 25% CPU/384 MiB scopes; runner is outside scopes.',
    expected_selection_games=128,expected_confirmation_games=64,selection_map_seeds=list(range(23500,23504)),confirmation_map_seeds=list(range(23600,23604)),
    selection_policy={'baseline':'v8','required':'all games complete; 0 bot errors/forfeits; 0 strict issues; all scopes independently verified and cleaned',
        'rank':['win points (W=1, D=0.5)','Y win points','worst-opponent win points','raw score difference'],
        'baseline_tie':'v8 wins any tie in overall win points',
        'confirmation':'Only one selected non-v8 candidate compared with v8; no sequential fallback selection on confirmation maps.',
        'replace_gate':'overall points, Y points, and j_balanced points each >= v8, and overall or Y strictly greater; otherwise v8',
        'v8_selection_wins':'skip duplicate confirmation and retain v8'},
    estimate={'old_quarter_seconds_per_game':20,'192_games_8_workers_seconds':480,'conservative_30_seconds_per_game_total_seconds':720,
              'cpu_logical':20,'available_memory_gib_observed':18.1,'bot_max_aggregate_vcpu':4,'bot_max_aggregate_memory_gib':6},
    limitations=['Server quota period unpublished; local100ms period is explicit.','v9_lock has time seeded RNG; no unsupported seed CLI passed.','This is a small local paired comparison, not official leaderboard performance.'],jobs=[])
for phase,seeds in [('selection',plan['selection_map_seeds']),('confirmation',plan['confirmation_map_seeds'])]:
    for seed in seeds:
        for opponent in plan['opponents']:
            for candidate in plan['candidates']:
                for side in 'YK':
                    plan['jobs'].append({'id':f'{phase}-{candidate}-{opponent}-{side}-{seed}','phase':phase,'condition':'quarter','candidate':candidate,'opponent':opponent,'candidate_side':side,'map_seed':seed,
                        'Y':candidate if side=='Y' else opponent,'K':opponent if side=='Y' else candidate})
plan['harness_sha256']={name:sha(HERE/name) for name in ['scope_runtime.py','launch_bot.py','busy_probe.py','parallel_matches.py','prepare_plan.py']}
(HERE/'plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'bots':len(bots),'sources':len(sources),'plan_sha256':sha(HERE/'plan.json'),'harness':plan['harness_sha256']},indent=2),flush=True)
