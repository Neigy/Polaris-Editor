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
    if len(sys.argv) < 1:
        print("Usage: python tools/analyze_zone_model_stats.py <file.dat>")
        sys.exit(1)
    path = sys.argv[1]
    with open(path, "rb") as f:
        data = f.read()
    sections = read_header(data)
    zones = parse_zones(data, sections)
    moby = sections.get(MOBY_DATA_ID)
    print(f"Zones={len(zones)}")
    for idx, z in enumerate(zones):
        off, cnt = z["entries"][0]
        t0, t1 = z["tail0"], z["tail1"]
        if cnt == 0 or off == 0:
            print(f"Zone[{idx}] '{z['name']}' moby=0 tail0=(hi={hi16(t0)}, lo={lo16(t0)}) tail1=(hi={hi16(t1)}, lo={lo16(t1)})")
            continue
        models = Counter()
        for i in range(cnt):
            pos = off + i * 80
            model_index = struct.unpack_from(">H", data, pos + 0)[0]
            models[model_index] += 1
        distinct = len(models)
        most = models.most_common(4)
        top_counts = [c for _m, c in most]
        while len(top_counts) < 4:
            top_counts.append(0)
        print(
            f"Zone[{idx}] '{z['name']}' moby_cnt={cnt} distinct_models={distinct} top4={top_counts} "
            f"tails: ({hi16(t0)},{lo16(t0)},{hi16(t1)},{lo16(t1)})"
        )


if __name__ == "__main__":
    main()



