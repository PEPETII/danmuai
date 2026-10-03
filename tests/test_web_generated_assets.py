"""Exercise generation checks against a disposable copy, including stale output."""

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_html_check_rejects_stale_output_without_repairing_it(tmp_path):
    source = ROOT / 'web/static'
    for name in ['build_index_html.py', 'index.template.html', 'index.html']:
        shutil.copy2(source / name, tmp_path / name)
    shutil.copytree(source / 'partials', tmp_path / 'partials')
    builder = tmp_path / 'build_index_html.py'
    output = tmp_path / 'index.html'
    command = [sys.executable, str(builder), '--check']
    assert subprocess.run(command, capture_output=True).returncode == 0
    output.write_text('stale sentinel', encoding='utf-8')
    before = output.stat().st_mtime_ns
    result = subprocess.run(command, capture_output=True)
    assert result.returncode == 1
    assert output.read_text(encoding='utf-8') == 'stale sentinel'
    assert output.stat().st_mtime_ns == before
    assert subprocess.run([sys.executable, str(builder)], capture_output=True).returncode == 0
    assert subprocess.run(command, capture_output=True).returncode == 0


def test_repository_html_matches_sources():
    result = subprocess.run(
        [sys.executable, str(ROOT / 'web/static/build_index_html.py'), '--check'],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_locale_check_rejects_drift_without_rewriting_shards(tmp_path):
    script_dir = tmp_path / 'scripts'
    script_dir.mkdir()
    for name in ['build_locale_shards.py', 'locale_en_extra.json']:
        shutil.copy2(ROOT / 'scripts' / name, script_dir / name)
    static = tmp_path / 'web/static'
    shutil.copytree(ROOT / 'web/static/locales', static / 'locales')
    (static / 'modules').mkdir()
    shutil.copy2(ROOT / 'web/static/modules/settings-hints.js', static / 'modules/settings-hints.js')
    builder = script_dir / 'build_locale_shards.py'
    command = [sys.executable, str(builder), '--check']
    assert subprocess.run(command, capture_output=True).returncode == 0
    counts = static / 'locales/_shard_counts.json'
    counts.write_text('{}', encoding='utf-8')
    before = {p: p.stat().st_mtime_ns for p in (static / 'locales').rglob('*.json')}
    result = subprocess.run(command, capture_output=True)
    assert result.returncode == 1
    assert counts.read_text(encoding='utf-8') == '{}'
    assert before == {p: p.stat().st_mtime_ns for p in before}


def test_css_check_rejects_drift_without_repairing_it(tmp_path):
    output = tmp_path / 'utilities.css'
    output.write_text('stale sentinel', encoding='utf-8')
    before = output.stat().st_mtime_ns
    command = ['node', str(ROOT / 'scripts/build_web_css.mjs'), '--output', str(output)]
    result = subprocess.run(command + ['--check'], capture_output=True, timeout=30)
    assert result.returncode == 1
    assert b'is stale' in result.stderr
    assert output.read_text(encoding='utf-8') == 'stale sentinel'
    assert output.stat().st_mtime_ns == before
    assert subprocess.run(command, capture_output=True, timeout=30).returncode == 0
    assert subprocess.run(command + ['--check'], capture_output=True, timeout=30).returncode == 0
