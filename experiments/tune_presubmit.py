"""Build small, reviewable v1 variants; run paired development matches."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'records/tuning'
TEAM = shlex.join([sys.executable, str(ROOT / 'artifacts/opponents/delineate-v1/main.py')])
BASE = (ROOT / 'submissions/first/main.cpp').read_text()
LINEAR = [('tanh(evaluation(trial,us)/200.0)', 'evaluation(trial,us)/200.0')]
ASSETS = [
    ('if (board.type[b] == ENG && !has(s,t,ENG))',
     'if (board.type[b] == ENG && (!has(s,t,ENG) || s.owner[b] == t))'),
    ('(style == 1 ? 42 : 30)', '(style == 1 ? 75 : 55)'),
    ('.65*future*(val[t]-val[1-t])', '1.3*future*(val[t]-val[1-t])'),
    ('bonus += 70;', 'bonus += 110;'),
    ('(income(s,team)-10)*19', '(income(s,team)-10)*35'),
]
VARIANTS = {
    'linear': LINEAR,
    'assets': LINEAR + ASSETS,
    'lean': LINEAR + ASSETS + [
        ('style == 2 ? 5 : 7', 'style == 2 ? 4 : 6'),
        ('if (enemy_flag_dist[c] > 5 && !(available[F][c] && danger[c])) continue;',
         'if (enemy_flag_dist[c] > 5 && !near_enemy[c] && !(available[F][c] && danger[c])) continue;'),
    ],
}


def run(name, changes):
    folder = OUT / name
    folder.mkdir(parents=True, exist_ok=True)
    source = BASE
    for old, new in changes:
        assert source.count(old) == 1, (name, old)
        source = source.replace(old, new)
    (folder / 'main.cpp').write_text(source)
    (folder / 'changes.json').write_text(json.dumps(changes, indent=2))
    subprocess.run(['g++', '-std=c++20', '-O2', '-I', str(ROOT / 'submissions/first'),
                    str(folder/'main.cpp'), '-o', str(folder/'bot')], check=True)
    with (folder / 'development.log').open('w') as log:
        subprocess.run([sys.executable, str(ROOT/'tests/benchmark.py'),
                        '--candidate', str(folder/'bot'), '--opponent', TEAM,
                        '--start', '1000', '--seeds', '6', '--workers', '2',
                        '--output', str(folder/'development.json')], stdout=log, check=True, cwd=ROOT)
    result = json.loads((folder/'development.json').read_text())['summary']
    print(name, json.dumps(result), flush=True)
    return name, result


if __name__ == '__main__':
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda item: run(*item), VARIANTS.items()))
    (OUT/'summary.json').write_text(json.dumps(dict(results), indent=2))
