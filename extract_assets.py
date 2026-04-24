#!/usr/bin/env python3
"""
Star Fox SNES Asset Extractor
Converts all SNES source assets into universal formats:
  - 3D shapes  → animated rotating GIFs
  - Palettes   → PNG color strips
  - Graphics   → PNG tile sheets
  - Maps       → PNG overhead views
  - Sounds     → info PNG cards
"""

import os, re, math, struct
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

BASE = Path(__file__).parent / "SF"
OUT  = Path(__file__).parent / "assets"

# ── output directories ─────────────────────────────────────────────────────
for d in ["models","palettes","graphics","maps","sounds","index"]:
    (OUT / d).mkdir(parents=True, exist_ok=True)

# ═══════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def norm3(v):
    l = math.sqrt(v[0]**2+v[1]**2+v[2]**2)
    return (v[0]/l, v[1]/l, v[2]/l) if l > 1e-9 else (0,0,1)

def dot3(a,b): return a[0]*b[0]+a[1]*b[1]+a[2]*b[2]

def rot_y(v, a):
    c,s = math.cos(a), math.sin(a)
    return (v[0]*c+v[2]*s, v[1], -v[0]*s+v[2]*c)

def rot_x(v, a):
    c,s = math.cos(a), math.sin(a)
    return (v[0], v[1]*c-v[2]*s, v[1]*s+v[2]*c)

def project(v, scale, cx, cy, fov=300):
    z = v[2] + fov
    if z < 1: z = 1
    px = int(v[0]*fov/z*scale + cx)
    py = int(-v[1]*fov/z*scale + cy)
    return (px, py)

# Star Fox palette — 64 colors cycling through shape color indices
# Based on Corneria greens, ship grays, enemy reds/yellows
SF_PALETTE = [
    (20,20,30),    # 0  black
    (40,80,40),    # 1  dark green
    (60,120,60),   # 2  green
    (80,160,80),   # 3  bright green
    (100,200,100), # 4  light green
    (160,220,130), # 5  yellow-green
    (80,80,100),   # 6  dark blue-gray
    (110,110,140), # 7  blue-gray
    (150,150,180), # 8  light blue-gray
    (200,200,220), # 9  silver
    (220,220,240), # 10 bright silver
    (240,240,255), # 11 white
    (180,60,40),   # 12 dark red
    (220,80,60),   # 13 red
    (240,120,60),  # 14 orange-red
    (255,160,60),  # 15 orange
    (255,200,60),  # 16 yellow
    (255,230,120), # 17 light yellow
    (60,60,180),   # 18 blue
    (80,100,220),  # 19 medium blue
    (100,140,255), # 20 light blue
    (60,180,180),  # 21 cyan
    (80,220,200),  # 22 light cyan
    (160,60,180),  # 23 purple
    (200,80,220),  # 24 magenta
    (120,80,40),   # 25 brown
    (160,110,60),  # 26 tan
    (200,150,90),  # 27 light tan
    (30,60,30),    # 28 very dark green
    (50,100,50),   # 29 forest green
    (140,180,60),  # 30 olive
    (200,220,80),  # 31 lime
    (80,40,20),    # 32 dark brown
    (120,60,30),   # 33 medium brown
    (180,100,50),  # 34 copper
    (220,160,80),  # 35 gold
    (140,140,140), # 36 gray
    (170,170,170), # 37 light gray
    (200,200,200), # 38 very light gray
    (100,120,80),  # 39 khaki
    (60,100,120),  # 40 steel blue
    (80,140,160),  # 41 sky blue
    (60,40,80),    # 42 dark purple
    (100,60,120),  # 43 purple
    (140,80,160),  # 44 medium purple
    (255,100,100), # 45 pink-red
    (255,150,150), # 46 pink
    (255,180,180), # 47 light pink
    (20,40,60),    # 48 deep navy
    (30,60,90),    # 49 navy
    (40,80,120),   # 50 medium navy
    (50,100,150),  # 51 slate blue
    (160,200,240), # 52 pale blue
    (220,240,255), # 53 ice blue
    (60,30,30),    # 54 dark maroon
    (100,40,40),   # 55 maroon
    (160,40,40),   # 56 crimson
    (200,60,60),   # 57 bright red
    (255,80,80),   # 58 vivid red
    (255,120,80),  # 59 coral
    (180,220,180), # 60 pale green
    (200,230,200), # 61 mint
    (40,80,60),    # 62 teal
    (60,120,90),   # 63 medium teal
]

def color_for_index(idx):
    return SF_PALETTE[idx % len(SF_PALETTE)]

def blend(c, bright):
    return tuple(min(255, int(ch * bright)) for ch in c)

# ═══════════════════════════════════════════════════════════════════════════
# 1. 3D SHAPE PARSER + RENDERER
# ═══════════════════════════════════════════════════════════════════════════

def parse_shapes(path):
    """
    Returns dict: name -> {'verts':[(x,y,z),...], 'faces':[(color,nx,ny,nz,[vi,...]),...]}

    Handles two shapehdr patterns in the SNES source:
      Pattern A: name<TAB>shapehdr args    (name on same line)
      Pattern B: name<NL><TAB>shapehdr args (name on previous bare label line)
    The data (Pointsb/Faces) is always in the elseif block below shapehdr.
    """
    shapes = {}
    cur_name    = None
    pending_label = None   # bare label line seen before shapehdr
    verts = []
    faces = []
    in_points = False
    in_faces  = False

    with open(path, encoding='latin-1', errors='replace') as f:
        for raw in f:
            stripped = raw.split(';')[0].rstrip()
            line = stripped.strip()
            if not line:
                continue

            # EndShape — save current shape
            if re.match(r'EndShape\b', line, re.I):
                if cur_name and verts:
                    shapes[cur_name] = {'verts': verts[:], 'faces': faces[:]}
                cur_name = None; pending_label = None
                verts = []; faces = []
                in_points = False; in_faces = False
                continue

            # shapehdr (or shapehdr_s) — captures shape name
            if re.search(r'shapehdr', line, re.I):
                # Pattern A: "name  shapehdr  args"
                m = re.match(r'^(\w+)\s+shapehdr', line, re.I)
                if m:
                    cur_name = m.group(1)
                elif pending_label:
                    cur_name = pending_label
                pending_label = None
                verts = []; faces = []
                in_points = False; in_faces = False
                continue

            # Bare label line (no leading whitespace, single identifier, no args)
            # Used as shape name in Pattern B
            if not stripped[0:1].isspace() and re.match(r'^[A-Za-z_]\w*$', line):
                pending_label = line
                continue
            else:
                # Any non-blank, non-label line resets pending (except directives)
                if not re.match(r'^(ifne|elseif|endc|ifeq|endif|include)\b', line, re.I):
                    pass  # keep pending_label across blank/directive lines

            # Pointsb <n>
            if re.match(r'Pointsb\s+\d+', line, re.I):
                in_points = True; continue

            # EndPoints
            if re.match(r'EndPoints\b', line, re.I):
                in_points = False; continue

            # pb x,y,z  (vertex)
            if in_points:
                m = re.match(r'pb\s+(-?\d+)\s*,\s*(-?\d+)\s*,\s*(-?\d+)', line, re.I)
                if m:
                    verts.append((int(m.group(1)), int(m.group(2)), int(m.group(3))))
                continue

            # Fend terminates faces
            if re.match(r'Fend\b', line, re.I):
                in_faces = False; continue

            # Faces section start — label optionally precedes "Faces"
            if re.search(r'\bFaces\b', line, re.I) and not re.match(r'Face\d', line, re.I):
                in_faces = True; continue

            if in_faces:
                # Face2/3/4/5  color,flag,nx,ny,nz,v0[,v1,...]
                m = re.match(r'Face(\d)\s+(-?\d+)\s*,\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*(-?\d+)\s*,(.+)', line, re.I)
                if m:
                    n_verts = int(m.group(1))
                    color   = int(m.group(2))
                    flag    = int(m.group(3))
                    nx,ny,nz = int(m.group(4)), int(m.group(5)), int(m.group(6))
                    vi_raw  = m.group(7).split(',')
                    vis = []
                    for v in vi_raw[:n_verts]:
                        try: vis.append(int(v.strip()))
                        except: pass
                    if len(vis) >= 2:
                        faces.append((color, nx, ny, nz, vis))

    return shapes


def render_shape_gif(name, shape, out_path, size=160, frames=24):
    verts = shape['verts']
    faces = shape['faces']
    if not verts or not faces:
        return False

    # Normalise vertex scale
    maxv = max((abs(x) for x,y,z in verts), default=1)
    maxv = max(maxv, max((abs(y) for x,y,z in verts), default=1))
    maxv = max(maxv, max((abs(z) for x,y,z in verts), default=1))
    if maxv == 0: maxv = 1
    scale = (size * 0.38) / maxv

    cx, cy = size // 2, size // 2
    light  = norm3((0.6, 1.0, 0.8))
    BG     = (15, 20, 35)
    imgs   = []

    for fi in range(frames):
        angle_y = 2 * math.pi * fi / frames
        angle_x = math.radians(18)  # slight downward tilt

        # Transform all vertices
        tv = [rot_x(rot_y(v, angle_y), angle_x) for v in verts]

        # Depth-sort faces (painter's algorithm)
        def face_depth(face):
            _, nx, ny, nz, vis = face
            valid = [i for i in vis if i < len(tv)]
            if not valid: return 0
            return sum(tv[i][2] for i in valid) / len(valid)

        sorted_faces = sorted(faces, key=face_depth, reverse=True)

        img  = Image.new('RGB', (size, size), BG)
        draw = ImageDraw.Draw(img)

        for color_idx, nx, ny, nz, vis in sorted_faces:
            valid = [i for i in vis if i < len(tv)]
            if len(valid) < 2:
                continue

            # Lighting
            n = norm3(rot_x(rot_y((nx/128, ny/128, nz/128), angle_y), angle_x))
            diffuse  = max(0.0, dot3(n, light))
            rim      = max(0.0, dot3(n, norm3((-0.4, 0.2, -1.0))))
            ambient  = 0.25
            bright   = ambient + 0.65 * diffuse + 0.15 * (rim**3)
            bright   = min(1.0, bright)

            base = color_for_index(color_idx)
            fill = blend(base, bright)

            pts = [project(tv[i], scale, cx, cy) for i in valid]

            if len(pts) >= 3:
                draw.polygon(pts, fill=fill)
            # Outline
            for k in range(len(pts)):
                x0,y0 = pts[k]
                x1,y1 = pts[(k+1)%len(pts)]
                edge_c = blend(base, bright * 0.55)
                draw.line([x0,y0,x1,y1], fill=edge_c, width=1)

        imgs.append(img)

    # Save as GIF
    imgs[0].save(
        out_path,
        save_all=True,
        append_images=imgs[1:],
        loop=0,
        duration=60,
        optimize=False
    )
    return True


def extract_models():
    print("\n── 3D Models ──────────────────────────────────────────────")
    shape_files = list((BASE / "SHAPES").glob("*.ASM"))
    all_shapes = {}
    for sf in shape_files:
        parsed = parse_shapes(sf)
        for k,v in parsed.items():
            if k not in all_shapes:
                all_shapes[k] = v
    print(f"  Found {len(all_shapes)} shapes across {len(shape_files)} files")

    ok = 0
    skipped = 0
    for name, shape in sorted(all_shapes.items()):
        out = OUT / "models" / f"{name}.gif"
        if render_shape_gif(name, shape, out):
            ok += 1
        else:
            skipped += 1

    print(f"  Rendered {ok} GIFs  ({skipped} skipped — no geometry)")
    return all_shapes

# ═══════════════════════════════════════════════════════════════════════════
# 2. PALETTE EXTRACTOR (.COL files → PNG)
# ═══════════════════════════════════════════════════════════════════════════

def snes_rgb555_to_rgb(word):
    r = (word & 0x1F) * 255 // 31
    g = ((word >> 5) & 0x1F) * 255 // 31
    b = ((word >> 10) & 0x1F) * 255 // 31
    return (r, g, b)

def extract_palettes():
    print("\n── Palettes ───────────────────────────────────────────────")
    col_dir = BASE / "DATA" / "COL"
    col_files = sorted(col_dir.glob("*.COL")) + sorted((BASE / "DATA").glob("*.COL"))
    # deduplicate
    seen = set()
    unique = []
    for f in col_files:
        if f.name not in seen:
            seen.add(f.name)
            unique.append(f)
    col_files = unique

    print(f"  Processing {len(col_files)} palette files")

    for cf in col_files:
        data = cf.read_bytes()
        n_colors = len(data) // 2
        if n_colors == 0: continue

        cols = []
        for i in range(n_colors):
            word = struct.unpack_from('<H', data, i*2)[0]
            cols.append(snes_rgb555_to_rgb(word))

        # Render as rows of 16 colours per row
        per_row = 16
        rows = math.ceil(n_colors / per_row)
        sw, sh = 24, 24
        img = Image.new('RGB', (per_row * sw, rows * sh + 30), (30, 30, 30))
        draw = ImageDraw.Draw(img)

        for i, c in enumerate(cols):
            rx = (i % per_row) * sw
            ry = (i // per_row) * sh + 30
            draw.rectangle([rx, ry, rx+sw-1, ry+sh-1], fill=c)

        draw.text((4, 4), cf.name, fill=(220, 220, 220))
        draw.text((4, 16), f"{n_colors} colors", fill=(160, 160, 160))

        img.save(OUT / "palettes" / f"{cf.stem}.png")

    print(f"  Saved {len(col_files)} palette PNGs")

# ═══════════════════════════════════════════════════════════════════════════
# 3. TILE GRAPHICS EXTRACTOR (.CGX → PNG tile sheets)
# ═══════════════════════════════════════════════════════════════════════════

def decode_4bpp_tile(data, offset):
    """Decode one 8x8 SNES 4BPP tile → 8x8 list of color indices (0-15)."""
    pixels = [[0]*8 for _ in range(8)]
    for row in range(8):
        b0 = data[offset + row*2    ] if offset + row*2     < len(data) else 0
        b1 = data[offset + row*2 + 1] if offset + row*2 + 1 < len(data) else 0
        b2 = data[offset + 16 + row*2    ] if offset + 16 + row*2     < len(data) else 0
        b3 = data[offset + 16 + row*2 + 1] if offset + 16 + row*2 + 1 < len(data) else 0
        for col in range(8):
            bit = 7 - col
            p  = ((b0 >> bit) & 1)
            p |= ((b1 >> bit) & 1) << 1
            p |= ((b2 >> bit) & 1) << 2
            p |= ((b3 >> bit) & 1) << 3
            pixels[row][col] = p
    return pixels

# Default SNES-style 16-color palette for display
DEFAULT_TILE_PAL = [
    (0,0,0), (255,255,255), (200,200,200), (150,150,150),
    (100,100,100), (60,160,60), (100,200,100), (160,230,160),
    (60,100,200), (100,140,240), (200,60,60), (240,100,100),
    (200,160,60), (255,210,80), (80,200,200), (255,255,100),
]

def extract_graphics():
    print("\n── Tile Graphics ──────────────────────────────────────────")
    cgx_files = sorted((BASE / "DATA").glob("*.CGX"))
    cgx_files += sorted((BASE / "MSPRITES").glob("*.CGX"))
    print(f"  Processing {len(cgx_files)} CGX files")

    # Try to load ALLCOLS.COL as master palette
    allcols_path = BASE / "DATA" / "COL" / "ALLCOLS.COL"
    if allcols_path.exists():
        raw = allcols_path.read_bytes()
        master_pal = []
        for i in range(len(raw) // 2):
            word = struct.unpack_from('<H', raw, i*2)[0]
            master_pal.append(snes_rgb555_to_rgb(word))
    else:
        master_pal = DEFAULT_TILE_PAL * 32  # fallback

    # Map CGX basename to .COL file if one exists
    def get_palette(stem):
        for variant in [stem, stem.upper(), stem.lower()]:
            p = BASE / "DATA" / "COL" / f"{variant}.COL"
            if p.exists():
                raw = p.read_bytes()
                pal = []
                for i in range(min(16, len(raw)//2)):
                    word = struct.unpack_from('<H', raw, i*2)[0]
                    pal.append(snes_rgb555_to_rgb(word))
                return (pal + DEFAULT_TILE_PAL)[:16]
        # Use first 16 colors from master palette
        return (master_pal + DEFAULT_TILE_PAL)[:16]

    for cf in cgx_files:
        data = cf.read_bytes()
        tile_size = 32  # 4BPP
        n_tiles = len(data) // tile_size
        if n_tiles == 0: continue

        pal = get_palette(cf.stem)

        # Layout: up to 32 tiles per row
        cols_per_row = min(32, n_tiles)
        rows = math.ceil(n_tiles / cols_per_row)
        tw = 8  # tile width in pixels

        img = Image.new('RGB', (cols_per_row * tw, rows * tw), (20, 20, 20))

        for ti in range(n_tiles):
            tx = (ti % cols_per_row) * tw
            ty = (ti // cols_per_row) * tw
            tile = decode_4bpp_tile(data, ti * tile_size)
            for row in range(8):
                for col in range(8):
                    cidx = tile[row][col]
                    color = pal[cidx] if cidx < len(pal) else (0,0,0)
                    img.putpixel((tx + col, ty + row), color)

        # Scale up 2× for visibility
        img = img.resize((img.width * 2, img.height * 2), Image.NEAREST)

        out_name = f"{cf.stem}.png"
        img.save(OUT / "graphics" / out_name)

    print(f"  Saved {len(cgx_files)} tile sheet PNGs")

# ═══════════════════════════════════════════════════════════════════════════
# 4. MAP VIEWER — overhead 2D plot of object placements
# ═══════════════════════════════════════════════════════════════════════════

SHAPE_COLORS = {
    # ships
    'imyship': (80, 160, 255),
    'myship':  (80, 160, 255),
    # enemies
    'zaco':    (255, 80, 80),
    'cameleon':(255, 160, 60),
    'd_body':  (255, 60, 200),
    'd_head':  (255, 60, 200),
    'walker':  (180, 255, 80),
    # environment
    'asteroid': (160, 140, 120),
    'item':     (255, 255, 60),
    'op_':      (60, 180, 60),
    'gnd':      (80, 100, 80),
    'BU_':      (200, 80, 80),
}

def shape_dot_color(shape_name):
    sn = shape_name.lower()
    for k, c in SHAPE_COLORS.items():
        if k.lower() in sn:
            return c
    return (180, 180, 180)

def parse_map(path):
    """Returns list of (x, y, z, depth, shape_name) from mapobj / cspecial lines."""
    objects = []
    with open(path, encoding='latin-1', errors='replace') as f:
        for raw in f:
            line = raw.split(';')[0].strip()
            # mapobj x,y,z,depth,shape,strategy
            m = re.match(r'(?:mapobj|mapobjnomem|cspecial)\s+(-?\w+)\s*,\s*(-?\w+)\s*,\s*(-?\w+)\s*,\s*(-?\w+)\s*,\s*(\w+)', line, re.I)
            if m:
                try:
                    x = int(m.group(1), 0)
                    y = int(m.group(2), 0)
                    z = int(m.group(3), 0)
                    d = int(m.group(4), 0)
                except:
                    x=y=z=d=0
                objects.append((x, y, z, d, m.group(5)))
    return objects

def extract_maps():
    print("\n── Level Maps ─────────────────────────────────────────────")
    map_dir = BASE / "MAPS"
    map_files = sorted(map_dir.glob("MAP*.ASM")) + sorted(map_dir.glob("LEVEL*.ASM"))
    print(f"  Processing {len(map_files)} map files")

    for mf in map_files:
        objects = parse_map(mf)
        if not objects:
            continue

        # Use X and depth (arg 4) as the 2D plane (rail shooter = depth is Z)
        xs = [o[0] for o in objects]
        ds = [o[3] for o in objects]

        xmin, xmax = min(xs, default=0), max(xs, default=1)
        dmin, dmax = min(ds, default=0), max(ds, default=1)
        if xmax == xmin: xmax = xmin + 1
        if dmax == dmin: dmax = dmin + 1

        W, H = 800, 600
        MARGIN = 40
        img  = Image.new('RGB', (W, H), (10, 14, 20))
        draw = ImageDraw.Draw(img)

        # Draw grid
        for gx in range(0, W, 80):
            draw.line([(gx, 0), (gx, H)], fill=(25, 35, 45))
        for gy in range(0, H, 60):
            draw.line([(0, gy), (W, gy)], fill=(25, 35, 45))

        # Axes labels
        draw.text((MARGIN, H - 20), "← X →", fill=(80, 80, 100))
        draw.text((4, MARGIN), "↑ depth", fill=(80, 80, 100))

        def to_screen(x, d):
            px = int((x - xmin) / (xmax - xmin) * (W - 2*MARGIN)) + MARGIN
            py = H - MARGIN - int((d - dmin) / (dmax - dmin) * (H - 2*MARGIN))
            return (px, py)

        # Draw objects
        for x, y, z, d, shape in objects:
            px, py = to_screen(x, d)
            r = 4
            color = shape_dot_color(shape)
            draw.ellipse([px-r, py-r, px+r, py+r], fill=color, outline=(255,255,255))

        # Legend (unique shapes)
        seen_shapes = {}
        for _,_,_,_,s in objects:
            if s not in seen_shapes:
                seen_shapes[s] = shape_dot_color(s)
        ly = 8
        draw.text((W//2, 4), mf.stem, fill=(200, 220, 255))
        for sname, sc in list(seen_shapes.items())[:15]:
            draw.rectangle([W-120, ly, W-108, ly+10], fill=sc)
            draw.text((W-104, ly), sname[:14], fill=(180, 180, 180))
            ly += 14

        img.save(OUT / "maps" / f"{mf.stem}.png")

    print(f"  Saved map overview PNGs")

# ═══════════════════════════════════════════════════════════════════════════
# 5. SOUND FILE INFO CARDS
# ═══════════════════════════════════════════════════════════════════════════

BGM_NAMES = {
    'SGBGM1': 'Corneria',
    'SGBGM2': 'Space Armada',
    'SGBGM3': 'Asteroid Belt',
    'SGBGM4': 'Fortresses',
    'SGBGM5': 'Boss Battle',
    'SGBGM6': 'Black Hole',
    'SGBGM7': 'Title Screen',
    'SGBGM8': 'Game Over',
    'SGBGM9': 'Victory',
    'SGBGMA': 'Mission Complete',
    'SGBGMB': 'Course Clear',
    'SGBGMC': 'Map Select',
    'SGBGMD': 'Map Theme',
    'SGBGME': 'Ending',
    'SGBGMF': 'Credits',
    'SGBGMG': 'Intro',
    'SGBGMH': 'Staff Roll',
    'SGBGMI': 'Demo',
    'SGBGMJ': 'Fortresses 2',
    'SGBGMK': 'Boss Phase 2',
    'SGBGML': 'Final Boss',
    'SGBGMM': 'Invincibility',
    'SGBGMN': 'Training',
    'SGBGMO': 'Continue',
    'SGBGMP': 'Extra',
    'SGSOUND0': 'SFX Bank 0',
    'SGSOUND1': 'SFX Bank 1',
    'SGSOUND2': 'SFX Bank 2',
    'SGSOUND3': 'SFX Bank 3',
    'SGSOUND4': 'SFX Bank 4',
    'SGSOUND5': 'SFX Bank 5',
    'SGSOUND6': 'SFX Bank 6',
    'SGSOUND7': 'SFX Bank 7',
    'SGSOUND8': 'SFX Bank 8',
    'SGSOUND9': 'SFX Bank 9',
    'SGSOUNDA': 'SFX Bank A',
    'GSGSNDA':  'SoundGood Driver',
    'PSGSNDA':  'PSG Music Driver',
    'PSGSND2':  'PSG SFX 2',
    'PSGSND5':  'PSG SFX 5',
    'PSGBGMM':  'PSG BGM Master',
}

def extract_sounds():
    print("\n── Sound Files ─────────────────────────────────────────────")
    snd_dir = BASE / "SND"
    bin_files = sorted(snd_dir.glob("*.BIN")) + sorted(snd_dir.glob("*.bin"))
    print(f"  Processing {len(bin_files)} sound BIN files")

    # Render waveform-style visualisation of raw bytes
    for bf in bin_files:
        data = bf.read_bytes()
        if not data: continue

        W, H = 480, 120
        img  = Image.new('RGB', (W, H), (10, 14, 24))
        draw = ImageDraw.Draw(img)

        friendly = BGM_NAMES.get(bf.stem.upper(), bf.stem)
        size_kb   = len(data) / 1024
        kind      = "BGM" if bf.stem.upper().startswith("SGBGM") else (
                    "SFX" if bf.stem.upper().startswith("SGSOUND") else "Driver")
        kind_colors = {"BGM": (80,160,255), "SFX": (255,160,60), "Driver": (160,255,160)}
        bar_color = kind_colors.get(kind, (180,180,180))

        # Header
        draw.rectangle([0, 0, W, 28], fill=(20, 26, 40))
        draw.text((8, 6),  f"{bf.name}", fill=(220, 230, 255))
        draw.text((8, 16), f"{friendly}  •  {kind}  •  {size_kb:.1f} KB  •  SNES SoundGood format", fill=(140, 150, 180))

        # Waveform-like display of raw bytes (visualise sequence data)
        n = min(len(data), W - 4)
        step = max(1, len(data) // n)
        for xi in range(n):
            byte_val = data[xi * step]
            bh = int(byte_val / 255 * (H - 34))
            x = xi + 2
            y0 = H - 4
            y1 = y0 - bh
            # Color by value range
            if byte_val < 32:
                c = (40, 60, 120)
            elif byte_val < 128:
                c = bar_color
            else:
                c = tuple(min(255, v + 60) for v in bar_color)
            draw.line([(x, y0), (x, y1)], fill=c)

        draw.text((4, H - 16), "⚠ SNES proprietary driver format — playback requires SNES emulator", fill=(100, 100, 120))

        img.save(OUT / "sounds" / f"{bf.stem}.png")

    print(f"  Saved {len(bin_files)} sound info cards")

# ═══════════════════════════════════════════════════════════════════════════
# 6. INDEX PAGE — HTML overview of all assets
# ═══════════════════════════════════════════════════════════════════════════

def build_index(all_shapes):
    print("\n── Building HTML index ────────────────────────────────────")

    model_gifs  = sorted((OUT / "models").glob("*.gif"))
    palette_pngs= sorted((OUT / "palettes").glob("*.png"))
    gfx_pngs    = sorted((OUT / "graphics").glob("*.png"))
    map_pngs    = sorted((OUT / "maps").glob("*.png"))
    snd_pngs    = sorted((OUT / "sounds").glob("*.png"))

    html = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Star Fox SNES — Asset Browser</title>
<style>
  body { background:#0a0e18; color:#c8d4e8; font-family:monospace; margin:0; padding:16px; }
  h1   { color:#80c0ff; border-bottom:1px solid #203050; padding-bottom:8px; }
  h2   { color:#60a0e0; margin-top:32px; border-left:3px solid #4080c0; padding-left:10px; }
  .grid{ display:flex; flex-wrap:wrap; gap:10px; margin-top:12px; }
  .card{ background:#131a28; border:1px solid #1e2e44; border-radius:4px;
         padding:6px; text-align:center; width:180px; }
  .card img { max-width:168px; max-height:168px; image-rendering:pixelated; }
  .card .label { font-size:10px; color:#8090a8; margin-top:4px; word-break:break-all; }
  .wide .card { width:360px; }
  .wide .card img { max-width:340px; max-height:200px; }
  .fullw .card { width:100%; }
  .fullw .card img { max-width:100%; max-height:160px; }
  .stats { background:#0f1520; border:1px solid #1e2e44; border-radius:4px;
           padding:12px; margin:12px 0; display:flex; gap:32px; flex-wrap:wrap; }
  .stat  { text-align:center; }
  .stat .n { font-size:2em; color:#80c0ff; }
  .stat .l { font-size:0.8em; color:#607080; }
</style>
</head>
<body>
<h1>⭐ Star Fox SNES — Asset Browser</h1>
<div class="stats">
"""
    html += f'<div class="stat"><div class="n">{len(model_gifs)}</div><div class="l">3D Models</div></div>\n'
    html += f'<div class="stat"><div class="n">{len(gfx_pngs)}</div><div class="l">Tile Sheets</div></div>\n'
    html += f'<div class="stat"><div class="n">{len(palette_pngs)}</div><div class="l">Palettes</div></div>\n'
    html += f'<div class="stat"><div class="n">{len(map_pngs)}</div><div class="l">Level Maps</div></div>\n'
    html += f'<div class="stat"><div class="n">{len(snd_pngs)}</div><div class="l">Sound Files</div></div>\n'
    html += '</div>\n'

    # Backgrounds
    bg_pngs = sorted((OUT / "backgrounds").glob("*.png"))
    if bg_pngs:
        html += f'<h2>Level Backgrounds ({len(bg_pngs)} assembled from CGX + SCR + palette)</h2>\n<div class="grid wide">\n'
        for p in bg_pngs:
            rel = os.path.relpath(p, OUT / "index")
            html += f'<div class="card"><img src="{rel}" loading="lazy"><div class="label">{p.stem.replace("_"," ")}</div></div>\n'
        html += '</div>\n'

    # Models
    html += '<h2>3D Models (rotating GIFs)</h2>\n<div class="grid">\n'
    for p in model_gifs:
        rel = os.path.relpath(p, OUT / "index")
        html += f'<div class="card"><img src="{rel}" loading="lazy"><div class="label">{p.stem}</div></div>\n'
    html += '</div>\n'

    # Graphics
    html += '<h2>Tile Graphics</h2>\n<div class="grid wide">\n'
    for p in gfx_pngs:
        rel = os.path.relpath(p, OUT / "index")
        html += f'<div class="card"><img src="{rel}" loading="lazy"><div class="label">{p.stem}</div></div>\n'
    html += '</div>\n'

    # Palettes
    html += '<h2>Palettes</h2>\n<div class="grid">\n'
    for p in palette_pngs:
        rel = os.path.relpath(p, OUT / "index")
        html += f'<div class="card"><img src="{rel}" loading="lazy"><div class="label">{p.stem}</div></div>\n'
    html += '</div>\n'

    # Maps
    html += '<h2>Level Maps</h2>\n<div class="grid wide">\n'
    for p in map_pngs:
        rel = os.path.relpath(p, OUT / "index")
        html += f'<div class="card"><img src="{rel}" loading="lazy"><div class="label">{p.stem}</div></div>\n'
    html += '</div>\n'

    # Captured audio
    audio_files = sorted((OUT / "sounds").glob("*.ogg")) + sorted((OUT / "sounds").glob("*.mp3"))
    # deduplicate by stem (prefer ogg)
    seen_stems = {}
    for af in audio_files:
        if af.stem not in seen_stems or af.suffix == '.ogg':
            seen_stems[af.stem] = af
    captured = list(seen_stems.values())

    if captured:
        html += '<h2>Captured Audio (recorded via snes9x)</h2>\n'
        for af in captured:
            rel = os.path.relpath(af, OUT / "index")
            mp3_rel = rel.replace('.ogg', '.mp3')
            html += f'''<div style="background:#131a28;border:1px solid #1e2e44;border-radius:4px;padding:10px;margin:6px 0">
  <span style="color:#80c0ff">{af.stem.replace("_"," ").title()}</span>
  <audio controls style="margin-left:12px;vertical-align:middle">
    <source src="{rel}" type="audio/ogg">
    <source src="{mp3_rel}" type="audio/mpeg">
  </audio>
  <a href="{rel}" download style="margin-left:8px;color:#4080c0;font-size:0.85em">OGG</a>
  <a href="{mp3_rel}" download style="margin-left:6px;color:#4080c0;font-size:0.85em">MP3</a>
</div>\n'''

    # Sound driver info cards
    html += '<h2>Sound Driver Data (.BIN)</h2>\n<div class="grid fullw">\n'
    for p in snd_pngs:
        rel = os.path.relpath(p, OUT / "index")
        html += f'<div class="card"><img src="{rel}" loading="lazy"><div class="label">{p.stem}</div></div>\n'
    html += '</div>\n'

    html += '</body></html>\n'

    idx = OUT / "index" / "index.html"
    idx.write_text(html)
    print(f"  Saved {idx}")
    return idx

# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("Star Fox SNES Asset Extractor")
    print(f"  Source: {BASE}")
    print(f"  Output: {OUT}")

    all_shapes = extract_models()
    extract_palettes()
    extract_graphics()
    extract_maps()
    extract_sounds()
    idx = build_index(all_shapes)

    print(f"\n✓ Done. Open {idx} in a browser to browse all assets.")
