import sys
import struct


def read_header(data: bytes):
    if data[:4] != b"IGHW":
        raise ValueError("Bad magic")
    ver_major = struct.unpack_from(">H", data, 0x04)[0]
    if ver_major == 0:
        section_count = struct.unpack_from(">H", data, 0x08)[0]
        sh_base = 0x10
    else:
        section_count = struct.unpack_from(">I", data, 0x08)[0]
        sh_base = 0x20
    sections = {}
    for i in range(section_count):
        off = sh_base + i * 16
        sid, data_off = struct.unpack_from(">II", data, off)
        flag = data[off + 8]
        count = int.from_bytes(data[off + 9: off + 12], "big")
        size = struct.unpack_from(">I", data, off + 12)[0]
        sections[sid] = {"offset": data_off, "flag": flag, "count": count, "size": size}
    return sections


def parse_zone_meta(data: bytes, sections):
    ZID = 0x00025008
    s = sections.get(ZID)
    if not s or s["flag"] != 0x10 or s["size"] != 144:
        return []
    zones = []
    base = s["offset"]
    for i in range(s["count"]):
        pos = base + i * 144
        name = data[pos: pos + 64].split(b"\x00", 1)[0].decode("utf-8", errors="ignore")
        counts = []
        p = pos + 64
        for t in range(9):
            _off = struct.unpack_from(">I", data, p)[0]
            cnt = struct.unpack_from(">I", data, p + 4)[0]
            counts.append(cnt)
            p += 8
        tail0 = struct.unpack_from(">I", data, pos + 64 + 9 * 8)[0]
        tail1 = struct.unpack_from(">I", data, pos + 64 + 9 * 8 + 4)[0]
        zones.append({"name": name, "counts": counts, "tail0": tail0, "tail1": tail1})
    return zones


def hi16(x):
    return (x >> 16) & 0xFFFF


def lo16(x):
    return x & 0xFFFF


def main():
    if len(sys.argv) < 2:
        print("Usage: python tools/correlate_zone_tails.py <file.dat>")
        sys.exit(1)
    path = sys.argv[1]
    with open(path, "rb") as f:
        data = f.read()
    sections = read_header(data)
    zones = parse_zone_meta(data, sections)
    print(f"Zones={len(zones)}")
    # Print per zone quick table + basic correlations
    for idx, z in enumerate(zones):
        t0, t1 = z["tail0"], z["tail1"]
        counts = z["counts"]
        nz = sum(1 for c in counts if c)
        total = sum(counts)
        maxv = max(counts) if counts else 0
        maxidx = counts.index(maxv) if maxv else -1
        def match_pos(v):
            try:
                return counts.index(v)
            except ValueError:
                return -1
        h0, l0, h1, l1 = hi16(t0), lo16(t0), hi16(t1), lo16(t1)
        print(
            f"Zone[{idx}] '{z['name']}'\n"
            f"  counts={counts} nz={nz} total={total} max={maxv}@{maxidx}\n"
            f"  tail0=(hi={h0}, lo={l0}) match_idx=(hi->{match_pos(h0)}, lo->{match_pos(l0)})\n"
            f"  tail1=(hi={h1}, lo={l1}) match_idx=(hi->{match_pos(h1)}, lo->{match_pos(l1)})"
        )
    # Try mapping tail0/tail1 high/low 16 bits to one of the 9 counts
    candidates = []
    for a in range(9):
        for b in range(9):
            ok = True
            for z in zones:
                t0 = z["tail0"]
                if t0 == 0:
                    continue
                if hi16(t0) != z["counts"][a]:
                    ok = False
                    break
                if lo16(t0) != z["counts"][b]:
                    ok = False
                    break
            if ok:
                candidates.append(("tail0", a, b))
    for a in range(9):
        for b in range(9):
            ok = True
            for z in zones:
                t1 = z["tail1"]
                if t1 == 0:
                    continue
                if hi16(t1) != z["counts"][a]:
                    ok = False
                    break
                if lo16(t1) != z["counts"][b]:
                    ok = False
                    break
            if ok:
                candidates.append(("tail1", a, b))
    if not candidates:
        print("No direct (hi16,lo16) mapping to counts found across zones (non-zero tails).")
    else:
        for kind, a, b in candidates:
            print(f"{kind}: hi16=count[type {a}] lo16=count[type {b}]")


if __name__ == "__main__":
    main()


