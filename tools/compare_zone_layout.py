import sys
import os
from collections import defaultdict


SUFFIXES = [
    ('.moby.json', 'moby'),
    ('.clue.json', 'clue'),
    ('.volume.json', 'volume'),
    ('.controller.json', 'controller'),
    ('.area.json', 'area'),
    ('.pod.json', 'pod'),
    ('.scent.json', 'scent'),
    ('.path.json', 'path'),
]


def scan(root: str):
    # expected layout: root/default/<zoneName>/*.json
    base = os.path.join(root, 'default')
    counts = defaultdict(lambda: defaultdict(int))
    if not os.path.isdir(base):
        return counts
    for zone in os.listdir(base):
        zpath = os.path.join(base, zone)
        if not os.path.isdir(zpath):
            continue
        for dirpath, _dirs, files in os.walk(zpath):
            for fn in files:
                for suf, key in SUFFIXES:
                    if fn.endswith(suf):
                        counts[zone][key] += 1
                        break
    return counts


def main():
    if len(sys.argv) < 3:
        print('Usage: python tools/compare_zone_layout.py <extractA_dir> <extractB_dir>')
        sys.exit(1)
    A = scan(sys.argv[1])
    B = scan(sys.argv[2])
    zones = sorted(set(A.keys()) | set(B.keys()))
    keys = [k for _s, k in SUFFIXES]
    print('Zone layout diff (A=orig, B=repacked):')
    for z in zones:
        ca = A.get(z, {})
        cb = B.get(z, {})
        line = [f"{z}:"]
        diffs = []
        for k in keys:
            va = ca.get(k, 0)
            vb = cb.get(k, 0)
            if va != vb:
                diffs.append(f"{k} {va}!={vb}")
        if diffs:
            print('  ' + ' '.join(line + diffs))
    # Totals
    ta = defaultdict(int)
    tb = defaultdict(int)
    for z, m in A.items():
        for k, v in m.items():
            ta[k] += v
    for z, m in B.items():
        for k, v in m.items():
            tb[k] += v
    print('Totals:')
    for k in keys:
        print(f"  {k}: A={ta.get(k,0)} B={tb.get(k,0)}")


if __name__ == '__main__':
    main()



