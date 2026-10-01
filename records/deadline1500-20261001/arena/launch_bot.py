"""Record the child cgroup, then replace this process with one frozen bot."""
import argparse
import json
import os
from pathlib import Path
import resource

parser = argparse.ArgumentParser()
parser.add_argument('--metadata', type=Path, required=True)
parser.add_argument('--unit', required=True)
parser.add_argument('--expected-cpu-max', required=True)
parser.add_argument('command', nargs=argparse.REMAINDER)
args = parser.parse_args()
command = args.command[1:] if args.command[:1] == ['--'] else args.command
relative = Path('/proc/self/cgroup').read_text().strip().split('::', 1)[1]
cgroup = Path('/sys/fs/cgroup') / relative.lstrip('/')
limits = {}
for filename in ['cpu.max', 'cpu.max.burst', 'cpu.stat', 'memory.max', 'memory.peak', 'cgroup.procs', 'cpuset.cpus.effective']:
    path = cgroup / filename
    limits[filename] = path.read_text().strip() if path.exists() else None
ancestors = []
for parent in [cgroup, *cgroup.parents]:
    if not str(parent).startswith('/sys/fs/cgroup'):
        break
    cpu = parent / 'cpu.max'
    ancestors.append({'path': str(parent), 'cpu.max': cpu.read_text().strip() if cpu.exists() else None})
assert cgroup.name == args.unit, (cgroup, args.unit)
if args.expected_cpu_max == 'unlimited':
    assert limits['cpu.max'] is None or limits['cpu.max'].startswith('max '), limits
else:
    assert limits['cpu.max'] == args.expected_cpu_max, limits
assert limits['memory.max'] == '402653184', limits
resource.setrlimit(resource.RLIMIT_AS, (402653184, 402653184))
metadata = {'pid': os.getpid(), 'cgroup': str(cgroup), 'unit': args.unit,
            'limits': limits, 'ancestors': ancestors, 'command': command,
            'rlimit_as': list(resource.getrlimit(resource.RLIMIT_AS))}
args.metadata.parent.mkdir(parents=True, exist_ok=True)
args.metadata.write_text(json.dumps(metadata, indent=2) + '\n')
os.execv(command[0], command)
