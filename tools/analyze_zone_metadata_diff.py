import sys
import struct


TYPE_NAMES = [
    "MobyData", "PathData", "VolumeXform", "ClueInfo",
    "ControllerData", "AreaData", "PodData", "ScentData", "Unused"
]

TYPE_SECTIONS = [
    0x00025048, 0x00025050, 0x0002505C, 0x00025064,
    0x0002506C, 0x00025080, 0x00025074, 0x0002508C, 0
]


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
    ordered = []
    for i in range(section_count):
        off = sh_base + i * 16
        sid, data_off = struct.unpack_from(">II", data, off)
        flag = data[off + 8]
        count = int.from_bytes(data[off + 9: off + 12], "big")
        size = struct.unpack_from(">I", data, off + 12)[0]
        sections[sid] = {"offset": data_off, "flag": flag, "count": count, "size": size}
        ordered.append((sid, data_off, flag, count, size))
    return sections, ordered, ptr_off, ptr_cnt


def total_bytes(sec):
    return sec["size"] if sec["flag"] == 0x00 else sec["count"] * sec["size"]


def parse_zone_metadata(data: bytes, sections):
    ZID = 0x00025008
    s = sections.get(ZID)
    if not s:
        return []
    if s["flag"] != 0x10 or s["size"] != 144:
        # Format inattendu
        return []
    out = []
    base = s["offset"]
    for i in range(s["count"]):
        pos = base + i * 144
        name_bytes = data[pos: pos + 64]
        name = name_bytes.split(b"\x00", 1)[0].decode("utf-8", errors="ignore")
        entries = []
        p = pos + 64
        for t in range(9):
            off = struct.unpack_from(">I", data, p)[0]
            cnt = struct.unpack_from(">I", data, p + 4)[0]
            entries.append((off, cnt))
            p += 8
        tail = struct.unpack_from(">HHHH", data, pos + 64 + 9 * 8)
        out.append({"index": i, "name": name, "entries": entries, "tail_u16": tail})
    return out


def main():
    if len(sys.argv) < 3:
        print("Usage: python tools/analyze_zone_metadata_diff.py <original.dat> <rebuilt.dat>")
        sys.exit(1)
    with open(sys.argv[1], "rb") as f:
        A = f.read()
    with open(sys.argv[2], "rb") as f:
        B = f.read()

    SA, _, _, _ = read_header(A)
    SB, _, _, _ = read_header(B)
    zonesA = parse_zone_metadata(A, SA)
    zonesB = parse_zone_metadata(B, SB)

    print(f"Zones: A={len(zonesA)} B={len(zonesB)}")
    if len(zonesA) != len(zonesB):
        print("  Different zone counts")

    n = min(len(zonesA), len(zonesB))
    diffs = 0
    for i in range(n):
        ZA = zonesA[i]
        ZB = zonesB[i]
        name_diff = (ZA["name"] != ZB["name"])
        entry_diffs = []
        for t in range(9):
            offA, cntA = ZA["entries"][t]
            offB, cntB = ZB["entries"][t]
            if cntA != cntB or offA != offB or (offA == 0) != (offB == 0):
                entry_diffs.append((t, (offA, cntA), (offB, cntB)))
        print(f"Zone[{i}] A='{ZA['name']}' | B='{ZB['name']}'")
        for t in range(9):
            offA, cntA = ZA["entries"][t]
            offB, cntB = ZB["entries"][t]
            tname = TYPE_NAMES[t]
            mark = " !=" if (offA != offB or cntA != cntB) else "  ="
            print(f"  {t:02d} {tname}:{mark} A(off=0x{offA:08X}, cnt={cntA})  B(off=0x{offB:08X}, cnt={cntB})")
        ta = ZA.get("tail_u16", (0, 0, 0, 0))
        tb = ZB.get("tail_u16", (0, 0, 0, 0))
        mark_tail = " !=" if ta != tb else "  ="
        print(f"  tail_u16:{mark_tail} A={tuple(f'0x{x:04X}' for x in ta)}  B={tuple(f'0x{x:04X}' for x in tb)}")
        if name_diff or entry_diffs:
            diffs += 1
    if diffs == 0:
        print("No per-zone differences detected in 0x00025008 (values identical).")


if __name__ == "__main__":
    main()


