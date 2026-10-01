#!/usr/bin/env python3
"""Remove PNG text/EXIF metadata while preserving the compressed pixel data."""
import argparse
import struct
from pathlib import Path


def clean(path):
    data = path.read_bytes()
    if not data.startswith(b'\x89PNG\r\n\x1a\n'):
        raise ValueError('Invalid PNG')
    output, pos = bytearray(data[:8]), 8
    while pos + 12 <= len(data):
        size = struct.unpack('>I', data[pos:pos + 4])[0]
        end = pos + size + 12
        if end > len(data):
            raise ValueError('Truncated PNG')
        if data[pos + 4:pos + 8] not in {b'tEXt', b'zTXt', b'iTXt', b'eXIf'}:
            output.extend(data[pos:end])
        pos = end
    if pos != len(data):
        raise ValueError('Invalid PNG chunks')
    if bytes(output) != data:
        path.write_bytes(output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', nargs='?', type=Path,
                        default=Path(__file__).resolve().parents[1] / 'docs/screenshots')
    args = parser.parse_args()
    for path in args.directory.glob('*.png'):
        clean(path)
    print('Metadatos de capturas eliminados; píxeles conservados.')
