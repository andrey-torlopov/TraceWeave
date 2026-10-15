#!/usr/bin/env python3
"""Reproduce the Swift/TypeScript emoji tables from the pinned machine contract."""
import argparse
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--backend-root', type=Path, default=ROOT.parent / 'TraceWeaveBackend')
    parser.add_argument('--frontend-root', type=Path, default=ROOT.parent / 'TraceWeaveFrontend')
    args = parser.parse_args()
    corpus = json.loads((ROOT / 'contracts/emoji/17.0.json').read_text())
    entries = corpus['sequences']
    if corpus['version'] != '17.0' or len(entries) != len(set(entries)) or any(not x or len(x.encode()) > 128 or '\n' in x or '"' in x or '\\' in x for x in entries):
        raise SystemExit('Invalid pinned corpus')
    swift = args.backend_root / 'Sources/ResearchGraphDomain/EmojiValidation.swift'
    ts = args.frontend_root / 'src/shared/emojiSequences.ts'
    swift_source = swift.read_text()
    expected_swift, count = re.subn(r'(?s)(private static let sequences: Set<Data> = Set\("""\n).*?(\n"""\.split)', lambda m: m[1] + '\n'.join(entries) + m[2], swift_source)
    assert count == 1
    assert f'public static let version = "{corpus["version"]}"' in expected_swift
    assert f'public static let sourceSHA256 = "{corpus["sourceSha256"]}"' in expected_swift
    expected_ts = '// Generated from contracts/emoji/17.0.json. Unicode data: https://www.unicode.org/license.txt\n'
    expected_ts += f'export const emojiVersion = "{corpus["version"]}";\nexport const emojiSourceSHA256 = "{corpus["sourceSha256"]}";\n'
    expected_ts += 'const sequences = new Set<string>(' + json.dumps(entries, ensure_ascii=False, separators=(',', ':')) + ');\n'
    expected_ts += 'export const validEmoji = (value: string) => new TextEncoder().encode(value).byteLength <= 128 && sequences.has(value);\n'
    for path, expected in [(swift, expected_swift), (ts, expected_ts)]:
        if args.check:
            if path.read_text() != expected: raise SystemExit(f'Emoji corpus drift: {path}')
        else: path.write_text(expected)
    print(f'Emoji {corpus["version"]}: {len(entries)} sequences; Swift/TypeScript match.')

if __name__ == '__main__': main()
