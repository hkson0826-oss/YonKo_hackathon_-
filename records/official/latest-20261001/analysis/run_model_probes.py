"""Reproduce a fixed public-state, one-turn policy-model counterexample."""
from pathlib import Path
import argparse
import hashlib
import json
import subprocess
import tempfile

parser = argparse.ArgumentParser()
repo = next((p for p in Path(__file__).resolve().parents
    if (p / 'submissions/deadline-20260929-guard3/main.cpp').exists()), Path('/home/dlwltkd/YonKo_hackathon_-'))
parser.add_argument('--source', type=Path, default=repo / 'submissions/deadline-20260929-guard3/main.cpp')
parser.add_argument('--output', type=Path)
args = parser.parse_args()
folder = Path(__file__).resolve().parent
payload = (folder / 'probe_v8_models-input.txt').read_text()
assert '0 101 102 2 0' in payload
variants = {
    'recorded': payload,
    'flag_up_only': payload.replace('0 101 102 2 0', '0 101 86 2 0'),
    'flag_and_escort_up': payload.replace('0 101 102 2 0', '0 101 86 2 0').replace('1 101 102 2 0', '1 101 86 2 0'),
}
with tempfile.TemporaryDirectory(prefix='yk-one-turn-model-', dir='/tmp') as temp:
    binary = Path(temp) / 'probe'
    subprocess.run(['g++', '-std=c++20', '-O2', '-I', str(args.source.parent),
                    str(folder / 'probe_v8_models.cpp'), '-o', str(binary)], check=True)
    result = {name: json.loads(subprocess.run([str(binary)], input=data, text=True,
                    capture_output=True, check=True).stdout) for name, data in variants.items()}
report = {
    'scope': 'Recorded turn29 own action and two legal local alternatives against four internal opponent policies and no-op. A one-turn model probe, not reproduction of the original timed choice or actual hidden opponent orders. No full-game win claim.',
    'source_path': str(args.source),
    'source_sha256': hashlib.sha256(args.source.read_bytes()).hexdigest(),
    'input_sha256': hashlib.sha256(payload.encode()).hexdigest(),
    'bridge_sha256': hashlib.sha256((folder / 'probe_v8_models.cpp').read_bytes()).hexdigest(),
    'results': result,
}
output = args.output or folder / 'model-probe-reproducible.json'
output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
print(output)
