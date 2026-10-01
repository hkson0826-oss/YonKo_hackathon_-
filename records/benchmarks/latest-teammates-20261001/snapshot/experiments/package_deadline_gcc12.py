"""Run deadline ZIP validation entirely inside a temporary Debian GCC12 context."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import sys
import traceback

sys.dont_write_bytecode = True
import package_deadline_candidate as deadline
from verify_gcc12_tmp import gcc12_toolchain


def run(args):
    args = argparse.Namespace(**vars(args))
    args.compiler = 'g++'
    args = deadline.normalized(args)
    record_path = Path(args.compiler_record)
    deadline.require(not record_path.is_symlink(), 'Compiler record cannot be a symlink')
    args.compiler_record = record_path.resolve()
    deadline.require(not args.compiler_record.exists(), 'Compiler record already exists')
    deadline.require(type(args.toolchain_budget_seconds) is int and args.toolchain_budget_seconds > 0, 'Invalid toolchain budget')
    decision = deadline.read(args.decision_json)
    protected = [args.arena, args.decision_json, args.output_zip, args.records,
                 *[Path(decision[stage]['arena']).resolve() for stage in ('selection', 'final')]]
    for path in protected:
        deadline.require(not args.compiler_record.is_relative_to(path) and not path.is_relative_to(args.compiler_record),
                         'Compiler record overlaps an input or output')
    args.compiler_record.parent.mkdir(parents=True, exist_ok=True)
    report = {'status': 'started', 'started_utc': deadline.package.stamp(),
              'wrapper_sha256': deadline.sha(Path(__file__)),
              'packager_sha256': deadline.sha(Path(deadline.__file__)),
              'toolchain_helper_sha256': deadline.sha(Path(__file__).with_name('verify_gcc12_tmp.py')),
              'toolchain': {}, 'cpu_seed_start': args.cpu_seed_start,
              'paths': {key: str(getattr(args, key)) for key in ('arena','decision_json','output_zip','records','compiler_record')},
              'scope': 'Exact submission ZIP GCC12 compile, SDK smoke and four 384MiB CPU games; no old-campaign gate changes',
              'limitations': ['Toolchain budget covers setup, not the complete packaging run.',
                              'Official Debian HTTPS index and package SHA256 checks are reused; OpenPGP signature verification is not added.',
                              'Host binutils, CPU, kernel and isolation can differ from the official server.']}
    previous_env = dict(os.environ)
    previous_signals = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}

    def interrupted(number, frame):
        raise InterruptedError(f'Interrupted by signal {number}')

    with args.compiler_record.open('x', encoding='utf-8') as output:
        try:
            for sig in previous_signals:
                signal.signal(sig, interrupted)
            # Reject unaccepted or mismatched evidence before any network download.
            deadline.check_decision(args.arena, args.candidate, args.decision_json, args.cpu_seed_start)
            report['initial_decision_verified'] = True
            with gcc12_toolchain(report['toolchain'], budget_seconds=args.toolchain_budget_seconds) as toolchain:
                os.environ.clear()
                os.environ.update(toolchain['env'])
                args.compiler = toolchain['compiler_wrapper']
                report['packaging'] = deadline.run(args)
            deadline.require(report['toolchain'].get('temporary_directory_removed') is True,
                             'GCC12 temporary directory cleanup not confirmed')
            deadline.require(report['packaging'].get('status') == 'validated' and
                             report['packaging'].get('temporary_directory_removed') is True,
                             'Packaging validation or temporary cleanup not confirmed')
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
            report['finished_utc'] = deadline.package.stamp()
            json.dump(report, output, ensure_ascii=False, indent=2)
            output.write('\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('arena', 'decision-json', 'output-zip', 'records', 'compiler-record'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--candidate', required=True)
    parser.add_argument('--cpu-seed-start', type=int, default=15000)
    parser.add_argument('--toolchain-budget-seconds', type=int, default=300)
    args = parser.parse_args()
    try:
        report = run(args)
    except (OSError, ValueError, KeyError) as exc:
        print(f'{type(exc).__name__}: {exc}', file=sys.stderr)
        return 1
    print(json.dumps({'status': report['status'], 'error': report.get('error'),
                      'compiler_record': str(args.compiler_record)}, ensure_ascii=False), flush=True)
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
