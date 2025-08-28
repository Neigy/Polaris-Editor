import sys
import struct


def read_header(data: bytes):
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
    sections.sort(key=lambda e: e[1])
    return {
        "ver": (ver_major, ver_minor),
        "header_len": header_len,
        "ptr_off": ptr_off,
        "ptr_cnt": ptr_cnt,
        "sections": sections,
    }


def pattern_matches(buf: bytes) -> bool:
    if not buf:
        return True
    pat = bytes([i for i in range(1, 16)])
    for i, b in enumerate(buf):
        if b != pat[i % len(pat)]:
            return False
    return True


def analyze(path: str):
    with open(path, 'rb') as f:
        data = f.read()
    H = read_header(data)
    items = H['sections']

    print(f"File: {path}")
    print(f"  header_len=0x{H['header_len']:X} ptr_off=0x{H['ptr_off']:X} ptr_cnt={H['ptr_cnt']}")
    # Gap header -> first section
    items_sorted = items
    if not items_sorted:
        return
    first_off = items_sorted[0][1]
    gap = first_off - H['header_len']
    pad = data[H['header_len']:first_off]
    print(f"  gap header->sec0: {gap} bytes, align={first_off % 0x80 == 0}, pad_pattern={pattern_matches(pad)} uniq={sorted(set(pad))[:4]}")
    # Gaps between sections
    for i in range(len(items_sorted) - 1):
        sid, off, flag, cnt, sz = items_sorted[i]
        total = sz if flag == 0x00 else cnt * sz
        end = off + total
        sid2, off2, *_ = items_sorted[i + 1]
        gap = off2 - end
        pad = data[end:off2]
        print(f"  gap 0x{sid:08X}->0x{sid2:08X}: {gap} bytes, next_off=0x{off2:X} align80={off2 % 0x80 == 0} pad_pattern={pattern_matches(pad)} uniq={sorted(set(pad))[:4]}")
    # Gap last section -> pointer table
    sid, off, flag, cnt, sz = items_sorted[-1]
    total = sz if flag == 0x00 else cnt * sz
    end = off + total
    ptoff = H['ptr_off']
    if ptoff:
        gap = ptoff - end
        pad = data[end:ptoff]
        print(f"  gap last->ptr_table: {gap} bytes, ptr_off=0x{ptoff:X} align80={ptoff % 0x80 == 0} pad_pattern={pattern_matches(pad)} uniq={sorted(set(pad))[:4]}")


def main():
    if len(sys.argv) < 2:
        print("Usage: python tools/analyze_padding.py <file1.dat> [file2.dat]")
        sys.exit(1)
    for p in sys.argv[1:]:
        analyze(p)


if __name__ == '__main__':
    main()



