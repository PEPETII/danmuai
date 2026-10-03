"""Exercise a build guard before it can touch any output or install packages."""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_incremental_release_is_rejected_before_output_cleanup(tmp_path):
    powershell = shutil.which('powershell') or shutil.which('pwsh')
    if not powershell:
        pytest.skip('PowerShell build guard runs in Windows CI')
    output = tmp_path / 'dist/DanmuAI'
    output.mkdir(parents=True)
    sentinel = output / 'keep.txt'
    sentinel.write_text('original output', encoding='utf-8')
    result = subprocess.run(
        [powershell, '-NoProfile', '-File', str(ROOT / 'scripts/build_exe.ps1'),
         '-Incremental', '-SkipDependencyInstall', '-OutputRoot', str(tmp_path)],
        capture_output=True, timeout=30,
    )
    assert result.returncode != 0
    assert b'Incremental builds require' in result.stderr
    assert sentinel.read_text(encoding='utf-8') == 'original output'
