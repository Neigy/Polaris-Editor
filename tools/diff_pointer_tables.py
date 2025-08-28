import sys
import struct


SECS = {
    0x00025048: ("MOBY_DATA", 80),
    0x0002504C: ("MOBY_METADATA", 16),
    0x00025050: ("PATH_DATA", 16),
    0x00025054: ("PATH_METADATA", 16),
    0x00025058: ("PATH_POINTS", 16),
    0x0002505C: ("VOLUME_TRANSFORM", 64),
    0x00025060: ("VOLUME_METADATA", 16),
    0x00025064: ("CLUE_INFO", 16),
    0x00025068: ("CLUE_METADATA", 16),
    0x0002506C: ("CONTROLLER_DATA", 48),
    0x00025070: ("CONTROLLER_METADATA", 16),
    0x00025074: ("POD_DATA", 16),
    0x00025078: ("POD_METADATA", 16),
    0x0002507C: ("POD_OFFSETS", 4),
    0x00025080: ("AREA_DATA", 16),
    0x00025084: ("AREA_METADATA", 16),
    0x00025088: ("AREA_OFFSETS", 4),
    0x0002508C: ("SCENT_DATA", 16),
    0x00025090: ("SCENT_METADATA", 16),
    0x00025094: ("SCENT_OFFSETS", 4),
    0x00025008: ("ZONE_METADATA", 144),
    0x0002500C: ("ZONE_OFFSETS", 36),
    0x00025010: ("DEFAULT_REGION_NAMES", 0x48),
    0x00025005: ("REGION_DATA", 16),
    0x00011300: ("NAMES", 0),
    0x00025022: ("INSTANCE_TYPES", 16),
}


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
    secs = []
    for i in range(section_count):
        off = sh_base + i * 16
        sid, data_off = struct.unpack_from(">II", data, off)
        flag = data[off + 8]
        count = int.from_bytes(data[off + 9: off + 12], "big")
        size = struct.unpack_from(">I", data, off + 12)[0]
        secs.append((sid, data_off, flag, count, size))
    ptrs = []
    if ptr_off and ptr_cnt:
        for i in range(ptr_cnt):
            ptrs.append(struct.unpack_from(">I", data, ptr_off + 4 * i)[0])
    return secs, ptrs


def section_for_pos(sections, pos: int):
    for sid, off, flag, cnt, size in sections:
        total = size if flag == 0x00 else cnt * size
        if off <= pos < off + total:
            return (sid, off, flag, cnt, size)
    return None


def classify_pointer(sections, data: bytes, pos: int):
    s = section_for_pos(sections, pos)
    if not s:
        return ("UNKNOWN", None)
    sid, off, flag, cnt, size = s
    name, elem = SECS.get(sid, (f"0x{sid:08X}", size))
    rel = pos - off
    idx = (rel // elem) if elem else 0
    ofs = (rel % elem) if elem else rel
    # Heuristiques de champ
    field = None
    if sid == 0x00025080:  # AREA_DATA
        field = "Area.path_offset" if ofs == 0 else ("Area.volume_offset" if ofs == 4 else f"+{ofs}")
    elif sid == 0x00025074 and ofs == 0:
        field = "Pod.list_offset"
    elif sid == 0x0002508C and ofs == 0:
        field = "Scent.list_offset"
    elif sid == 0x0002506C and ofs == 0:
        field = "Controller.subfile_offset"
    elif sid == 0x00025048 and ofs == 12:
        field = "Moby.subfile_offset"
    elif sid == 0x00025064:
        field = "Clue.instType_offset" if ofs == 0 else ("Clue.subfile_offset" if ofs == 4 else f"+{ofs}")
    elif sid == 0x00025008 and ofs >= 64:
        t = (ofs - 64) // 8
        field = f"ZoneMeta.type[{t}].data_offset"
    elif sid == 0x0002500C:
        t = ofs // 4
        field = f"ZoneOffsets.type[{t}].meta_offset"
    else:
        field = f"+{ofs}"
    return (name, idx, field)


def main():
    if len(sys.argv) < 3:
        print("Usage: python tools/diff_pointer_tables.py <original.dat> <rebuilt.dat>")
        sys.exit(1)
    with open(sys.argv[1], "rb") as f:
        A = f.read()
    with open(sys.argv[2], "rb") as f:
        B = f.read()
    SA, Aptrs = read_header(A)
    SB, Bptrs = read_header(B)
    setB = set(Bptrs)
    missing = [p for p in Aptrs if p not in setB]
    print(f"Pointers: A={len(Aptrs)} B={len(Bptrs)} missing_in_B={len(missing)}")
    # Regrouper par section
    counts = {}
    samples = {}
    for p in missing:
        cls = classify_pointer(SA, A, p)
        key = cls[0]
        counts[key] = counts.get(key, 0) + 1
        if key not in samples:
            samples[key] = []
        if len(samples[key]) < 5:
            samples[key].append((p, cls))
    for k in sorted(counts.keys(), key=lambda x: (-counts[x], x)):
        print(f"  {k}: {counts[k]}")
    # Montrer quelques exemples
    print("Samples:")
    for k, arr in samples.items():
        for p, cls in arr[:3]:
            _, idx, field = cls
            print(f"  0x{p:08X} -> {k}[{idx}] {field}")


if __name__ == "__main__":
    main()


