"""GitHub CI and the local pre-push gate run one list of checks.

`.github/workflows/ci.yml` sets up a machine and calls `scripts/ci_local.sh`,
and the script takes the Python versions from the workflow's matrix. A second
copy of a check in the workflow is how the two drift apart: local says safe to
push, and GitHub goes red.
"""
import os
import re
import stat

import pytest

yaml = pytest.importorskip('yaml')

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_GATE = os.path.join(_REPO_ROOT, 'scripts', 'ci_local.sh')
_PINS = os.path.join(_REPO_ROOT, 'requirements-ci.txt')

with open(os.path.join(_REPO_ROOT, '.github', 'workflows', 'ci.yml'), encoding='utf-8') as _f:
    _WORKFLOW = yaml.safe_load(_f)
JOBS = sorted(_WORKFLOW['jobs'])


def _gate_source():
    with open(_GATE, encoding='utf-8') as f:
        return f.read()


def _run_lines(job):
    return [step['run'] for step in _WORKFLOW['jobs'][job]['steps'] if 'run' in step]


@pytest.mark.parametrize('job', JOBS)
def test_each_workflow_job_calls_the_gate_for_itself(job):
    runs = '\n'.join(_run_lines(job))
    assert f'./scripts/ci_local.sh --job {job}' in runs, f'{job} does not call the gate'


@pytest.mark.parametrize('job', JOBS)
def test_workflow_jobs_hold_no_copy_of_a_check(job):
    """Only setting up the machine and calling the gate belong in a job."""
    runs = '\n'.join(_run_lines(job))
    for tool in ('ruff check', 'pytest', 'semgrep ', 'pip-audit --', 'node --check',
                 'pip compile', 'check_i18n_fresh'):
        assert tool not in runs, f'{job} runs {tool} itself'


@pytest.mark.parametrize('job', JOBS)
def test_gate_has_a_body_for_each_workflow_job(job):
    assert re.search(rf'^\s*{re.escape(job)}\)', _gate_source(), re.M), job


def test_gate_reads_python_versions_from_the_workflow():
    source = _gate_source()
    assert 'python-version:' in source and 'PRIMARY_PYTHON:' in source
    # A version written in the script would be a second copy of the matrix.
    code = [ln for ln in source.splitlines() if not ln.lstrip().startswith('#')]
    assert not [ln for ln in code if re.search(r'3\.1[0-9]', ln)]


def test_every_tool_the_gate_installs_has_one_pinned_version():
    with open(_PINS, encoding='utf-8') as f:
        pins = dict(re.findall(r'^([a-z0-9-]+)==(\S+)$', f.read(), re.M))
    body = re.search(r'packages_for\(\) \{(.*?)^\}', _gate_source(), re.M | re.S).group(1)
    named = set(re.findall(r'[a-z][a-z0-9-]+', ' '.join(re.findall(r'echo "([^"]*)"', body))))
    assert named, 'packages_for lists no tools'
    assert not named - set(pins), f'not pinned in requirements-ci.txt: {named - set(pins)}'
    assert 'uv' in pins, 'the lockfile-drift check depends on the uv version'


def test_workflow_passes_its_python_through_an_environment_variable():
    """`${{ }}` inside `run:` is pasted into the shell (zizmor template-injection)."""
    for job in JOBS:
        for run in _run_lines(job):
            assert '${{' not in run, f'{job}: {run}'


def test_gate_is_executable():
    assert os.stat(_GATE).st_mode & stat.S_IXUSR
