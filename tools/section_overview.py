import sys
import struct


SECTIONS = [
    0x00025022,  # Instance Types
    0x00025094,  # Scent Offsets
    0x0002507C,  # Pod Offsets
    0x00025088,  # Area Offsets
    0x00025064,  # Clue Info
    0x00025080,  # Area Data
    0x00025084,  # Area Metadata
    0x00025058,  # Path Points
]


def read_sections(data: bytes):
    if data[:4] != b"IGHW":
        raise ValueError("Bad magic")
    ver_major = struct.unpack_from(">H", data, 0x04)[0]
    ver_minor = struct.unpack_from(">H", data, 0x06)[0]
    if ver_major == 0:
        section_count = struct.unpack_from(">H", data, 0x08)[0]
        header_len = 0x10 + 16 * section_count
        sh_base = 0x10
        ptr_off = 0
        ptr_cnt = 0
    else:
        section_count = struct.unpack_from(">I", data, 0x08)[0]
        header_len = struct.unpack_from(">I", data, 0x0C)[0]
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
    return {
        "ver": (ver_major, ver_minor),
        "section_count": section_count,
        "header_len": header_len,
        "ptr_off": ptr_off,
        "ptr_cnt": ptr_cnt,
        "sections": sections,
    }


def main():
    if len(sys.argv) < 3:
        print("Usage: python tools/section_overview.py <A.dat> <B.dat>")
        sys.exit(1)
    with open(sys.argv[1], "rb") as f:
        A = f.read()
    with open(sys.argv[2], "rb") as f:
        B = f.read()
    SA = read_sections(A)
    SB = read_sections(B)

    print(f"Header A ver={SA['ver']} sections={SA['section_count']} hdr_len=0x{SA['header_len']:X} ptr_off=0x{SA['ptr_off']:X} ptr_cnt={SA['ptr_cnt']}")
    print(f"Header B ver={SB['ver']} sections={SB['section_count']} hdr_len=0x{SB['header_len']:X} ptr_off=0x{SB['ptr_off']:X} ptr_cnt={SB['ptr_cnt']}")
    print("Sections:")
    for sid in SECTIONS:
        a = SA['sections'].get(sid)
        b = SB['sections'].get(sid)
        def fmt(x):
            return f"off=0x{x['offset']:X} flag={x['flag']:02X} count={x['count']} size={x['size']}" if x else "(absent)"
        print(f"  0x{sid:08X} A: {fmt(a)} | B: {fmt(b)}")


if __name__ == "__main__":
    main()


