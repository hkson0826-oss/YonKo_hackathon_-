"""Measure one exact evaluator on CPU/CUDA; this does not simulate games."""
from __future__ import annotations

import argparse
from collections import deque
import ctypes as C
from datetime import datetime, timezone
import hashlib
import itertools
import json
import math
import os
from pathlib import Path
import platform
import random
import statistics
import subprocess
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
CELLS, BUILDINGS = 225, 17
TYPES = ["PLAZA", "HALL", "STATION", "LIBRARY", "ENG", "HOSPITAL", "WATCH", "DEPOT"]


class Position(C.Structure):
    _fields_ = [
        ("turn", C.c_int), ("nb", C.c_int), ("team", C.c_int),
        ("resource", C.c_int * 2), ("army_value", C.c_int * 2),
        ("flags", (C.c_int * CELLS) * 2),
        ("owner", C.c_int * BUILDINGS), ("type", C.c_int * BUILDINGS),
        ("claimed", (C.c_int * BUILDINGS) * 2),
        ("building_position", C.c_int * BUILDINGS), ("base_position", C.c_int * 2),
        ("distance", (C.c_int * BUILDINGS) * CELLS),
        ("base_distance", (C.c_int * BUILDINGS) * 2),
        ("building_distance", (C.c_int * BUILDINGS) * BUILDINGS),
        ("score", C.c_double * BUILDINGS), ("occupation", C.c_double * 2),
    ]


class Parameters(C.Structure):
    _fields_ = [("engineering", C.c_double), ("hall_income", C.c_double), ("army", C.c_double)]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def utc():
    return datetime.now(timezone.utc).isoformat()


def distances(terrain, start):
    result = [10000] * CELLS
    result[start] = 0
    queue = deque([start])
    while queue:
        cell = queue.popleft()
        x, y = cell % 15, cell // 15
        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if 0 <= nx < 15 and 0 <= ny < 15 and terrain[ny][nx] != "#":
                nxt = nx + ny * 15
                if result[nxt] == 10000:
                    result[nxt] = result[cell] + 1
                    queue.append(nxt)
    return result


def legal_positions(path):
    replay = json.loads(path.read_text())
    observations = [row["observation"] for row in replay["turns"]]
    terrain = observations[0]["map"]
    buildings = observations[0]["buildings"]
    if len(buildings) > BUILDINGS:
        raise ValueError("Too many buildings")
    homes = [x + y * 15 for y, row in enumerate(terrain) for x, value in enumerate(row) if value == "H"]
    # The original INIT discloses both bases. This replay omits INIT; own first
    # move reveals which of its two already-public home tiles is ours.
    own = {int(parts[1]) + 15 * int(parts[2])
           for line in replay["turns"][1]["command"]["lines"]
           if (parts := line.split())[0] in ("MOVE", "MOVE2", "TELE")
           and int(parts[1]) + 15 * int(parts[2]) in homes}
    if len(homes) != 2 or len(own) != 1:
        raise ValueError("Cannot identify disclosed bases")
    side = 0 if replay["side"] == "Y" else 1
    bases = [0, 0]
    bases[side] = own.pop()
    bases[1 - side] = next(c for c in homes if c != bases[side])
    coords = [b["x"] + 15 * b["y"] for b in buildings]
    distance_to = [distances(terrain, cell) for cell in coords]
    base = Position()
    base.nb, base.team = len(buildings), side
    for t in range(2):
        base.base_position[t] = bases[t]
    for b, building in enumerate(buildings):
        base.type[b] = TYPES.index(building["type"])
        base.building_position[b] = coords[b]
        for cell in range(CELLS):
            base.distance[cell][b] = distance_to[b][cell]
        for t in range(2):
            base.base_distance[t][b] = distance_to[b][bases[t]]
        for j in range(len(buildings)):
            base.building_distance[b][j] = distance_to[j][coords[b]]
    history = [[0] * len(buildings) for _ in range(2)]
    claimed = [[False] * len(buildings) for _ in range(2)]
    for obs in observations:
        s = Position.from_buffer_copy(base)
        s.turn = obs["turn"]
        for t, team in enumerate(("Y", "K")):
            s.resource[t] = obs["resources"][team]
        for team, kind, x, y, count in obs["units"]:
            t = 0 if team == "Y" else 1
            s.army_value[t] += count * {"F": 5, "W": 3, "S": 2}[kind]
            if kind == "F":
                s.flags[t][x + 15 * y] += count
        for b, building in enumerate(obs["buildings"]):
            s.owner[b] = {"N": -1, "Y": 0, "K": 1}[building["owner"]]
            s.score[b] = building.get("score", -1)
            owner = s.owner[b]
            if owner >= 0:
                if obs["turn"] > 0:
                    history[owner][b] += 1
                if building["type"] == "DEPOT":
                    claimed[owner][b] = True
        # Match v2's ordered mirror/default estimates, including its uncertainty.
        for b, cell in enumerate(coords):
            if s.score[b] < 0:
                mirror = coords.index(224 - cell) if 224 - cell in coords else -1
                s.score[b] = s.score[mirror] if mirror >= 0 and s.score[mirror] >= 0 else (
                    3 if s.type[b] == 0 or 5 <= cell % 15 <= 9 else 1.5)
        for t in range(2):
            for b in range(s.nb):
                s.claimed[t][b] = claimed[t][b]
                s.occupation[t] += history[t][b] * s.score[b]
        yield s


def parameter_grid():
    return [Parameters(*values) for values in itertools.product(
        (55., 82.5, 110., 137.5, 165.), (17.5, 26.25, 35., 43.75, 52.5),
        (.65, .975, 1.3, 1.625, 1.95))]


def compile_cpu(output_dir):
    target = output_dir / "cpu_bridge.so"
    command = ["g++", "-std=c++20", "-O3", "-fopenmp", "-ffp-contract=off", "-fPIC", "-shared",
               str(HERE / "cpu_bridge.cpp"), "-o", str(target)]
    start = time.perf_counter()
    done = subprocess.run(command, capture_output=True, text=True)
    (output_dir / "cpu-build.log").write_text(done.stdout + done.stderr)
    done.check_returncode()
    elapsed = time.perf_counter() - start
    lib = C.CDLL(str(target.resolve()))
    lib.probe_position_size.restype = lib.probe_parameter_size.restype = C.c_size_t
    if lib.probe_position_size() != C.sizeof(Position) or lib.probe_parameter_size() != C.sizeof(Parameters):
        raise RuntimeError("C++/Python ABI mismatch")
    lib.probe_cpu.argtypes = [C.POINTER(Position), C.c_int, C.POINTER(Parameters), C.c_int,
                             C.POINTER(C.c_double), C.c_int, C.c_int]
    lib.probe_original.argtypes = [C.POINTER(Position), C.c_int, C.POINTER(C.c_double)]
    lib.probe_cpu.restype = lib.probe_original.restype = None
    return lib, {"command": command, "seconds": elapsed, "sha256": sha(target),
                 "compiler": subprocess.check_output(["g++", "--version"], text=True).splitlines()[0]}


def compile_cuda(nvrtc_path, architecture, output_dir):
    info = {"nvrtc_library": str(nvrtc_path), "nvrtc_sha256": sha(nvrtc_path)}
    nvrtc = C.CDLL(str(nvrtc_path))

    def rtc(name, signature, *args):
        fn = getattr(nvrtc, name)
        fn.argtypes, fn.restype = signature, C.c_int
        code = fn(*args)
        if code:
            raise RuntimeError(f"{name} failed: {code}")

    program = C.c_void_p()
    header = (C.c_char_p * 1)((HERE / "evaluation_shared.hpp").read_bytes())
    names = (C.c_char_p * 1)(b"evaluation_shared.hpp")
    rtc("nvrtcCreateProgram", [C.POINTER(C.c_void_p), C.c_char_p, C.c_char_p, C.c_int,
                              C.POINTER(C.c_char_p), C.POINTER(C.c_char_p)],
        C.byref(program), (HERE / "evaluation_kernel.cu").read_bytes(), b"evaluation_kernel.cu", 1, header, names)
    options = [b"--std=c++17", f"--gpu-architecture=compute_{architecture}".encode(), b"--fmad=false"]
    start = time.perf_counter()
    try:
        rtc("nvrtcCompileProgram", [C.c_void_p, C.c_int, C.POINTER(C.c_char_p)], program, len(options),
            (C.c_char_p * len(options))(*options))
    finally:
        size = C.c_size_t()
        rtc("nvrtcGetProgramLogSize", [C.c_void_p, C.POINTER(C.c_size_t)], program, C.byref(size))
        log = C.create_string_buffer(size.value)
        rtc("nvrtcGetProgramLog", [C.c_void_p, C.c_void_p], program, log)
        (output_dir / "cuda-build.log").write_bytes(log.value)
    info["compile_seconds"] = time.perf_counter() - start
    info["compile_options"] = [option.decode() for option in options]
    size = C.c_size_t()
    rtc("nvrtcGetPTXSize", [C.c_void_p, C.POINTER(C.c_size_t)], program, C.byref(size))
    ptx = C.create_string_buffer(size.value)
    rtc("nvrtcGetPTX", [C.c_void_p, C.c_void_p], program, ptx)
    (output_dir / "evaluation.ptx").write_bytes(ptx.value)
    rtc("nvrtcDestroyProgram", [C.POINTER(C.c_void_p)], C.byref(program))
    info["ptx_sha256"] = sha(output_dir / "evaluation.ptx")
    return ptx, info


class CUDAUnavailable(RuntimeError):
    pass


class CUDA:
    def __init__(self, ptx, device):
        self.driver = C.CDLL("libcuda.so.1")
        self.bindings = {}
        self.allocations, self.events = [], []
        self.context, self.module = C.c_void_p(), C.c_void_p()
        self.call("cuInit", [C.c_uint], 0)
        dev = C.c_int()
        self.call("cuDeviceGet", [C.POINTER(C.c_int), C.c_int], C.byref(dev), device)
        name = C.create_string_buffer(256)
        self.call("cuDeviceGetName", [C.c_void_p, C.c_int, C.c_int], name, 256, dev)
        major, minor = C.c_int(), C.c_int()
        self.call("cuDeviceGetAttribute", [C.POINTER(C.c_int), C.c_int, C.c_int], C.byref(major), 75, dev)
        self.call("cuDeviceGetAttribute", [C.POINTER(C.c_int), C.c_int, C.c_int], C.byref(minor), 76, dev)
        self.call("cuCtxCreate_v2", [C.POINTER(C.c_void_p), C.c_uint, C.c_int], C.byref(self.context), 0, dev)
        version = C.c_int()
        self.call("cuDriverGetVersion", [C.POINTER(C.c_int)], C.byref(version))
        self.info = {"name": name.value.decode(), "ordinal": device, "compute_capability": f"{major.value}.{minor.value}",
                     "driver_api_version": version.value}
        self.call("cuModuleLoadData", [C.POINTER(C.c_void_p), C.c_void_p], C.byref(self.module), ptx)
        self.function = C.c_void_p()
        self.call("cuModuleGetFunction", [C.POINTER(C.c_void_p), C.c_void_p, C.c_char_p],
                  C.byref(self.function), self.module, b"evaluate_batch")

    def call(self, name, signature, *args):
        fn = self.bindings.get(name)
        if fn is None:
            fn = getattr(self.driver, name)
            fn.argtypes, fn.restype = signature, C.c_int
            self.bindings[name] = fn
        error = fn(*args)
        if error in (100, 3, 802, 803, 804) and name in ("cuInit", "cuDeviceGet"):
            raise CUDAUnavailable(f"{name} failed with CUDA driver code {error}")
        if error:
            raise RuntimeError(f"{name} failed with CUDA driver code {error}")

    def allocate(self, size):
        pointer = C.c_uint64()
        self.call("cuMemAlloc_v2", [C.POINTER(C.c_uint64), C.c_size_t], C.byref(pointer), size)
        self.allocations.append(pointer)
        return pointer

    def upload(self, pointer, value):
        self.call("cuMemcpyHtoD_v2", [C.c_uint64, C.c_void_p, C.c_size_t], pointer, C.addressof(value), C.sizeof(value))

    def download(self, value, pointer):
        self.call("cuMemcpyDtoH_v2", [C.c_void_p, C.c_uint64, C.c_size_t], C.addressof(value), pointer, C.sizeof(value))

    def event(self):
        event = C.c_void_p()
        self.call("cuEventCreate", [C.POINTER(C.c_void_p), C.c_uint], C.byref(event), 0)
        self.events.append(event)
        return event

    def record(self, event):
        self.call("cuEventRecord", [C.c_void_p, C.c_void_p], event, None)

    def sync(self):
        self.call("cuCtxSynchronize", [])

    def launch(self, positions, states, parameters, params, output, count):
        values = [positions, C.c_int(states), parameters, C.c_int(params), output, C.c_int(count)]
        arguments = (C.c_void_p * len(values))(*(C.addressof(value) for value in values))
        self.call("cuLaunchKernel", [C.c_void_p] + [C.c_uint] * 7 + [C.c_void_p, C.c_void_p, C.c_void_p],
                  self.function, (count + 127) // 128, 1, 1, 128, 1, 1, 0, None, arguments, None)

    def elapsed(self, start, stop):
        result = C.c_float()
        self.call("cuEventElapsedTime", [C.POINTER(C.c_float), C.c_void_p, C.c_void_p], C.byref(result), start, stop)
        return result.value

    def close(self):
        for event in self.events:
            self.call("cuEventDestroy_v2", [C.c_void_p], event)
        for pointer in self.allocations:
            self.call("cuMemFree_v2", [C.c_uint64], pointer)
        if self.module:
            self.call("cuModuleUnload", [C.c_void_p], self.module)
        if self.context:
            self.call("cuCtxDestroy_v2", [C.c_void_p], self.context)


def timings(values):
    return {"samples_ms": values, "median_ms": statistics.median(values), "min_ms": min(values)}


def finite_max_difference(expected, actual):
    if len(expected) != len(actual) or not len(expected):
        raise ValueError("Parity requires equal, nonempty result arrays")
    maximum = 0.0
    for index, (left, right) in enumerate(zip(expected, actual)):
        if not math.isfinite(left) or not math.isfinite(right):
            raise ValueError(f"Non-finite evaluation result at index {index}: {left}, {right}")
        difference = abs(left - right)
        if not math.isfinite(difference):
            raise ValueError(f"Non-finite evaluation difference at index {index}")
        maximum = max(maximum, difference)
    return maximum


def run(args):
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=False)
    (output_dir / ".gitignore").write_text("cpu_bridge.so\nevaluation.ptx\n")
    started = utc()
    source_paths = list(HERE.glob("*.py")) + list(HERE.glob("*.hpp")) + list(HERE.glob("*.cpp")) + list(HERE.glob("*.cu"))
    source_paths += [ROOT / "submissions/tuned" / name for name in ("main.cpp", "protocol.hpp", "generated.hpp")]
    manifest = {
        "status": "running", "started_at": started, "scope": "v2 evaluation and building_value only; no game simulation, action generation, or win-rate measurement",
        "source_sha256": {str(path.relative_to(ROOT)): sha(path) for path in source_paths},
        "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "arguments": {key: str(value) if isinstance(value, Path) else value for key, value in vars(args).items()},
        "environment": {"python": platform.python_version(), "platform": platform.platform(), "logical_cpus": os.cpu_count()},
        "batches": [],
    }
    gpu = None
    try:
        load_start = time.perf_counter()
        files = sorted(args.replay_dir.glob("*.json"))
        positions_list = [state for path in files for state in legal_positions(path)]
        random.Random(20260927).shuffle(positions_list)
        if args.state_limit:
            positions_list = positions_list[:args.state_limit]
        if not positions_list:
            raise ValueError("No replay positions")
        positions = (Position * len(positions_list))(*positions_list)
        params = parameter_grid()
        parameters = (Parameters * len(params))(*params)
        manifest["dataset"] = {
            "states": len(positions), "parameter_sets": len(parameters), "unique_state_parameter_pairs": len(positions) * len(parameters),
            "fixture_shuffle_seed": 20260927, "load_seconds": time.perf_counter() - load_start,
            "parameter_values": {name: sorted({getattr(p, name) for p in params})
                                 for name in ("engineering", "hall_income", "army")},
            "position_bytes": C.sizeof(Position), "input_bytes": C.sizeof(positions) + C.sizeof(parameters),
            "sha256": hashlib.sha256(bytes(positions)).hexdigest(),
            "replays": [{"path": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path), "sha256": sha(path)} for path in files],
            "knowledge": "Current participant observation plus earlier observed ownership only; same ordered mirror/default estimates as v2; no retrospective hidden scores",
        }
        lib, manifest["cpu_build"] = compile_cpu(output_dir)
        baseline = (Parameters * 1)(Parameters(110, 35, 1.3))
        oracle, translated = (C.c_double * len(positions))(), (C.c_double * len(positions))()
        lib.probe_original(positions, len(positions), oracle)
        lib.probe_cpu(positions, len(positions), baseline, 1, translated, len(positions), 1)
        difference = finite_max_difference(oracle, translated)
        manifest["v2_original_parity"] = {"positions": len(positions), "max_abs_difference": difference, "tolerance": 1e-8, "passed": difference <= 1e-8}
        if difference > 1e-8:
            raise RuntimeError(f"Original evaluator parity failed: {difference}")
        if args.cpu_only:
            manifest["gpu"] = {"status": "skipped", "reason": "--cpu-only"}
        elif not args.nvrtc_lib:
            manifest["gpu"] = {"status": "skipped", "reason": "No --nvrtc-lib supplied"}
        else:
            ptx, manifest["cuda_build"] = compile_cuda(args.nvrtc_lib.resolve(), args.cuda_arch, output_dir)
            try:
                gpu = CUDA(ptx, args.device)
            except (CUDAUnavailable, OSError) as error:
                manifest["gpu"] = {"status": "skipped", "reason": str(error), "kernel_compiled": True}
        if gpu:
            manifest["gpu"] = {"status": "ready", **gpu.info}
            device_positions = gpu.allocate(C.sizeof(positions))
            device_parameters = gpu.allocate(C.sizeof(parameters))
            device_output = gpu.allocate(max(args.batch_sizes) * C.sizeof(C.c_double))
            gpu.upload(device_positions, positions)
            gpu.upload(device_parameters, parameters)
            event_start, event_stop = gpu.event(), gpu.event()
        for count in args.batch_sizes:
            row = {"evaluations": count, "unique_pairs": min(count, len(positions) * len(parameters)), "cpu": []}
            output = (C.c_double * count)()
            reference = None
            for workers in args.workers:
                for _ in range(args.warmup):
                    lib.probe_cpu(positions, len(positions), parameters, len(parameters), output, count, workers)
                measurements = []
                for _ in range(args.repeats):
                    t0 = time.perf_counter()
                    lib.probe_cpu(positions, len(positions), parameters, len(parameters), output, count, workers)
                    measurements.append(1000 * (time.perf_counter() - t0))
                if reference is None:
                    reference = list(output)
                difference = finite_max_difference(reference, output)
                row["cpu"].append({"workers": workers, **timings(measurements), "max_abs_difference": difference,
                                   "checksum_sha256": hashlib.sha256(bytes(output)).hexdigest()})
                if difference > 1e-8:
                    raise RuntimeError("CPU worker parity failed")
            if gpu:
                def launch():
                    gpu.launch(device_positions, len(positions), device_parameters, len(parameters), device_output, count)
                for _ in range(args.warmup):
                    launch()
                gpu.sync()
                kernel_ms, end_to_end_ms = [], []
                for _ in range(args.repeats):
                    gpu.record(event_start)
                    launch()
                    gpu.record(event_stop)
                    gpu.sync()
                    kernel_ms.append(gpu.elapsed(event_start, event_stop))
                gpu.download(output, device_output)
                difference = finite_max_difference(reference, output)
                for _ in range(args.repeats):
                    t0 = time.perf_counter()
                    gpu.upload(device_positions, positions)
                    gpu.upload(device_parameters, parameters)
                    launch()
                    gpu.download(output, device_output)
                    end_to_end_ms.append(1000 * (time.perf_counter() - t0))
                difference = max(difference, finite_max_difference(reference, output))
                row["gpu"] = {
                    "kernel": timings(kernel_ms), "transfer_plus_kernel": timings(end_to_end_ms),
                    "timing_exclusions": "Allocation, compilation, context creation, Python fixture packing; transfer test uploads full fixture and parameters each repeat and downloads output",
                    "max_abs_difference": difference, "tolerance": 1e-8, "parity_passed": difference <= 1e-8,
                    "checksum_sha256": hashlib.sha256(bytes(output)).hexdigest(),
                }
                if difference > 1e-8:
                    raise RuntimeError(f"GPU parity failed: {difference}")
            manifest["batches"].append(row)
            (output_dir / "result.json").write_text(json.dumps(manifest, indent=2) + "\n")
        manifest["status"] = "completed" if gpu else "cpu_only_gpu_skipped"
    except Exception as error:
        manifest["status"] = "failed"
        manifest["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        if gpu:
            gpu.close()
        manifest["finished_at"] = utc()
        (output_dir / "result.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--replay-dir", type=Path, default=ROOT / "artifacts/firstround_results")
    parser.add_argument("--device", type=int, default=0)
    parser.add_argument("--batch-sizes", type=lambda x: [int(n) for n in x.split(",")], default=[1024, 16384, 65536])
    parser.add_argument("--workers", type=lambda x: [int(n) for n in x.split(",")], default=[1, 4])
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--warmup", type=int, default=2)
    parser.add_argument("--nvrtc-lib", type=Path)
    parser.add_argument("--cpu-only", action="store_true")
    parser.add_argument("--cuda-arch", type=int, default=86, help="PTX target; 86 supports RTX 3090 and later GPUs")
    parser.add_argument("--state-limit", type=int)
    args = parser.parse_args()
    if (args.repeats < 1 or args.warmup < 1 or not args.batch_sizes or min(args.batch_sizes) < 1
            or not args.workers or min(args.workers) < 1 or (args.state_limit is not None and args.state_limit < 1)):
        parser.error("Batch sizes, workers, repeats and warmup must be positive")
    manifest = run(args)
    print(json.dumps({"status": manifest["status"], "output": str(args.output_dir / "result.json"),
                      "original_parity": manifest.get("v2_original_parity"), "gpu": manifest.get("gpu")}, indent=2))


if __name__ == "__main__":
    main()
