import sys
import struct


def parse_header(data: bytes):
    if data[:4] != b"IGHW":
        raise ValueError("Bad magic")
    ver_major = struct.unpack_from(">H", data, 0x04)[0]
    ver_minor = struct.unpack_from(">H", data, 0x06)[0]
    if ver_major == 0:
        # not expected here, but keep parser
        section_count = struct.unpack_from(">H", data, 0x08)[0]
        header_len = 0x10 + 16 * section_count
        ptr_off = 0
        ptr_cnt = 0
        sh_base = 0x10
    else:
        section_count = struct.unpack_from(">I", data, 0x08)[0]
        header_len = struct.unpack_from(">I", data, 0x0C)[0]
        ptr_off = struct.unpack_from(">I", data, 0x10)[0]
        ptr_cnt = struct.unpack_from(">I", data, 0x14)[0]
        sh_base = 0x20
    sections = []
    for i in range(section_count):
        off = sh_base + i * 16
        sid, data_off = struct.unpack_from(">II", data, off)
        flag = data[off + 8]
        count = int.from_bytes(data[off + 9: off + 12], "big")
        size = struct.unpack_from(">I", data, off + 12)[0]
        sections.append((sid, data_off, flag, count, size))
    return {
        "ver": (ver_major, ver_minor),
        "section_count": section_count,
        "header_len": header_len,
        "ptr_off": ptr_off,
        "ptr_cnt": ptr_cnt,
        "sections": sections,
    }


def load(path: str):
    with open(path, "rb") as f:
        return f.read()


def main():
    if len(sys.argv) < 3:
        print("Usage: python tools/verify_ighw.py <original.dat> <rebuilt.dat>")
        sys.exit(1)
    a = load(sys.argv[1])
    b = load(sys.argv[2])
    A = parse_header(a)
    B = parse_header(b)

    def fmt_secs(S):
        return [f"{sid:08X}@{off:08X} f={flag:02X} c={cnt} sz={sz}" for sid, off, flag, cnt, sz in S]

    print("Header:")
    print(f"  A ver={A['ver']} sections={A['section_count']} hdr_len=0x{A['header_len']:X} ptr_off=0x{A['ptr_off']:X} ptr_cnt={A['ptr_cnt']}")
    print(f"  B ver={B['ver']} sections={B['section_count']} hdr_len=0x{B['header_len']:X} ptr_off=0x{B['ptr_off']:X} ptr_cnt={B['ptr_cnt']}")

    print("Sections (only diffs shown):")
    setA = {(sid, flag) for sid, off, flag, cnt, sz in A['sections']}
    setB = {(sid, flag) for sid, off, flag, cnt, sz in B['sections']}
    onlyA = sorted([sid for sid, _ in setA - setB])
    onlyB = sorted([sid for sid, _ in setB - setA])
    if onlyA:
        print("  Only in A:", [f"0x{sid:08X}" for sid in onlyA])
    if onlyB:
        print("  Only in B:", [f"0x{sid:08X}" for sid in onlyB])

    # Compare per-section offsets/count/size if same ids exist
    mapA = {sid: (off, flag, cnt, sz) for sid, off, flag, cnt, sz in A['sections']}
    mapB = {sid: (off, flag, cnt, sz) for sid, off, flag, cnt, sz in B['sections']}
    for sid in sorted(set(mapA.keys()) & set(mapB.keys())):
        offA, flagA, cntA, szA = mapA[sid]
        offB, flagB, cntB, szB = mapB[sid]
        diffs = []
        if flagA != flagB: diffs.append(f"flag {flagA:02X}!={flagB:02X}")
        if cntA != cntB: diffs.append(f"count {cntA}!={cntB}")
        if szA != szB: diffs.append(f"size {szA}!={szB}")
        if diffs:
            print(f"  0x{sid:08X}: " + ", ".join(diffs))

    # Pointer table quick check
    if A['ptr_off'] and A['ptr_cnt']:
        aptrs = struct.unpack_from(f">{A['ptr_cnt']}I", a, A['ptr_off'])
    else:
        aptrs = ()
    if B['ptr_off'] and B['ptr_cnt']:
        bptrs = struct.unpack_from(f">{B['ptr_cnt']}I", b, B['ptr_off'])
    else:
        bptrs = ()
    print(f"Pointers: A={len(aptrs)} B={len(bptrs)}")
    # show first few mismatches
    for i in range(min(len(aptrs), len(bptrs))):
        if aptrs[i] == bptrs[i]:
            continue
        print(f"  ptr[{i}]: A=0x{aptrs[i]:08X} B=0x{bptrs[i]:08X}")
        if i > 10:
            break


if __name__ == "__main__":
    main()


