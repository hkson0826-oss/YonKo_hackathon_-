"""A short CPU-bound process for validating the temporary scope limit."""
import json
import time
from pathlib import Path
cpu_start = time.process_time()
wall_start = time.monotonic()
value = 0
while time.process_time() - cpu_start < .25:
    value = (value * 1103515245 + 12345) & 0x7fffffff
relative = Path('/proc/self/cgroup').read_text().strip().split('::', 1)[1]
cgroup = Path('/sys/fs/cgroup') / relative.lstrip('/')
print(json.dumps({'cpu_seconds': time.process_time() - cpu_start,
                  'wall_seconds': time.monotonic() - wall_start,
                  'cpu.max': (cgroup / 'cpu.max').read_text().strip() if (cgroup / 'cpu.max').exists() else None,
                  'cpu.stat': (cgroup / 'cpu.stat').read_text().strip()}))
