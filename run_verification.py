"""Single entry used by the runtime manifest.

Runs, in order:
  1. the original V1 unittest regression (check_project.py);
  2. the legacy V1 occlusion comparison (partial_cases.py legacy);
  3. the V2 partial-handoff verification including occlusion contrast,
     stop-station publication, mixed-handoff rejection, amendment/reopen
     collection and publication-failure retry paths exercised by the
     unittest suite in tests/test_partial.py.

Any failure exits non-zero so the runtime verify command reports it.
"""
import subprocess
import sys
import unittest


def _run_discovered(start_dir: str) -> bool:
    suite = unittest.defaultTestLoader.discover(start_dir, top_level_dir='.')
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return result.testsRun > 0 and result.wasSuccessful()


def _run_module(module_name: str) -> bool:
    suite = unittest.defaultTestLoader.loadTestsFromName(module_name)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return result.testsRun > 0 and result.wasSuccessful()


def _run_partial_cases(mode: str) -> bool:
    completed = subprocess.run(
        [sys.executable, '-B', 'partial_cases.py', mode],
        cwd='.',
    )
    return completed.returncode == 0


def main() -> int:
    steps = (
        ('V1 unittest regression', lambda: _run_discovered('tests')),
        ('V1 occlusion comparison', lambda: _run_partial_cases('legacy')),
        ('V2 partial handoff verification', lambda: _run_module('tests.test_partial')),
        ('V2 partial workflow script', lambda: _run_partial_cases('partial')),
    )
    failures = []
    for label, step in steps:
        print(f'== {label} ==', flush=True)
        if not step():
            failures.append(label)
    if failures:
        print('VERIFY FAILED: ' + ', '.join(failures), file=sys.stderr)
        return 1
    print('VERIFY PASS: original regression and partial handoff checks succeeded')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
