import sys
import struct


def read_header(data: bytes):
    if data[:4] != b"IGHW":
        raise ValueError("Bad magic")
    ver_major = struct.unpack_from(">H", data, 0x04)[0]
    if ver_major == 0:
        section_count = struct.unpack_from(">H", data, 0x08)[0]
        sh_base = 0x10
        ptr_off = 0
        ptr_cnt = 0
    else:
        section_count = struct.unpack_from(">I", data, 0x08)[0]
        sh_base = 0x20
        ptr_off = struct.unpack_from(">I", data, 0x10)[0]
        ptr_cnt = struct.unpack_from(">I", data, 0x14)[0]
    sections = {}
    for i in range(section_count):
        off = sh_base + i * 16
        sid, data_off = struct.unpack_from(">II", data, off)
        flag = data[off + 8]
        count = int.from_bytes(data[off + 9: off + 12], "big")
        size = struct.unpack_from(">I", data, off + 12)[0]
        sections[sid] = {"offset": data_off, "flag": flag, "count": count, "size": size}
    return sections


def total_bytes(sec):
    return sec["size"] if sec["flag"] == 0x00 else sec["count"] * sec["size"]


def section_for_pos(sections, pos: int):
    for sid, s in sections.items():
        start = s["offset"]
        end = start + total_bytes(s)
        if start <= pos < end:
            return sid
    return None


def parse_zone_entries(data: bytes, sections):
    ZID = 0x00025008
    s = sections.get(ZID)
    if not s:
        return []
    if s["flag"] != 0x10 or s["size"] != 144:
        return []
    out = []
    base = s["offset"]
    for i in range(s["count"]):
        pos = base + i * 144
        name = data[pos: pos + 64].split(b"\x00", 1)[0].decode("utf-8", errors="ignore")
        tails = data[pos + 64 + 9 * 8: pos + 64 + 9 * 8 + 8]
        t0 = struct.unpack_from(">I", tails, 0)[0]
        t1 = struct.unpack_from(">I", tails, 4)[0]
        out.append({"index": i, "name": name, "tail0": t0, "tail1": t1})
    return out


def main():
    if len(sys.argv) < 2:
        print("Usage: python tools/analyze_zone_tail.py <file.dat> [file2.dat]")
        sys.exit(1)
    paths = sys.argv[1:]
    for p in paths:
        with open(p, "rb") as f:
            data = f.read()
        sections = read_header(data)
        zones = parse_zone_entries(data, sections)
        print(f"File: {p} zones={len(zones)}")
        # Stats
        zeros = sum(1 for z in zones if z["tail0"] == 0 and z["tail1"] == 0)
        print(f"  tails_zero={zeros}")
        for z in zones:
            t0 = z["tail0"]
            t1 = z["tail1"]
            sid0 = section_for_pos(sections, t0) if t0 != 0 else None
            sid1 = section_for_pos(sections, t1) if t1 != 0 else None
            hint0 = f"->0x{sid0:08X}" if sid0 is not None else ("->0" if t0 == 0 else "->out")
            hint1 = f"->0x{sid1:08X}" if sid1 is not None else ("->0" if t1 == 0 else "->out")
            print(f"  Zone[{z['index']}] '{z['name']}' tail0=0x{t0:08X} {hint0} tail1=0x{t1:08X} {hint1}")


if __name__ == "__main__":
    main()



