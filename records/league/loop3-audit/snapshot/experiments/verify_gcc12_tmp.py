#!/usr/bin/env python3
"""Check a source ZIP with Debian GCC 12.2 extracted exclusively under /tmp."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import copy
import hashlib
import io
import json
import lzma
import os
from pathlib import Path, PurePosixPath
import platform
import shlex
import signal
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
MIRROR = 'https://deb.debian.org/debian/'
INDEX_URL = MIRROR + 'dists/bookworm/main/binary-amd64/Packages.xz'
PACKAGES = ('g++-12', 'gcc-12', 'cpp-12', 'gcc-12-base', 'libstdc++-12-dev',
            'libgcc-12-dev', 'libstdc++6', 'libgcc-s1', 'libc6', 'libc6-dev', 'linux-libc-dev')


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def download(url: str, target: Path, deadline: float, expected: str | None = None) -> dict:
    if not url.startswith(MIRROR):
        raise ValueError('Only official Debian HTTPS package URLs are accepted')
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError('Toolchain check exceeded its overall budget')
    with urllib.request.urlopen(url, timeout=min(40, remaining)) as response, target.open('wb') as out:
        if not response.geturl().startswith(MIRROR):
            raise ValueError('Unexpected download redirect')
        while chunk := response.read(1024 * 1024):
            if time.monotonic() >= deadline:
                raise TimeoutError('Toolchain download exceeded its overall budget')
            out.write(chunk)
    actual = sha(target)
    if expected is not None and actual != expected:
        raise ValueError(f'Debian SHA256 mismatch: {target.name}')
    return {'url': url, 'sha256': actual, 'bytes': target.stat().st_size}


def package_index(path: Path) -> dict[str, dict[str, str]]:
    wanted = set(PACKAGES)
    result = {}
    with lzma.open(path, 'rt', encoding='utf-8') as handle:
        record = {}
        for line in handle:
            if not line.strip():
                if record.get('Package') in wanted:
                    result[record['Package']] = record
                record = {}
            elif not line.startswith((' ', '\t')) and ': ' in line:
                key, value = line.rstrip('\n').split(': ', 1)
                record[key] = value
        if record.get('Package') in wanted:
            result[record['Package']] = record
    if set(result) != wanted:
        raise ValueError(f'Missing Debian packages: {wanted - set(result)}')
    for name in ('g++-12', 'gcc-12', 'cpp-12', 'gcc-12-base', 'libstdc++-12-dev', 'libgcc-12-dev'):
        if not result[name]['Version'].startswith('12.2.0-'):
            raise ValueError(f'Expected GCC 12.2.0, found {name} {result[name]["Version"]}')
    return result


def extract_deb(path: Path, destination: Path) -> None:
    # Read the ar data member without running Debian maintainer scripts.
    with path.open('rb') as handle:
        if handle.read(8) != b'!<arch>\n':
            raise ValueError('Invalid Debian ar archive')
        while header := handle.read(60):
            if len(header) != 60 or header[-2:] != b'`\n':
                raise ValueError('Invalid ar header')
            name = header[:16].decode('ascii').strip().rstrip('/')
            size = int(header[48:58].strip())
            payload = handle.read(size)
            if len(payload) != size:
                raise ValueError('Truncated Debian archive')
            if size % 2:
                handle.read(1)
            if not name.startswith('data.tar'):
                continue
            with tarfile.open(fileobj=io.BytesIO(payload), mode='r:*') as archive:
                members = []
                for original in archive.getmembers():
                    member = copy.copy(original)
                    member_path = PurePosixPath(member.name)
                    if member_path.is_absolute() or '..' in member_path.parts:
                        raise ValueError('Unsafe archive member')
                    if (member.issym() or member.islnk()) and member.linkname.startswith('/'):
                        # Keep Debian absolute symlinks inside this relocatable sysroot.
                        target = destination / member.linkname.lstrip('/')
                        member.linkname = (os.path.relpath(target, (destination / member.name).parent)
                                           if member.issym() else member.linkname.lstrip('/'))
                    members.append(member)
                archive.extractall(destination, members=members, filter='data')
            return
    raise ValueError('Debian package has no data archive')


def run(argv: list[str], *, env: dict, cwd: Path, deadline: float, cap: int = 180) -> dict:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError('Toolchain check exceeded its overall budget')
    started = time.monotonic()
    process = subprocess.Popen(argv, cwd=cwd, env=env, text=True, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, start_new_session=True)
    try:
        stdout, stderr = process.communicate(timeout=min(cap, remaining))
        return {'argv': argv, 'returncode': process.returncode,
                'elapsed_seconds': time.monotonic() - started,
                'stdout': stdout, 'stderr': stderr}
    finally:
        # Clean this invocation's descendants even if the SDK or compiler times out.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()


@contextmanager
def _gcc12_toolchain(report: dict, *, budget_seconds: int = 900):
    if platform.machine() != 'x86_64':
        raise ValueError('This bounded toolchain check currently supports x86_64 only')
    deadline = time.monotonic() + budget_seconds
    with tempfile.TemporaryDirectory(prefix='yk-gcc12-', dir='/tmp') as folder:
        work = Path(folder)
        report['temporary_directory'] = str(work)
        packages, sysroot, scratch = work / 'packages', work / 'sysroot', work / 'scratch'
        for path in (packages, sysroot, scratch):
            path.mkdir()
        env = dict(os.environ)
        for key in ('GCC_EXEC_PREFIX', 'COMPILER_PATH', 'LIBRARY_PATH', 'CPATH', 'C_INCLUDE_PATH',
                    'CPLUS_INCLUDE_PATH', 'LD_PRELOAD', 'LD_LIBRARY_PATH'):
            env.pop(key, None)
        env.update(TMPDIR=str(scratch), PYTHONDONTWRITEBYTECODE='1', LC_ALL='C')
        index = packages / 'Packages.xz'
        report['debian_index'] = download(INDEX_URL, index, deadline)
        report['metadata_verification'] = 'Official Debian HTTPS index; package SHA256 verified against it; OpenPGP signature not independently verified'
        records = package_index(index)
        report['packages'] = []
        for name in PACKAGES:
            record = records[name]
            archive = packages / Path(record['Filename']).name
            item = {'name': name, 'version': record['Version'],
                    **download(MIRROR + record['Filename'], archive, deadline, record['SHA256'])}
            report['packages'].append(item)
            extract_deb(archive, sysroot)
        compiler = sysroot / 'usr/bin/x86_64-linux-gnu-g++-12'
        support = sysroot / 'usr/lib/gcc/x86_64-linux-gnu/12'
        compiler_args = [str(compiler), '-B' + str(support) + '/', '--sysroot=' + str(sysroot)]
        loader = sysroot / 'lib/x86_64-linux-gnu/ld-linux-x86-64.so.2'
        library_path = ':'.join(str(sysroot / path) for path in ('lib/x86_64-linux-gnu', 'usr/lib/x86_64-linux-gnu'))
        direct_args = compiler_args + ['-Wl,--dynamic-linker,' + str(loader),
                                      '-Wl,--disable-new-dtags,-rpath,' + library_path]
        wrapper = work / 'gcc12-wrapper'
        wrapper.write_text('#!/bin/sh\n'
                           'unset GCC_EXEC_PREFIX COMPILER_PATH LIBRARY_PATH CPATH C_INCLUDE_PATH CPLUS_INCLUDE_PATH LD_PRELOAD LD_LIBRARY_PATH\n'
                           'export TMPDIR=' + shlex.quote(str(scratch)) + ' LC_ALL=C\n'
                           'exec ' + shlex.join(direct_args) + ' "$@"\n')
        wrapper.chmod(0o755)
        report['direct_compiler_wrapper'] = {'path': str(wrapper), 'sha256': sha(wrapper),
                                             'extra_link_options': direct_args[len(compiler_args):],
                                             'lifetime': 'Build and direct execution must finish inside gcc12_toolchain context'}
        report['compiler'] = run([str(compiler), '--version'], env=env, cwd=work, deadline=deadline)
        if report['compiler']['returncode'] or '12.2.0' not in report['compiler']['stdout']:
            raise RuntimeError('Extracted GCC 12.2 did not run')
        report['search_paths'] = run(compiler_args + ['-print-search-dirs'], env=env, cwd=work, deadline=deadline)
        report['host_assembler'] = run(['as', '--version'], env=env, cwd=work, deadline=deadline)
        report['host_linker'] = run(['ld', '--version'], env=env, cwd=work, deadline=deadline)
        yield {'work': work, 'sysroot': sysroot, 'compiler': compiler_args,
               'compiler_wrapper': str(wrapper), 'env': env, 'deadline': deadline}
    report['temporary_directory_removed'] = not work.exists()


@contextmanager
def gcc12_toolchain(report: dict, *, budget_seconds: int = 900):
    try:
        with _gcc12_toolchain(report, budget_seconds=budget_seconds) as toolchain:
            yield toolchain
    finally:
        folder = report.get('temporary_directory')
        report['temporary_directory_removed'] = bool(folder) and not Path(folder).exists()


def verify(zip_path: Path, seed: int = 0, budget_seconds: int = 900, direct_wrapper: bool = False) -> dict:
    report = {'status': 'started', 'zip': str(zip_path), 'zip_sha256': sha(zip_path),
              'started_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
              'verification_script_sha256': sha(Path(__file__)),
              'direct_wrapper': direct_wrapper,
              'scope': 'Debian GCC 12.2 C++20/O2 compatibility plus one SDK protocol smoke; not official container equivalence',
              'limits': ['Host assembler/linker and compiler runtime dependencies are used',
                         'Debian package revision, CPU, kernel, SDK runner, and isolation may differ from the official server',
                         'SDK smoke checks protocol at its 300ms/3000ms limits; it is not a 384MiB container or strength test']}
    try:
        with gcc12_toolchain(report, budget_seconds=budget_seconds) as toolchain:
            work, sysroot, env, deadline = (toolchain[k] for k in ('work', 'sysroot', 'env', 'deadline'))
            starter = ROOT / 'yk-development-tools/bots/dist/starter'
            sys.path.insert(0, str(starter))
            from submission import inspect_zip, extract_zip
            report['zip_inspection'] = inspect_zip(zip_path)
            if not report['zip_inspection']['ok']:
                raise ValueError('SDK ZIP inspection failed')
            source = work / 'source'
            source.mkdir()
            if extract_zip(zip_path, source) != 'cpp':
                raise ValueError('Expected a C++ submission')
            report['source_sha256'] = {str(p.relative_to(source)): sha(p)
                                       for p in sorted(source.rglob('*')) if p.is_file()}
            binary = work / 'bot'
            sources = [str(p) for p in sorted(source.rglob('*.cpp'))]
            command = [toolchain['compiler_wrapper']] if direct_wrapper else toolchain['compiler']
            report['build'] = run(command + ['-std=c++20', '-O2', '-I', str(source),
                                                         *sources, '-o', str(binary)],
                                  env=env, cwd=work, deadline=deadline)
            if report['build']['returncode']:
                raise RuntimeError('GCC 12.2 source ZIP compile failed')
            report['binary_sha256'] = sha(binary)
            report['elf_interpreter'] = run(['readelf', '-l', str(binary)], env=env, cwd=work, deadline=deadline)
            loader = sysroot / 'lib/x86_64-linux-gnu/ld-linux-x86-64.so.2'
            library_path = ':'.join(str(sysroot / path) for path in ('lib/x86_64-linux-gnu', 'usr/lib/x86_64-linux-gnu'))
            runtime = [str(binary)] if direct_wrapper else [str(loader), '--library-path', library_path, str(binary)]
            if direct_wrapper and str(loader) not in report['elf_interpreter']['stdout']:
                raise RuntimeError('ELF direct execution interpreter was not pinned to Debian sysroot')
            report['runtime_dependencies'] = run([str(loader), '--library-path', library_path, '--list', str(binary)],
                                                 env=env, cwd=work, deadline=deadline)
            if report['runtime_dependencies']['returncode']:
                raise RuntimeError('Debian runtime dependency resolution failed')
            for line in report['runtime_dependencies']['stdout'].splitlines():
                if '=>' in line:
                    resolved = line.split('=>', 1)[1].strip().split()[0]
                    if not Path(resolved).is_relative_to(sysroot):
                        raise RuntimeError(f'Runtime dependency escaped Debian sysroot: {resolved}')
            report['sdk'] = run([sys.executable, str(starter / 'run_tests.py'), '--bot', shlex.join(runtime),
                                 '--seed', str(seed)], env=env, cwd=work, deadline=deadline)
            if report['sdk']['stdout'].strip():
                report['sdk_result'] = json.loads(report['sdk']['stdout'])
            if report['sdk']['returncode'] or not report.get('sdk_result', {}).get('ok'):
                raise RuntimeError('SDK protocol smoke failed')
            report['status'] = 'passed'
    except (Exception, KeyboardInterrupt) as exc:
        report['status'] = 'failed'
        report['error'] = f'{type(exc).__name__}: {exc}'
    finally:
        temporary = report.get('temporary_directory')
        report['temporary_directory_removed'] = bool(temporary) and not Path(temporary).exists()
        report['finished_utc'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--zip', type=Path, default=ROOT / 'artifacts/submission-v3.zip')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seed', type=int, default=0)
    parser.add_argument('--budget-seconds', type=int, default=900)
    parser.add_argument('--direct-wrapper', action='store_true', help='Build with the single-path compiler wrapper and run the ELF directly')
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Output already exists; preserve past verification records')
    def interrupted(signum, frame):
        raise KeyboardInterrupt(f'Interrupted by signal {signum}')
    signal.signal(signal.SIGTERM, interrupted)
    report = verify(args.zip.resolve(), args.seed, args.budget_seconds, args.direct_wrapper)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: report.get(k) for k in ('status', 'error', 'temporary_directory_removed')}, ensure_ascii=False))
    return 0 if report['status'] == 'passed' and report['temporary_directory_removed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
