#!/usr/bin/env python3
"""
Star Fox SNES Background Extractor
Parses BGS.ASM and INCBINS.ASM to map every level background to its
CGX (tile graphics) + SCR (tilemap) + COL (palette) files, then
assembles full-resolution PNG background images.
"""

import re, struct
from pathlib import Path
from PIL import Image

BASE   = Path(__file__).parent / "SF"
DATA   = BASE / "DATA"
OUT    = Path(__file__).parent / "assets" / "backgrounds"
OUT.mkdir(parents=True, exist_ok=True)

# ── SNES RGB555 → RGB888 ───────────────────────────────────────────────────
def rgb555(word):
    r = (word & 0x1F) * 255 // 31
    g = ((word >> 5) & 0x1F) * 255 // 31
    b = ((word >> 10) & 0x1F) * 255 // 31
    return (r, g, b)

# ── Load a .COL file → list of 16-color sub-palettes ──────────────────────
def load_col(path):
    if path is None or not Path(path).exists():
        return [[(i*17, i*17, i*17) for i in range(16)]] * 8
    data = Path(path).read_bytes()
    pals = []
    for i in range(len(data) // 32):         # 32 bytes = 16 colors × 2 bytes
        pal = []
        for j in range(16):
            word = struct.unpack_from('<H', data, i*32 + j*2)[0]
            pal.append(rgb555(word))
        pals.append(pal)
    return pals   # list of sub-palettes

# ── Palette name → COL file ────────────────────────────────────────────────
PAL_MAP = {
    '2a':    'BG2-A.COL',
    '2b':    'BG2-B.COL',
    '2c':    'BG2-C.COL',
    '2d':    'BG2-D.COL',
    '2e':    'BG2-E.COL',
    '2ep':   'BG2-E-P.COL',
    '2f':    'BG2-F.COL',
    '2g':    'BG2-G.COL',
    'tm':    'TM-1.COL',
    'tm2':   'TM-2.COL',
    'tm3':   'TM-3.COL',
    'tm4':   'TM-4.COL',
    'bm':    'B-M.COL',
    'light': 'LIGHT.COL',
    'space': 'SPACE.COL',
    'stars': 'STARS.COL',
    'hole':  'HOLE.COL',
    'cp':    'CP.COL',
    'blue':  'BLUE.COL',
    'ground':'GROUND.COL',
    'sea':   'SEA.COL',
    'red':   'RED.COL',
    'night': 'NIGHT.COL',
    'mist':  'MIST.COL',
    'oops':  'OOPS.COL',
    'l':     'L.COL',
    'lsb':   'LSB.COL',
    'fox':   'FOX.COL',
    'etest': 'E-TEST.COL',
}

def find_col(pal_name):
    if not pal_name:
        pal_name = '2a'
    pn = pal_name.lower().replace('-','').replace('_','')
    if pn in PAL_MAP:
        p = DATA / 'COL' / PAL_MAP[pn]
        if p.exists(): return p
    # fallback: search for matching name
    for f in sorted((DATA / 'COL').glob('*.COL')):
        if pn in f.stem.lower().replace('-','').replace('_',''):
            return f
    # last resort — use first available COL
    available = sorted((DATA / 'COL').glob('*.COL'))
    return available[0] if available else None

# ── Parse INCBINS.ASM: build label→filename maps ──────────────────────────
def parse_incbins():
    """
    Returns:
      chr_map: {label_stem → CGX path}  e.g. {'bgstpccr' → Path('ST-P.CGX')}
      scr_map: {label_stem → SCR path}  e.g. {'bgstppcr' → Path('ST-P.SCR')}
    """
    chr_map = {}
    scr_map = {}
    inc = BASE / 'BANK' / 'INCBINS.ASM'
    if not inc.exists():
        return chr_map, scr_map

    for raw in inc.read_text(encoding='latin-1', errors='replace').splitlines():
        line = raw.split(';')[0].strip()
        m = re.match(r'inccru\s+(\w+)\s*,\s*data\\(.+)', line, re.I)
        if not m:
            continue
        label = m.group(1).lower()
        fname = m.group(2).replace('\\', '/').upper()
        stem  = Path(fname).stem   # e.g. 'ST-P'

        if fname.endswith('.CCR'):
            # CGX source file
            cgx = DATA / (stem + '.CGX')
            chr_map[label] = cgx
        elif fname.endswith('.PCR'):
            # SCR source file
            scr = DATA / (stem + '.SCR')
            scr_map[label] = scr

    return chr_map, scr_map

# ── Parse BGS.ASM: extract all bg_XXX_1 handlers ─────────────────────────
def parse_bgs(chr_map, scr_map):
    """
    Returns list of:
      { 'name': str, 'cgx': Path, 'scr': Path, 'col': Path, 'label': str }
    """
    bgs_path = BASE / 'ASM' / 'BGS.ASM'
    if not bgs_path.exists():
        return []

    lines   = bgs_path.read_text(encoding='latin-1', errors='replace').splitlines()
    results = []

    cur_name = None
    cur_chr  = None
    cur_scr  = None
    cur_pal  = None

    def flush():
        nonlocal cur_name, cur_chr, cur_scr, cur_pal
        if cur_name and (cur_chr or cur_scr):
            results.append({
                'name': cur_name,
                'cgx':  cur_chr,
                'scr':  cur_scr,
                'col':  find_col(cur_pal) if cur_pal else find_col('2a'),
                'pal':  cur_pal or '?',
            })
        cur_name = cur_chr = cur_scr = cur_pal = None

    for raw in lines:
        line = raw.split(';')[0].strip()
        if not line:
            continue

        # bg_name_1 label (background handler entry point)
        m = re.match(r'^(bg_\w+_1)\b', line, re.I)
        if m:
            flush()
            # Extract readable level name: bg_1_1c_1 → 1_1c
            lbl = m.group(1)
            parts = lbl.split('_')
            if len(parts) >= 4:
                cur_name = '_'.join(parts[1:-1])
            else:
                cur_name = lbl
            continue

        # bg2chr <name> — maps to bg<name>ccr label
        m = re.match(r'bg2chr\s+(\w+)', line, re.I)
        if m and cur_name:
            chr_lbl = 'bg' + m.group(1).lower() + 'ccr'
            cur_chr = chr_map.get(chr_lbl)
            # Fallback: direct filename match
            if cur_chr is None:
                stem = m.group(1).upper().replace('_', '-')
                for suffix in [stem, stem.replace('-',''), stem + '-P']:
                    p = DATA / (suffix + '.CGX')
                    if p.exists():
                        cur_chr = p
                        break
            continue

        # bg2scr <name>
        m = re.match(r'bg2scr\s+(\w+)', line, re.I)
        if m and cur_name:
            scr_lbl = 'bg' + m.group(1).lower() + 'pcr'
            cur_scr = scr_map.get(scr_lbl)
            if cur_scr is None:
                stem = m.group(1).upper().replace('_', '-')
                for suffix in [stem, stem.replace('-','')]:
                    p = DATA / (suffix + '.SCR')
                    if p.exists():
                        cur_scr = p
                        break
            continue

        # palette <name>
        m = re.match(r'palette\s+(\w+)', line, re.I)
        if m and cur_name:
            cur_pal = m.group(1).lower()
            continue

    flush()
    return results

# ── Decode SNES 4BPP tile → 8×8 list of color indices ────────────────────
def decode_tile_4bpp(data, offset):
    pixels = [[0]*8 for _ in range(8)]
    for row in range(8):
        b0 = data[offset + row*2    ] if offset + row*2     < len(data) else 0
        b1 = data[offset + row*2 + 1] if offset + row*2 + 1 < len(data) else 0
        b2 = data[offset + 16+row*2  ] if offset + 16+row*2   < len(data) else 0
        b3 = data[offset + 16+row*2+1] if offset + 16+row*2+1 < len(data) else 0
        for col in range(8):
            bit = 7 - col
            p  = ((b0 >> bit) & 1)
            p |= ((b1 >> bit) & 1) << 1
            p |= ((b2 >> bit) & 1) << 2
            p |= ((b3 >> bit) & 1) << 3
            pixels[row][col] = p
    return pixels

# ── Assemble full background image from CGX + SCR + COL ───────────────────
def render_background(cgx_path, scr_path, col_path, name):
    # Load tiles
    if cgx_path is None or not cgx_path.exists():
        return None
    cgx_data = cgx_path.read_bytes()
    n_tiles  = len(cgx_data) // 32
    if n_tiles == 0:
        return None

    # Pre-decode all tiles
    tiles = [decode_tile_4bpp(cgx_data, t*32) for t in range(n_tiles)]

    # Load tilemap
    if scr_path is None or not scr_path.exists():
        # No SCR — just render the tile sheet
        cols = min(32, n_tiles)
        rows = (n_tiles + cols - 1) // cols
        return render_tilesheet(tiles, load_col(col_path)[0:8], cols, rows)

    scr_data = scr_path.read_bytes()
    n_entries = len(scr_data) // 2

    # Determine map dimensions
    if n_entries <= 1024:
        map_w, map_h = 32, 32
    elif n_entries <= 2048:
        map_w, map_h = 64, 32
    else:
        map_w, map_h = 64, 64

    # Load palette (sub-palettes 0-7 from COL file)
    sub_pals = load_col(col_path)
    if not sub_pals:
        sub_pals = [[(i*17, i*17, i*17) for i in range(16)]]

    # Render at 1× (each tile = 8×8 px)
    img_w = map_w * 8
    img_h = map_h * 8
    img   = Image.new('RGB', (img_w, img_h), (0, 0, 0))
    pix   = img.load()

    for entry_idx in range(min(n_entries, map_w * map_h)):
        word     = struct.unpack_from('<H', scr_data, entry_idx * 2)[0]
        tile_idx = word & 0x3FF
        hflip    = bool(word & (1 << 10))
        vflip    = bool(word & (1 << 11))
        pal_num  = (word >> 14) & 0x3   # 0-3 for BG2 in Mode 2

        tile_x = (entry_idx % map_w) * 8
        tile_y = (entry_idx // map_w) * 8

        if tile_idx >= len(tiles):
            continue

        tile  = tiles[tile_idx]
        subpal = sub_pals[pal_num % len(sub_pals)]

        for row in range(8):
            r = (7 - row) if vflip else row
            for col in range(8):
                c = (7 - col) if hflip else col
                cidx  = tile[r][c]
                color = subpal[cidx] if cidx < len(subpal) else (0, 0, 0)
                px, py = tile_x + col, tile_y + row
                if px < img_w and py < img_h:
                    pix[px, py] = color

    return img

def render_tilesheet(tiles, sub_pals, cols, rows):
    img = Image.new('RGB', (cols*8, rows*8), (0,0,0))
    pix = img.load()
    subpal = sub_pals[0] if sub_pals else [(i*17,i*17,i*17) for i in range(16)]
    for ti, tile in enumerate(tiles):
        tx = (ti % cols) * 8
        ty = (ti // cols) * 8
        for row in range(8):
            for col in range(8):
                cidx = tile[row][col]
                color = subpal[cidx % len(subpal)]
                if tx+col < cols*8 and ty+row < rows*8:
                    pix[tx+col, ty+row] = color
    return img

# ── Main ──────────────────────────────────────────────────────────────────
def main():
    print("Extracting Star Fox level backgrounds...")

    chr_map, scr_map = parse_incbins()
    print(f"  INCBINS: {len(chr_map)} CHR labels, {len(scr_map)} SCR labels")

    bg_defs = parse_bgs(chr_map, scr_map)
    print(f"  BGS.ASM: {len(bg_defs)} background handlers found")

    ok = 0
    for bg in bg_defs:
        name    = bg['name']
        cgx     = bg['cgx']
        scr     = bg['scr']
        col     = bg['col']

        cgx_s = cgx.name if cgx and cgx.exists() else '(missing)'
        scr_s = scr.name if scr and scr.exists() else '(missing)'
        col_s = col.name if col and col.exists() else '(missing)'

        img = render_background(cgx, scr, col, name)
        if img:
            out_path = OUT / f"{name}.png"
            # Scale up 2× for visibility (each 8px tile becomes 16px)
            w, h = img.size
            img = img.resize((w*2, h*2), Image.NEAREST)
            img.save(out_path)
            ok += 1
            print(f"  ✓ {name:12s}  CGX:{cgx_s:12s}  SCR:{scr_s:12s}  PAL:{bg['pal']:6s}  → {w}x{h} → {out_path.name}")
        else:
            print(f"  ✗ {name:12s}  CGX:{cgx_s}  (no image)")

    # Also render any CGX+SCR pairs not referenced in BGS (e.g. map screens, title)
    extra_pairs = [
        ('CONT',   DATA/'CONT.CGX',   DATA/'CONT.SCR',   DATA/'COL'/'CP.COL',     'controls'),
        ('FOX',    DATA/'FOX.CGX',    DATA/'FOX.SCR',    DATA/'COL'/'BG2-B.COL',   'fox_sprite'),
        ('MAP',    DATA/'MAP.CGX',    DATA/'MAP.SCR',    DATA/'COL'/'BG2-A.COL',   'map_screen'),
        ('DEMO',   DATA/'DEMO.CGX',   DATA/'DEMO.SCR',   DATA/'COL'/'BG2-A.COL',  'demo_screen'),
        ('STARS',  DATA/'STARS.CGX',  DATA/'STARS.SCR',  DATA/'COL'/'STARS.COL',  'stars'),
        ('B-HOLE', DATA/'B-HOLE.CGX', DATA/'B-HOLE.SCR', DATA/'COL'/'HOLE.COL',   'black_hole'),
        ('SPACE',  DATA/'SPACE.CGX',  None,              DATA/'COL'/'SPACE.COL',  'space_tiles'),
        ('TI-3',   DATA/'TI-3.CGX',   DATA/'TI-3.SCR',   DATA/'COL'/'TM-3.COL',  'title_screen'),
        ('LSB',    DATA/'LSB.CGX',    DATA/'LSB.SCR',    DATA/'COL'/'L.COL',      'laser_beam'),
        ('F-1',    DATA/'F-1.CGX',    DATA/'F-1.SCR',    DATA/'COL'/'BG2-F.COL', 'fortresses_1'),
        ('2-2',    DATA/'2-2.CGX',    DATA/'2-2.SCR',    DATA/'COL'/'BG2-B.COL', 'route2_area2'),
        ('2-3',    DATA/'2-3.CGX',    DATA/'2-3.SCR',    DATA/'COL'/'SPACE.COL', 'route2_area3'),
        ('2-4',    DATA/'2-4.CGX',    DATA/'2-4.SCR',    DATA/'COL'/'BG2-F.COL', 'route2_area4'),
        ('3-2',    DATA/'3-2.CGX',    DATA/'3-2.SCR',    DATA/'COL'/'TM-3.COL',  'route3_area2'),
        ('3-3',    DATA/'3-3.CGX',    DATA/'3-3.SCR',    DATA/'COL'/'TM-3.COL',  'route3_area3'),
        ('3-4',    DATA/'3-4.CGX',    DATA/'3-4.SCR',    DATA/'COL'/'BG2-F.COL', 'route3_area4'),
        ('1-3',    DATA/'1-3.CGX',    DATA/'1-3.SCR',    DATA/'COL'/'SPACE.COL', 'space_asteroid'),
        ('1-3-B',  DATA/'1-3-B.CGX',  DATA/'1-3-B.SCR',  DATA/'COL'/'TM-3.COL', 'boss_bg'),
        ('1-4',    DATA/'1-4.CGX',    DATA/'1-4.SCR',    DATA/'COL'/'BG2-D.COL', 'route1_area4'),
    ]

    print(f"\n  Rendering {len(extra_pairs)} additional CGX/SCR pairs...")
    for key, cgx, scr, col, label in extra_pairs:
        if not cgx.exists():
            continue
        img = render_background(cgx, scr, col, label)
        if img:
            out_path = OUT / f"{label}.png"
            w, h = img.size
            img = img.resize((w*2, h*2), Image.NEAREST)
            img.save(out_path)
            ok += 1
            print(f"  ✓ {label}")

    print(f"\n  Done — {ok} background images saved to {OUT}")

if __name__ == '__main__':
    main()
