#!/usr/bin/env python3
"""
Puzzle reel generator v2: "follow the object" shell games in many skins and formats.

Skins  : cup, bowling pin, traffic cone, top hat, egg, cloche (silver dome)
Formats: ball      - a ball hides under one object
         twin      - follow two balls
         decoy     - two balls, only one counts
         marked    - no ball: one object glows a colour, then looks like the rest
         empty     - every object hides a ball except one
Extras : rotating table, blackout flicker, fake ending with a second round,
         grid / ring / bowling-triangle layouts

Needs python3, numpy, Pillow, ffmpeg.

  python3 shellgame.py --list
  python3 shellgame.py --preset all --handle @yourpage --out out
  python3 shellgame.py --preset strike_zone --seed 5
"""
import argparse, json, math, os, random, subprocess, wave
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H, FPS, SR = 1080, 1920, 30, 44100
MASTER_W = 400

FONT_DIRS = ["/usr/share/fonts/truetype/google-fonts", "/usr/share/fonts/opentype/inter",
             "/usr/share/fonts/truetype/dejavu", "C:/Windows/Fonts", "/Library/Fonts"]
FONT_BOLD = ["Poppins-Bold.ttf", "Poppins-ExtraBold.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"]
FONT_SEMI = ["Poppins-SemiBold.ttf", "Inter-SemiBold.otf", "Poppins-Bold.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"]


def font(names, size):
    for d in FONT_DIRS:
        for n in names:
            p = os.path.join(d, n)
            if os.path.exists(p):
                return ImageFont.truetype(p, size)
    return ImageFont.load_default(size)


BALLS = dict(gold=(246, 178, 38), red=(232, 48, 58), lime=(150, 236, 60), cyan=(60, 215, 240), pink=(255, 80, 150),
             green=(50, 210, 110), white=(240, 242, 246), orange=(255, 140, 40), blue=(70, 120, 255))

# ---------------------------------------------------------------- skins
def _egg_profile():
    v = np.linspace(0, 1, 40)
    r = np.sin(np.pi * v) ** 0.75 * (0.80 + 0.25 * v)
    return list(zip(v, r / r.max()))

def _cloche_profile():
    pts = [(0, 0), (0.03, 0.10), (0.07, 0.13), (0.11, 0.10), (0.14, 0.07)]
    for v in np.linspace(0.15, 0.93, 30):
        pts.append((v, 0.95 * math.sqrt(max(0, 1 - ((0.93 - v) / 0.79) ** 2)) + 0.02))
    return pts + [(0.945, 1.0), (1.0, 1.0)]

def _c(col): return np.array(col, np.float32) / 255

SKINS = {
    "cup": dict(noun="CUP", profile=[(0, 0.70), (1, 1.0)], aspect=0.95, wscale=1.0, cap=True, spec=0.8,
                num_v=0.56, num_size=0.30,
                color=lambda v, p: _c(p["obj"]) * (1.12 if v > 0.94 else 1.0), cap_color=lambda p: _c(p["cap"])),
    "pin": dict(noun="PIN", aspect=2.8, wscale=0.60, cap=False, spec=1.0, num_v=0.66, num_size=0.44, num_col=(30, 34, 48),
                profile=[(0, 0.0), (0.015, 0.22), (0.05, 0.40), (0.10, 0.50), (0.15, 0.50), (0.21, 0.42), (0.27, 0.36),
                         (0.33, 0.37), (0.42, 0.55), (0.52, 0.82), (0.62, 0.98), (0.70, 1.0), (0.80, 0.92), (0.90, 0.74),
                         (0.97, 0.58), (1.0, 0.54)],
                color=lambda v, p: _c(p["band"]) if (0.245 < v < 0.285 or 0.315 < v < 0.355) else _c(p["obj"])),
    "cone": dict(noun="CONE", profile=[(0, 0.15), (0.88, 0.70), (0.90, 1.0), (1.0, 1.0)], aspect=1.12, wscale=0.90,
                 cap=True, spec=0.45, num_v=0.80, num_size=0.27, num_col=(40, 20, 6),
                 color=lambda v, p: _c((250, 250, 250)) if (0.30 < v < 0.44 or 0.56 < v < 0.68) else _c(p["obj"]) * (0.72 if v > 0.89 else 1.0),
                 cap_color=lambda p: _c(p["obj"]) * 0.8),
    "hat": dict(noun="HAT", profile=[(0, 0.60), (0.88, 0.56), (0.905, 1.0), (1.0, 1.0)], aspect=0.80, wscale=1.08,
                cap=True, spec=0.55, num_v=0.34, num_size=0.26, num_col=(255, 255, 255),
                color=lambda v, p: _c(p["band"]) if 0.66 < v < 0.87 else _c(p["obj"]),
                cap_color=lambda p: np.clip(_c(p["obj"]) * 1.7 + 0.04, 0, 1)),
    "egg": dict(noun="EGG", profile=_egg_profile(), aspect=1.28, wscale=0.80, cap=False, spec=0.5, shadow_r=0.62,
                num_v=0.56, num_size=0.34, num_col=(70, 50, 30), color=lambda v, p: _c(p["obj"])),
    "cloche": dict(noun="DOME", profile=_cloche_profile(), aspect=0.62, wscale=1.12, cap=False, spec=1.4,
                   num_v=0.64, num_size=0.26, num_col=(40, 46, 60), color=lambda v, p: _c(p["obj"])),
}


SKINS["tricup"] = dict(SKINS["cup"], num_col=(0, 0, 128), num_v=0.52, num_size=0.24,
    color=lambda v, p: _c((255, 153, 51)) if v < 0.36 else (_c((250, 250, 250)) if v < 0.67 else _c((19, 136, 8))),
    cap_color=lambda p: _c((255, 226, 190)))
SKINS["orb"] = dict(noun="ORB", profile=[(v, math.sqrt(max(0.0, 1 - (2 * v - 1) ** 2))) for v in np.linspace(0, 1, 40)],
    aspect=1.0, wscale=0.55, cap=False, spec=1.2, shadow_r=0.7, num_v=0.5, num_size=0.42, num_col=(6, 30, 40),
    color=lambda v, p: _c(p["obj"]))


def _trophy_handles(im, cx, top, h, R):
    dr = ImageDraw.Draw(im)
    for sgn, (a0, a1) in ((-1, (90, 270)), (1, (270, 90))):
        x0, x1 = sorted((cx + sgn * R * 0.50, cx + sgn * R * 1.0))
        dr.arc([x0, top + 0.03 * h, x1, top + 0.33 * h], a0, a1, fill=(204, 146, 30, 255), width=18)
        dr.arc([x0 + 5, top + 0.03 * h + 5, x1 - 5, top + 0.33 * h - 5], a0, a1, fill=(250, 214, 110, 255), width=5)
SKINS["trophy"] = dict(noun="TROPHY", aspect=1.08, wscale=1.0, pill_v=0.84, cap=True, spec=1.3, shadow_r=0.6, num_v=0.2, num_size=0.2,
    profile=[(0, 0.76), (0.05, 0.78), (0.20, 0.72), (0.32, 0.58), (0.42, 0.34), (0.50, 0.11), (0.70, 0.09), (0.78, 0.26),
             (0.84, 0.46), (0.86, 0.60), (1.0, 0.62)],
    color=lambda v, p: _c(p["obj"]) * (0.80 if v > 0.86 else 1.0), cap_color=lambda p: _c(p["obj"]) * 0.55, post=_trophy_handles)


def render_die(d, val, ss=3):
    S = d * ss
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0)); dr = ImageDraw.Draw(im)
    dr.rounded_rectangle([2, 2, S - 3, S - 3], S * 0.2, fill=(250, 250, 250, 255), outline=(150, 150, 165, 255), width=ss * 2)
    g = [0.27, 0.5, 0.73]
    pips = {1: [(1, 1)], 2: [(0, 0), (2, 2)], 3: [(0, 0), (1, 1), (2, 2)], 4: [(0, 0), (2, 0), (0, 2), (2, 2)],
            5: [(0, 0), (2, 0), (1, 1), (0, 2), (2, 2)], 6: [(0, 0), (2, 0), (0, 1), (2, 1), (0, 2), (2, 2)]}[val]
    r = S * 0.085
    for i, j in pips: dr.ellipse([g[i] * S - r, g[j] * S - r, g[i] * S + r, g[j] * S + r], fill=(200, 30, 40, 255))
    return im.resize((d, d), Image.LANCZOS)


def make_ball(name, d, die_val):
    if name == "die": return render_die(int(d * 1.3), die_val)
    if name == "cricket":
        im = render_ball(d, (196, 28, 36)); dr = ImageDraw.Draw(im); w = im.width
        dr.arc([w * 0.30, -w * 0.25, w * 1.30, w * 1.05], 150, 250, fill=(250, 240, 220, 255), width=max(2, d // 22))
        dr.arc([w * 0.38, -w * 0.25, w * 1.38, w * 1.05], 150, 250, fill=(250, 240, 220, 255), width=max(2, d // 22))
        return im
    return render_ball(d, BALLS[name])


def render_master(skin, pal):
    """Solid of revolution drawn slice by slice, bottom to top. Returns (RGBA, anchor_xy, top_y, height)."""
    R = MASTER_W / 2 * 0.96
    h = skin["aspect"] * 2 * R
    k = 0.30
    pv, pr = np.array([a for a, _ in skin["profile"]]), np.array([b for _, b in skin["profile"]])
    pad = 8
    top = pad + R * k
    sw, sh = int(MASTER_W + 2 * pad), int(top + h + R * k + pad)
    cx = sw / 2
    rgb = np.zeros((sh, sw, 3), np.float32)
    alpha = np.zeros((sh, sw), np.float32)
    X = np.arange(sw) + 0.5 - cx
    n = int(h * 1.5)
    vs = np.linspace(1, 0, n)
    rs = np.interp(vs, pv, pr)
    tan = np.gradient(rs, vs) * R / h
    L = np.array([-0.45, 0.55, 0.70]); L /= np.linalg.norm(L)
    Hv = L + np.array([0, 0.29, 0.957]); Hv /= np.linalg.norm(Hv)
    for i in range(n):
        a = R * rs[i]
        if a < 0.6: continue
        b = a * k
        yc = top + vs[i] * h
        y0, y1 = int(max(0, yc - b)), int(min(sh, yc + b + 1))
        Y = np.arange(y0, y1) + 0.5 - yc
        inside = (X[None, :] / a) ** 2 + (Y[:, None] / max(b, 0.5)) ** 2 <= 1
        u = np.clip(X / a, -1, 1)
        nz = np.sqrt(1 - u * u)
        cphi = 1 / math.sqrt(1 + tan[i] ** 2); sphi = tan[i] * cphi
        nx, ny, nzz = u * cphi, sphi, nz * cphi
        diff = np.clip(nx * L[0] + ny * L[1] + nzz * L[2], 0, 1)
        spec = np.clip(nx * Hv[0] + ny * Hv[1] + nzz * Hv[2], 0, 1) ** 50 * skin["spec"]
        rim = np.clip(u, 0, 1) ** 8 * 0.18
        col = skin["color"](vs[i], pal)[None, :] * (0.24 + 0.86 * diff)[:, None] + (spec + rim)[:, None]
        rgb[y0:y1] = np.where(inside[..., None], col[None, :, :], rgb[y0:y1])
        alpha[y0:y1] = np.maximum(alpha[y0:y1], inside)
    if skin["cap"] and pr[0] > 0.05:
        a = R * pr[0]; b = a * k
        Yg, Xg = np.mgrid[0:sh, 0:sw].astype(np.float32)
        rr = np.sqrt(((Xg + 0.5 - cx) / a) ** 2 + ((Yg + 0.5 - top) / b) ** 2)
        capc = skin["cap_color"](pal)
        cc = capc[None, None, :] * (1.0 - 0.16 * rr ** 2 + 0.06 * np.clip(-(Xg - cx) / a, 0, 1))[..., None]
        cc[rr > 0.88] *= 0.80
        m = rr <= 1
        rgb[m] = cc[m]
    im = Image.fromarray(np.dstack([np.clip(rgb, 0, 1) * 255, alpha * 255]).astype(np.uint8), "RGBA")
    if skin.get("post"): skin["post"](im, cx, top, h, R)
    return im, (cx, top + h), top, h


def render_ball(d, color, ss=3):
    D = d * ss
    s = int(D + 4 * ss)
    Y, X = np.mgrid[0:s, 0:s].astype(np.float32)
    nx, ny = (X - s / 2) / (D / 2), (Y - s / 2) / (D / 2)
    r2 = nx * nx + ny * ny
    nz = np.sqrt(np.clip(1 - r2, 0, 1))
    L = np.array([-0.5, -0.6, 0.62]); L /= np.linalg.norm(L)
    Hv = L + np.array([0, 0, 1.0]); Hv /= np.linalg.norm(Hv)
    diff = np.clip(nx * L[0] + ny * L[1] + nz * L[2], 0, 1)
    spec = np.clip(nx * Hv[0] + ny * Hv[1] + nz * Hv[2], 0, 1) ** 70
    base = np.array(color, np.float32) / 255
    rgb = base * (0.22 + 0.85 * diff + np.clip(ny, 0, 1) ** 3 * 0.18)[..., None] + (spec * 0.95)[..., None]
    a = np.clip((1 - np.sqrt(r2)) * D / 1.5, 0, 1)
    im = Image.fromarray(np.dstack([np.clip(rgb, 0, 1) * 255, a * 255]).astype(np.uint8), "RGBA")
    return im.resize((s // ss, s // ss), Image.LANCZOS)


def render_blob(w, h, color=(0, 0, 0), alpha=150, blur=0.35):
    pad = int(max(h, 8) * 1.2)
    im = Image.new("L", (int(w + 2 * pad), int(h + 2 * pad)), 0)
    ImageDraw.Draw(im).ellipse([pad, pad, pad + w, pad + h], fill=alpha)
    im = im.filter(ImageFilter.GaussianBlur(max(2, h * blur)))
    out = Image.new("RGBA", im.size, tuple(color) + (0,))
    out.putalpha(im)
    return out


def text_sprite(segs, f, default, shadow=True):
    """segs: str or [(text, color|None)]."""
    if isinstance(segs, str): segs = [(segs, None)]
    full = "".join(t for t, _ in segs)
    l, t, r, b = f.getbbox(full)
    pad = 24
    im = Image.new("RGBA", (r - l + 2 * pad, b - t + 2 * pad), (0, 0, 0, 0))
    if shadow:
        s = Image.new("RGBA", im.size, (0, 0, 0, 0))
        ImageDraw.Draw(s).text((pad - l, pad - t + 4), full, font=f, fill=(0, 0, 0, 170))
        im = Image.alpha_composite(im, s.filter(ImageFilter.GaussianBlur(6)))
    d = ImageDraw.Draw(im)
    x = pad - l
    for txt, col in segs:
        d.text((x, pad - t), txt, font=f, fill=col or default)
        x += f.getlength(txt)
    return im


def fit_text(segs, names, size, default, maxw=980, shadow=True):
    while True:
        spr = text_sprite(segs, font(names, size), default, shadow)
        if spr.width <= maxw or size < 30: return spr
        size -= 4


def paste_c(frame, spr, x, y, scale=1.0, alpha=1.0):
    if scale != 1.0:
        spr = spr.resize((max(1, int(spr.width * scale)), max(1, int(spr.height * scale))), Image.BILINEAR)
    if alpha < 1.0:
        spr = spr.copy(); spr.putalpha(spr.getchannel("A").point(lambda v: int(v * alpha)))
    frame.paste(spr, (int(x - spr.width / 2), int(y - spr.height / 2)), spr)


# ---------------------------------------------------------------- easing
def io_cubic(t): t = min(max(t, 0.0), 1.0); return 4 * t ** 3 if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2
def out_cubic(t): t = min(max(t, 0.0), 1.0); return 1 - (1 - t) ** 3
def in_quad(t): t = min(max(t, 0.0), 1.0); return t * t
def smooth(t): t = min(max(t, 0.0), 1.0); return t * t * (3 - 2 * t)


# ---------------------------------------------------------------- layouts
def layout(spec):
    kind = spec[0]
    if kind == "grid":
        rows, cols = spec[1], spec[2]
        slots = [(c - (cols - 1) / 2, r - (rows - 1) / 2) for r in range(rows) for c in range(cols)]
        ring = []
        if rows >= 2:
            cells = [(0, j) for j in range(cols)] + [(i, cols - 1) for i in range(1, rows)] + \
                    [(rows - 1, j) for j in range(cols - 2, -1, -1)] + [(i, 0) for i in range(rows - 2, 0, -1)]
            ring = [i * cols + j for i, j in cells]
        return slots, ring
    if kind == "ring":
        n, R = spec[1], spec[2]
        slots = [(R * math.sin(2 * math.pi * i / n), -R * math.cos(2 * math.pi * i / n)) for i in range(n)]
        return slots, list(range(n))
    if kind == "tri":  # ten-pin triangle, back row of four at the top
        slots = []
        for i, cnt in enumerate([4, 3, 2, 1]):
            for j in range(cnt):
                slots.append((j - (cnt - 1) / 2, (i - 1.5) * 0.87))
        return slots, [0, 1, 2, 3, 6, 8, 9, 7, 4]
    raise ValueError(kind)


# ---------------------------------------------------------------- puzzle logic
class Puzzle:
    def __init__(self, slots, ring, rng, cfg, n_track):
        self.slots, self.ring, self.rng, self.cfg = slots, ring, rng, cfg
        self.n = len(slots)
        self.tracked = rng.sample(range(self.n), n_track)  # cup ids == their starting slots
        d = [math.dist(a, b) for i, a in enumerate(slots) for b in slots[i + 1:]]
        self.near = min(d) * 1.5
        self.moves, self.gap = [], None
        self._generate()

    def _neighbors(self, s):
        return [t for t in range(self.n) if t != s and math.dist(self.slots[s], self.slots[t]) <= self.near]

    def _arc(self, a, b):
        (x0, y0), (x1, y1) = self.slots[a], self.slots[b]
        dx, dy = x1 - x0, y1 - y0
        dist = math.hypot(dx, dy) or 1
        px, py = -dy / dist, dx / dist
        bulge = min(max(0.32 * dist, 0.22), 0.6)
        return lambda e: (x0 + dx * e + px * bulge * math.sin(math.pi * e), y0 + dy * e + py * bulge * math.sin(math.pi * e))

    def _spin(self, a, b, k):
        (x0, y0), (x1, y1) = self.slots[a], self.slots[b]
        a0, a1 = math.atan2(y0, x0), math.atan2(y1, x1)
        da = a1 - a0
        while k > 0 and da <= 0: da += 2 * math.pi
        while k < 0 and da >= 0: da -= 2 * math.pi
        R0, R1 = math.hypot(x0, y0), math.hypot(x1, y1)
        def f(e):
            ang, R = a0 + da * e, R0 + (R1 - R0) * e + 0.08 * math.sin(math.pi * e)
            return (R * math.cos(ang), R * math.sin(ang))
        return f

    def _generate(self):
        rng, C = self.rng, self.cfg
        slot_of, cup_at = list(range(self.n)), list(range(self.n))
        t, total = 0.0, C["shuffle"]
        gap = C.get("gap")
        boost = 1.0
        while t < total:
            if gap and self.gap is None and t >= total * gap[0]:
                self.gap = (t, t + gap[1]); t += gap[1]; total += gap[1]; boost = 0.8
            frac = min(1.0, t / total)
            dur = (C["speed"][0] + (C["speed"][1] - C["speed"][0]) * frac) * boost
            r = rng.random()
            tracks, sends = {}, []
            focus = slot_of[rng.choice(self.tracked)]
            if self.ring and r < C["ring"]:
                m = len(self.ring)
                k = rng.choice([1, 1, 2, -1, -2]) if m >= 8 else rng.choice([1, -1])
                for i, s in enumerate(self.ring):
                    tgt = self.ring[(i + k) % m]
                    tracks[cup_at[s]] = self._spin(s, tgt, k); sends.append((s, tgt))
                dur *= 1.7
            elif self.n >= 3 and r < C["ring"] + C["cyc"]:
                a = focus if rng.random() < 0.6 else rng.randrange(self.n)
                cyc = [a] + rng.sample([s for s in range(self.n) if s != a], 2)
                for i in range(3):
                    s, tgt = cyc[i], cyc[(i + 1) % 3]
                    tracks[cup_at[s]] = self._arc(s, tgt); sends.append((s, tgt))
                dur *= 1.3
            else:
                npairs = 1
                if self.n >= 4 and r < C["ring"] + C["cyc"] + C["multi"]:
                    npairs = rng.choice([2, 2, 3]) if self.n >= 6 else 2
                used = set()
                for p in range(npairs):
                    free = [s for s in range(self.n) if s not in used]
                    if len(free) < 2: break
                    a = focus if (p == 0 and focus in free and rng.random() < 0.65) else rng.choice(free)
                    nb = [x for x in self._neighbors(a) if x in free]
                    b = rng.choice(nb) if nb and rng.random() < 0.75 else rng.choice([x for x in free if x != a])
                    used |= {a, b}
                    tracks[cup_at[a]] = self._arc(a, b); tracks[cup_at[b]] = self._arc(b, a)
                    sends += [(a, b), (b, a)]
                dur *= 1.0 + 0.15 * (npairs - 1)
            before = [self.slots[slot_of[c]] for c in range(self.n)]
            new = cup_at[:]
            for s, tgt in sends: new[tgt] = cup_at[s]
            cup_at = new
            for s, c in enumerate(cup_at): slot_of[c] = s
            self.moves.append(dict(t0=t, t1=t + dur, tracks=tracks, before=before))
            t += dur + 0.04
        self.length = t
        self.final_slot = slot_of[:]
        self.final = [self.slots[slot_of[c]] for c in range(self.n)]

    def positions(self, tt):
        if tt <= 0: return list(self.slots)
        for m in self.moves:
            if tt < m["t0"]: return m["before"]
            if tt <= m["t1"]:
                e = io_cubic((tt - m["t0"]) / (m["t1"] - m["t0"]))
                return [m["tracks"][c](e) if c in m["tracks"] else m["before"][c] for c in range(self.n)]
        return self.final


# ---------------------------------------------------------------- audio
def synth(duration, ev, rng):
    n = int(duration * SR) + SR
    out = np.zeros(n, np.float32)
    def add(t, sig):
        i = int(t * SR)
        if 0 <= i < n: out[i:i + len(sig)] += sig[:n - i]
    tt = lambda d: np.arange(int(d * SR)) / SR
    def whoosh(d=0.22):
        x = rng.standard_normal(int(d * SR)).astype(np.float32)
        x = np.convolve(x, np.ones(18) / 18, "same"); x -= np.convolve(x, np.ones(120) / 120, "same")
        return x * np.sin(np.pi * np.linspace(0, 1, len(x))) ** 2 * 0.66
    def beep(f, d=0.16): t = tt(d); return np.sin(2 * np.pi * f * t) * np.exp(-t * 14) * 0.32
    def thud(): t = tt(0.4); return np.sin(2 * np.pi * (70 + 90 * np.exp(-t * 30)) * t) * np.exp(-t * 11) * 0.7
    def kick(): t = tt(0.3); return np.sin(2 * np.pi * (50 + 90 * np.exp(-t * 45)) * t) * np.exp(-t * 10) * 0.32
    def tick(): t = tt(0.04); return (np.sin(2 * np.pi * 2400 * t) * 0.5 + rng.standard_normal(len(t)) * 0.3) * np.exp(-t * 120) * 0.35
    def ding():
        t = tt(1.4)
        return (np.sin(2 * np.pi * 1046.5 * t) + 0.6 * np.sin(2 * np.pi * 1568 * t) + 0.3 * np.sin(2 * np.pi * 2093 * t)) * np.exp(-t * 3.2) * 0.22
    def zap(): t = tt(0.25); return np.sin(2 * np.pi * (900 - 2800 * t) * t) * np.exp(-t * 12) * 0.25
    def band(x, lo, hi):  # crude band-pass: short moving average minus long moving average
        return np.convolve(x, np.ones(lo) / lo, "same") - np.convolve(x, np.ones(hi) / hi, "same")
    def riser(d):  # tension pad that climbs in pitch and pulse rate through the shuffle
        t = tt(d); u = t / d
        ph = 2 * np.pi * np.cumsum(150 + 260 * u ** 1.5) / SR
        trem = 0.6 + 0.4 * np.sin(2 * np.pi * np.cumsum(2 + 7 * u) / SR)
        return (np.sin(ph) + 0.5 * np.sin(ph * 1.5) + 0.3 * np.sin(ph * 2.01)) * trem * (0.02 + 0.07 * u) * np.minimum(1, (1 - u) * 30)
    def roll(d):  # snare roll that speeds up and swells into the reveal
        out_ = np.zeros(int(d * SR) + SR // 4, np.float32); t = 0.0
        while t < d:
            u = t / d
            hit = band(rng.standard_normal(int(0.07 * SR)).astype(np.float32), 3, 40) * np.exp(-tt(0.07) * 60) * (0.10 + 0.30 * u)
            i = int(t * SR); out_[i:i + len(hit)] += hit
            t += 1.0 / (11 + 20 * u)
        return out_
    def cheer(d):  # crowd roar: band-limited noise with a slow swell
        t = tt(d)
        x = band(rng.standard_normal(len(t)).astype(np.float32), 8, 90)
        env = np.minimum(1, t / 0.35) * np.exp(-np.maximum(0, t - d * 0.55) * 2.2) * (0.8 + 0.2 * np.sin(2 * np.pi * 1.7 * t))
        return x * env * 0.9
    for kind, t, *a in ev:
        if kind == "riser": add(t, riser(a[0] - t)); continue
        if kind == "roll": add(t, roll(a[0] - t)); continue
        if kind == "cheer": add(t, cheer(a[0])); continue
        if kind == "pop":
            tp = tt(0.07); add(t, np.sin(2 * np.pi * a[0] * tp * (1 + 2 * tp)) * np.exp(-tp * 55) * 0.10); continue
        if kind == "whoosh": add(t, whoosh())
        elif kind == "beep": add(t, beep(*a))
        elif kind == "thud": add(t, thud())
        elif kind == "tick": add(t, tick())
        elif kind == "ding": add(t, ding())
        elif kind == "zap": add(t, zap())
        elif kind == "bed":
            k = t
            while k < a[0]:
                add(k, kick()); add(k + 0.23, tick() * 0.25); k += 0.46
    out /= max(1e-6, np.abs(out).max()) / 0.85
    return (out[:int(duration * SR)] * 32767).astype(np.int16)


# ---------------------------------------------------------------- presets
def T(bg_c, bg_e, obj, cap=(235, 240, 245), band=(220, 50, 60), accent=(255, 196, 58), ink=(255, 255, 255), sub=(210, 225, 225), table=None):
    return dict(bg_c=bg_c, bg_e=bg_e, obj=obj, cap=cap, band=band, accent=accent, ink=ink, sub=sub, table=table)

RED, GOLD, CYAN, PINK, GREEN, LIME = (255, 92, 92), (255, 196, 58), (90, 225, 250), (255, 110, 170), (80, 225, 130), (168, 245, 74)

PRESETS = {
    "strike_zone": dict(title="STRIKE ZONE", sub=[("REMEMBER THE ", None), ("RED", RED), (" PIN", None)], skin="pin", layout=("tri",),
        mode="marked", hi=(235, 40, 52), theme=T((30, 62, 112), (5, 9, 22), (246, 244, 236), accent=RED),
        shuffle=17, speed=(0.62, 0.40), multi=0.25, cyc=0.12, ring=0.10,
        caption="🎳 One pin turns red, then hides in plain sight. Which pin was it? Comment the number 👇"),
    "golden_egg": dict(title="GOLDEN EGG", sub=[("ONE EGG IS ", None), ("GOLD", (214, 150, 20)), (". DON'T LOSE IT", None)], skin="egg", layout=("grid", 3, 3),
        mode="marked", hi=(250, 190, 40), theme=T((236, 244, 238), (196, 214, 204), (252, 246, 232), accent=(204, 140, 10), ink=(34, 52, 46), sub=(60, 84, 76)),
        shuffle=16, speed=(0.64, 0.42), multi=0.22, cyc=0.12, ring=0.10,
        caption="🥚 One of these eggs is golden. Keep your eyes on it! Which number? 👇"),
    "red_herring": dict(title="RED HERRING", sub=[("FOLLOW ", None), ("GOLD", GOLD), (", IGNORE ", None), ("RED", RED)], skin="cloche", layout=("grid", 2, 3),
        mode="decoy", balls=["gold", "red"], theme=T((40, 52, 74), (7, 9, 16), (206, 212, 224), accent=GOLD),
        shuffle=16, speed=(0.60, 0.38), multi=0.30, cyc=0.14, ring=0.10, q="WHERE IS GOLD?",
        caption="🍽️ Two balls, only one matters. Follow GOLD and ignore red. Which dome? 👇"),
    "twin_trouble": dict(title="TWIN TROUBLE", sub=[("TRACK ", None), ("CYAN", CYAN), (" AND ", None), ("PINK", PINK)], skin="cup", layout=("grid", 3, 3),
        mode="twin", balls=["cyan", "pink"], theme=T((74, 34, 110), (10, 5, 20), (164, 96, 236), cap=(242, 230, 255), accent=CYAN),
        shuffle=16, speed=(0.66, 0.44), multi=0.22, cyc=0.10, ring=0.08,
        caption="👀 Two balls at once. Can your brain track both? Comment BOTH cup numbers 👇"),
    "dizzy_table": dict(title="DIZZY TABLE", sub=[("FOLLOW ", None), ("CYAN", CYAN), (" AS THE TABLE SPINS", None)], skin="cup", layout=("ring", 6, 1.15),
        mode="ball", balls=["cyan"], rotate=1.0, theme=T((34, 40, 52), (6, 7, 12), (240, 132, 44), cap=(255, 236, 214), accent=CYAN, table=(52, 60, 76)),
        shuffle=16, speed=(0.66, 0.46), multi=0.20, cyc=0.14, ring=0.10,
        caption="🌀 The cups shuffle AND the whole table spins. Which cup hides the ball? 👇"),
    "blackout": dict(title="BLACKOUT", sub=[("FOLLOW ", None), ("PINK", PINK), (" WHEN THE LIGHTS DIE", None)], skin="cup", layout=("grid", 2, 3),
        mode="ball", balls=["pink"], blackout=True, theme=T((16, 58, 30), (3, 9, 5), (140, 226, 50), cap=(232, 255, 214), accent=PINK),
        shuffle=16, speed=(0.66, 0.46), multi=0.18, cyc=0.12, ring=0.10,
        caption="💡 The lights keep cutting out. Don't lose the ball in the dark! Which cup? 👇"),
    "cone_zone": dict(title="CONE ZONE", sub=[("FOLLOW THE ", None), ("GREEN", GREEN), (" BALL", None)], skin="cone", layout=("grid", 3, 3),
        mode="ball", balls=["green"], gap=(0.55, 2.2), theme=T((92, 46, 14), (14, 7, 3), (255, 122, 26), accent=GREEN),
        shuffle=17, speed=(0.60, 0.40), multi=0.26, cyc=0.12, ring=0.10,
        caption="🚧 Think it's over? Think again. Which cone hides the ball at the END? 👇"),
    "ghost_cup": dict(title="GHOST CUP", sub=[("ONE CUP IS ", None), ("EMPTY", (190, 70, 30)), (". FIND IT", None)], skin="cup", layout=("ring", 5, 1.05),
        mode="empty", balls=["white"], theme=T((240, 228, 208), (206, 190, 164), (188, 92, 50), cap=(250, 226, 208), accent=(176, 62, 24), ink=(64, 36, 20), sub=(104, 72, 50)),
        shuffle=15, speed=(0.66, 0.44), multi=0.25, cyc=0.14, ring=0.12, q="WHICH CUP IS EMPTY?",
        caption="👻 Every cup hides a ball... except one. Which cup is EMPTY? 👇"),
    "hat_trick": dict(title="HAT TRICK", sub=[("FOLLOW ", None), ("GOLD", GOLD), (", TRUST NOTHING", None)], skin="hat", layout=("ring", 8, 1.30),
        mode="ball", balls=["gold"], theme=T((84, 42, 132), (10, 5, 20), (30, 28, 40), band=(214, 44, 64), accent=GOLD),
        shuffle=18, speed=(0.60, 0.38), multi=0.24, cyc=0.12, ring=0.26,
        caption="🎩 Eight hats, one gold ball, and the circle keeps turning. Which hat? 👇"),
    "final_boss": dict(title="FINAL BOSS", sub=[("TWELVE CUPS, ONE ", None), ("LIME", LIME), (" BALL", None)], skin="cup", layout=("grid", 3, 4),
        mode="ball", balls=["lime"], theme=T((96, 22, 34), (14, 4, 7), (222, 62, 80), cap=(255, 226, 228), accent=LIME),
        shuffle=22, speed=(0.48, 0.30), multi=0.38, cyc=0.14, ring=0.12,
        caption="😈 Twelve cups. Top speed. Almost nobody gets this one. Which cup? 👇"),
}

PRESETS.update({
    "threes_a_crowd": dict(title="THREE'S A CROWD", sub=[("TRACK ", None), ("GOLD", GOLD), (", ", None), ("CYAN", CYAN), (" AND ", None), ("PINK", PINK)], skin="cup", layout=("grid", 3, 3),
        mode="twin", balls=["gold", "cyan", "pink"], theme=T((40, 44, 56), (6, 7, 11), (214, 220, 232), cap=(250, 252, 255), accent=GOLD),
        shuffle=15, speed=(0.72, 0.50), multi=0.18, cyc=0.10, ring=0.06,
        caption="🧠 Three balls. One brain. Can you track them ALL? Comment all three cups 👇"),
    "double_yolk": dict(title="DOUBLE YOLK", sub=[("TWO EGGS ARE ", None), ("GOLD", (214, 150, 20)), (". TRACK BOTH", None)], skin="egg", layout=("grid", 3, 3),
        mode="marked", n=2, hi=(250, 190, 40), theme=T((250, 232, 214), (224, 196, 170), (255, 250, 240), accent=(204, 120, 10), ink=(70, 40, 24), sub=(110, 74, 50)),
        shuffle=15, speed=(0.68, 0.46), multi=0.20, cyc=0.10, ring=0.08,
        caption="🥚🥚 Two golden eggs this time. Keep track of BOTH. Which numbers? 👇"),
    "pin_wheel": dict(title="PIN WHEEL", sub=[("REMEMBER ", None), ("RED", RED), (" WHILE THE LANE SPINS", None)], skin="pin", layout=("ring", 7, 1.15),
        mode="marked", hi=(235, 40, 52), rotate=1.0, theme=T((70, 44, 22), (12, 7, 3), (246, 244, 236), accent=RED, table=(150, 104, 58)),
        shuffle=16, speed=(0.66, 0.46), multi=0.20, cyc=0.14, ring=0.12,
        caption="🎳 One red pin, a spinning lane, zero mercy. Which pin was red? 👇"),
    "empty_plate": dict(title="EMPTY PLATE", sub=[("ONE DOME HIDES ", None), ("NOTHING", (255, 150, 90))], skin="cloche", layout=("grid", 2, 3),
        mode="empty", balls=["orange"], theme=T((60, 30, 36), (10, 4, 6), (212, 216, 226), accent=(255, 150, 90)),
        shuffle=15, speed=(0.64, 0.42), multi=0.26, cyc=0.14, ring=0.12, q="WHICH DOME IS EMPTY?",
        caption="🍽️ Five domes are served. One is empty. Which dome hides NOTHING? 👇"),
    "mad_hatter": dict(title="MAD HATTER", sub=[("TRACK ", None), ("RED", RED), (" AND ", None), ("GOLD", GOLD)], skin="hat", layout=("grid", 3, 3),
        mode="twin", balls=["red", "gold"], theme=T((24, 92, 84), (3, 14, 13), (30, 28, 40), band=(240, 190, 50), accent=GOLD),
        shuffle=16, speed=(0.66, 0.44), multi=0.22, cyc=0.10, ring=0.08,
        caption="🎩 Nine hats, two balls. Follow both or lose both. Comment the two hats 👇"),
    "night_shift": dict(title="NIGHT SHIFT", sub=[("FOLLOW ", None), ("WHITE", (255, 255, 255)), (" THROUGH THE POWER CUTS", None)], skin="cone", layout=("grid", 2, 3),
        mode="ball", balls=["white"], blackout=True, theme=T((30, 36, 70), (4, 5, 12), (255, 122, 26), accent=(255, 220, 90)),
        shuffle=16, speed=(0.66, 0.46), multi=0.18, cyc=0.12, ring=0.10,
        caption="🌙 Roadworks at night and the power keeps failing. Which cone hides the ball? 👇"),
    "spin_doctor": dict(title="SPIN DOCTOR", sub=[("FOLLOW ", None), ("LIME", LIME), (", IGNORE ", None), ("PINK", PINK)], skin="cup", layout=("ring", 7, 1.20),
        mode="decoy", balls=["lime", "pink"], rotate=-1.0, theme=T((22, 34, 66), (4, 6, 14), (70, 120, 250), cap=(226, 234, 255), accent=LIME, table=(34, 46, 86)),
        shuffle=16, speed=(0.66, 0.46), multi=0.22, cyc=0.14, ring=0.10, q="WHERE IS LIME?",
        caption="🌀 Two balls on a spinning table. Only LIME counts. Which cup? 👇"),
    "speed_demon": dict(title="SPEED DEMON", sub=[("ONLY 3 CUPS. FOLLOW ", None), ("BLUE", (40, 80, 220))], skin="cup", layout=("grid", 1, 3),
        mode="ball", balls=["blue"], theme=T((226, 240, 232), (188, 210, 198), (232, 96, 76), cap=(255, 232, 226), accent=(30, 70, 210), ink=(28, 48, 42), sub=(60, 84, 76)),
        shuffle=13, speed=(0.40, 0.21), multi=0.0, cyc=0.22, ring=0.0,
        caption="⚡ Only three cups. Sounds easy, right? Watch the speed. Which cup? 👇"),
    "encore": dict(title="ENCORE", sub=[("FOLLOW THE ", None), ("CYAN", CYAN), (" BALL TO THE END", None)], skin="hat", layout=("ring", 6, 1.15),
        mode="ball", balls=["cyan"], gap=(0.55, 2.2), theme=T((110, 26, 40), (16, 4, 7), (30, 28, 40), band=(90, 225, 250), accent=CYAN),
        shuffle=16, speed=(0.62, 0.40), multi=0.24, cyc=0.14, ring=0.18,
        caption="🎭 The show isn't over until it's over. Which hat at the very END? 👇"),
    "brain_melt": dict(title="BRAIN MELT", sub=[("12 CUPS. FOLLOW ", None), ("GOLD", GOLD), (", IGNORE ", None), ("RED", RED)], skin="cup", layout=("grid", 3, 4),
        mode="decoy", balls=["gold", "red"], theme=T((18, 78, 86), (4, 12, 16), (22, 172, 150), cap=(222, 246, 240), accent=GOLD),
        shuffle=20, speed=(0.52, 0.32), multi=0.34, cyc=0.14, ring=0.12, q="WHERE IS GOLD?",
        caption="🫠 Twelve cups, two balls, one right answer. Where is GOLD? 👇"),
})

BLUE = (110, 150, 255)
COMMENT_SET = {
    "birth_month": dict(title="BIRTH MONTH", sub=[("IS THE BALL UNDER ", None), ("YOUR MONTH?", GOLD)], skin="cup", layout=("grid", 3, 4),
        mode="ball", balls=["gold"], labels=["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], q="WHICH MONTH?", q2="Comment YOUR birth month", r_fmt="IT'S UNDER {a}",
        theme=T((66, 30, 116), (8, 4, 18), (236, 72, 153), cap=(255, 226, 240), accent=GOLD),
        shuffle=16, speed=(0.62, 0.42), multi=0.20, cyc=0.12, ring=0.10,
        caption="🎂 Is the ball hiding under YOUR birth month? Comment your month and let's see which month has the sharpest eyes 👇"),
    "city_pride": dict(title="CITY VS CITY", sub=[("WHICH CITY HIDES THE ", None), ("BALL?", CYAN)], skin="cup", layout=("grid", 3, 3),
        mode="ball", balls=["cyan"], labels=["MUMBAI", "DELHI", "BENGALURU", "KOLKATA", "CHENNAI", "HYDERABAD", "PUNE", "JAIPUR", "LUCKNOW"], q="WHICH CITY?", q2="Comment YOUR city", r_fmt="{a} HAS THE BALL",
        theme=T((16, 70, 90), (3, 10, 14), (250, 140, 40), cap=(255, 236, 214), accent=CYAN),
        shuffle=16, speed=(0.64, 0.42), multi=0.22, cyc=0.12, ring=0.10,
        caption="🏙️ Which city is hiding the ball? Comment YOUR city and prove it has the sharpest people 👇 Not on the list? Comment it anyway!"),
    "tricolour": dict(title="SHARP INDIANS ONLY", sub=[("FOLLOW THE ", None), ("BLUE", BLUE), (" BALL", None)], skin="cup", layout=("grid", 3, 3), cup_colors=[(255, 153, 51), (246, 246, 240), (19, 136, 8)],
        mode="ball", balls=["blue"], theme=T((40, 44, 58), (6, 7, 11), (255, 255, 255), accent=(255, 153, 51)),
        q2="Comment your cup + your state", shuffle=16, speed=(0.64, 0.42), multi=0.22, cyc=0.12, ring=0.10,
        caption="🇮🇳 Only sharp Indians get this one. Comment your cup number and your STATE. Which state wins? 👇"),
    "howzat": dict(title="HOWZAT!", sub=[("FOLLOW THE ", None), ("CRICKET BALL", (255, 110, 110))], skin="cup", layout=("grid", 3, 3),
        mode="ball", balls=["cricket"], cheer=True, theme=T((30, 112, 52), (4, 22, 10), (244, 244, 238), cap=(255, 255, 255), accent=(255, 220, 90)),
        q2="Comment cup + your favourite cricketer", shuffle=16, speed=(0.62, 0.40), multi=0.24, cyc=0.12, ring=0.10,
        caption="🏏 Howzat?! Follow the cricket ball. Comment the cup number AND your favourite cricketer of all time 👇"),
    "lock_on": dict(title="LOCK ON", sub=[("ONE TURNS ", None), ("GOLD", GOLD), (". 11 IDENTICAL DECOYS", None)], skin="orb", layout=("ring", 12, 1.5),
        mode="marked", hi=(250, 190, 40), theme=T((10, 18, 26), (0, 0, 0), (60, 200, 235), accent=GOLD),
        shuffle=16, speed=(0.64, 0.42), multi=0.26, cyc=0.14, ring=0.22,
        caption="🎯 One orb turns gold, then looks exactly like the other 11. Lock on and don't let go. Which number? 👇"),
    "no_spoilers": dict(title="NO SPOILERS", sub=[("FOLLOW THE ", None), ("GOLD", GOLD), (" BALL", None)], skin="cup", layout=("grid", 3, 3),
        mode="ball", balls=["gold"], no_reveal=True, theme=T((24, 74, 82), (5, 13, 17), (22, 172, 150), cap=(222, 246, 240), accent=GOLD),
        shuffle=18, speed=(0.56, 0.34), multi=0.30, cyc=0.12, ring=0.12,
        caption="🤐 No reveal this time. Comment your answer FIRST, then check the pinned comment. Be honest! 👇"),
    "birth_year": dict(title="BIRTH YEAR TEST", sub=[("LAST DIGIT OF ", None), ("YOUR BIRTH YEAR?", PINK)], skin="cup", layout=("tri",),
        mode="ball", balls=["pink"], num_offset=-1, q="WHICH DIGIT?", q2="Comment the last digit of YOUR birth year", r_fmt="IT'S UNDER {a}",
        theme=T((96, 34, 66), (14, 4, 9), (250, 200, 60), cap=(255, 244, 210), accent=PINK),
        shuffle=16, speed=(0.64, 0.42), multi=0.22, cyc=0.12, ring=0.10,
        caption="🔢 Is the ball under the last digit of YOUR birth year? Comment your digit. Which year is the luckiest? 👇"),
    "pick_a_side": dict(title="PICK A SIDE", sub=[("TEAM ", None), ("RED", RED), (" OR TEAM ", None), ("BLUE", BLUE), ("?", None)], skin="cup", layout=("grid", 3, 3),
        mode="twin", balls=["red", "blue"], teams=[("RED", RED), ("BLUE", BLUE)], q="WHERE IS YOUR BALL?", q2="Comment your team + cup number",
        theme=T((40, 44, 56), (6, 7, 11), (214, 220, 232), cap=(250, 252, 255), accent=GOLD),
        shuffle=16, speed=(0.64, 0.42), multi=0.22, cyc=0.10, ring=0.08,
        caption="🔴🔵 Pick a team BEFORE it starts: Red or Blue. Follow only your ball. Comment your team + cup. Which team is sharper? 👇"),
    "dice_trick": dict(title="DICE TRICK", sub=[("REMEMBER THE NUMBER. ", None), ("FOLLOW THE DICE", GOLD)], skin="cup", layout=("ring", 8, 1.30),
        mode="ball", balls=["die"], hold=2.2, q="WHICH CUP? WHAT NUMBER?", q2="Comment both: cup + dice number", r_fmt="CUP {a}, DICE SHOWED {d}",
        theme=T((30, 34, 60), (4, 5, 12), (214, 36, 48), cap=(255, 214, 214), accent=GOLD),
        shuffle=16, speed=(0.64, 0.42), multi=0.24, cyc=0.12, ring=0.20,
        caption="🎲 Two questions: which cup hides the dice, AND what number was on it? Most people forget one. Comment both 👇"),
    "count_it": dict(title="COUNT IT", sub=[("COUNT EVERY MOVE OF THE ", None), ("GOLD", GOLD), (" CUP", None)], skin="cup", layout=("ring", 5, 1.05),
        mode="count", hi=(246, 178, 38), theme=T((70, 36, 92), (9, 4, 14), (150, 110, 190), cap=(236, 224, 248), accent=GOLD),
        q="HOW MANY TIMES DID GOLD MOVE?", q2="Comment your count", shuffle=13, speed=(0.78, 0.56), multi=0.30, cyc=0.20, ring=0.10,
        caption="🧮 No hiding this time. Just COUNT how many times the gold cup moves. Everyone gets a different number... what's yours? 👇"),
}
COMMENT_SET["cup_winner"] = dict(no_reveal=False,  # the reveal IS the content here
    title="WHO WINS THE CUP?", sub=[("TRACK THE ", None), ("BLUE", BLUE), (" TROPHY", None)], skin="trophy", layout=("grid", 3, 3),
    mode="marked", hi=(70, 150, 255), win_label="INDIA", cheer=True,
    labels=["INDIA", "AUSTRALIA", "ENGLAND", "PAKISTAN", "SOUTH AFRICA", "NEW ZEALAND", "SRI LANKA", "WEST INDIES", "BANGLADESH"],
    q="WHO TAKES THE CUP?", q2="Comment your team before the reveal", r_fmt="THE CUP GOES TO {a}", r2="Agree? Comment your team",
    theme=T((20, 40, 92), (3, 6, 16), (236, 178, 48), accent=(255, 153, 51)),
    shuffle=16, speed=(0.64, 0.42), multi=0.22, cyc=0.12, ring=0.10,
    caption="🏆 9 trophies, 9 teams, 1 winner. Track the blue trophy and see who takes the cup. Agree with the result? Comment YOUR team 🏏👇")
PRESETS.update(COMMENT_SET)

TITLE_BANK = ["BRAIN MELT", "NO MERCY", "GENIUS ONLY", "NIGHTMARE MODE", "EYES WIDE OPEN", "BLINK AND LOSE", "ZERO ERRORS",
              "LAST ONE STANDING", "SPEED DEMON", "HAWK MODE", "IMPOSSIBLE?", "LOCK IN", "FOCUS CHECK", "TUNNEL VISION",
              "MAX CHAOS", "THE GRINDER", "SLEIGHT OF HAND", "TRUST NOTHING", "MIND THE GAP", "ONE SHOT"]
NO_REVEAL = False  # set True to end every reel on a call to comment instead of showing the answer
END_LINES = ["Be honest. No rewatching!", "Tag a friend who'd get this wrong", "First instinct only. No pausing!",
             "Drop your answer before you scroll", "Let's see who really got it"]
FOLLOW_LINES = ["Got it? Follow for harder ones", "Got it right? Follow. Wrong? Try the next one",
                "Nailed it? Follow for the next level", "Too easy? Follow, it gets harder",
                "Right or wrong? Follow for round two", "Got it? Follow and prove it again tomorrow"]
HOOKS = ["THE LAST SWAP FOOLS EVERYONE", "DON'T BLINK. SERIOUSLY.", "WATCH TILL THE END. IT'S A TRAP.",
         "IT GETS FASTER. STAY WITH IT.", "ONE SLIP AND IT'S OVER", "EYES ON IT. NO PAUSING.",
         "PROVE YOU'RE NOT A BOT", "YOU'LL LOSE IT AT THE END", "READY? IT WON'T WAIT FOR YOU",
         "LOCK IN. THIS ONE IS MEAN.", "THE ENDING WILL GET YOU", "BET YOU CAN'T KEEP UP"]
REHOOKS = ["FASTER NOW...", "STILL WITH IT?", "DON'T LOOK AWAY", "ALMOST THERE...", "HERE IT GETS HARD", "STAY LOCKED IN"]
HASHTAGS = "#FindTheBall #ShellGame #BrainChallenge #PuzzleChallenge #FocusTest #SpotTheBall #BrainGames #CanYouSolveIt"


# ---------------------------------------------------------------- render
def badge_sprite(txt, th):
    f = font(FONT_BOLD, 28 * 2)
    w, h = int(f.getlength(txt)) + 60, 76
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0)); dr = ImageDraw.Draw(im)
    light = sum(th["bg_c"]) > 450
    fill = (255, 255, 255, 225) if light else (8, 10, 16, 170)
    ink = tuple(int(c * 0.75) for c in th["accent"]) if light else tuple(th["accent"])
    dr.rounded_rectangle([0, 0, w - 1, h - 1], h // 2, fill=fill, outline=tuple(th["accent"]) + (255,), width=4)
    dr.text((w / 2, h / 2), txt, font=f, fill=ink, anchor="mm")
    return im.resize((w // 2, h // 2), Image.LANCZOS)


def make_video(name, handle, out_dir, seed, crf=20):
    P = PRESETS[name]
    rng = random.Random(seed)
    th, skin, mode = P["theme"], SKINS[P["skin"]], P["mode"]
    slots, ring = layout(P["layout"])
    n = len(slots)
    n_track = P.get("n") or {"ball": 1, "marked": 1, "count": 1, "empty": 1, "twin": len(P.get("balls", [])), "decoy": 2}[mode]
    pz = Puzzle(slots, ring, rng, P, n_track)
    targets = pz.tracked[:1] if mode == "decoy" else pz.tracked
    ball_of = {}
    if mode in ("ball", "twin", "decoy"):
        ball_of = {c: P["balls"][i] for i, c in enumerate(pz.tracked)}
    elif mode == "empty":
        ball_of = {c: P["balls"][0] for c in range(n) if c != pz.tracked[0]}
    lift_intro = list(range(n)) if mode == "empty" else list(ball_of)
    lift_reveal = lift_intro
    labels, off = P.get("labels"), P.get("num_offset", 0)
    if P.get("win_label"):  # the tracked object always lands on this label; the rest are shuffled
        rest = [l for l in labels if l != P["win_label"]]; rng.shuffle(rest)
        rest.insert(pz.final_slot[targets[0]], P["win_label"]); labels = rest
    def lab(slot): return labels[slot] if labels else str(slot + 1 + off)
    if not P.get("teams"): targets = sorted(targets, key=lambda c: pz.final_slot[c])
    numbers = [lab(pz.final_slot[c]) for c in targets]
    die_val = rng.randint(1, 6)
    move_count = sum(1 for mv in pz.moves if targets[0] in mv["tracks"])
    nolift = mode in ("marked", "count")
    no_reveal = P["no_reveal"] if "no_reveal" in P else NO_REVEAL  # a preset can force its own choice

    # geometry
    rotate = P.get("rotate", 0)
    maxx = max(abs(x) for x, _ in slots); maxy = max(abs(y) for _, y in slots)
    maxr = max(math.hypot(x, y) for x, y in slots)
    ext_x = maxr if rotate else maxx
    ext_y = maxr if rotate else maxy
    ky = 0.80
    U = min(290, 455 / (ext_x + 0.33 * skin["wscale"]))
    Rt = maxr + 0.80
    if th["table"]: U = min(U, 520 / Rt)
    cw = U * 0.60
    objw = cw * skin["wscale"]
    f0 = objw / MASTER_W
    master, (max_ax, max_ay), mtop, mh = render_master(skin, th)
    objh = mh * f0
    # Instagram safe zone: keep everything between y=290 and y=1470 (clear of the top bar, caption and feed crop)
    SAFE_TOP, TEXT_MAX, AVAIL = 490, 1330, 720
    def spans(U_):
        ow = U_ * 0.60 * skin["wscale"]; oh = mh * ow / MASTER_W
        up = max(oh * 1.1 + ext_y * U_ * ky + (0 if mode == "marked" else 0.42 * U_), Rt * U_ * ky if th["table"] else 0)
        down = Rt * U_ * ky + 16 if th["table"] else ext_y * U_ * ky + ow * 0.35
        return up, down
    up, down = spans(U)
    if up + down > AVAIL:
        U *= AVAIL / (up + down)
        cw = U * 0.60; objw = cw * skin["wscale"]; f0 = objw / MASTER_W; objh = mh * f0
        up, down = spans(U)
    cy = SAFE_TOP + up + (AVAIL - up - down) * 0.4
    def persp(Y): return 1.0 if ext_y == 0 else min(max(1 + 0.12 * Y / ext_y, 0.85), 1.15)

    cup_cols = P.get("cup_colors")  # optional solid colour per object (by starting slot)
    bases = [render_master(skin, dict(th, obj=col))[0] for col in cup_cols] if cup_cols else [master]
    def ci_of(c): return c * len(bases) // n
    masters = {}
    def get_master(num, hi, ci=0):
        key = (num, hi, ci)
        if key not in masters:
            master = bases[ci]
            im = master
            if hi > 0:
                a = np.asarray(master).astype(np.float32)
                lum = a[..., :3].mean(-1, keepdims=True) / 255
                tint = np.clip(np.array(P["hi"], np.float32) * (0.35 + 1.0 * lum) + 255 * np.clip(lum - 0.85, 0, 1) * 2, 0, 255)
                a[..., :3] = a[..., :3] * (1 - hi) + tint * hi
                im = Image.fromarray(a.astype(np.uint8), "RGBA")
            if num is not None:
                im = im.copy()
                pr_v = np.interp(skin["num_v"], [a for a, _ in skin["profile"]], [b for _, b in skin["profile"]])
                bcol = cup_cols[ci] if cup_cols else th["obj"]
                ncol = skin.get("num_col") or ((255, 255, 255) if sum(bcol) / 3 < 110 else tuple(int(c * 0.28) for c in bcol))
                ImageDraw.Draw(im).text((max_ax, mtop + skin["num_v"] * mh + MASTER_W * 0.48 * pr_v * 0.30 * 0.5), str(num),
                                        font=font(FONT_BOLD, int(skin["num_size"] * MASTER_W)), fill=tuple(ncol) + (240,), anchor="mm")
            masters[key] = im
        return masters[key]
    sprites = {}
    def get_sprite(num, hi, s, ci=0):
        q = round(s * 50) / 50
        key = (num, hi, q, ci)
        if key not in sprites:
            m = get_master(num, hi, ci); f = f0 * q
            sprites[key] = (m.resize((max(1, int(m.width * f)), max(1, int(m.height * f))), Image.LANCZOS), max_ax * f, max_ay * f)
        return sprites[key]
    r_bot = skin.get("shadow_r", skin["profile"][-1][1])
    shadow = render_blob(objw * r_bot * 1.08, objw * r_bot * 0.30)
    ball_d = int(cw * 0.36)
    ball_spr = {k: make_ball(k, ball_d, die_val) for k in set(ball_of.values())}
    ball_sh = render_blob(ball_d, ball_d * 0.3, alpha=170)
    glow = render_blob(objw * 1.5, objh * 1.0, color=P.get("hi", (255, 255, 255)), alpha=200, blur=0.22)
    lift_h = max(cw * 0.66, ball_d * 1.8)

    # background
    Yg, Xg = np.mgrid[0:H, 0:W].astype(np.float32)
    d = np.sqrt(((Xg - W / 2) / W) ** 2 + ((Yg - H * 0.47) / (H * 0.62)) ** 2)
    m = np.clip(d / 0.78, 0, 1) ** 1.3
    img = np.array(th["bg_c"], np.float32) * (1 - m[..., None]) + np.array(th["bg_e"], np.float32) * m[..., None]
    img += np.random.default_rng(0).uniform(-1.5, 1.5, img.shape)
    bg = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8), "RGB")
    light_bg = sum(th["bg_c"]) > 450
    if th["table"]:
        dd = ImageDraw.Draw(bg)
        rx, ry = Rt * U, Rt * U * ky
        dd.ellipse([W / 2 - rx, cy - ry + 16, W / 2 + rx, cy + ry + 16], fill=tuple(int(c * 0.45) for c in th["table"]))
        dd.ellipse([W / 2 - rx, cy - ry, W / 2 + rx, cy + ry], fill=th["table"], outline=tuple(int(c * 1.35) for c in th["table"]), width=6)
    paste_c(bg, fit_text(P["title"], FONT_BOLD, 104, th["ink"], shadow=not light_bg), W / 2, 340)
    paste_c(bg, fit_text(P["sub"], FONT_BOLD, 46, th["sub"], maxw=940, shadow=not light_bg), W / 2, 428)
    if P.get("badge", True) and mode != "count":  # a move count would give the count puzzle away
        paste_c(bg, badge_sprite(f"{len(pz.moves)} MOVES", th), W / 2, 478)
    if handle:  # big translucent brand watermark behind the objects
        wm = fit_text(" ".join(handle.upper().lstrip("@")), FONT_BOLD, 150, tuple(th["ink"]) + (255,), maxw=940, shadow=False)
        paste_c(bg, wm, W / 2, cy, alpha=0.13 if light_bg else 0.10)

    # timeline
    T_HOLD = P.get("hold", 1.3 if mode in ("ball", "count") else 2.1)
    T_DROP = 0.45
    T_CD = T_HOLD + T_DROP + 0.15
    T_SH = T_CD + 1.8
    T_Q = T_SH + pz.length + 0.35
    T_QLEN = 3.2
    T_REV = T_Q + T_QLEN
    T_END = T_REV + (2.2 if no_reveal else 2.8)
    ty = min(cy + down + 140, TEXT_MAX)

    noun = skin["noun"]
    k = len(numbers)
    q_text = P.get("q") or (f"WHICH {noun}?" if k == 1 else f"WHICH {['', '', 'TWO', 'THREE'][k]} {noun}S?")
    r_text = f"IT WAS {noun} {numbers[0]}" if k == 1 else f"{noun}S " + ", ".join(map(str, numbers[:-1])) + f" & {numbers[-1]}"
    if P.get("r_fmt"): r_text = P["r_fmt"].format(a=numbers[0], d=die_val)
    if mode == "count": r_text = f"GOLD MOVED {move_count} TIMES"
    if P.get("teams"): r_text = [(f"{nm}: {noun} {a}", col) if nm else (a, None) for (nm, col), a in zip(P["teams"], numbers)]
    if P.get("teams"): r_text = [r_text[0], ("     ", None), r_text[1]]
    if no_reveal: r_text = "COMMENT YOUR ANSWER"
    sh_on = not light_bg
    cd_spr = {k: text_sprite(str(k), font(FONT_BOLD, 150), th["ink"], sh_on) for k in (3, 2, 1)}
    q1 = fit_text(q_text, FONT_BOLD, 72, th["ink"], shadow=sh_on)
    q2 = fit_text(P.get("q2") or "Comment the number" + ("s" if len(numbers) > 1 else ""), FONT_SEMI, 42, th["sub"], maxw=960, shadow=sh_on)
    r1 = fit_text(r_text, FONT_BOLD, 76, th["accent"], shadow=sh_on)
    r2 = fit_text(rng.choice(END_LINES) if no_reveal else P.get("r2") or rng.choice(FOLLOW_LINES), FONT_SEMI, 42, th["sub"], maxw=960, shadow=sh_on)
    pills = {}
    def pill(txt, on):
        if (txt, on) not in pills:
            fs = 30 if max(map(len, labels)) <= 9 else 25
            w, h = int(font(FONT_BOLD, fs).getlength(txt)) + 28, 46
            im = Image.new("RGBA", (w * 2, h * 2), (0, 0, 0, 0)); dr = ImageDraw.Draw(im)
            dr.rounded_rectangle([0, 0, w * 2 - 1, h * 2 - 1], h, fill=tuple(th["accent"]) + (255,) if on else (10, 12, 18, 215))
            dr.text((w, h), txt, font=font(FONT_BOLD, fs * 2), fill=(10, 12, 18) if on else (255, 255, 255), anchor="mm")
            pills[(txt, on)] = im.resize((w, h), Image.LANCZOS)
        return pills[(txt, on)]
    hook = fit_text(P.get("hook") or rng.choice(HOOKS), FONT_BOLD, 64, th["accent"], maxw=960, shadow=sh_on)
    rehook = fit_text(P.get("rehook") or rng.choice(REHOOKS), FONT_BOLD, 56, th["ink"], maxw=960, shadow=sh_on)
    rh0 = pz.length * 0.52
    g1 = fit_text(q_text, FONT_BOLD, 72, th["ink"], shadow=sh_on)
    g2 = fit_text("WAIT... NOT DONE YET!", FONT_BOLD, 72, th["accent"], shadow=sh_on)

    blackouts = []
    if P.get("blackout"):
        t = 2.4
        while t < pz.length - 1.2:
            blackouts.append((t, t + 1.0)); t += 3.3
    def brightness(ts):
        for a, b in blackouts:
            if a <= ts <= b:
                edge = min(ts - a, b - ts)
                return 0.13 + 0.87 * (1 - smooth(edge / 0.12))
        return 1.0

    events = [("thud", T_HOLD + T_DROP - 0.02), ("beep", T_CD, 660), ("beep", T_CD + 0.6, 660), ("beep", T_CD + 1.2, 990),
              ("bed", T_SH, T_SH + pz.length), ("ding", T_REV)]
    events += [("whoosh", T_SH + mv["t0"]) for mv in pz.moves]
    events += [("tick", T_Q + i * 0.5) for i in range(int(T_QLEN / 0.5))]
    events += [("zap", T_SH + a) for a, _ in blackouts]
    events += [("riser", T_SH, T_SH + pz.length), ("roll", T_Q, T_REV)]
    if P.get("cheer") and not no_reveal: events.append(("cheer", T_REV, T_END - T_REV))
    if pz.gap: events += [("tick", T_SH + pz.gap[0] + 0.1), ("zap", T_SH + pz.gap[0] + 1.0)]

    out_path = os.path.join(out_dir, f"{name}_{seed}.mp4")
    wav_path = out_path + ".wav"
    with wave.open(wav_path, "wb") as wf:
        wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(SR)
        wf.writeframes(synth(T_END, events, np.random.default_rng(seed)).tobytes())
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
           "-i", "-", "-i", wav_path, "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf), "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart", out_path]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    cover = None

    for fi in range(int(T_END * FPS)):
        t = fi / FPS
        ts = t - T_SH
        frame = bg.copy()
        pos = pz.positions(ts)
        theta = 2 * math.pi * rotate * smooth(ts / pz.length) if rotate else 0.0
        ct, st = math.cos(theta), math.sin(theta)
        if th["table"]:
            dd = ImageDraw.Draw(frame)
            dot = tuple(int(c * 1.6) for c in th["table"])
            for i in range(14):
                a = theta + 2 * math.pi * i / 14
                x, y = W / 2 + (Rt - 0.14) * U * math.cos(a), cy + (Rt - 0.14) * U * ky * math.sin(a)
                rr = 7 if i else 13
                dd.ellipse([x - rr, y - rr * ky, x + rr, y + rr * ky], fill=th["accent"] if i == 0 else dot)
        # per-object state
        lift = [0.0] * n
        hi = 0.0
        if t < T_HOLD:
            for c in lift_intro: lift[c] = lift_h
            hi = 0.85 + 0.15 * math.sin(t * 9)
        elif t < T_HOLD + T_DROP:
            e = (t - T_HOLD) / T_DROP
            for c in lift_intro: lift[c] = lift_h * (1 - in_quad(e))
            hi = 1 - e
        if t >= T_REV and not no_reveal:
            e = out_cubic((t - T_REV) / 0.45)
            for c in lift_reveal: lift[c] = lift_h * e
            hi = e
        hi_q = round(hi * 5) / 5 if mode == "marked" else (1.0 if mode == "count" else 0)
        numbered = t >= T_Q - 0.05 and mode != "count"
        objs = []
        for c in range(n):
            X, Y = pos[c]
            X, Y = X * ct - Y * st, X * st + Y * ct
            objs.append((cy + Y * U * ky, c, W / 2 + X * U, persp(Y)))
        objs.sort()
        for y, c, x, s in objs:
            l = 0 if nolift else lift[c]
            paste_c(frame, shadow, x + 6, y + 4, scale=s, alpha=max(0.35, 1 - l / lift_h * 0.55))
        for y, c, x, s in objs:
            is_marked = nolift and c in targets
            if c in ball_of:
                b = ball_spr[ball_of[c]]
                paste_c(frame, ball_sh, x + 3, y + 2, scale=s)
                paste_c(frame, b, x, y - b.height * 0.42 * s, scale=s)
            if is_marked and hi_q > 0:
                paste_c(frame, glow, x, y - objh * s * 0.5, scale=s, alpha=hi_q * 0.8)
            num = lab(pz.final_slot[c]) if (numbered and not labels) else None
            spr, ax, ay = get_sprite(num, hi_q if is_marked else 0, s, ci_of(c))
            l = 0 if nolift else lift[c]
            frame.paste(spr, (int(x - ax), int(y - l - ay)), spr)
        # a lifted object in a front row must never hide a revealed ball behind it: redraw those balls on top
        for y, c, x, s in objs:
            if c in ball_of and lift[c] > 0 and not nolift:
                b = ball_spr[ball_of[c]]
                paste_c(frame, b, x, y - b.height * 0.42 * s, scale=s, alpha=min(1.0, max(0.0, (lift[c] / lift_h - 0.5) * 2)))
        if labels and numbered:
            for y, c, x, s in objs:
                paste_c(frame, pill(lab(pz.final_slot[c]), t >= T_REV and c in targets and not no_reveal), x, y - objh * s * skin["pill_v"] if "pill_v" in skin else y + 30)
        # overlays
        if t < T_CD:  # retention hook over the intro
            paste_c(frame, hook, W / 2, ty + 20, scale=1.22 - 0.22 * out_cubic(t / 0.3) + 0.025 * math.sin(t * 7), alpha=min(1.0, t / 0.15) * (1 - in_quad(max(0, t - T_CD + 0.2) / 0.2)))
        elif not pz.gap and rh0 <= ts < rh0 + 1.5:
            g = ts - rh0
            paste_c(frame, rehook, W / 2, ty + 20, scale=1.1 - 0.1 * out_cubic(g / 0.25), alpha=min(1.0, g / 0.15, (1.5 - g) / 0.3))
        if T_CD <= t < T_SH:
            k = 3 - int((t - T_CD) / 0.6); lt = ((t - T_CD) % 0.6) / 0.6
            paste_c(frame, cd_spr[k], W / 2, ty + 20, scale=1.35 - 0.35 * out_cubic(lt * 2.5), alpha=1 - in_quad(max(0, lt - 0.6) / 0.4))
        elif pz.gap and pz.gap[0] <= ts < pz.gap[1]:
            g = ts - pz.gap[0]
            if g < 1.0: paste_c(frame, g1, W / 2, ty, alpha=out_cubic(g / 0.2))
            else: paste_c(frame, g2, W / 2, ty, scale=1.2 - 0.2 * out_cubic((g - 1.0) / 0.25))
        elif T_Q <= t < T_REV:
            a = out_cubic((t - T_Q) / 0.25)
            paste_c(frame, q1, W / 2, ty, alpha=a)
            paste_c(frame, q2, W / 2, ty + 75, alpha=a)
            p = (t - T_Q) / T_QLEN; bw = 520
            dd = ImageDraw.Draw(frame)
            dd.rounded_rectangle([W / 2 - bw / 2, ty + 130, W / 2 + bw / 2, ty + 144], 7, fill=(150, 150, 150) if light_bg else (40, 55, 60))
            dd.rounded_rectangle([W / 2 - bw / 2, ty + 130, W / 2 - bw / 2 + max(14, bw * (1 - p)), ty + 144], 7, fill=th["accent"])
        elif t >= T_REV:
            a = out_cubic((t - T_REV - 0.25) / 0.3)
            if a > 0:
                paste_c(frame, r1, W / 2, ty, scale=1.15 - 0.15 * a, alpha=a)
                paste_c(frame, r2, W / 2, ty + 80, alpha=a)
        b = brightness(ts)
        if b < 1.0: frame = frame.point(lambda v: int(v * b))
        if cover is None and t >= 0.5: cover = frame.copy()
        proc.stdin.write(frame.tobytes())
    proc.stdin.close(); proc.wait()
    os.remove(wav_path)
    cover.save(out_path[:-4] + "_cover.jpg", quality=92)
    meta = dict(file=os.path.basename(out_path), title=P["title"], format=mode, skin=P["skin"], seed=seed,
                answer=numbers, dice=die_val if "die" in ball_of.values() else None, gold_moves=move_count if mode == "count" else None, objects=n, moves=len(pz.moves), duration=round(T_END, 1), caption=f"{P['caption']}\n\n{HASHTAGS}")
    with open(out_path[:-4] + ".json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    return meta


def main():
    ap = argparse.ArgumentParser(description="Puzzle reel generator")
    ap.add_argument("--preset", default="all", help="preset name, comma list, or 'all'")
    ap.add_argument("--handle", default="cupnotic", help="brand name for the watermark")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--out", default="out")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()
    if a.list:
        for k, v in PRESETS.items(): print(f"{k:14s} {v['title']:14s} {v['skin']:7s} {v['mode']}")
        print("\nSpare titles:", ", ".join(TITLE_BANK)); return
    os.makedirs(a.out, exist_ok=True)
    names = list(PRESETS) if a.preset == "all" else a.preset.split(",")
    base = a.seed if a.seed is not None else random.randrange(10 ** 6)
    for i, nm in enumerate(names):
        m = make_video(nm, a.handle, a.out, base + i)
        print(f"{m['file']:28s} answer={m['answer']} moves={m['moves']} {m['duration']}s", flush=True)


if __name__ == "__main__":
    main()
