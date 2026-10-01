#!/usr/bin/env python3
"""Package only explicit extension sources; never include account data or caches."""
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    subprocess.run([sys.executable, str(ROOT / 'scripts/security-check.py'), '--working-tree'], check=True)
    metadata = json.loads((ROOT / 'metadata.json').read_text())
    out = ROOT / 'dist'
    out.mkdir(exist_ok=True)
    target = out / (metadata['uuid'] + '.shell-extension.zip')
    with tempfile.TemporaryDirectory() as directory:
        stage = Path(directory)
        for name in ['metadata.json', 'extension.js', 'prefs.js', 'ui-model.js', 'stylesheet.css', 'README.md', 'SECURITY.md']:
            shutil.copy2(ROOT / name, stage / name)
        for name in ['backend', 'icons', 'schemas', 'docs']:
            shutil.copytree(ROOT / name, stage / name, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', 'gschemas.compiled'))
        subprocess.run(['glib-compile-schemas', '--strict', str(stage / 'schemas')], check=True)
        with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(stage.rglob('*')):
                if path.is_file(): archive.write(path, path.relative_to(stage))
    print(target)


if __name__ == '__main__': main()
