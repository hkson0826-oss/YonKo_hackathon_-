"""Run a frozen league over SSH entirely in a disposable remote /tmp directory.

Example: python3 experiments/run_remote_tmp.py --host yonsei-root \
  --output-dir records/benchmarks/remote-run --command python3 \
  experiments/league_campaign.py --arena output --workers 16
"""
from __future__ import annotations

import argparse
import base64
import ctypes
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import resource
import selectors
import shlex
import shutil
import signal
import struct
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import traceback


ROOT = Path(__file__).resolve().parents[1]
MAX_ARCHIVE_BYTES = 20 * 1024**3
SKIP_PARTS = {".git", "bin", "__pycache__", ".pytest_cache", ".venv", "venv", ".firecrawl"}
SKIP_SUFFIXES = {".pyc", ".pyo", ".o", ".so", ".a", ".ptx", ".cubin"}


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_relative(name):
    path = PurePosixPath(name)
    if path.is_absolute() or not path.parts or ".." in path.parts or "\\" in name:
        raise ValueError(f"Unsafe archive path: {name!r}")
    return Path(*path.parts)


def safe_extract(archive, destination, max_bytes=MAX_ARCHIVE_BYTES):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    total = 0
    with tarfile.open(archive, "r:gz") as source:
        for member in source:
            relative = safe_relative(member.name)
            if not (member.isfile() or member.isdir()):
                raise ValueError(f"Archive links/devices are forbidden: {member.name}")
            target = destination / relative
            if not target.resolve().is_relative_to(destination.resolve()):
                raise ValueError(f"Archive path leaves destination: {member.name}")
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            total += member.size
            if member.size < 0 or total > max_bytes:
                raise ValueError("Archive exceeds extraction size limit")
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as output, source.extractfile(member) as incoming:
                shutil.copyfileobj(incoming, output, length=1024 * 1024)
            target.chmod(0o600)
    return total


def source_files(root):
    root = Path(root)
    paths = set((root / "experiments").glob("*.py"))
    paths.update((root / "experiments/local_league").glob("*.py"))
    for directory in ("submissions/first", "submissions/tuned"):
        paths.update(p for p in (root / directory).glob("*") if p.suffix in {".cpp", ".hpp", ".json"})
    paths.add(root / "submissions/delineate-v1.zip")
    for directory in ("engine", "runner", "mapgen", "config", "bots/dist/starter/python"):
        paths.update(p for p in (root / "yk-development-tools" / directory).rglob("*")
                     if p.suffix in {".py", ".json"})
    selected = []
    for path in sorted(paths):
        relative = path.relative_to(root)
        if path.is_symlink() or not path.is_file() or set(relative.parts) & SKIP_PARTS:
            raise ValueError(f"Missing or forbidden source: {relative}")
        selected.append(relative)
    return selected


def pack_sources(root, archive):
    paths = source_files(root)
    with tarfile.open(archive, "w:gz") as output:
        for relative in paths:
            output.add(Path(root) / relative, arcname=str(relative), recursive=False)
    return {str(relative): digest(Path(root) / relative) for relative in paths}


def pack_results(root, archive):
    with tarfile.open(archive, "w:gz") as output:
        for path in sorted(Path(root).rglob("*")):
            relative = path.relative_to(root)
            if set(relative.parts) & SKIP_PARTS or path.suffix in SKIP_SUFFIXES:
                continue
            if path.is_symlink():
                raise ValueError(f"Result contains a symlink: {relative}")
            if not path.is_file():
                continue
            with path.open("rb") as stream:
                if stream.read(4) == b"\x7fELF":
                    continue
            output.add(path, arcname=str(relative), recursive=False)


def read_exact(stream, count):
    parts = []
    while count:
        data = stream.read(min(count, 1024 * 1024))
        if not data:
            raise EOFError("Transport closed before the framed archive finished")
        parts.append(data)
        count -= len(data)
    return b"".join(parts)


def receive_archive(stream, path):
    size = struct.unpack("!Q", read_exact(stream, 8))[0]
    if size <= 0 or size > MAX_ARCHIVE_BYTES:
        raise ValueError(f"Invalid framed archive size: {size}")
    with Path(path).open("wb") as output:
        remaining = size
        while remaining:
            data = read_exact(stream, min(1024 * 1024, remaining))
            output.write(data)
            remaining -= len(data)
    return size


def send_archive(stream, path):
    stream.write(struct.pack("!Q", Path(path).stat().st_size))
    with Path(path).open("rb") as incoming:
        shutil.copyfileobj(incoming, stream, length=1024 * 1024)
    stream.flush()


def memory_info():
    values = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        key, value = line.split(":", 1)
        values[key] = int(value.strip().split()[0]) * 1024
    return values


def compute_limits(affinity, available_memory, workers, process_mib=768):
    cpus = sorted(affinity)
    if len(cpus) < 2:
        raise ValueError("At least two allowed CPUs are needed for a strict 90% affinity ceiling")
    cpu_count = math.floor(len(cpus) * .9)
    if workers < 1 or workers > cpu_count:
        raise ValueError(f"Workers must be between 1 and {cpu_count}")
    process_bytes = process_mib * 1024**2
    # One worker and two shell+bot pairs per game, plus controller/compiler slack.
    expected_processes = 5 * workers + 8
    memory_ceiling = math.floor(available_memory * .9)
    if process_mib < 128 or expected_processes * process_bytes > memory_ceiling:
        raise ValueError("Per-process address-space limits exceed the 90% memory budget")
    return {"affinity_before": cpus, "affinity": cpus[:cpu_count], "cpu_fraction": cpu_count / len(cpus),
            "workers": workers, "process_address_space_bytes": process_bytes,
            "expected_process_count_bound": expected_processes,
            "expected_address_space_bound_bytes": expected_processes * process_bytes,
            "memory_available_before_bytes": available_memory, "memory_budget_bytes": memory_ceiling,
            "memory_bound_note": "RLIMIT_AS is per process; the aggregate bound assumes the frozen league worker topology."}


def command_workers(command):
    values = []
    for index, value in enumerate(command):
        if value == "--workers":
            values.append(int(command[index + 1]))
        elif value.startswith("--workers="):
            values.append(int(value.split("=", 1)[1]))
    if len(values) > 1:
        raise ValueError("Pass --workers only once in the remote command")
    return values[0] if values else 1


def remote_bootstrap(config):
    def event(kind, **data):
        print(json.dumps({"event": kind, "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **data}),
              file=sys.stderr, flush=True)

    cancelled = threading.Event()
    acknowledgement = threading.Event()
    ack = {"value": None}
    signal_reason = {"value": None}
    def on_signal(signum, _frame):
        signal_reason["value"] = signum
        cancelled.set()
    for signum in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
        signal.signal(signum, on_signal)
    # Adopt and reap grandchildren if their parent exits while a bot is running.
    subreaper = ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) == 0
    temporary = tempfile.TemporaryDirectory(prefix="yk-league-", dir="/tmp")
    task_root = Path(temporary.name)
    task_root.chmod(0o700)
    process = None
    returncode = 1
    result = {"status": "starting", "command": config["command"], "source_commit": config.get("source_commit"),
              "input_sha256": config.get("input_sha256", {}), "subreaper": subreaper,
              "cleanup_limit": "SIGKILL, host failure, or filesystem failure can prevent cleanup."}
    event("temporary_created", path=str(task_root))
    output = task_root / safe_relative(config["remote_output"])
    try:
        incoming = task_root / "source.tar.gz"
        receive_archive(sys.stdin.buffer, incoming)
        workspace = task_root / "workspace"
        def monitor_input():
            try:
                ack["value"] = sys.stdin.buffer.readline().decode("ascii", errors="replace").strip()
            except OSError:
                ack["value"] = ""
            if not ack["value"]:
                cancelled.set()
            acknowledgement.set()
        threading.Thread(target=monitor_input, daemon=True).start()
        safe_extract(incoming, workspace)
        incoming.unlink()
        for relative, expected in config.get("input_sha256", {}).items():
            if digest(workspace / safe_relative(relative)) != expected:
                raise ValueError(f"Input snapshot checksum mismatch: {relative}")
        output = workspace / safe_relative(config["remote_output"])
        memory = memory_info()
        limits = compute_limits(os.sched_getaffinity(0), memory["MemAvailable"],
                                command_workers(config["command"]), config["process_mib"])
        result.update(limits=limits, memory_total_bytes=memory["MemTotal"], load_before=list(os.getloadavg()))
        event("limits", **limits, load_before=result["load_before"])
        temp_dir = task_root / "tmp"
        temp_dir.mkdir(mode=0o700)
        env = dict(os.environ, TMPDIR=str(temp_dir), TMP=str(temp_dir), TEMP=str(temp_dir),
                   PYTHONDONTWRITEBYTECODE="1", YK_SOURCE_COMMIT=config.get("source_commit") or "unversioned",
                   OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1")
        # Apply to this disposable supervisor so every descendant inherits limits;
        # avoid Python preexec_fn after the transport monitor thread has started.
        os.sched_setaffinity(0, limits["affinity"])
        resource.setrlimit(resource.RLIMIT_AS, (limits["process_address_space_bytes"],) * 2)
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        os.nice(5)
        process = subprocess.Popen(config["command"], cwd=workspace, env=env, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   start_new_session=True)
        start = time.monotonic()
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        carry = b""
        while process.poll() is None or selector.get_map():
            if cancelled.is_set() or time.monotonic() - start > config["wall_seconds"]:
                result["stop_reason"] = "signal_or_disconnect" if cancelled.is_set() else "wall_timeout"
                break
            if memory_info()["MemAvailable"] < memory["MemTotal"] * .1:
                result["stop_reason"] = "host_memory_reserve_below_10_percent"
                break
            for key, _ in selector.select(timeout=.25):
                chunk = os.read(key.fileobj.fileno(), 65536)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                carry += chunk
                while b"\n" in carry:
                    line, carry = carry.split(b"\n", 1)
                    event("progress", line=line.decode("utf-8", errors="replace"))
                if len(carry) > 65536:
                    event("progress", line=carry.decode("utf-8", errors="replace"));carry = b""
        selector.close()
        if carry:
            event("progress", line=carry.decode("utf-8", errors="replace"))
        if "stop_reason" in result:
            try: os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError: pass
        try:
            returncode = process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            returncode = process.wait(timeout=5)
        result.update(status="complete" if returncode == 0 and "stop_reason" not in result else "failed",
                      returncode=returncode, wall_seconds=time.monotonic()-start, signal=signal_reason["value"])
    except BaseException as error:
        result.update(status="failed", exception=repr(error), traceback=traceback.format_exc())
        event("error", message=repr(error))
        if not (task_root / "workspace").exists():
            acknowledgement.set()
    finally:
        if process is not None:
            # Also clean up orphaned bot shells after an otherwise successful controller exit.
            try: os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError: pass
            time.sleep(.05)
            try: os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError: pass
            process.wait(timeout=5)
            if subreaper:
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    try:
                        pid, _ = os.waitpid(-1, os.WNOHANG)
                        if pid == 0: time.sleep(.02)
                    except ChildProcessError:
                        break
        try:
            if cancelled.is_set() and (signal_reason["value"] is not None or ack["value"] == ""):
                raise ConnectionAbortedError("Controller disconnected or terminated; cleanup takes priority over result transfer")
            output.mkdir(parents=True, exist_ok=True)
            (output / "remote_supervisor.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
            archive = task_root / "result.tar.gz"
            pack_results(output, archive)
            event("archive_ready", sha256=digest(archive), bytes=archive.stat().st_size, status=result["status"])
            send_archive(sys.stdout.buffer, archive)
            # The receiver verifies and extracts the archive before acknowledging it.
            ack_deadline = time.monotonic() + 120
            while not acknowledgement.wait(timeout=.25) and not cancelled.is_set() and time.monotonic() < ack_deadline:
                pass
            event("archive_acknowledgement", value=ack["value"])
        except BaseException as error:
            event("archive_error", message=repr(error))
        finally:
            temporary.cleanup()
            event("cleanup_complete", path=str(task_root), exists=task_root.exists(),
                  archive_accepted=ack["value"] == "OK")
    return 0 if result["status"] == "complete" and ack["value"] == "OK" else 1


def run_transport(transport, config, source_archive, output_dir):
    output_dir = Path(output_dir)
    if output_dir.exists():
        raise FileExistsError(output_dir)
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    events = []
    with tempfile.TemporaryDirectory(prefix="yk-remote-receive-", dir="/tmp") as local_temp:
        local_temp = Path(local_temp)
        stderr_file = local_temp / "transport.jsonl"
        process = subprocess.Popen(transport, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        def stderr_reader():
            with stderr_file.open("w") as log:
                for raw in iter(process.stderr.readline, b""):
                    line = raw.decode("utf-8", errors="replace").rstrip("\n")
                    try: event = json.loads(line)
                    except json.JSONDecodeError: event = {"event": "transport_stderr", "line": line}
                    if not isinstance(event, dict):
                        event = {"event": "transport_stderr", "line": line}
                    events.append(event)
                    log.write(json.dumps(event, ensure_ascii=False) + "\n");log.flush()
                    print(json.dumps(event, ensure_ascii=False), file=sys.stderr, flush=True)
        reader = threading.Thread(target=stderr_reader, daemon=True)
        reader.start()
        received = local_temp / "download.tar.gz"
        extracted = local_temp / "results"
        error = None
        try:
            send_archive(process.stdin, source_archive)
            size = receive_archive(process.stdout, received)
            sha256 = digest(received)
            safe_extract(received, extracted)
            # The remote hash travels on stderr, so allow the reader to catch up.
            deadline = time.monotonic() + 5
            while not any(e.get("event") == "archive_ready" for e in events) and time.monotonic() < deadline:
                time.sleep(.01)
            announced = next((e for e in events if e.get("event") == "archive_ready"), None)
            if announced is None or announced.get("sha256") != sha256 or announced.get("bytes") != size:
                raise ValueError("Returned archive checksum/size was not confirmed by the remote supervisor")
            process.stdin.write(b"OK\n");process.stdin.flush();process.stdin.close()
            returncode = process.wait(timeout=30)
            reader.join(timeout=5)
            cleanup = next((e for e in reversed(events) if e.get("event") == "cleanup_complete"), None)
            if cleanup is None or cleanup.get("exists") or not cleanup.get("archive_accepted"):
                raise RuntimeError("Remote temporary-directory cleanup was not confirmed")
            receipt = {"transport": transport[:2], "command": config["command"], "returncode": returncode,
                       "archive_sha256": sha256, "archive_bytes": size, "cleanup": cleanup}
            (extracted / "transport_receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
        except BaseException as caught:
            error = caught
            try: process.stdin.close()
            except (OSError, ValueError): pass
            try: process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.terminate()
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired: process.kill();process.wait()
            reader.join(timeout=5)
        finally:
            extracted.mkdir(exist_ok=True)
            if stderr_file.exists(): shutil.copyfile(stderr_file, extracted / "transport.jsonl")
            if error:
                (extracted / "transport_failure.json").write_text(json.dumps({"error": repr(error),
                    "cleanup_confirmed": any(e.get("event") == "cleanup_complete" and not e.get("exists") for e in events)}, indent=2) + "\n")
            shutil.move(str(extracted), str(output_dir))
        if error:
            raise error
        return returncode


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--bootstrap":
        return remote_bootstrap(json.loads(base64.b64decode(sys.argv[2])))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--remote-output", default="output")
    parser.add_argument("--wall-seconds", type=float, default=7200)
    parser.add_argument("--process-mib", type=int, default=768)
    parser.add_argument("--command", nargs=argparse.REMAINDER, required=True)
    args = parser.parse_args()
    if not args.command or args.host.startswith("-") or args.wall_seconds <= 0:
        parser.error("A command, valid SSH host, and positive wall timeout are required")
    safe_relative(args.remote_output)
    command_workers(args.command)
    if args.output_dir.exists():
        parser.error("--output-dir must not exist")
    with tempfile.TemporaryDirectory(prefix="yk-remote-send-") as directory:
        archive = Path(directory) / "source.tar.gz"
        inputs = pack_sources(ROOT, archive)
        source_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        config = {"command": args.command, "remote_output": args.remote_output, "wall_seconds": args.wall_seconds,
                  "process_mib": args.process_mib, "source_commit": source_commit, "input_sha256": inputs}
        encoded = base64.b64encode(Path(__file__).read_bytes()).decode()
        code = "import base64;__file__='yk_remote_bootstrap.py';exec(compile(base64.b64decode(" + repr(encoded) + "),__file__,'exec'))"
        request = base64.b64encode(json.dumps(config).encode()).decode()
        remote_command = "exec " + shlex.join(["python3", "-c", code, "--bootstrap", request])
        transport = ["ssh", "-T", "-o", "BatchMode=yes", "-o", "ServerAliveInterval=15",
                     "-o", "ServerAliveCountMax=3", args.host, remote_command]
        return run_transport(transport, config, archive, args.output_dir)


if __name__ == "__main__":
    raise SystemExit(main())
