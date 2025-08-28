import sys
import struct


def parse_header(data: bytes):
    if data[:4] != b"IGHW":
        raise ValueError("Bad magic")
    ver_major = struct.unpack_from(">H", data, 0x04)[0]
    ver_minor = struct.unpack_from(">H", data, 0x06)[0]
    if ver_major == 0:
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


def total_bytes(entry):
    sid, off, flag, cnt, sz = entry
    return cnt * sz if flag == 0x10 else sz


def expected_entries(entry, default_elem_size=16):
    sid, off, flag, cnt, sz = entry
    if flag == 0x10:
        return cnt
    # single block → derive by size/elem
    return sz // default_elem_size if default_elem_size else 0


def load(path: str):
    with open(path, "rb") as f:
        return f.read()


def main():
    if len(sys.argv) < 3:
        print("Usage: python tools/diag_ighw.py <original.dat> <rebuilt.dat>")
        sys.exit(1)
    a = load(sys.argv[1])
    b = load(sys.argv[2])
    A = parse_header(a)
    B = parse_header(b)

    mapA = {e[0]: e for e in A['sections']}
    mapB = {e[0]: e for e in B['sections']}

    def show(s, eA, eB, elem_size=None):
        if s in mapA and s in mapB:
            tA = total_bytes(mapA[s])
            tB = total_bytes(mapB[s])
            cA = expected_entries(mapA[s], elem_size)
            cB = expected_entries(mapB[s], elem_size)
            print(f"0x{s:08X}: flag A/B = {mapA[s][2]:02X}/{mapB[s][2]:02X}, elem_size={mapA[s][4] if mapA[s][2]==0x10 else elem_size}, total A/B = {tA}/{tB}, entries A/B ≈ {cA}/{cB}")
        else:
            print(f"0x{s:08X}: missing in one file")

    print("Diag sections clés:")
    # Name tables
    show(0x00011300, A, B, None)
    # Instance types
    show(0x00025022, A, B, 16)
    # Host/Local
    show(0x00025020, A, B, None)
    show(0x00025030, A, B, None)
    # Paths
    show(0x00025050, A, B, 16)  # data
    show(0x00025058, A, B, 16)  # points (16 bytes/point)
    # Areas
    show(0x00025080, A, B, 16)
    show(0x00025084, A, B, 16)
    show(0x00025088, A, B, 36)


if __name__ == "__main__":
    main()


