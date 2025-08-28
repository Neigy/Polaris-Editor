import sys
import struct


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


def read_types(data: bytes, sections):
    s = sections.get(INST_TYPES_ID)
    if not s:
        return {}, {}
    off = s["offset"]
    flag = s["flag"]
    size = s["size"]
    count = s["count"] if flag == 0x10 else (size // 16 if size else 0)
    tuid_to_type = {}
    tuid_to_addr = {}
    for i in range(count):
        pos = off + i * 16
        if pos + 16 <= len(data):
            tuid = struct.unpack_from(">Q", data, pos)[0]
            type_id = struct.unpack_from(">I", data, pos + 8)[0]
            tuid_to_type[tuid] = type_id
            tuid_to_addr[tuid] = pos
    return tuid_to_type, tuid_to_addr


def section_for_pos(sections, pos: int):
    for sid, s in sections.items():
        start = s["offset"]
        total = s["size"] if s["flag"] == 0x00 else s["count"] * s["size"]
        if start <= pos < start + total:
            return sid
    return None


def find_u32_positions(data: bytes, value: int):
    # big-endian 4-byte value
    pat = value.to_bytes(4, "big")
    positions = []
    start = 0
    while True:
        idx = data.find(pat, start)
        if idx == -1:
            break
        positions.append(idx)
        start = idx + 1
    return positions


def main():
    if len(sys.argv) < 3:
        print("Usage: python tools/analyze_25022_refs.py <original.dat> <rebuilt.dat>")
        sys.exit(1)
    with open(sys.argv[1], "rb") as f:
        A = f.read()
    with open(sys.argv[2], "rb") as f:
        B = f.read()

    SA = read_sections(A)
    SB = read_sections(B)
    typesA, addrA = read_types(A, SA)
    typesB, addrB = read_types(B, SB)

    tuidsA = set(typesA.keys())
    tuidsB = set(typesB.keys())
    missing_in_B = sorted(tuidsA - tuidsB)
    # Duplicates check in A
    dup_check = {}
    dups = []
    for t in typesA.keys():
        if t in dup_check:
            dups.append(t)
        else:
            dup_check[t] = True
    print(f"Missing in B: {len(missing_in_B)}; Duplicates in A: {len(dups)}")

    referenced = 0
    unreferenced = 0
    show_limit = 50
    for tuid in missing_in_B[:200]:
        entry_addr = addrA.get(tuid)
        if entry_addr is None:
            continue
        hits = find_u32_positions(A, entry_addr)
        # Exclure occurrences à l'intérieur de la section 0x25022 elle-même
        hits = [h for h in hits if section_for_pos(SA, h) != INST_TYPES_ID]
        if hits:
            referenced += 1
            # Montrer les 2 premières avec leur section
            for h in hits[:2]:
                sid = section_for_pos(SA, h)
                print(f"REF: tuid=0x{tuid:016X} addr=0x{entry_addr:08X} used_at=0x{h:08X} sec=0x{sid:08X}")
        else:
            unreferenced += 1
            print(f"NREF: tuid=0x{tuid:016X} addr=0x{entry_addr:08X}")
            if unreferenced >= show_limit:
                break
    print(f"Summary: referenced={referenced}, unreferenced~(first {show_limit})={unreferenced}")


if __name__ == "__main__":
    main()


