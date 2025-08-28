import sys
import struct
from collections import Counter


NAMES_ID = 0x00011300


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


def read_name_list(data: bytes, sections) -> list[str]:
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
        nxt = cur
        while nxt < end and data[nxt] != 0:
            nxt += 1
        try:
            nm = data[cur:nxt].decode("utf-8", errors="ignore") if nxt >= cur else ""
        except Exception:
            nm = ""
        names.append(nm)
        nxt += 1
        cur = nxt
    # Retirer les éventuelles chaînes vides terminales
    while names and names[-1] == "":
        names.pop()
    return names


def main():
    if len(sys.argv) < 3:
        print("Usage: python tools/diff_name_counts.py <A.dat> <B.dat>")
        sys.exit(1)
    with open(sys.argv[1], "rb") as f:
        A = f.read()
    with open(sys.argv[2], "rb") as f:
        B = f.read()
    SA = read_sections(A)
    SB = read_sections(B)
    namesA = read_name_list(A, SA)
    namesB = read_name_list(B, SB)
    cA = Counter(namesA)
    cB = Counter(namesB)
    # Diff de multiplicité
    all_keys = set(cA.keys()) | set(cB.keys())
    diffs = []
    for k in all_keys:
        if cA[k] != cB[k]:
            diffs.append((k, cA[k], cB[k]))
    print(f"Total names (with multiplicity): A={len(namesA)} B={len(namesB)}")
    print(f"Unique names: A={len(cA)} B={len(cB)}")
    print(f"Names with different multiplicity: {len(diffs)} (show up to 50)")
    for k, a, b in diffs[:50]:
        alen = len(k.encode('utf-8')) if k else 0
        print(f"  '{k}' bytes={alen} countA={a} countB={b} deltaBytes={(a-b)*(alen+1)}")
    # Totaux bytes reconstitués
    bytesA = sum((len(k.encode('utf-8')) + 1) * v for k, v in cA.items())
    bytesB = sum((len(k.encode('utf-8')) + 1) * v for k, v in cB.items())
    print(f"Reconstructed bytes (sum of len+1): A={bytesA} B={bytesB} delta={bytesA-bytesB}")


if __name__ == "__main__":
    main()


