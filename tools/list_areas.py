import sys
import os
import struct
import json


AREA_METADATA_ID = 0x00025084
NAME_TABLES_ID = 0x00011300


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


def read_c_string(data: bytes, pos: int) -> str:
    if pos <= 0 or pos >= len(data):
        return ""
    end = pos
    while end < len(data) and data[end] != 0:
        end += 1
    try:
        return data[pos:end].decode("utf-8", errors="ignore")
    except Exception:
        return ""


def list_areas_from_dat(dat_path: str):
    with open(dat_path, "rb") as f:
        data = f.read()
    sections = read_sections(data)
    meta = sections.get(AREA_METADATA_ID)
    if not meta:
        return []
    count = meta["count"] if meta["flag"] == 0x10 else (meta["size"] // 16)
    items = []
    for i in range(count):
        entry_off = meta["offset"] + i * 16
        tuid = struct.unpack_from(">Q", data, entry_off)[0]
        name_off = struct.unpack_from(">I", data, entry_off + 8)[0]
        zone = struct.unpack_from(">I", data, entry_off + 12)[0]
        name = read_c_string(data, name_off) if sections.get(NAME_TABLES_ID) else ""
        items.append({"tuid": tuid, "name": name, "zone": zone})
    return items


def list_areas_from_folder(folder: str):
    items = []
    for root, _dirs, files in os.walk(folder):
        for fn in files:
            if fn.endswith('.area.json'):
                p = os.path.join(root, fn)
                try:
                    with open(p, 'r', encoding='utf-8') as f:
                        obj = json.load(f)
                    tuid = int(obj.get('tuid', 0)) & 0xFFFFFFFFFFFFFFFF
                    name = obj.get('name') or os.path.splitext(fn)[0]
                    zone = int(obj.get('zone', 0))
                    items.append({"tuid": tuid, "name": name, "zone": zone, "path": p})
                except Exception:
                    pass
    return items


def main():
    if len(sys.argv) < 3:
        print("Usage: python tools/list_areas.py <original.dat> <extracted_folder>")
        sys.exit(1)
    dat_path = sys.argv[1]
    src_folder = sys.argv[2]

    a_dat = list_areas_from_dat(dat_path)
    a_src = list_areas_from_folder(src_folder)

    set_dat = {it["tuid"] for it in a_dat}
    set_src = {it["tuid"] for it in a_src}

    missing_in_src = sorted(set_dat - set_src)
    extra_in_src = sorted(set_src - set_dat)

    print(f"Original Areas (dat): {len(a_dat)}", flush=True)
    print(f"Extracted Areas (json): {len(a_src)}", flush=True)
    if missing_in_src:
        print(f"Missing in JSON ({len(missing_in_src)}):", flush=True)
        for tuid in missing_in_src:
            rec = next((x for x in a_dat if x["tuid"] == tuid), None)
            if rec:
                print(f"  - TUID=0x{tuid:016X} name='{rec['name']}' zone={rec['zone']}", flush=True)
            else:
                print(f"  - TUID=0x{tuid:016X}", flush=True)
    if extra_in_src:
        print(f"Extra in JSON ({len(extra_in_src)}):", flush=True)
        for tuid in extra_in_src:
            rec = next((x for x in a_src if x["tuid"] == tuid), None)
            if rec:
                print(f"  - TUID=0x{tuid:016X} name='{rec['name']}' zone={rec['zone']} path={rec['path']}", flush=True)
            else:
                print(f"  - TUID=0x{tuid:016X}", flush=True)


if __name__ == "__main__":
    main()


