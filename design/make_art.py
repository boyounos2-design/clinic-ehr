import numpy as np, math, asyncio
from playwright.async_api import async_playwright
F="/root/.claude/skills/synced/5c9f108e-c1f5-49e9-ae2e-16772258fc91_838cccfb-6bbb-476c-8d10-b28a73aa0fc1/canvas-design/canvas-fonts/"
W,H=2400,3200; CX,CY=1230,1330; ROT=-34; A=250
IVORY="#EFE6D2"; BG="#0B0F14"; VERM="#E4572E"
def pt(u,v):
    x=A*math.cosh(u)*math.cos(v); y=A*math.sinh(u)*math.sin(v)
    r=math.radians(ROT); return (CX+x*math.cos(r)-y*math.sin(r), CY+x*math.sin(r)+y*math.cos(r))
def path(points): return "M"+" L".join(f"{x:.1f},{y:.1f}" for x,y in points)
UMAX=2.35
els=[]; N=84
for k in range(1,N+1):
    u=UMAX*(k/N)**1.55
    pts=[pt(u,2*math.pi*i/360) for i in range(361)]
    major=(k%6==0)
    els.append(f'<path d="{path(pts)}Z" stroke-width="{1.7 if major else 1.0}" opacity="{0.85 if major else 0.42}"/>')
hyp=[]; M=120; accent=None
for j in range(M):
    v=2*math.pi*j/M
    pts=[pt(UMAX*(i/120)**1.0,v) for i in range(0,121)]
    if j==17: accent=f'<path d="{path(pts)}" stroke="{VERM}" stroke-width="3.4" fill="none"/>'; end=pts[-1]; mid=pts[60]
    hyp.append(f'<path d="{path(pts)}" stroke-width="0.9" opacity="{0.8 if j%5==0 else 0.3}"/>')
# soft organic contour: head circle + neck bar + shaft
hx,hy=1560,990
mask=f'''<mask id="m" maskUnits="userSpaceOnUse" x="0" y="0" width="{W}" height="{H}"><g filter="url(#b)" fill="white">
<circle cx="{hx}" cy="{hy}" r="590"/>
<g transform="rotate(-34 {hx} {hy})"><rect x="{hx-1250}" y="{hy-300}" width="1500" height="640" rx="320"/></g>
<g transform="rotate(8 900 2060)"><rect x="560" y="1610" width="760" height="1000" rx="180"/></g></g></mask>'''
ticks=[]
for i in range(0,201):
    y=160+i*((H-320)/200); L=34 if i%10==0 else (20 if i%5==0 else 9)
    ticks.append(f'<line x1="160" y1="{y:.1f}" x2="{160+L}" y2="{y:.1f}"/>')
for i in range(0,151):
    x=160+i*((W-320)/150); L=34 if i%10==0 else (20 if i%5==0 else 9)
    ticks.append(f'<line x1="{x:.1f}" y1="{H-160}" x2="{x:.1f}" y2="{H-160-L}"/>')
svg=f'''<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">
<defs><style>
@font-face{{font-family:IS;src:url("file://{F}InstrumentSerif-Regular.ttf")}}
@font-face{{font-family:IT;src:url("file://{F}InstrumentSerif-Italic.ttf")}}
@font-face{{font-family:DM;src:url("file://{F}DMMono-Regular.ttf")}}
.m{{font-family:DM;font-size:23px;letter-spacing:.32em;fill:{IVORY};opacity:.62}}
</style><filter id="b" x="-20%" y="-20%" width="140%" height="140%"><feGaussianBlur stdDeviation="46"/></filter>{mask}
<radialGradient id="g" cx="{CX/W:.3f}" cy="{CY/H:.3f}" r="0.55"><stop offset="0" stop-color="#1b2a33" stop-opacity=".9"/><stop offset="1" stop-color="{BG}" stop-opacity="0"/></radialGradient></defs>
<rect width="{W}" height="{H}" fill="{BG}"/><rect width="{W}" height="{H}" fill="url(#g)"/>
<g mask="url(#m)" fill="none" stroke="{IVORY}" stroke-linecap="round">{''.join(els)}{''.join(hyp)}</g>
<g mask="url(#m)">{accent}</g>
<circle cx="{end[0]:.1f}" cy="{end[1]:.1f}" r="0" />
<g stroke="{IVORY}" stroke-width="1.2" opacity=".35">{''.join(ticks)}</g>
<text class="m" x="260" y="200">PLATE  07</text>
<text class="m" x="{W-260}" y="200" text-anchor="end">σ₁  ⟂  σ₂</text>
<text class="m" x="{W-260}" y="{H-220}" text-anchor="end">WOLFF · 1892</text>
<text x="260" y="{H-330}" font-family="IS" font-size="190" fill="{IVORY}" letter-spacing="-2">Trabecular</text>
<text x="262" y="{H-215}" font-family="IT" font-size="96" fill="{IVORY}" opacity=".72">silence</text>
<line x1="260" y1="{H-360-190}" x2="260" y2="{H-360-190}" />
</svg>'''
open("trabecular_silence.svg","w").write(svg)
async def main():
    async with async_playwright() as p:
        b=await p.chromium.launch(); pg=await b.new_page(viewport={"width":W,"height":H})
        await pg.goto("file:///home/claude/design/trabecular_silence.svg"); await pg.wait_for_timeout(1200)
        await pg.screenshot(path="trabecular_silence.png"); await b.close()
asyncio.run(main())
