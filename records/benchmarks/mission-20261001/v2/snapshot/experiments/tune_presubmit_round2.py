"""Compare targeted economic defense, army value, and the expanded portfolio."""
from concurrent.futures import ThreadPoolExecutor
import json
import tune_presubmit as tune

VARIANTS = {
    'defense': [
        ('if (board.type[b] == ENG && !has(s,t,ENG))',
         'if (board.type[b] == ENG && (!has(s,t,ENG) || s.owner[b] == t))'),
        ('(style == 1 ? 42 : 30)', '(style == 1 ? 75 : 55)'),
        ('if (enemy_flag_dist[c] > 5 && !(available[F][c] && danger[c])) continue;',
         'if (enemy_flag_dist[c] > 5 && !near_enemy[c] && !(available[F][c] && danger[c])) continue;'),
    ],
    'army': [
        ('.65*future*(val[t]-val[1-t])', '2.0*future*(val[t]-val[1-t])'),
        ('tanh(evaluation(trial,us)/200.0)', 'tanh(evaluation(trial,us)/400.0)'),
    ],
    'portfolio-assets': [
        (tune.BASE, (tune.OUT/'portfolio/main.cpp').read_text()),
        *tune.LINEAR, *tune.ASSETS,
    ],
}

if __name__ == '__main__':
    with ThreadPoolExecutor(max_workers=3) as pool:
        results=list(pool.map(lambda item:tune.run(*item),VARIANTS.items()))
    (tune.OUT/'summary-round2.json').write_text(json.dumps(dict(results),indent=2))
