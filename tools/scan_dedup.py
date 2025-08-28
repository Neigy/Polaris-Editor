import sys
import struct


HOST_CLASS_ID = 0x00025020
LOCAL_CLASS_ID = 0x00025030

MOBY_DATA_ID = 0x00025048
CONTROLLER_DATA_ID = 0x0002506C
CLUE_INFO_ID = 0x00025064


def read_header(data: bytes):
    if data[:4] != b"IGHW":
        raise ValueError("Bad magic")
    ver_major = struct.unpack_from(">H", data, 0x04)[0]
    ver_minor = struct.unpack_from(">H", data, 0x06)[0]
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


def total_bytes(section):
    return section["size"] if section["flag"] == 0x00 else section["count"] * section["size"]


def in_section(sections, sid, addr):
    s = sections.get(sid)
    if not s:
        return False
    start = s["offset"]
    total = total_bytes(s)
    return start <= addr < start + total


def scan_file(path: str):
    with open(path, "rb") as f:
        data = f.read()
    S = read_header(data)

    host_rng = (S.get(HOST_CLASS_ID, {}).get("offset", 0), S.get(HOST_CLASS_ID, {}).get("offset", 0) + total_bytes(S.get(HOST_CLASS_ID, {"offset": 0, "flag": 0x00, "size": 0})))
    local_rng = (S.get(LOCAL_CLASS_ID, {}).get("offset", 0), S.get(LOCAL_CLASS_ID, {}).get("offset", 0) + total_bytes(S.get(LOCAL_CLASS_ID, {"offset": 0, "flag": 0x00, "size": 0})))

    def collect_from(section_id: int, entry_size: int, offset_in_entry: int):
        sec = S.get(section_id)
        if not sec:
            return []
        base = sec["offset"]
        cnt = sec["count"]
        sz = sec["size"]
        vals = []
        for i in range(cnt):
            where = base + i * sz + offset_in_entry
            val = struct.unpack_from(">I", data, where)[0]
            if val != 0 and (in_section(S, HOST_CLASS_ID, val) or in_section(S, LOCAL_CLASS_ID, val)):
                vals.append(val)
        return vals

    moby_vals = collect_from(MOBY_DATA_ID, 80, 12)
    ctrl_vals = collect_from(CONTROLLER_DATA_ID, 48, 0)
    clue_vals = collect_from(CLUE_INFO_ID, 16, 4)

    all_vals = moby_vals + ctrl_vals + clue_vals
    unique_vals = len(sorted(set(all_vals)))
    total_refs = len(all_vals)

    return {
        "file": path,
        "total_refs": total_refs,
        "unique_ptrs": unique_vals,
        "dedup_ratio": (unique_vals / total_refs) if total_refs else 1.0,
        "counts": {
            "moby": (len(moby_vals), len(set(moby_vals))),
            "controller": (len(ctrl_vals), len(set(ctrl_vals))),
            "clue": (len(clue_vals), len(set(clue_vals))),
        }
    }


def main():
    if len(sys.argv) < 2:
        print("Usage: python tools/scan_dedup.py <file1.dat> [file2.dat]")
        sys.exit(1)
    for p in sys.argv[1:]:
        info = scan_file(p)
        print(f"File: {info['file']}")
        print(f"  subfile refs: total={info['total_refs']} unique_ptrs={info['unique_ptrs']} dedup_ratio={info['dedup_ratio']:.3f}")
        m = info['counts']['moby']
        c = info['counts']['controller']
        cl = info['counts']['clue']
        print(f"  moby: refs={m[0]} unique={m[1]}")
        print(f"  ctrl: refs={c[0]} unique={c[1]}")
        print(f"  clue: refs={cl[0]} unique={cl[1]}")


if __name__ == "__main__":
    main()







