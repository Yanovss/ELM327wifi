#!/usr/bin/env python3
"""Protocol-neutral statistics for sniffer JSONL captures (standard library only)."""
import argparse
from collections import Counter, defaultdict
import json
import math
from pathlib import Path
import statistics
import sys


def load_frames(path):
    frames = []
    with path.open(encoding='utf-8') as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                data = bytes.fromhex(row['data'])
                ts = row['ts']
                end = row.get('ts_end', ts)
                if (not data or type(row['length']) is not int or row['length'] != len(data)
                        or any(type(t) not in (int, float) or not math.isfinite(t) for t in (ts, end))):
                    raise ValueError('invalid length, data or timestamps')
                frames.append((ts, end, data, row.get('reason', 'unknown'), 'ts_end' in row))
            except (ValueError, KeyError, TypeError) as exc:
                raise ValueError(f'{path}:{line_number}: {exc}') from exc
    return frames


def summary(label, values):
    if not values:
        print(f'{label}: insufficient data')
        return
    print(f'{label}: n={len(values)} min={min(values):.3f} '
          f'median={statistics.median(values):.3f} mean={statistics.mean(values):.3f} '
          f'max={max(values):.3f} ms')
    if any(v < 0 for v in values):
        print('  Warning: negative intervals; check clock changes or mixed capture sessions.')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--top', type=int, default=10)
    parser.add_argument('--header-bytes', type=int, default=4)
    args = parser.parse_args(argv)
    if args.top <= 0 or args.header_bytes <= 0:
        parser.error('--top and --header-bytes must be positive')
    try:
        frames = load_frames(args.input)
    except (OSError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 1
    print(f'Frames: {len(frames)}; bytes: {sum(len(f[2]) for f in frames)}')
    print(f'Completion reasons: {dict(Counter(f[3] for f in frames))}')
    print('\nMost frequent frames:')
    for data, count in Counter(f[2] for f in frames).most_common(args.top):
        print(f'  {count:6d} x len={len(data)}  {data.hex(" ").upper()}')
    groups = defaultdict(list)
    for frame in frames:
        groups[len(frame[2])].append(frame[2])
    print('\nGroups by length:')
    for length, items in sorted(groups.items()):
        print(f'  {length} bytes: {len(items)} frames; {len(set(items))} distinct')
    print('\nIntervals in file order (host wall-clock timestamps):')
    pairs = list(zip(frames, frames[1:]))
    summary('Start-to-start', [(b[0] - a[0]) * 1000 for a, b in pairs])
    summary('End-to-next-start', [(b[0] - a[1]) * 1000 for a, b in pairs if a[4]])
    print(f'First {args.top} intervals:')
    for i, (a, b) in enumerate(pairs[:args.top], 1):
        gap = f'{(b[0] - a[1]) * 1000:.3f}' if a[4] else 'unknown'
        print(f'  {i}->{i+1}: start_delta={(b[0]-a[0])*1000:.3f} ms; idle={gap} ms')
    print('\nRepeated prefix candidates (not proven protocol headers):')
    for size in range(1, min(args.header_bytes, max(groups, default=0)) + 1):
        counts = Counter(f[2][:size] for f in frames if len(f[2]) >= size)
        for prefix, count in counts.most_common(args.top):
            if count >= 2:
                distinct = len({f[2] for f in frames if f[2].startswith(prefix)})
                print(f'  {size} bytes: {prefix.hex(" ").upper()}  '
                      f'count={count}; distinct_frames={distinct}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
