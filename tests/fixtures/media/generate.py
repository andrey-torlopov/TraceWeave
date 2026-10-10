#!/usr/bin/env python3
"""Generate only synthetic local media; no downloads or copyrighted samples.

Run with Python 3 and the existing ffmpeg/ffprobe executables. The manifest is
the byte/hash source of truth; different ffmpeg versions may encode differently.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import json
from pathlib import Path
import struct
import subprocess
import zlib

ROOT = Path(__file__).resolve().parent
FFMPEG = os.environ.get('TW_FIXTURE_FFMPEG') or shutil.which('ffmpeg')
FFPROBE = os.environ.get('TW_FIXTURE_FFPROBE') or shutil.which('ffprobe')
if not FFMPEG or not FFPROBE:
    raise SystemExit('Install ffmpeg and ffprobe on PATH, or set TW_FIXTURE_FFMPEG and TW_FIXTURE_FFPROBE.')


def encode(name, source, options):
    subprocess.run([FFMPEG, '-hide_banner', '-loglevel', 'error', '-nostdin', '-y',
                    '-f', 'lavfi', '-i', source, '-map_metadata', '-1', '-threads', '1',
                    *options, str(ROOT / name)], check=True, timeout=60)


def png(name, width, height):
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
    compressor = zlib.compressobj(9)
    pieces = [compressor.compress(b'\x00' + b'\x31\x79\xb5' * width) for _ in range(height)]
    pieces.append(compressor.flush())
    payload = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
    (ROOT / name).write_bytes(payload + chunk(b'IDAT', b''.join(pieces)) + chunk(b'IEND', b''))


def main():
    png('synthetic.png', 96, 64)
    # 8000 × 4001 = 32,008,000 pixels, above the automatic-preview limit.
    png('preview-limit.png', 8000, 4001)
    image = 'color=c=0x3179b5:s=96x64:r=1'
    encode('synthetic.jpg', image, ['-frames:v', '1', '-c:v', 'mjpeg', '-q:v', '3'])
    encode('synthetic.gif', image, ['-frames:v', '1', '-c:v', 'gif'])
    # A VP8 intra frame is the normative payload of the simple lossy WebP RIFF.
    encode('synthetic.ivf', image, ['-frames:v', '1', '-c:v', 'libvpx', '-f', 'ivf'])
    ivf = (ROOT / 'synthetic.ivf').read_bytes()
    frame_length = struct.unpack_from('<I', ivf, 32)[0]
    frame = ivf[44:44 + frame_length]
    padded = frame + (b'\0' if len(frame) % 2 else b'')
    (ROOT / 'synthetic.webp').write_bytes(b'RIFF' + struct.pack('<I', 12 + len(padded)) + b'WEBPVP8 ' + struct.pack('<I', len(frame)) + padded)
    (ROOT / 'synthetic.ivf').unlink()
    sound = 'sine=frequency=440:sample_rate=16000:duration=4'
    encode('synthetic.wav', sound, ['-c:a', 'pcm_s16le'])
    encode('synthetic.mp3', sound, ['-c:a', 'libmp3lame', '-b:a', '32k'])
    encode('synthetic.ogg', sound, ['-c:a', 'libopus', '-b:a', '24k'])
    encode('synthetic.m4a', sound, ['-c:a', 'aac', '-b:a', '32k'])
    video = 'testsrc2=s=128x96:r=12:d=4'
    encode('synthetic.mp4', video, ['-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-g', '12', '-movflags', '+faststart'])
    encode('synthetic.webm', video, ['-c:v', 'libvpx', '-b:v', '80k', '-g', '12'])
    encode('unsupported-prores.mov', 'color=c=0x3179b5:s=64x64:r=4:d=2', ['-c:v', 'prores_ks', '-profile:v', '3'])
    (ROOT / 'synthetic.txt').write_text('Synthetic E4 private text canary 79bafe44.\n', encoding='utf-8')
    (ROOT / 'synthetic.md').write_text('# Synthetic E4\n\nNo external images or links.\n', encoding='utf-8')
    types = {'png': 'image/png', 'jpg': 'image/jpeg', 'webp': 'image/webp', 'gif': 'image/gif',
             'wav': 'audio/wav', 'mp3': 'audio/mpeg', 'ogg': 'audio/ogg', 'm4a': 'audio/mp4',
             'mp4': 'video/mp4', 'webm': 'video/webm', 'mov': 'video/quicktime',
             'txt': 'text/plain', 'md': 'text/markdown'}
    entries = []
    for path in sorted(ROOT.iterdir()):
        if not (path.name.startswith('synthetic.') or path.name in ('preview-limit.png', 'unsupported-prores.mov')):
            continue
        mime = types.get(path.suffix.lstrip('.'))
        if mime is None:
            continue
        data = path.read_bytes()
        streams = []
        if not mime.startswith('text/'):
            probe = subprocess.run([FFPROBE, '-v', 'error', '-show_entries',
                                    'stream=codec_name,codec_type,width,height:format=duration',
                                    '-of', 'json', str(path)], capture_output=True, check=True, timeout=15)
            streams = json.loads(probe.stdout).get('streams', [])
        entries.append({'name': path.name, 'mime': mime, 'kind': mime.split('/')[0],
                        'byteSize': len(data), 'sha256': hashlib.sha256(data).hexdigest(), 'streams': streams})
    (ROOT / 'manifest.json').write_text(json.dumps(entries, indent=2) + '\n', encoding='utf-8')
    print(f'Generated and ffprobe-validated {len(entries)} synthetic fixtures; {sum(row["byteSize"] for row in entries)} bytes total')


if __name__ == '__main__':
    main()
