# Gp_Prius Documentation

This project explores the `gp_prius.dat` files, which utilize the IGHW format to store level data for *Ratchet & Clank* games on the PS3. These files contain various elements such as mobys (objects), volumes, paths, and more. This README details the known sections within these files, their purposes, and their structural layout.

## IGHW Format

- **Magic**: The file begins with the signature `IGHW` (big-endian), followed by the version number (2 bytes for major version, 2 bytes for minor version).
- **Header**:
  - **Version Handling**:
    - *Version 0*: Section count is stored at offset `0x0A` (2 bytes), and section headers begin at `0x10`.
    - *Version 1*: Section count is stored at offset `0x0C` (4 bytes), and section headers begin at `0x20`.
  - **Section Count**: Located at `0x08` (4 bytes, u32), this indicates the total number of sections in the file.
  - **Length of Header**: At `0x0C` (4 bytes, u32), this represents the combined length of the header itself plus all section headers.
  - **End of File / Two-Level Redirection System**:  At `0x10` (4 bytes), this address points to a list of 4-byte pointers. Each pointer in this list redirects to each pointer in the mainfile
  - **Pointer Count**: At `0x14` (4 bytes, u32), this specifies the total number of pointers in the two-level redirection system.
- **Section**: Each section entry is 16 bytes long, structured as follows:
  - **ID**: 4 bytes, identifies the section type.
  - **Offset**: 4 bytes, points to the start of the section’s data in the file.
  - **Flag**: 1 byte, indicates the section’s structure:
    - `0x10`: Multiple items are present (count specified in `item_count`).
    - `0x00`: Single item (size specified in `section_size/elem_size`).
  - **Item Count**: 3 bytes, number of items (used when flag is `0x10`).
  - **Section Size / Element Size**: 4 bytes, size of the section or individual element:
    - If flag is `0x00`, this is the total section size.
    - If flag is `0x10`, this is the size of each item.

## Known Sections

Here’s what we’ve figured out about the sections in `gp_prius.dat`, grouped by data type:

### General
| Offset       | Role                | Data Structure                              | Notes                                                                         |
|--------------|---------------------|---------------------------------------------|-------------------------------------------------------------------------------|
| `0x00011300` | Name Tables         | Consecutive null-terminated strings         | Indexed by TUID or position in other sections.                                |
| `0x00025022` | Instance Types      | 16 bytes: TUID (8), Type (4), Padding (4)   | Types: 0=Moby, 1=Path, 2=Volume, 3=Clue, 4=Controller, 5=Scent, 6=Area, 7=Pod |

### Mobys
| Offset       | Role                | Data Structure                                      | Notes                                                                |
|--------------|---------------------|-----------------------------------------------------|----------------------------------------------------------------------|
| `0x00025048` | Moby Instances      | 80 bytes: Model Index (2), Zone Render Index (2), Dist Disappear Force Float default -1 (4), Disappear Dist default -1 (4), Address to IGHW subfile for class setup (4), Subfile Length (4), Pos/Rot/Scale (28), Always `01 01 00 01 00 00 00 01 FF FF FF FF FF FF FF FF 00 00 00 00 00 00 00` (24), Unknown param default `FF 00 00 00` (4), Rest is 00 padding (4) | Coordinates as floats, rotation in radians. Zone Render Index ties to rendering zones. |
| `0x0002504C` | Moby Metadata       | 16 bytes: TUID (8), NameOffset (4), Zone (4)        | Zone’s in the last 4 bytes.                                          |

### Cuboids (Volumes/Clues)
| Offset       | Role                  | Data Structure                                      | Notes                                                               |
|--------------|-----------------------|-----------------------------------------------------|---------------------------------------------------------------------|
| `0x0002505C` | Cuboid Transformations| 64 bytes: 4x4 Matrix (16 floats)                    | Position pulled from floats 12-14 (x, y, z).                        |
| `0x00025060` | Cuboid Metadata       | 16 bytes: TUID (8), NameOffset (4), Zone (4)        | Covers Volumes and Clues; type set by `0x00025022`.                 |
| `0x00025064` | Clue Info             | 16 bytes: TUIDOffset (4), IGHWRef (4), IGHWLength (4), Class (4) | Points to a Cuboid TUID in `0x00025022`, links to an IGHW for class setup, and gives class length. |
| `0x00025068` | Clue Metadata         | 16 bytes: TUID (8), NameOffset (4), Zone (4)        | Zone’s in the last 4 bytes.                                         |

### Controllers
| Offset       | Role                  | Data Structure                                      | Notes                                                                |
|--------------|-----------------------|-----------------------------------------------------|----------------------------------------------------------------------|
| `0x0002506C` | Controller Data       | 48 bytes: IGHWOffset (4), Length (4), Pos/Rot/Scale (36), Padding (4) | Nested IGHW at the listed offset.                  |
| `0x00025070` | Controller Metadata   | 16 bytes: TUID (8), NameOffset (4), Zone (4)        | Zone’s in the last 4 bytes.                                          |

### Paths
| Offset       | Role                  | Data Structure                                      | Notes                                                                |
|--------------|-----------------------|-----------------------------------------------------|----------------------------------------------------------------------|
| `0x00025050` | Path Metadata         | 16 bytes: PathPointOffset (4), Unknown value `07 04 17 76` for all paths (4), Total Duration (4), IntroPATH flag (2) (`01 01` for intro paths, `00 00` otherwise—maybe enemies use firepoints with intro paths), PointNum (2) Int16 (how many lines from PathPointOffset, each line is `0x10`) | |
| `0x00025054` | Path TUIDs            | 16 bytes: TUID (8), NameOffset (4), Zone (4)        | Zone’s in the last 4 bytes.                                         |
| `0x00025058` | Path Points           | 16 bytes per point: X, Y, Z, Timestamp (4 floats)   | Timestamp converted to ms (x1000/30).                               |

### Areas
| Offset       | Role                  | Data Structure                                      | Notes                                                               |
|--------------|-----------------------|-----------------------------------------------------|---------------------------------------------------------------------|
| `0x00025080` | Area Data             | 16 bytes: (Path) Offset/Count (8) or (Volume) Offset/Count (8) | Type depends on `0x00025022` (1=Path, 6=Area).           |
| `0x00025084` | Area Metadata         | 16 bytes: TUID (8), NameOffset (4), Zone (4)        | Zone’s in the last 4 bytes.                                         |
| `0x00025088` | Area Offsets          | 4 bytes per offset: Address to list of TUIDs        | Points to elements (TUID, Type, Zone).                              |

### Pods
| Offset       | Role                  | Data Structure                                      | Notes                                                               |
|--------------|-----------------------|-----------------------------------------------------|---------------------------------------------------------------------|
| `0x00025074` | Pod Data              | 16 bytes: Offset (4), Count (4), Padding (8)        | Offset points to a list in `0x0002507C`.                            |
| `0x00025078` | Pod Metadata          | 16 bytes: TUID (8), NameOffset (4), Zone (4)        | Zone’s in the last 4 bytes.                                         |
| `0x0002507C` | Pod Offsets           | 4 bytes per offset: Address to elements             | Elements: TUID (8), Type (4), Padding/Zone (4).                     |

### Scents
| Offset       | Role                  | Data Structure                                      | Notes                                                               |
|--------------|-----------------------|-----------------------------------------------------|---------------------------------------------------------------------|
| `0x0002508C` | Scent Data            | 16 bytes: Pointer (4), Count (4), Padding (8)       | Pointer leads to offsets in `0x00025094`.                           |
| `0x00025090` | Scent Metadata        | 16 bytes: TUID (8), NameOffset (4), Zone (4)        | Zone’s in the last 4 bytes.                                         |
| `0x00025094` | Scent Offsets         | 4 bytes per offset: Address to instances            | Instances pointed to: TUID (8).                                     |

### Regions and Zones
| Offset       | Role                        | Data Structure                                      | Notes                                                               |
|--------------|-----------------------------|-----------------------------------------------------|---------------------------------------------------------------------|
| `0x00025005` | Regions                     | 16 bytes: ZoneOffset (4), ZoneCount (4), DataOffset (4), Index (4) | `ZoneOffset` (e.g., `0x0019CF80`) points to region data; `DataOffset` (e.g., `0x0004CE80`) contains a 64-byte null-terminated name. Appears in `0x0019D000`’s final entries. |
| `0x00025008` | Rendering Zones (names)     | 144 bytes: Name (64), Counts per type (9x8)         | Types: Moby, Path, Volume, etc.                                     |
| `0x0002500C` | Rendering Zones (offsets)   | 36 bytes: 9 offsets (4 each)                        | Points to TUID lists by type; first offset is `0x0001B900`.         |
| `0x00025010` | Default Region              | Name "default" + Offset (4), Count (4)              | List of indices at the offset (e.g., 9 elements).                   |
| `0x00025014` | List tied to `0x00025010`   | Indices (4 bytes each)                              | Example: 18 bytes for 4 elements. Used in places like `0x00025054`. |

### Nested IGHW Sections
| Offset       | Role                        | Data Structure                                      | Notes                                                                |
|--------------|-----------------------------|-----------------------------------------------------|----------------------------------------------------------------------|
| `0x00025020` | Nested IGHW (Class Setup)   | Sub-IGHW file (version 0.2)                         | Instance info can redirect to a subfile for class configuration.    |
| `0x00025030` | Nested IGHW (Class Setup)   | Sub-IGHW file (version 0.2)                         | Similar to `0x00025020`.                                             |

### Global Offset Table (at `0x0019D000`)
- **Role**: Centralized table of 4-byte offsets redirecting to various data structures throughout the file.
- **Structure**: Consecutive 4-byte pointers.
- **Details**:
  - First entry (`0x0001B900`): Matches `0x0002500C`, points to 9 offsets (36 bytes) for rendering zones by type (Moby, Path, Volume, etc.).
  - Middle entries (e.g., `0x0000089C`, `0x0000093C`): Redirect to intermediate structures (often 16 bytes) that point to data like names (`0x00011300`), sub-IGHW files, scents, pods, etc.
  - Last entries (`0x0019CF80`, `0x0019CF88`, `0x0019D000`): Link to `0x00025005` (Regions) definitions (`ZoneOffset`, `ZoneCount`, `DataOffset`, `Index`) and loop back to the table’s start.
- **Notes**: Acts as a high-level index connecting regions, rendering zones, and other elements. Referenced by multiple sections (e.g., `0x00025006`, `0x0002500C`, `0x00025005`).

### Offset Index Table
| Offset       | Role                       |
|--------------|-----------------------------|
| `0x00025006` | Offset Reference to Rendering Zones (offsets) |



## Extra Notes
- **Global Offset Table (`4 bytes after 0x00025006`)**: A key structure referenced by sections like `0x00025006`, `0x0002500C`, and `0x00025005`. It centralizes all pointers (names, sub-IGHW, etc.), with a two-level redirection system.
- **Zones**: In sections with TUID and NameOffset (e.g., `0x0002504C`, `0x00025060`), the last 4 bytes mark the rendering zone (e.g., `0x00000001`).
- **TUIDs**: 8-byte unique IDs, often tied to a name in `0x00011300` or kept local.
- **Types**: Defined in `0x00025022`, essential for sorting out Mobys, Paths, Volumes, and more.
