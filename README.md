# Gp_Prius Documentation

This project explores the `gp_prius.dat` files, which use the IGHW format to store level data for *Ratchet & Clank* games on the PS3. These files contain data for mobys, volumes, paths, and more. This documentation breaks down the known sections, their functions, and how they're structured.

## IGHW Format
### Magic Header
- Begins with `IGHW` (big-endian), followed by version numbers (major/minor, 2 bytes each).

### Header Structure
- **Version 0:**
  - Section count at `0x0A` (2 bytes)
  - Sections start at `0x10`
- **Version 1:**
  - Section count at `0x0C` (4 bytes)
  - Sections start at `0x20`

### Section Structure
Each section entry is **16 bytes** long, containing:
- ID
- Offset
- Count/Size
- Padding/Element size

## Known Sections
Below is a breakdown of the identified sections in `gp_prius.dat`, categorized by data type.

### General
| Offset      | Role          | Data Structure | Notes |
|------------|--------------|---------------|-------|
| `0x00011300` | Name Tables  | Consecutive null-terminated strings | Indexed by TUID or position in other sections. |
| `0x00025022` | Instance Types | 16 bytes: `TUID (8)`, `Type (4)`, `Padding (4)` | Types: `0 = Moby`, `1 = Path`, `2 = Volume`, `3 = Clue`, `4 = Controller`, `5 = Scent`, etc. |

### Mobys
| Offset      | Role          | Data Structure | Notes |
|------------|--------------|---------------|-------|
| `0x00025048` | Moby Instances | 80 bytes: `Index/Group (4)`, `Unknown (16)`, `Pos/Rot/Scale (28)`, `Unknown (32)` | Coordinates as floats, rotation in radians. |
| `0x0002504C` | Moby Metadata | 16 bytes: `TUID (8)`, `NameOffset (4)`, `Zone (4)` | Zone data in the last 4 bytes. |

### Cuboids (Volumes/Clues)
| Offset      | Role          | Data Structure | Notes |
|------------|--------------|---------------|-------|
| `0x0002505C` | Cuboid Transformations | 64 bytes: `4x4 Matrix (16 floats)` | Position from floats 12-14 `(x, y, z)`. |
| `0x00025060` | Cuboid Metadata | 16 bytes: `TUID (8)`, `NameOffset (4)`, `Zone (4)` | Covers Volumes and Clues; type set by `0x00025022`. |
| `0x00025064` | Clue Info | 16 bytes: `TUIDOffset (4)`, `IGHWRef (4)`, `IGHWLength (4)`, `Class (4)` | Links to a Cuboid TUID in `0x00025022`. |
| `0x00025068` | Clue Metadata | 16 bytes: `TUID (8)`, `NameOffset (4)`, `Zone (4)` | Zone in the last 4 bytes. |

### Controllers
| Offset      | Role          | Data Structure | Notes |
|------------|--------------|---------------|-------|
| `0x0002506C` | Controller Data | 48 bytes: `IGHWOffset (4)`, `Length (4)`, `Pos/Rot/Scale (36)`, `Padding (4)` | Nested IGHW at the listed offset. |
| `0x00025070` | Controller Metadata | 16 bytes: `TUID (8)`, `NameOffset (4)`, `Zone (4)` | Zone in the last 4 bytes. |

### Paths
| Offset      | Role          | Data Structure | Notes |
|------------|--------------|---------------|-------|
| `0x00025050` | Path Metadata | 16 bytes: `PathPointOffset (4)`, `Unknown (4)`, `Total Duration (4)`, `IntroPATH flag (2)`, `PointNum (2)` | Determines number of points to read. |
| `0x00025054` | Path TUIDs | 16 bytes: `TUID (8)`, `NameOffset (4)`, `Zone (4)` | Zone in the last 4 bytes. |
| `0x00025058` | Path Points | 16 bytes per point: `X, Y, Z, Timestamp (4 floats)` | Timestamp converted to ms `(x1000/30)`. |

### Areas
| Offset      | Role          | Data Structure | Notes |
|------------|--------------|---------------|-------|
| `0x00025080` | Area Data | 16 bytes: `(Path) Offset/Count (8)` or `(Volume) Offset/Count (8)` | Type depends on `0x00025022` (`1 = Path`, `6 = Area`). |
| `0x00025084` | Area Metadata | 16 bytes: `TUID (8)`, `NameOffset (4)`, `Zone (4)` | Zone in the last 4 bytes. |
| `0x00025088` | Area Offsets | 4 bytes per offset: `Address to list of TUIDs` | Points to elements `(TUID, Type, Zone)`. |

### Pods
| Offset      | Role          | Data Structure | Notes |
|------------|--------------|---------------|-------|
| `0x00025074` | Pod Data | 16 bytes: `Offset (4)`, `Count (4)`, `Padding (8)` | Offset leads to a list in `0x0002507C`. |
| `0x00025078` | Pod Metadata | 16 bytes: `TUID (8)`, `NameOffset (4)`, `Zone (4)` | Zone in the last 4 bytes. |
| `0x0002507C` | Pod Offsets | 4 bytes per offset: `Address to elements` | Elements: `TUID (8)`, `Type (4)`, `Padding/Zone (4)`. |

### Scents
| Offset      | Role          | Data Structure | Notes |
|------------|--------------|---------------|-------|
| `0x0002508C` | Scent Data | 16 bytes: `Pointer (4)`, `Count (4)`, `Padding (8)` | Pointer hits offsets in `0x00025094`. |
| `0x00025090` | Scent Metadata | 16 bytes: `TUID (8)`, `NameOffset (4)`, `Zone (4)` | Zone in the last 4 bytes. |
| `0x00025094` | Scent Offsets | 4 bytes per offset: `Address to instances` | Instances pointed to: `TUID (8)`. |

### Regions and Zones
| Offset      | Role          | Data Structure | Notes |
|------------|--------------|---------------|-------|
| `0x00025005` | Regions | 16 bytes: `ZoneOffset (4)`, `ZoneCount (4)`, `DataOffset (4)`, `Index (4)` | Name is at `DataOffset` (64 bytes). |
| `0x00025008` | Rendering Zones (Names) | 144 bytes: `Name (64)`, `Counts per type (9x8)` | Types: Moby, Path, Volume, etc. |
| `0x0002500C` | Rendering Zones (Offsets) | 36 bytes: `9 offsets (4 each)` | Points to TUID lists per type. |

## Additional Notes
- **Zones:** Sections with `TUID` and `NameOffset` store the rendering zone in the last 4 bytes.
- **TUIDs:** 8-byte unique IDs, often linked to names in `0x00011300` or stored locally.
- **Types:** Defined in `0x00025022`, crucial for distinguishing Mobys, Paths, Volumes, etc.

For further details, check the source code or contribute to the project!

