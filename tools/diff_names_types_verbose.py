import sys
import struct

NAMES_ID = 0x00011300
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


def find_name_by_offset(data: bytes, names_section, name_off: int) -> str:
    # Best effort: si l'offset pointe dans la section des noms, lire la chaîne
    if not names_section:
        return ""
    start = names_section["offset"]
    end = start + names_section["size"]
    if not (start <= name_off < end):
        return ""
    cur = name_off
    buf = []
    while cur < end and data[cur] != 0:
        buf.append(data[cur])
        cur += 1
    try:
        return bytes(buf).decode("utf-8", errors="ignore")
    except Exception:
        return ""


def find_name_for_tuid(data: bytes, sections, tuid: int) -> str:
    # Chercher dans les métadatas connues (Moby, Path, Volume, Clue, Controller, Area, Pod, Scent)
    meta_ids = [0x0002504C, 0x00025054, 0x00025060, 0x00025068, 0x00025070, 0x00025084, 0x00025078, 0x00025090]
    names_section = sections.get(NAMES_ID)
    for sid in meta_ids:
        s = sections.get(sid)
        if not s:
            continue
        count = s["count"] if s["flag"] == 0x10 else (s["size"] // 16)
        base = s["offset"]
        for i in range(count):
            pos = base + i * 16
            if pos + 16 <= len(data):
                t = struct.unpack_from(">Q", data, pos)[0]
                if t == tuid:
                    name_off = struct.unpack_from(">I", data, pos + 8)[0]
                    nm = find_name_by_offset(data, names_section, name_off)
                    return nm
    return ""


def main():
    if len(sys.argv) < 3:
        print("Usage: python tools/diff_names_types_verbose.py <A.dat> <B.dat>")
        sys.exit(1)
    with open(sys.argv[1], "rb") as f:
        A = f.read()
    with open(sys.argv[2], "rb") as f:
        B = f.read()
    SA = read_sections(A)
    SB = read_sections(B)

    # Lire Instance Types
    def read_types(data, sections):
        s = sections.get(INST_TYPES_ID)
        if not s:
            return {}
        off = s["offset"]
        flag = s["flag"]
        size = s["size"]
        count = s["count"] if flag == 0x10 else (size // 16 if size else 0)
        out = {}
        for i in range(count):
            pos = off + i * 16
            if pos + 16 <= len(data):
                tuid = struct.unpack_from(">Q", data, pos)[0]
                type_id = struct.unpack_from(">I", data, pos + 8)[0]
                out[tuid] = type_id
        return out

    typesA = read_types(A, SA)
    typesB = read_types(B, SB)
    missB = sorted(set(typesA.keys()) - set(typesB.keys()))
    print(f"Missing in B = {len(missB)} (show up to 100):")
    for t in missB[:100]:
        nm = find_name_for_tuid(A, SA, t)
        print(f"  - TUID=0x{t:016X} typeA={typesA.get(t)} name='{nm}'")


if __name__ == "__main__":
    main()


