import struct


def _pack_section_header(section_id: int, data_offset: int, flag: int, item_count: int, element_size: int) -> bytes:
    """Pack une entrée d'entête de section (16 octets).

    Format commun (big-endian):
    - u32: section_id
    - u32: data_offset (offset absolu dans le fichier, 0 si non défini)
    - u8 : flag (0x10 = multi-items avec count, 0x00 = single, autres valeurs possibles)
    - u24: item_count (3 octets)
    - u32: element_size (si multi-items: taille par élément, sinon taille totale)
    """
    item_count_3 = item_count.to_bytes(3, "big")
    return struct.pack(
        ">IIB3sI", section_id, data_offset, flag, item_count_3, element_size
    )


def build_ighw_header_bytes(
    *,
    version_major: int = 1,
    version_minor: int = 0,
    sections: list | None = None,
    pointer_table_offset: int = 0,
    pointer_count: int = 0,
) -> bytes:
    """Construit les octets de l'en-tête IGHW (version 0 ou 1+), avec entêtes de sections.

    - version_major == 0:
        - En-tête de base sur 0x10 octets
        - Section count: u16 @ 0x08 (0x0A..0x10 réservés)
        - Les entrées de sections (16 octets) commencent à 0x10

    - version_major >= 1:
        - En-tête de base sur 0x20 octets
        - u32 section_count @ 0x08
        - u32 header_length @ 0x0C (taille en-tête complet, y compris les entêtes de sections)
        - u32 pointer_table_offset @ 0x10 (début de la table des pointeurs = fin des données)
        - u32 pointer_count @ 0x14
        - 0x18..0x20 réservés (0)
        - Les entrées de sections commencent à 0x20

    Paramètre sections: liste de dicts {id, flag, count, size, data_offset?}
    """
    sections = sections or []

    if version_major == 0:
        # Header v0: 16 octets
        header = bytearray(0x10)
        header[0:4] = b"IGHW"
        struct.pack_into(">H", header, 4, version_major)
        struct.pack_into(">H", header, 6, version_minor)
        struct.pack_into(">H", header, 8, len(sections))
        # 0x0A..0x10 restent à 0

        buf = bytearray(header)
        for s in sections:
            buf.extend(
                _pack_section_header(
                    s["id"], s.get("data_offset", 0), s.get("flag", 0), s.get("count", 0), s.get("size", 0)
                )
            )
        return bytes(buf)

    # Header v1+
    header_length = 0x20 + 16 * len(sections)
    buf = bytearray(0x20)
    buf[0:4] = b"IGHW"
    struct.pack_into(">H", buf, 4, version_major)
    struct.pack_into(">H", buf, 6, version_minor)
    struct.pack_into(">I", buf, 8, len(sections))
    struct.pack_into(">I", buf, 12, header_length)
    struct.pack_into(">I", buf, 16, pointer_table_offset)
    struct.pack_into(">I", buf, 20, pointer_count)
    # 0x18..0x20: padding/sentinel -> DEAD DEAD DEAD DEAD
    # 8 bytes: DE AD DE AD DE AD DE AD
    buf[0x18:0x20] = bytes([0xDE, 0xAD, 0xDE, 0xAD, 0xDE, 0xAD, 0xDE, 0xAD])

    for s in sections:
        buf.extend(
            _pack_section_header(
                s["id"], s.get("data_offset", 0), s.get("flag", 0), s.get("count", 0), s.get("size", 0)
            )
        )

    return bytes(buf)


def write_empty_ighw_file(output_path: str, *, version_major: int = 1, version_minor: int = 0) -> None:
    """Écrit un fichier IGHW minimal ne contenant que l'en-tête (0 section).

    - Pour v1+, l'offset 0x10 indique la fin de fichier; ici, il vaut 0x20.
    - Pour v0, aucun champ fin de fichier n'existe dans l'entête court; on écrit juste l'entête.
    """
    pointer_table_offset = 0x20 if version_major >= 1 else 0
    data = build_ighw_header_bytes(
        version_major=version_major,
        version_minor=version_minor,
        sections=[],
        pointer_table_offset=pointer_table_offset,
        pointer_count=0,
    )
    with open(output_path, "wb") as f:
        f.write(data)


