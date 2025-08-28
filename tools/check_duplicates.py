import sys
import struct


CLUE_METADATA_ID = 0x00025068
INST_TYPES_ID = 0x00025022


def read_sections(data: bytes):
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


def read_entries(data: bytes, sec, elem_size: int):
    off = sec["offset"]
    if sec["flag"] == 0x10:
        count = sec["count"]
        size = sec["size"]
    else:
        size = sec["size"]
        count = size // elem_size if elem_size else 0
    return [(off + i * (sec["size"] if sec["flag"] == 0x10 else elem_size)) for i in range(count)]


def collect_tuids_from_inst_types(data: bytes, sections):
    s = sections.get(INST_TYPES_ID)
    tuids = []
    if not s:
        return tuids
    entries = read_entries(data, s, 16)
    for pos in entries:
        tuid = struct.unpack_from(">Q", data, pos)[0]
        tuids.append(tuid)
    return tuids


def collect_tuids_from_clue_meta(data: bytes, sections):
    s = sections.get(CLUE_METADATA_ID)
    tuids = []
    if not s:
        return tuids
    entries = read_entries(data, s, 16)
    for pos in entries:
        tuid = struct.unpack_from(">Q", data, pos)[0]
        tuids.append(tuid)
    return tuids


def report(path: str):
    with open(path, "rb") as f:
        data = f.read()
    S = read_sections(data)
    inst_tuids = collect_tuids_from_inst_types(data, S)
    clue_meta_tuids = collect_tuids_from_clue_meta(data, S)

    def dup_count(seq):
        seen = set()
        dups = set()
        for x in seq:
            if x in seen:
                dups.add(x)
            else:
                seen.add(x)
        return len(dups)

    print(f"File: {path}")
    print(f"  0x25022 entries={len(inst_tuids)} duplicates={dup_count(inst_tuids)}")
    print(f"  CLUE_METADATA entries={len(clue_meta_tuids)} duplicates={dup_count(clue_meta_tuids)}")


def main():
    if len(sys.argv) < 2:
        print("Usage: python tools/check_duplicates.py <file.dat> [file2.dat]")
        sys.exit(1)
    for p in sys.argv[1:]:
        report(p)


if __name__ == "__main__":
    main()




