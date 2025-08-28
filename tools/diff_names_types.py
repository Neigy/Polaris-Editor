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


def read_names(data: bytes, sections) -> list[str]:
    s = sections.get(NAMES_ID)
    if not s:
        return []
    start = s["offset"]
    total = s["size"]
    end = start + total
    if end > len(data):
        end = len(data)
    names = []
    cur = start
    while cur < end:
        # Read until null
        nxt = cur
        while nxt < end and data[nxt] != 0:
            nxt += 1
        try:
            if nxt > cur:
                names.append(data[cur:nxt].decode("utf-8", errors="ignore"))
            else:
                names.append("")
        except Exception:
            pass
        nxt += 1
        cur = nxt
    # Filtrer vides superflus
    return [n for n in names if n]


def read_instance_types(data: bytes, sections) -> dict[int, int]:
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


def main():
    if len(sys.argv) < 3:
        print("Usage: python tools/diff_names_types.py <A.dat> <B.dat>")
        sys.exit(1)
    with open(sys.argv[1], "rb") as f:
        A = f.read()
    with open(sys.argv[2], "rb") as f:
        B = f.read()

    SA = read_sections(A)
    SB = read_sections(B)

    namesA = set(read_names(A, SA))
    namesB = set(read_names(B, SB))
    onlyA = sorted(namesA - namesB)
    onlyB = sorted(namesB - namesA)
    print(f"Names: A={len(namesA)} B={len(namesB)}")
    print(f"  Missing in B: {len(onlyA)}")
    for n in onlyA[:50]:
        print(f"    - {n}")
    if len(onlyA) > 50:
        print(f"    ... (+{len(onlyA)-50} more)")
    print(f"  Extra in B: {len(onlyB)}")
    for n in onlyB[:20]:
        print(f"    + {n}")
    if len(onlyB) > 20:
        print(f"    ... (+{len(onlyB)-20} more)")

    typesA = read_instance_types(A, SA)
    typesB = read_instance_types(B, SB)
    tuidsA = set(typesA.keys())
    tuidsB = set(typesB.keys())
    missB = sorted(tuidsA - tuidsB)
    extraB = sorted(tuidsB - tuidsA)
    print(f"InstanceTypes: A={len(tuidsA)} B={len(tuidsB)}")
    print(f"  Missing in B (first 20): {len(missB)}")
    for t in missB[:20]:
        print(f"    - TUID=0x{t:016X} typeA={typesA.get(t)}")
    if len(missB) > 20:
        print(f"    ... (+{len(missB)-20} more)")
    print(f"  Extra in B (first 10): {len(extraB)}")
    for t in extraB[:10]:
        print(f"    + TUID=0x{t:016X} typeB={typesB.get(t)}")


if __name__ == "__main__":
    main()


