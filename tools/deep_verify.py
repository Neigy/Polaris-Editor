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
    sections = {}
    ordered = []
    for i in range(section_count):
        off = sh_base + i * 16
        sid, data_off = struct.unpack_from(">II", data, off)
        flag = data[off + 8]
        count = int.from_bytes(data[off + 9: off + 12], "big")
        size = struct.unpack_from(">I", data, off + 12)[0]
        sections[sid] = {"offset": data_off, "flag": flag, "count": count, "size": size}
        ordered.append((sid, data_off, flag, count, size))
    ptrs = []
    if ptr_off and ptr_cnt:
        for i in range(ptr_cnt):
            pos = struct.unpack_from(">I", data, ptr_off + 4 * i)[0]
            ptrs.append(pos)
    return {
        "ver": (ver_major, ver_minor),
        "sections": sections,
        "ordered": ordered,
        "ptr_off": ptr_off,
        "ptr_cnt": len(ptrs),
        "ptrs": ptrs,
    }


def total_bytes(section):
    return section["size"] if section["flag"] == 0x00 else section["count"] * section["size"]


def in_section(sections, sid, addr):
    s = sections.get(sid)
    if not s:
        return False
    start = s["offset"]
    total = total_bytes(s)
    return start <= addr < start + total


def expect_ptr(data, ptr_positions_set, where_name, where_addr, target_sid, sections, must_align=False, allow_zero=True):
    try:
        val = struct.unpack_from(">I", data, where_addr)[0]
    except Exception:
        return f"{where_name}: read_fail@0x{where_addr:08X}"
    if must_align and (val % 4 != 0):
        # L'alignement n'est pas garanti (ex: pointeurs vers des chaînes). Ne pas considérer comme erreur par défaut.
        pass
    if allow_zero and val == 0:
        return None
    if not in_section(sections, target_sid, val):
        return f"{where_name}: target_miss ptr=0x{val:08X} not in sec 0x{target_sid:08X}"
    if where_addr not in ptr_positions_set:
        return f"{where_name}: ptr_pos_not_in_table pos=0x{where_addr:08X}"
    return None


def check_file(path: str):
    with open(path, "rb") as f:
        data = f.read()
    H = read_header(data)
    S = H["sections"]
    ptr_positions_set = set(H["ptrs"]) if H["ptrs"] else set()

    NAME_TABLES_ID = 0x00011300
    INSTANCE_TYPES_ID = 0x00025022
    # Subfiles
    HOST_CLASS_ID = 0x00025020
    LOCAL_CLASS_ID = 0x00025030
    # Paths
    PATH_DATA_ID = 0x00025050
    PATH_POINTS_ID = 0x00025058
    PATH_METADATA_ID = 0x00025054
    # Volumes
    VOLUME_TRANSFORM_ID = 0x0002505C
    VOLUME_METADATA_ID = 0x00025060
    # Controllers
    CONTROLLER_DATA_ID = 0x0002506C
    CONTROLLER_METADATA_ID = 0x00025070
    # Pods
    POD_DATA_ID = 0x00025074
    POD_METADATA_ID = 0x00025078
    POD_OFFSETS_ID = 0x0002507C
    # Areas
    AREA_DATA_ID = 0x00025080
    AREA_METADATA_ID = 0x00025084
    AREA_OFFSETS_ID = 0x00025088
    # Clues
    CLUE_INFO_ID = 0x00025064
    CLUE_METADATA_ID = 0x00025068
    # Scents
    SCENT_DATA_ID = 0x0002508C
    SCENT_METADATA_ID = 0x00025090
    SCENT_OFFSETS_ID = 0x00025094
    # Zones/Regions
    ZONE_METADATA_ID = 0x00025008
    ZONE_OFFSETS_ID = 0x0002500C
    ZONE_COUNTS_ID = 0x00025014
    DEFAULT_REGION_NAMES_ID = 0x00025010
    REGION_DATA_ID = 0x00025005
    REGION_POINTERS_ID = 0x00025006

    errors = []

    # Generic: name pointer at +8 for metadata sections with 16-byte entries
    for sid in [
        0x0002504C,  # Moby Metadata
        PATH_METADATA_ID,
        VOLUME_METADATA_ID,
        CONTROLLER_METADATA_ID,
        AREA_METADATA_ID,
        POD_METADATA_ID,
        SCENT_METADATA_ID,
        CLUE_METADATA_ID,
    ]:
        sec = S.get(sid)
        if not sec or sec["flag"] != 0x10 or sec["size"] != 16:
            continue
        base = sec["offset"]
        for i in range(sec["count"]):
            where = base + i * 16 + 8
            err = expect_ptr(data, ptr_positions_set, f"sec 0x{sid:08X} name_ptr[{i}]", where, NAME_TABLES_ID, S)
            if err:
                errors.append(err)

    # Moby Data: subfile at +12 points to host/local; data must start with IGHW if length>0
    sec = S.get(0x00025048)
    if sec and sec["flag"] == 0x10 and sec["size"] >= 20:
        base = sec["offset"]
        for i in range(sec["count"]):
            where = base + i * sec["size"] + 12
            # unknown which class; accept either
            errH = expect_ptr(data, ptr_positions_set, f"MOBY_DATA subfile[{i}]", where, HOST_CLASS_ID, S, allow_zero=True)
            errL = expect_ptr(data, ptr_positions_set, f"MOBY_DATA subfile[{i}]", where, LOCAL_CLASS_ID, S, allow_zero=True)
            if errH and errL:
                errors.append(errH)
            else:
                val = struct.unpack_from(">I", data, where)[0]
                if val + 4 <= len(data) and data[val:val+4] != b"IGHW":
                    # Subfile may be empty (offset 0) → already covered by expect_ptr
                    pass

    # Controller Data: subfile at +0
    sec = S.get(CONTROLLER_DATA_ID)
    if sec and sec["flag"] == 0x10 and sec["size"] >= 8:
        base = sec["offset"]
        for i in range(sec["count"]):
            where = base + i * sec["size"] + 0
            errH = expect_ptr(data, ptr_positions_set, f"CTRL_DATA subfile[{i}]", where, HOST_CLASS_ID, S, allow_zero=True)
            errL = expect_ptr(data, ptr_positions_set, f"CTRL_DATA subfile[{i}]", where, LOCAL_CLASS_ID, S, allow_zero=True)
            if errH and errL:
                errors.append(errH)

    # Path Data: points to PATH_POINTS
    sec = S.get(PATH_DATA_ID)
    if sec and sec["flag"] == 0x10 and sec["size"] >= 4:
        base = sec["offset"]
        for i in range(sec["count"]):
            where = base + i * sec["size"] + 0
            err = expect_ptr(data, ptr_positions_set, f"PATH_DATA points[{i}]", where, PATH_POINTS_ID, S)
            if err:
                errors.append(err)

    # Area Data: points to AREA_OFFSETS at +0,+4
    sec = S.get(AREA_DATA_ID)
    if sec and sec["flag"] == 0x10 and sec["size"] >= 8:
        base = sec["offset"]
        for i in range(sec["count"]):
            where0 = base + i * sec["size"] + 0
            where1 = base + i * sec["size"] + 4
            for where in (where0, where1):
                err = expect_ptr(data, ptr_positions_set, f"AREA_DATA off[{i}]", where, AREA_OFFSETS_ID, S, allow_zero=False)
                if err:
                    errors.append(err)

    # Pod Data: +0 -> POD_OFFSETS
    sec = S.get(POD_DATA_ID)
    if sec and sec["flag"] == 0x10 and sec["size"] >= 4:
        base = sec["offset"]
        for i in range(sec["count"]):
            where = base + i * sec["size"] + 0
            err = expect_ptr(data, ptr_positions_set, f"POD_DATA off[{i}]", where, POD_OFFSETS_ID, S, allow_zero=False)
            if err:
                errors.append(err)

    # Scent Data: +0 -> SCENT_OFFSETS
    sec = S.get(SCENT_DATA_ID)
    if sec and sec["flag"] == 0x10 and sec["size"] >= 4:
        base = sec["offset"]
        for i in range(sec["count"]):
            where = base + i * sec["size"] + 0
            err = expect_ptr(data, ptr_positions_set, f"SCENT_DATA off[{i}]", where, SCENT_OFFSETS_ID, S, allow_zero=False)
            if err:
                errors.append(err)

    # Offsets sections: values -> INSTANCE_TYPES_ID
    for sid in (AREA_OFFSETS_ID, POD_OFFSETS_ID, SCENT_OFFSETS_ID):
        sec = S.get(sid)
        if not sec:
            continue
        base = sec["offset"]
        total = total_bytes(sec)
        for pos in range(base, base + total, 4):
            val = struct.unpack_from(">I", data, pos)[0]
            if val == 0:
                continue
            if not in_section(S, INSTANCE_TYPES_ID, val):
                errors.append(f"OFFSETS 0x{sid:08X} bad target 0x{val:08X}")
            if pos not in ptr_positions_set:
                errors.append(f"OFFSETS 0x{sid:08X} ptr_pos_not_in_table pos=0x{pos:08X}")

    # Clue Info: +0 -> INSTANCE_TYPES_ID, +4 -> host/local
    sec = S.get(CLUE_INFO_ID)
    if sec and sec["flag"] == 0x10 and sec["size"] >= 8:
        base = sec["offset"]
        for i in range(sec["count"]):
            w0 = base + i * sec["size"] + 0
            w1 = base + i * sec["size"] + 4
            err = expect_ptr(data, ptr_positions_set, f"CLUE_INFO instType[{i}]", w0, INSTANCE_TYPES_ID, S, allow_zero=False)
            if err:
                errors.append(err)
            errH = expect_ptr(data, ptr_positions_set, f"CLUE_INFO subfile[{i}]", w1, HOST_CLASS_ID, S, allow_zero=True)
            errL = expect_ptr(data, ptr_positions_set, f"CLUE_INFO subfile[{i}]", w1, LOCAL_CLASS_ID, S, allow_zero=True)
            if errH and errL:
                errors.append(errH)

    # Zones/Regions pointers
    sec = S.get(ZONE_METADATA_ID)
    if sec and sec["flag"] == 0x10 and sec["size"] == 144:
        base = sec["offset"]
        for i in range(sec["count"]):
            base_i = base + i * 144 + 64
            for t in range(9):
                off_addr = base_i + t * 8
                cnt_addr = off_addr + 4
                cnt = struct.unpack_from(">I", data, cnt_addr)[0]
                if cnt == 0:
                    continue
                # type sections mapping
                TYPE_DATA = [
                    0x00025048, 0x00025050, 0x0002505C, 0x00025064, 0x0002506C, 0x00025080, 0x00025074, 0x0002508C, 0
                ]
                target = TYPE_DATA[t]
                if target == 0:
                    continue
                err = expect_ptr(data, ptr_positions_set, f"ZONE_META[{i}].t{t}", off_addr, target, S)
                if err:
                    errors.append(err)

    sec = S.get(ZONE_OFFSETS_ID)
    if sec and sec["flag"] == 0x10 and sec["size"] == 36:
        base = sec["offset"]
        for i in range(sec["count"]):
            base_i = base + i * 36
            for t in range(9):
                off_addr = base_i + t * 4
                err = expect_ptr(data, ptr_positions_set, f"ZONE_OFF[{i}].t{t}", off_addr, [
                    0x0002504C, 0x00025054, 0x00025060, 0x00025068, 0x00025070, 0x00025084, 0x00025078, 0x00025090, 0
                ][t], S)
                if err:
                    errors.append(err)

    sec = S.get(DEFAULT_REGION_NAMES_ID)
    if sec and total_bytes(sec) >= 72:
        off_addr = sec["offset"] + 64
        err = expect_ptr(data, ptr_positions_set, f"DEFAULT_REGION_NAMES indices_offset", off_addr, ZONE_COUNTS_ID, S, allow_zero=False)
        if err:
            errors.append(err)

    sec = S.get(REGION_DATA_ID)
    if sec and total_bytes(sec) >= 16:
        base = sec["offset"]
        err = expect_ptr(data, ptr_positions_set, f"REGION_DATA zone_meta_offset", base + 0, ZONE_METADATA_ID, S, allow_zero=False)
        if err:
            errors.append(err)
        err = expect_ptr(data, ptr_positions_set, f"REGION_DATA default_region_names_offset", base + 8, DEFAULT_REGION_NAMES_ID, S, allow_zero=False)
        if err:
            errors.append(err)

    # Quick subfile magic check on HOST/LOCAL referenced pointers (sample some)
    for sid in (HOST_CLASS_ID, LOCAL_CLASS_ID):
        sec = S.get(sid)
        if not sec:
            continue
        start = sec["offset"]
        end = start + total_bytes(sec)
        # Scan every 0x10000 for a potential IGHW header; this is heuristic only
        for p in range(start, end, 0x10000):
            if p + 4 <= len(data) and data[p:p+4] == b"IGHW":
                break

    return H, errors


def main():
    if len(sys.argv) < 3:
        print("Usage: python tools/deep_verify.py <original.dat> <rebuilt.dat>")
        sys.exit(1)
    with open(sys.argv[1], "rb") as f:
        A = f.read()
    with open(sys.argv[2], "rb") as f:
        B = f.read()

    HA, errA = check_file(sys.argv[1])
    HB, errB = check_file(sys.argv[2])

    print(f"A: ptr_cnt={HA['ptr_cnt']} sections={len(HA['sections'])}")
    print(f"B: ptr_cnt={HB['ptr_cnt']} sections={len(HB['sections'])}")

    print("Errors in A:", len(errA))
    for e in errA[:20]:
        print("  ", e)
    print("Errors in B:", len(errB))
    for e in errB[:200]:
        print("  ", e)


if __name__ == "__main__":
    main()


