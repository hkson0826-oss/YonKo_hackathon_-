"""Check whether conservative warrior routing stalls reinforcements."""
from concurrent.futures import ThreadPoolExecutor
import json
import tune_presubmit as tune
from tune_presubmit_round2 import VARIANTS as ROUND2

MARCH=[('if (loss) v -= min(16.0,2.0*loss) * (style == 2 ? .55 : 1.0);',
        'if (loss) v -= min(3.0,0.3*loss) * (style == 2 ? .55 : 1.0);')]
VARIANTS={
    'march':MARCH,
    'march-defense':MARCH+ROUND2['defense'],
    'march-army':MARCH+ROUND2['army'],
}
if __name__ == '__main__':
    with ThreadPoolExecutor(max_workers=3) as pool:
        results=list(pool.map(lambda item:tune.run(*item),VARIANTS.items()))
    (tune.OUT/'summary-round3.json').write_text(json.dumps(dict(results),indent=2))
