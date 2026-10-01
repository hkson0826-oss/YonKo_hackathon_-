"""Run copied analysis in the final directory shape and compare output bytes."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
H=Path(__file__).resolve().parent
parser=argparse.ArgumentParser();parser.add_argument('--repo-root',type=Path,required=True);args=parser.parse_args()
expected=['strength-analysis.json','enriched-matches.json','latest-opponents-loo.json','termination-merged.json','previous-rank-sensitivity.json','formula-checks.json','latest-official-metrics.json','results.md']
commands=['analyze_strength.py','rank_sensitivity.py','verify_existing_formula.py','compute_latest_metrics.py','write_report.py']
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
with tempfile.TemporaryDirectory(prefix='.relocation-',dir=H) as tmp:
 root=Path(tmp);dest=root/'records/official/submission-strength-20261001/method';dest.mkdir(parents=True)
 for script in commands:shutil.copy2(H/script,dest/script)
 for name in ['matches.json','leaderboard-latest.json','previous-rank-inference.json','leaderboard-help.json']:
  target=dest.parent/'data'/name;target.parent.mkdir(exist_ok=True);shutil.copy2(H.parent/'data'/name,target)
 for directory,name in [('history','known-termination.json'),('latest-detail','details.json')]:
  target=dest.parent/directory/name;target.parent.mkdir(exist_ok=True);shutil.copy2(H.parent/directory/name,target)
 inputs=list(json.loads((H/'formula-checks.json').read_text())['source_sha256'])+['records/official/opponent-intel-20260928/leaderboard-live-followup.json']
 for relative in inputs:
  target=root/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(args.repo_root/relative,target)
 execution=[]
 for script in commands:
  # No --repo-root: default discovery must find this relocated repository.
  result=subprocess.run([sys.executable,str(dest/script)],text=True,capture_output=True,timeout=30)
  execution.append({'script':script,'returncode':result.returncode,'stderr':result.stderr})
  assert result.returncode==0,execution[-1]
 checks={name:{'original':sha(H/name),'relocated':sha(dest/name),'identical':(H/name).read_bytes()==(dest/name).read_bytes()} for name in expected}
 assert all(row['identical'] for row in checks.values()),checks
result={'passed':True,'python':sys.version,'layout':'records/official/submission-strength-20261001/method','repo_root_flag_used':False,'source_hashes':{name:sha(H/name) for name in commands},'output_checks':checks,'execution':execution,'temporary_fixture_removed':True}
(H/'relocation-check.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'passed':True,'identical_outputs':len(checks),'temporary_fixture_removed':True}))
