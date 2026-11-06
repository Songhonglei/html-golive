#!/usr/bin/env python3
"""Run the full matching sdist suite against an installed CI wheel, source-free.

Run with a fresh venv containing the wheel, pytest/pytest-timeout, Pillow and
cryptography. The manifest next to the distributions pins hashes and commit.
No source Python package is copied beside the tests; all artifacts are retained.
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wheel', type=Path, required=True)
    parser.add_argument('--sdist', type=Path, required=True)
    parser.add_argument('--work-dir', type=Path)
    args = parser.parse_args()
    wheel, sdist = args.wheel.resolve(), args.sdist.resolve()
    manifest = json.loads((wheel.parent / 'artifact-manifest.json').read_text())
    for path in (wheel, sdist):
        assert sha256(path) == manifest['files'][path.name]['sha256'], path.name
    if args.work_dir:
        root = args.work_dir.resolve()
        root.mkdir(parents=True, exist_ok=False)
    else:
        root = Path(tempfile.mkdtemp(prefix='golive-installed-')).resolve()
    root.chmod(0o700)
    bundle = root / 'test-resources'
    bundle.mkdir()

    import golive
    package = Path(golive.__file__).resolve().parent
    assert sys.prefix != sys.base_prefix, 'use an isolated venv'
    assert package.is_relative_to(Path(sys.prefix).resolve()), 'golive must import from the installed venv'
    runtime_files = {}
    with zipfile.ZipFile(wheel) as archive:
        for name in archive.namelist():
            if name.startswith('golive/') and not name.endswith('/'):
                content = archive.read(name)
                assert package.parent.joinpath(name).read_bytes() == content, name
                runtime_files[name] = content
    with tarfile.open(sdist) as archive:
        members = archive.getmembers()
        prefix = members[0].name.split('/')[0]
        for name, content in runtime_files.items():
            assert archive.extractfile(prefix + '/' + name).read() == content, name
        for member in members:
            if not member.isfile():
                continue
            parts = Path(member.name).parts
            assert parts[0] == prefix and '..' not in parts and not Path(member.name).is_absolute()
            relative = Path(*parts[1:])
            if not relative.parts:
                continue
            if relative.parts[0] == 'golive' and (relative.suffix in ('.py', '.pyc') or '__pycache__' in relative.parts):
                continue
            # Keep matching docs/metadata/static fixtures for source-level
            # assertions, but never create an importable local golive package.
            target = bundle / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.extractfile(member).read())
    assert not list((bundle / 'golive').rglob('*.py'))
    assert (bundle / 'tests/__init__.py').is_file()
    assert (bundle / 'pyproject.toml').is_file()

    import importlib.metadata
    distribution = importlib.metadata.distribution('html-golive')
    receipt = {'source_commit': manifest['source_commit'], 'python': sys.executable,
               'version': distribution.version, 'module': golive.__file__,
               'wheel_sha256': sha256(wheel), 'sdist_sha256': sha256(sdist),
               'runtime_files_matched': len(runtime_files),
               'direct_url': json.loads(distribution.read_text('direct_url.json') or 'null'),
               'source_package_copied': False}
    (root / 'provenance.json').write_text(json.dumps(receipt, indent=2))
    env = {key: value for key, value in os.environ.items() if not key.startswith(('GOLIVE_', 'PYTHON'))}
    for key, relative in [('HOME', 'user'), ('GOLIVE_HOME', 'home'), ('TMPDIR', 'tmp'),
                          ('XDG_CONFIG_HOME', 'xdg/config'), ('XDG_CACHE_HOME', 'xdg/cache'),
                          ('XDG_DATA_HOME', 'xdg/data')]:
        path = root / relative
        path.mkdir(parents=True, exist_ok=True)
        env[key] = str(path)
    env.update(PYTHONNOUSERSITE='1', PYTHONDONTWRITEBYTECODE='1')
    # Check resolution from the test working directory too: the bundle must
    # not shadow the installed package through namespace-package discovery.
    probe = subprocess.check_output([sys.executable, '-c',
        'import golive; print(golive.__file__)'], cwd=bundle, env=env, text=True).strip()
    assert Path(probe).resolve() == Path(golive.__file__).resolve(), probe
    print(json.dumps(receipt), flush=True)
    command = [sys.executable, '-m', 'pytest', 'tests/', '-q', '--timeout=45',
               '--timeout-method=signal', '--junitxml=' + str(root / 'results.xml')]
    with (root / 'pytest.log').open('w') as output:
        result = subprocess.run(command, cwd=bundle, env=env, stdout=output, stderr=subprocess.STDOUT)
    receipt['exit_code'] = result.returncode
    (root / 'result.json').write_text(json.dumps(receipt, indent=2))
    print((root / 'pytest.log').read_text(), end='')
    print('Installed acceptance evidence:', root)
    return result.returncode


if __name__ == '__main__':
    sys.exit(main())
