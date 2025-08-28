import sys
import struct


ZID = 0x00025008
MOBY_DATA_ID = 0x00025048
CLUE_INFO_ID = 0x00025064
CTRL_DATA_ID = 0x0002506C


def read_header(data: bytes):
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


def parse_zones(data: bytes, sections):
    s = sections.get(ZID)
    if not s or s["flag"] != 0x10 or s["size"] != 144:
        return []
    zones = []
    base = s["offset"]
    for i in range(s["count"]):
        pos = base + i * 144
        name = data[pos: pos + 64].split(b"\x00", 1)[0].decode("utf-8", errors="ignore")
        entries = []
        p = pos + 64
        for t in range(9):
            off = struct.unpack_from(">I", data, p)[0]
            cnt = struct.unpack_from(">I", data, p + 4)[0]
            entries.append((off, cnt))
            p += 8
        tail0 = struct.unpack_from(">I", data, pos + 64 + 9 * 8)[0]
        tail1 = struct.unpack_from(">I", data, pos + 64 + 9 * 8 + 4)[0]
        zones.append({"name": name, "entries": entries, "tail0": tail0, "tail1": tail1})
    return zones


def _in_section(sections, sid: int, pos: int) -> bool:
    s = sections.get(sid)
    if not s:
        return False
    start = s["offset"]
    end = start + (s["size"] if s["flag"] == 0x00 else s["count"] * s["size"])
    return start <= pos < end


def count_moby_subfiles(data: bytes, sections, off: int, cnt: int) -> tuple[int, int, int]:
    if cnt == 0 or not sections.get(MOBY_DATA_ID):
        return (0, 0, 0)
    size = 80
    host = local = none = 0
    for i in range(cnt):
        pos = off + i * size
        sub_off = struct.unpack_from(">I", data, pos + 12)[0]
        sub_len = struct.unpack_from(">I", data, pos + 16)[0]
        if sub_len == 0 or sub_off == 0:
            none += 1
        elif _in_section(sections, 0x00025020, sub_off):
            host += 1
        elif _in_section(sections, 0x00025030, sub_off):
            local += 1
        else:
            # compte comme none si hors sections
            none += 1
    return host, local, none


def count_clue_subfiles(data: bytes, sections, off: int, cnt: int) -> tuple[int, int, int]:
    if cnt == 0 or not sections.get(CLUE_INFO_ID):
        return (0, 0, 0)
    size = 16
    host = local = none = 0
    for i in range(cnt):
        pos = off + i * size
        sub_off = struct.unpack_from(">I", data, pos + 4)[0]
        sub_len = struct.unpack_from(">I", data, pos + 8)[0]
        if sub_len == 0 or sub_off == 0:
            none += 1
        elif _in_section(sections, 0x00025020, sub_off):
            host += 1
        elif _in_section(sections, 0x00025030, sub_off):
            local += 1
        else:
            none += 1
    return host, local, none


def count_ctrl_subfiles(data: bytes, sections, off: int, cnt: int) -> tuple[int, int, int]:
    if cnt == 0 or not sections.get(CTRL_DATA_ID):
        return (0, 0, 0)
    size = 48
    host = local = none = 0
    for i in range(cnt):
        pos = off + i * size
        sub_off = struct.unpack_from(">I", data, pos + 0)[0]
        sub_len = struct.unpack_from(">I", data, pos + 4)[0]
        if sub_len == 0 or sub_off == 0:
            none += 1
        elif _in_section(sections, 0x00025020, sub_off):
            host += 1
        elif _in_section(sections, 0x00025030, sub_off):
            local += 1
        else:
            none += 1
    return host, local, none


def hi16(x):
    return (x >> 16) & 0xFFFF


def lo16(x):
    return x & 0xFFFF


def main():
    if len(sys.argv) < 2:
        print("Usage: python tools/analyze_zone_subfiles.py <file.dat>")
        sys.exit(1)
    path = sys.argv[1]
    with open(path, "rb") as f:
        data = f.read()
    sections = read_header(data)
    zones = parse_zones(data, sections)
    print(f"Zones={len(zones)}")
    for idx, z in enumerate(zones):
        ent = z["entries"]
        m_host, m_local, m_none = count_moby_subfiles(data, sections, ent[0][0], ent[0][1])
        c_host, c_local, c_none = count_clue_subfiles(data, sections, ent[3][0], ent[3][1])
        k_host, k_local, k_none = count_ctrl_subfiles(data, sections, ent[4][0], ent[4][1])
        t0, t1 = z["tail0"], z["tail1"]
        host_total = m_host + c_host + k_host
        local_total = m_local + c_local + k_local
        none_total = m_none + c_none + k_none
        print(f"Zone[{idx}] '{z['name']}'")
        print(f"  moby(host/local/none)={m_host}/{m_local}/{m_none}")
        print(f"  clue(host/local/none)={c_host}/{c_local}/{c_none}")
        print(f"  ctrl(host/local/none)={k_host}/{k_local}/{k_none}")
        print(f"  totals host={host_total} local={local_total} none={none_total}")
        print(f"  tails: tail0=(hi={hi16(t0)}, lo={lo16(t0)}) tail1=(hi={hi16(t1)}, lo={lo16(t1)})")


if __name__ == "__main__":
    main()


