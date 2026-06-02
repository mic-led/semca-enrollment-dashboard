"""
generate_donut_mask.py
----------------------
Generates a pre-baked donut shading mask PNG (and its base64 data URL) that
the dashboard loads as a static image instead of running per-pixel math on
every chart render.

The mask is a grayscale image:
  - Ring pixels: brightness value (kA + kD * NdL) * 255
  - Outside ring / hole: 255 (white = identity under multiply blend)

Dashboard uses:
  ctx.globalCompositeOperation = 'multiply';
  ctx.drawImage(maskImg, x, y, w, h);

Run:  python3 generate_donut_mask.py
Outputs: donut_shading_mask.png  +  donut_shading_mask_b64.txt
"""

import math, base64, struct, zlib
from PIL import Image

# ── Parameters — must match dashboard values ──────────────────────────────────
MASK_SIZE       = 512          # output PNG resolution (square)
CUTOUT          = 0.52         # inner radius fraction (matches Chart.js cutout:"52%")
TUBE_ROUNDNESS  = 0.75         # normal softening at rim
LIGHT_ANGLE_DEG = 225          # compass: 0=top 90=right 180=bottom 270=left
LIGHT_TILT      = 0.88         # horizontal component (0=overhead, 1=side-lit)
kA              = 0.58         # ambient
kD              = 0.28         # diffuse

# ── Derived light vector ───────────────────────────────────────────────────────
a   = math.radians(LIGHT_ANGLE_DEG)
Lx  =  math.sin(a) * LIGHT_TILT
Ly  = -math.cos(a) * LIGHT_TILT          # y is DOWN in screen space
Lz  =  math.sqrt(max(0.0, 1.0 - LIGHT_TILT ** 2))

# ── Geometry ───────────────────────────────────────────────────────────────────
cx = cy  = MASK_SIZE / 2.0
outerR   = MASK_SIZE / 2.0
innerR   = outerR * CUTOUT
midR     = (outerR + innerR) / 2.0
tubeR    = (outerR - innerR) / 2.0
oR2, iR2 = outerR ** 2, innerR ** 2

# ── Render ─────────────────────────────────────────────────────────────────────
img = Image.new("L", (MASK_SIZE, MASK_SIZE), 255)   # start with white (identity)
pixels = img.load()

for py in range(MASK_SIZE):
    for px in range(MASK_SIZE):
        dx   = px - cx
        dy   = py - cy
        rho2 = dx*dx + dy*dy

        if rho2 > oR2 or rho2 < iR2:
            continue                          # outside ring → stay white

        rho    = math.sqrt(rho2)
        invRho = 1.0 / rho
        cosT   = dx * invRho
        sinT   = dy * invRho

        cosPhi = (rho - midR) / tubeR
        cosPhi = max(-1.0, min(1.0, cosPhi)) * TUBE_ROUNDNESS
        sinPhi = math.sqrt(max(0.0, 1.0 - cosPhi * cosPhi))

        Nx, Ny, Nz = cosPhi * cosT, cosPhi * sinT, sinPhi

        NdL    = max(0.0, Nx*Lx + Ny*Ly + Nz*Lz)
        bright = kA + kD * NdL

        pixels[px, py] = min(255, int(bright * 255 + 0.5))

# ── Save ───────────────────────────────────────────────────────────────────────
out_png = "/tmp/semca-check/donut_shading_mask.png"
img.save(out_png, "PNG", optimize=True)

with open(out_png, "rb") as f:
    b64 = base64.b64encode(f.read()).decode()

data_url = f"data:image/png;base64,{b64}"

out_txt = "/tmp/semca-check/donut_shading_mask_b64.txt"
with open(out_txt, "w") as f:
    f.write(data_url)

size_kb = len(b64) * 3 / 4 / 1024
print(f"PNG saved:  {out_png}")
print(f"Base64 txt: {out_txt}")
print(f"Data URL size: {size_kb:.1f} KB")
print(f"Paste the data URL as DONUT_MASK_SRC in the dashboard.")
