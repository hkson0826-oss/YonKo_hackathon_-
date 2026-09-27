#!/usr/bin/env python3
"""Package a gated winner with a temporary GCC 12.2 toolchain and retain its audit."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import sys
import traceback

sys.dont_write_bytecode = True
if __package__:
    from . import package_frozen_candidate as package
    from .verify_gcc12_tmp import gcc12_toolchain
else:
    import package_frozen_candidate as package
    from verify_gcc12_tmp import gcc12_toolchain

PATHS = ('arena', 'audit', 'source_output', 'zip_output', 'record_output', 'compiler_record')
OUTPUTS = ('source_output', 'zip_output', 'record_output', 'compiler_record')


def normalized(args):
    args = argparse.Namespace(**vars(args))
    for name in PATHS:
        path = Path(getattr(args, name))
        if name in OUTPUTS and path.is_symlink():
            raise ValueError(f'Refusing an output symlink: {path}')
        setattr(args, name, path.resolve())
    args.cpu_seed_start = getattr(args, 'cpu_seed_start', 8800)
    package.cpu_seeds(args.cpu_seed_start)
    outputs = [getattr(args, name) for name in OUTPUTS]
    for i, left in enumerate(outputs):
        package.require(not left.exists(), f'Refusing to overwrite output: {left}')
        for right in outputs[i + 1:] + [args.arena, args.audit]:
            package.require(not left.is_relative_to(right) and not right.is_relative_to(left),
                            f'Output path overlaps another output or frozen input: {left}, {right}')
    return args


def run(args):
    args = normalized(args)
    args.compiler_record.parent.mkdir(parents=True, exist_ok=True)
    report = {'status': 'started', 'started_utc': package.stamp(),
              'helper_sha256': package.sha(Path(__file__)),
              'paths': {name: str(getattr(args, name)) for name in PATHS},
              'cpu_seed_start': args.cpu_seed_start, 'toolchain': {},
              'scope': 'GCC12 packaging of the actual ZIP; SDK smoke plus four CPU matches under the existing packager limits',
              'limits': ['Toolchain setup budget does not impose an overall packaging deadline; compiler and match subprocess limits remain active.',
                         'Host binutils, CPU, kernel and isolation can differ from the official server.']}
    previous_env = dict(os.environ)
    previous_signals = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}

    def interrupted(number, frame):
        raise InterruptedError(f'Interrupted by signal {number}')

    # Reserve this independent record before downloading; never replace an existing record.
    with args.compiler_record.open('x', encoding='utf-8') as output:
        try:
            for sig in previous_signals:
                signal.signal(sig, interrupted)
            candidate, *_ = package.check_gates(args.arena, args.audit)
            report['candidate'] = candidate
            report['initial_gates_passed'] = True
            with gcc12_toolchain(report['toolchain']) as toolchain:
                os.environ.clear()
                os.environ.update(toolchain['env'])
                args.compiler = toolchain['compiler_wrapper']
                report['packaging'] = package.run(args)
            package.require(report['toolchain'].get('temporary_directory_removed') is True,
                            'GCC12 temporary toolchain cleanup was not confirmed')
            package.require(report['packaging'].get('status') == 'validated' and
                            report['packaging'].get('tmp_cleanup', {}).get('exists') is False,
                            'Packaging validation or TMP cleanup was not confirmed')
            report['status'] = 'passed'
        except BaseException as exc:
            report.update(status='failed', error=f'{type(exc).__name__}: {exc}', traceback=traceback.format_exc())
        finally:
            os.environ.clear()
            os.environ.update(previous_env)
            for sig, handler in previous_signals.items():
                signal.signal(sig, handler)
            report['environment_restored'] = dict(os.environ) == previous_env
            report['signal_handlers_restored'] = all(signal.getsignal(sig) == handler for sig, handler in previous_signals.items())
            report['toolchain_started'] = bool(report['toolchain'].get('temporary_directory'))
            report['finished_utc'] = package.stamp()
            json.dump(report, output, ensure_ascii=False, indent=2)
            output.write('\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in PATHS:
        parser.add_argument('--' + name.replace('_', '-'), type=Path, required=True,
                            help='New separate JSON outside all package output directories' if name == 'compiler_record' else None)
    parser.add_argument('--cpu-seed-start', type=int, default=8800)
    args = parser.parse_args()
    try:
        report = run(args)
    except (OSError, ValueError) as exc:
        print(f'{type(exc).__name__}: {exc}', file=sys.stderr)
        return 1
    print(json.dumps({'status': report['status'], 'error': report.get('error'),
                      'compiler_record': report['paths']['compiler_record']}, ensure_ascii=False))
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
