import sys
import struct
from collections import Counter


ZID = 0x00025008
MOBY_DATA_ID = 0x00025048


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


def parse_zones(data: bytes, sections):
    s = sections.get(ZID)
    if not s or s["flag"] != 0x10 or s["size"] != 144:
        return []
    zones = []
    base = s["offset"]
    for i in range(s["count"]):
        pos = base + i * 144
        name = data[pos: pos + 64].split(b"\x00", 1)[0].decode("utf-8", errors="ignore")
        p = pos + 64
        entries = []
        for t in range(9):
            off = struct.unpack_from(">I", data, p)[0]
            cnt = struct.unpack_from(">I", data, p + 4)[0]
            entries.append((off, cnt))
            p += 8
        tail0 = struct.unpack_from(">I", data, pos + 64 + 9 * 8)[0]
        tail1 = struct.unpack_from(">I", data, pos + 64 + 9 * 8 + 4)[0]
        zones.append({"name": name, "entries": entries, "tail0": tail0, "tail1": tail1})
    return zones


def hi16(x):
    return (x >> 16) & 0xFFFF


def lo16(x):
    return x & 0xFFFF


def main():
    if len(sys.argv) < 2:
        print("Usage: python tools/analyze_zone_moby_flags.py <file.dat>")
        sys.exit(1)
    path = sys.argv[1]
    with open(path, "rb") as f:
        data = f.read()
    sections = read_header(data)
    zones = parse_zones(data, sections)
    moby_sec = sections.get(MOBY_DATA_ID)
    if not moby_sec:
        print("No Moby data section")
        return
    print(f"Zones={len(zones)}")
    for idx, z in enumerate(zones):
        off, cnt = z["entries"][0]
        flags_counter = Counter()
        bit_counter = Counter()
        if cnt > 0 and off != 0:
            for i in range(cnt):
                pos = off + i * 80
                flags = data[pos + 48: pos + 56]
                flags_counter[flags] += 1
                # compter bits individuels sur le premier octet (heuristique)
                b0 = flags[0]
                for b in range(8):
                    if b0 & (1 << b):
                        bit_counter[b] += 1
        t0, t1 = z["tail0"], z["tail1"]
        print(f"Zone[{idx}] '{z['name']}' Moby cnt={cnt} tail0=(hi={hi16(t0)}, lo={lo16(t0)}) tail1=(hi={hi16(t1)}, lo={lo16(t1)})")
        if cnt > 0 and off != 0:
            most = flags_counter.most_common(3)
            print("  Top flags patterns:")
            for (fv, c) in most:
                print(f"    {fv.hex()} x{c}")
            print("  First-byte bit counts:")
            for b in range(8):
                v = bit_counter.get(b, 0)
                if v:
                    print(f"    bit{b}={v}")


if __name__ == "__main__":
    main()



