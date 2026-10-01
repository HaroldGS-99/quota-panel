#!/usr/bin/env python3
"""Check publication inputs without printing matched values."""
import argparse
import re
import struct
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UUID = 'quota-panel@extensions.local'
PATTERNS = {
    'clave privada': re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY'),
    'token GitHub': re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{30,})\b'),
    'clave API': re.compile(r'\b(?:sk-(?:proj-)?[A-Za-z0-9_-]{20,}|AIza[A-Za-z0-9_-]{30,}|GOCSPX-[A-Za-z0-9_-]{20,}|AKIA[A-Z0-9]{16})\b'),
    'JWT': re.compile(r'\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b'),
    'credencial en URL': re.compile(r'https?://[^\s/@:]+:[^\s/@]+@'),
    'ruta personal': re.compile(r'/(?:home|Users)/[A-Za-z0-9._-]+/'),
    'credencial literal': re.compile(r'''(?i)["']?(?:password|passwd|api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret)["']?\s*[:=]\s*["']([^"'\n]{4,})["']'''),
}
EMAIL = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b')
BLOCKED_DIRS = {'.git', '.aws', '.codex', '.agents', '.ssh', '.cache', '__pycache__', 'node_modules'}
BLOCKED_NAMES = {'auth.json', 'oauth_creds.json', 'quotas.json', 'id_rsa', 'id_ed25519', '.npmrc', '.netrc'}


def git(*args):
    return subprocess.check_output(['git', '-C', str(ROOT), *args])


def scan(path, data):
    findings = []
    parts = Path(path).parts
    if (any(p in BLOCKED_DIRS for p in parts) or Path(path).name in BLOCKED_NAMES
            or Path(path).name.startswith('.env') or Path(path).suffix in {'.pem', '.key', '.log', '.pyc'}):
        findings.append(f'{path}: archivo privado o generado')
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        pos = 8
        while pos + 12 <= len(data):
            size = struct.unpack('>I', data[pos:pos + 4])[0]
            kind = data[pos + 4:pos + 8]
            if kind in {b'tEXt', b'zTXt', b'iTXt', b'eXIf'}:
                findings.append(f'{path}: metadatos PNG; ejecuta scripts/clean-screenshots.py')
                break
            pos += size + 12
        return findings
    if b'\0' in data:
        findings.append(f'{path}: formato binario sin revisión automática')
        return findings
    text = data.decode('utf-8', 'replace').replace(UUID, 'extension-identifier')
    for label, pattern in PATTERNS.items():
        for match in pattern.finditer(text):
            if label == 'credencial literal' and match.group(1) in {'fixture-secret', 'wrong'}:
                continue
            line = text.count('\n', 0, match.start()) + 1
            findings.append(f'{path}:{line}: {label}')
    for match in EMAIL.finditer(text):
        if match.group().endswith('@users.noreply.github.com'):
            continue
        line = text.count('\n', 0, match.start()) + 1
        findings.append(f'{path}:{line}: correo personal')
    return findings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--staged', action='store_true')
    mode.add_argument('--history', action='store_true')
    mode.add_argument('--working-tree', action='store_true')
    args = parser.parse_args()
    findings, count = [], 0
    if args.history:
        for line in git('log', '--all', '--format=%H%x00%ae%x00%ce').decode().splitlines():
            sha, author, committer = line.split('\0')
            if not all(v.endswith('@users.noreply.github.com') for v in (author, committer)):
                findings.append(f'commit {sha[:12]}: autor o committer sin noreply')
        for line in git('rev-list', '--objects', '--all').decode().splitlines():
            sha, _, path = line.partition(' ')
            if git('cat-file', '-t', sha).strip() != b'blob':
                continue
            count += 1
            findings.extend(scan(path, git('cat-file', 'blob', sha)))
    else:
        options = ['ls-files', '-z', '--cached']
        if not args.staged:
            options += ['--others', '--exclude-standard']
        for path in sorted(set(git(*options).decode().split('\0')) - {''}):
            file = ROOT / path
            if not args.staged and not file.exists():
                continue
            data = git('show', ':' + path) if args.staged else file.read_bytes()
            count += 1
            findings.extend(scan(path, data))
    if findings:
        print('Revisión bloqueada (los valores detectados se ocultan):')
        print('\n'.join(sorted(set(findings))))
        return 1
    print(f'Revisión de privacidad correcta: {count} archivos.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
