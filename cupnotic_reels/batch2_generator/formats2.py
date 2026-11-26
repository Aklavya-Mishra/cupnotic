#!/usr/bin/env python3
"""
New Cupnotic formats (needs shellgame.py next to it):
  split  - two shell games at once, top and bottom (answer: two cup numbers)
  blink  - grid of icons that blink / vanish / light up; one never does (answer: letter + number)
  wander - identical orbs drifting in an arena; one was gold at the start (answer: number)
"""
import json, math, os, random, subprocess, wave
import shellgame as sg
import numpy as np
from PIL import Image, ImageDraw
from shellgame import (W, H, FPS, SR, MASTER_W, SKINS, BALLS, FONT_BOLD, FONT_SEMI, HOOKS, REHOOKS, FOLLOW_LINES,
                       font, render_master, render_ball, render_blob, text_sprite, fit_text, paste_c, badge_sprite,
                       out_cubic, in_quad, smooth, layout, Puzzle, synth, T)

HANDLE = "cupnotic"
SAFE_TOP, TEXT_Y = 490, 1330
TAGS = "#BrainChallenge #PuzzleChallenge #FocusTest #BrainGames #CanYouSolveIt #Cupnotic"


# ---------------------------------------------------------------- shared plumbing
def base_bg(th, title, sub, wm_y, badge=None):
    Yg, Xg = np.mgrid[0:H, 0:W].astype(np.float32)
    d = np.sqrt(((Xg - W / 2) / W) ** 2 + ((Yg - H * 0.47) / (H * 0.62)) ** 2)
    m = np.clip(d / 0.78, 0, 1) ** 1.3
    img = np.array(th["bg_c"], np.float32) * (1 - m[..., None]) + np.array(th["bg_e"], np.float32) * m[..., None]
    img += np.random.default_rng(0).uniform(-1.5, 1.5, img.shape)
    bg = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8), "RGB")
    paste_c(bg, fit_text(title, FONT_BOLD, 104, th["ink"]), W / 2, 340)
    paste_c(bg, fit_text(sub, FONT_BOLD, 46, th["sub"], maxw=940), W / 2, 428)
    if badge: paste_c(bg, badge_sprite(badge, th), W / 2, 478)
    wm = fit_text(" ".join(HANDLE.upper()), FONT_BOLD, 150, tuple(th["ink"]) + (255,), maxw=940, shadow=False)
    paste_c(bg, wm, W / 2, wm_y, alpha=0.10)
    return bg


class Texts:
    """Hook, re-hook, countdown, question with timer bar, reveal. Same look as the classic reels."""
    def __init__(self, th, rng, hook, q, q2, r1, r2=None):
        self.th = th
        self.hook = fit_text(hook or rng.choice(HOOKS), FONT_BOLD, 64, th["accent"], maxw=960)
        self.rehook = fit_text(rng.choice(REHOOKS), FONT_BOLD, 56, th["ink"], maxw=960)
        self.cd = {k: text_sprite(str(k), font(FONT_BOLD, 150), th["ink"]) for k in (3, 2, 1)}
        self.q1 = fit_text(q, FONT_BOLD, 72, th["ink"])
        self.q2 = fit_text(q2, FONT_SEMI, 42, th["sub"], maxw=960)
        self.r1 = fit_text(r1, FONT_BOLD, 76, th["accent"])
        self.r2 = fit_text(r2 or rng.choice(FOLLOW_LINES), FONT_SEMI, 42, th["sub"], maxw=960)

    def draw(self, fr, t, T_CD, T_GO, T_Q, T_REV, rh0, ty=TEXT_Y):
        if t < T_CD:
            paste_c(fr, self.hook, W / 2, ty + 20, scale=1.22 - 0.22 * out_cubic(t / 0.3) + 0.025 * math.sin(t * 7),
                    alpha=min(1.0, t / 0.15) * (1 - in_quad(max(0, t - T_CD + 0.2) / 0.2)))
        elif t < T_GO:
            k = 3 - int((t - T_CD) / 0.6); lt = ((t - T_CD) % 0.6) / 0.6
            paste_c(fr, self.cd[max(1, k)], W / 2, ty + 20, scale=1.35 - 0.35 * out_cubic(lt * 2.5), alpha=1 - in_quad(max(0, lt - 0.6) / 0.4))
        elif rh0 <= t < rh0 + 1.5:
            g = t - rh0
            paste_c(fr, self.rehook, W / 2, ty + 20, scale=1.1 - 0.1 * out_cubic(g / 0.25), alpha=max(0, min(1.0, g / 0.15, (1.5 - g) / 0.3)))
        elif T_Q <= t < T_REV:
            a = out_cubic((t - T_Q) / 0.25)
            paste_c(fr, self.q1, W / 2, ty, alpha=a)
            paste_c(fr, self.q2, W / 2, ty + 75, alpha=a)
            p = (t - T_Q) / (T_REV - T_Q); bw = 520
            dd = ImageDraw.Draw(fr)
            dd.rounded_rectangle([W / 2 - bw / 2, ty + 130, W / 2 + bw / 2, ty + 144], 7, fill=(40, 55, 60))
            dd.rounded_rectangle([W / 2 - bw / 2, ty + 130, W / 2 - bw / 2 + max(14, bw * (1 - p)), ty + 144], 7, fill=self.th["accent"])
        elif t >= T_REV:
            a = out_cubic((t - T_REV - 0.25) / 0.3)
            if a > 0:
                paste_c(fr, self.r1, W / 2, ty, scale=1.15 - 0.15 * a, alpha=a)
                paste_c(fr, self.r2, W / 2, ty + 80, alpha=a)


def open_writer(out_path, T_END, events, seed, crf=20):
    wav_path = out_path + ".wav"
    with wave.open(wav_path, "wb") as wf:
        wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(SR)
        wf.writeframes(synth(T_END, events, np.random.default_rng(seed)).tobytes())
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
           "-i", "-", "-i", wav_path, "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf), "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart", out_path]
    return subprocess.Popen(cmd, stdin=subprocess.PIPE), wav_path


def finish(proc, wav_path, out_path, cover, meta):
    proc.stdin.close(); proc.wait()
    os.remove(wav_path)
    cover.save(out_path[:-4] + "_cover.jpg", quality=92)
    with open(out_path[:-4] + ".json", "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    return meta


def std_events(T_HOLD, T_CD, T_GO, T_SH_END, T_Q, T_REV, extra=()):
    ev = [("beep", T_CD, 660), ("beep", T_CD + 0.6, 660), ("beep", T_CD + 1.2, 990), ("bed", T_GO, T_SH_END),
          ("riser", T_GO, T_SH_END), ("roll", T_Q, T_REV), ("ding", T_REV)]
    ev += [("tick", T_Q + i * 0.5) for i in range(int((T_REV - T_Q) / 0.5))]
    return ev + list(extra)


# ---------------------------------------------------------------- SPLIT: two games at once
def make_split(job, out_dir, seed):
    rng = random.Random(seed)
    th, per = job["theme"], job.get("per", 3)
    halves = []
    for h, (cup, ball) in enumerate(job["halves"]):
        slots, ring = layout(("grid", 1, per))
        cfg = dict(shuffle=job.get("shuffle", 15), speed=job.get("speed", (0.62, 0.40)), multi=0.25 if per >= 4 else 0.0,
                   cyc=0.18, ring=0.0)
        pz = Puzzle(slots, ring, random.Random(seed * 7 + h), cfg, 1)
        halves.append(dict(pz=pz, cup=cup, ball=ball))
    length = max(hv["pz"].length for hv in halves)
    U = 290 if per == 3 else 225
    cw = U * 0.60
    skin = SKINS["cup"]
    f0 = cw / MASTER_W
    for hv in halves:
        m, (ax, ay), top, mh = render_master(skin, dict(th, obj=hv["cup"], cap=tuple(min(255, int(c * 0.35 + 170)) for c in hv["cup"])))
        hv["m"], hv["a"], hv["mh"] = m, (ax, ay), mh
        hv["spr"] = m.resize((int(m.width * f0), int(m.height * f0)), Image.LANCZOS)
        hv["ball_spr"] = render_ball(int(cw * 0.36), BALLS[hv["ball"]])
    objh = halves[0]["mh"] * f0
    lift_h = cw * 0.70
    panels = [(505, 890), (910, 1295)]
    grounds = [p[0] + (p[1] - p[0]) * 0.80 for p in panels]
    shadow = render_blob(cw * 1.08, cw * 0.30)
    ball_sh = render_blob(cw * 0.36, cw * 0.11, alpha=170)

    moves = sum(len(hv["pz"].moves) for hv in halves)
    bg = base_bg(th, job["title"], job["sub"], 900, badge=f"{moves} MOVES")
    dr = ImageDraw.Draw(bg, "RGBA")
    for (y0, y1), hv in zip(panels, halves):
        tint = tuple(int(c * 0.22) for c in hv["cup"])
        dr.rounded_rectangle([60, y0, W - 60, y1], 28, fill=tint + (150,), outline=tuple(int(c * 0.6) for c in hv["cup"]) + (200,), width=3)

    nums = []
    for h, hv in enumerate(halves):
        hv["target"] = hv["pz"].tracked[0]
        hv["answer"] = hv["pz"].final_slot[hv["target"]] + 1 + h * per
        nums.append(hv["answer"])
    numbered = {}
    def num_spr(hv, num):
        key = (id(hv), num)
        if key not in numbered:
            im = hv["m"].copy()
            ImageDraw.Draw(im).text((hv["a"][0], hv["a"][1] - hv["mh"] * 0.45), str(num), font=font(FONT_BOLD, int(0.30 * MASTER_W)),
                                    fill=tuple(int(c * 0.28) for c in hv["cup"]) + (240,), anchor="mm")
            numbered[key] = im.resize((int(im.width * f0), int(im.height * f0)), Image.LANCZOS)
        return numbered[key]

    T_HOLD, T_DROP = 1.6, 0.45
    T_CD = T_HOLD + T_DROP + 0.15
    T_GO = T_CD + 1.8
    T_Q = T_GO + length + 0.35
    nr = job.get("no_reveal", sg.NO_REVEAL)
    T_REV = T_Q + 3.4
    T_END = T_REV + (2.2 if nr else 2.8)
    tx = Texts(th, rng, job.get("hook"), "WHICH TWO CUPS?", "Comment BOTH numbers, top & bottom",
               "COMMENT YOUR ANSWER" if nr else f"CUPS {nums[0]} & {nums[1]}", rng.choice(sg.END_LINES) if nr else None)
    rh0 = T_GO + length * 0.5
    ev = std_events(T_HOLD, T_CD, T_GO, T_GO + length, T_Q, T_REV, [("thud", T_HOLD + T_DROP - 0.02)])
    for hv in halves: ev += [("whoosh", T_GO + mv["t0"]) for mv in hv["pz"].moves]
    out_path = os.path.join(out_dir, f"{job['name']}_{seed}.mp4")
    proc, wav = open_writer(out_path, T_END, ev, seed)
    cover = None
    for fi in range(int(T_END * FPS)):
        t = fi / FPS
        fr = bg.copy()
        for h, hv in enumerate(halves):
            pz = hv["pz"]
            pos = pz.positions(t - T_GO)
            gy = grounds[h]
            lift = 0.0
            if t < T_HOLD: lift = lift_h
            elif t < T_HOLD + T_DROP: lift = lift_h * (1 - in_quad((t - T_HOLD) / T_DROP))
            if t >= T_REV and not nr: lift = lift_h * out_cubic((t - T_REV) / 0.45)
            for c in range(pz.n):
                x = W / 2 + pos[c][0] * U
                paste_c(fr, shadow, x + 6, gy + 4)
            for c in range(pz.n):
                x = W / 2 + pos[c][0] * U
                l = lift if c == hv["target"] else 0
                if c == hv["target"]:
                    b = hv["ball_spr"]; paste_c(fr, ball_sh, x + 3, gy + 2); paste_c(fr, b, x, gy - b.height * 0.42)
                spr = num_spr(hv, pz.final_slot[c] + 1 + h * per) if t >= T_Q - 0.05 else hv["spr"]
                fr.paste(spr, (int(x - hv["a"][0] * f0), int(gy - l - hv["a"][1] * f0)), spr)
        tx.draw(fr, t, T_CD, T_GO, T_Q, T_REV, rh0)
        if cover is None and t >= 0.5: cover = fr.copy()
        proc.stdin.write(fr.tobytes())
    return finish(proc, wav, out_path, cover, dict(file=os.path.basename(out_path), title=job["title"], format="split",
                  seed=seed, answer=[str(n) for n in nums], duration=round(T_END, 1), caption=job["caption"] + "\n\n" + TAGS))


# ---------------------------------------------------------------- BLINK GRID: one never does it
PASTEL = [(255, 154, 170), (255, 205, 120), (150, 220, 160), (140, 190, 255), (200, 160, 255), (255, 180, 220), (120, 220, 220)]


def _eye(d, iris, open_):
    S = d * 3
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0)); dr = ImageDraw.Draw(im)
    h = max(0.06, open_) * S * 0.62
    cy = S / 2
    dr.ellipse([S * 0.04, cy - h / 2, S * 0.96, cy + h / 2], fill=(250, 250, 252, 255), outline=(30, 30, 40, 255), width=S // 30)
    if open_ > 0.25:
        r = S * 0.2 * min(1, open_ * 1.2)
        mask = Image.new("L", (S, S), 0); ImageDraw.Draw(mask).ellipse([S * 0.05, cy - h / 2 + 2, S * 0.95, cy + h / 2 - 2], fill=255)
        iris_l = Image.new("RGBA", (S, S), (0, 0, 0, 0)); di = ImageDraw.Draw(iris_l)
        di.ellipse([S / 2 - r, cy - r, S / 2 + r, cy + r], fill=tuple(iris) + (255,))
        di.ellipse([S / 2 - r * 0.48, cy - r * 0.48, S / 2 + r * 0.48, cy + r * 0.48], fill=(15, 15, 20, 255))
        di.ellipse([S / 2 + r * 0.1, cy - r * 0.55, S / 2 + r * 0.45, cy - r * 0.2], fill=(255, 255, 255, 230))
        im.paste(iris_l, (0, 0), Image.composite(iris_l, Image.new("RGBA", (S, S)), mask))
    else:
        dr.line([S * 0.08, cy, S * 0.92, cy], fill=(30, 30, 40, 255), width=S // 22)
    return im.resize((d, d), Image.LANCZOS)


def _ghost(d, col, a=1.0):
    S = d * 3
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0)); dr = ImageDraw.Draw(im)
    x0, x1, top, bot = S * 0.16, S * 0.84, S * 0.08, S * 0.86
    w = x1 - x0
    dr.ellipse([x0, top, x1, top + w], fill=tuple(col) + (255,))
    dr.rectangle([x0, top + w / 2, x1, bot], fill=tuple(col) + (255,))
    for i in range(4):
        cx = x0 + w * (i + 0.5) / 4
        dr.ellipse([cx - w / 8, bot - w / 8, cx + w / 8, bot + w / 8], fill=tuple(col) + (255,) if i % 2 == 0 else (0, 0, 0, 0))
    for ex in (0.38, 0.62):
        dr.ellipse([S * ex - S * 0.06, S * 0.36, S * ex + S * 0.06, S * 0.48], fill=(40, 30, 60, 255))
    dr.ellipse([S * 0.44, S * 0.53, S * 0.56, S * 0.60], fill=(40, 30, 60, 200))
    im = im.resize((d, d), Image.LANCZOS)
    if a < 1: im.putalpha(im.getchannel("A").point(lambda v: int(v * a)))
    return im


def _bulb(d, lit):
    S = d * 3
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0)); dr = ImageDraw.Draw(im)
    if lit > 0:
        g = render_blob(S * 0.9, S * 0.9, color=(255, 210, 90), alpha=int(200 * lit), blur=0.3)
        im.paste(g, (int(S / 2 - g.width / 2), int(S * 0.38 - g.height / 2)), g)
    glass = tuple(int(a * (1 - lit) + b * lit) for a, b in zip((128, 134, 152), (255, 236, 150)))
    dr.ellipse([S * 0.22, S * 0.08, S * 0.78, S * 0.64], fill=glass + (255,), outline=(30, 32, 40, 255), width=S // 40)
    dr.rectangle([S * 0.36, S * 0.60, S * 0.64, S * 0.80], fill=(170, 170, 180, 255))
    for yy in (0.65, 0.71, 0.77): dr.line([S * 0.36, S * yy, S * 0.64, S * yy], fill=(110, 110, 120, 255), width=S // 50)
    dr.ellipse([S * 0.32, S * 0.16, S * 0.44, S * 0.28], fill=(255, 255, 255, 120))
    return im.resize((d, d), Image.LANCZOS)


def _star(d, col, glow):
    S = d * 3
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    if glow > 0:
        g = render_blob(S * 0.95, S * 0.95, color=(255, 255, 255), alpha=int(180 * glow), blur=0.3)
        im.paste(g, (int(S / 2 - g.width / 2), int(S / 2 - g.height / 2)), g)
    dr = ImageDraw.Draw(im)
    pts = []
    for i in range(10):
        r = S * (0.44 if i % 2 == 0 else 0.19) * (1 + 0.12 * glow)
        a = -math.pi / 2 + i * math.pi / 5
        pts.append((S / 2 + r * math.cos(a), S / 2 + r * math.sin(a)))
    c = tuple(int(min(255, v + (255 - v) * glow * 0.7)) for v in col)
    dr.polygon(pts, fill=c + (255,), outline=(40, 40, 60, 255))
    return im.resize((d, d), Image.LANCZOS)


ITEMS = {  # kind -> (noun, verb for the question, state renderer(d, colour, amount 0..1), event length s)
    "eye":   ("EYE", "BLINKS", lambda d, col, a: _eye(d, col, 1 - a), 0.35),
    "ghost": ("GHOST", "VANISHES", lambda d, col, a: _ghost(d, col, 1 - a), 0.9),
    "bulb":  ("BULB", "LIGHTS UP", lambda d, col, a: _bulb(d, a), 0.8),
    "star":  ("STAR", "TWINKLES", lambda d, col, a: _star(d, col, a), 0.7),
    "orb":   ("ORB", "VANISHES", None, 0.9),
}


def make_blink(job, out_dir, seed):
    rng = random.Random(seed)
    th, kind, mode = job["theme"], job["item"], job.get("mode", "never")
    cols, rows = job.get("grid", (6, 7))
    noun, verb, render, ev_len = ITEMS[kind]
    n = cols * rows
    target = rng.randrange(n)
    D = job.get("dur", 17.0)
    # events: (item, start time). "never": every other item fires 2-3 times, target never.
    # "twice": every other item fires once, target fires exactly twice.
    sched = {i: [] for i in range(n)}
    def place(i, k):
        tries = 0
        while len(sched[i]) < k and tries < 200:
            s = rng.uniform(0.6, D - ev_len - 0.4)
            if all(abs(s - o) > ev_len + 0.9 for o in sched[i]): sched[i].append(s)
            tries += 1
    for i in range(n):
        if mode == "never": place(i, 0 if i == target else rng.choice([2, 2, 3]))
        else: place(i, 2 if i == target else 1)
    cell_w, cell_h = 860 / cols, 715 / rows
    d = int(min(cell_w, cell_h) * 0.78)
    x0, y0 = W / 2 - cell_w * cols / 2, 545
    centers = [(x0 + cell_w * (i % cols + 0.5), y0 + cell_h * (i // cols + 0.5)) for i in range(n)]
    colors = [rng.choice(job.get("colors", PASTEL)) for _ in range(n)]
    levels = [0, 0.25, 0.5, 0.75, 1.0]
    cache = {}
    def spr(i, a):
        q = min(levels, key=lambda v: abs(v - a))
        key = (colors[i], q)
        if key not in cache:
            if kind == "orb":
                b = render_ball(d, colors[i]); b.putalpha(b.getchannel("A").point(lambda v: int(v * (1 - q))))
                cache[key] = b
            else:
                cache[key] = render(d, colors[i], q)
        return cache[key]
    def amount(i, t):
        for s in sched[i]:
            u = (t - s) / ev_len
            if 0 <= u <= 1: return math.sin(math.pi * u) ** 0.6
        return 0.0

    letters = "ABCDEFGHIJ"
    answer = f"{letters[target % cols]}{target // cols + 1}"
    bg = base_bg(th, job["title"], job["sub"], 920, badge=job.get("badge", f"{n} {noun}S · ONLY 1 IS DIFFERENT"))
    dr = ImageDraw.Draw(bg)
    lf = font(FONT_BOLD, 30)
    for c in range(cols): dr.text((x0 + cell_w * (c + 0.5), y0 - 18), letters[c], font=lf, fill=th["accent"], anchor="mm")
    for r in range(rows): dr.text((x0 - 26, y0 + cell_h * (r + 0.5)), str(r + 1), font=lf, fill=th["accent"], anchor="mm")

    q = f"WHICH {noun} {'NEVER ' + verb if mode == 'never' else verb + ' TWICE'}?"
    nr = job.get("no_reveal", sg.NO_REVEAL)
    tx = Texts(th, rng, job.get("hook"), q, "Comment its letter + number", "COMMENT YOUR ANSWER" if nr else f"IT WAS {answer}",
               rng.choice(sg.END_LINES) if nr else None)
    T_CD = 2.0
    T_GO = T_CD + 1.8
    T_Q = T_GO + D + 0.3
    T_REV = T_Q + 3.6
    T_END = T_REV + (2.2 if nr else 3.0)
    rh0 = T_GO + D * 0.5
    pops = sorted(s for i in range(n) for s in sched[i])
    ev = std_events(0, T_CD, T_GO, T_GO + D, T_Q, T_REV, [("pop", T_GO + s, 520 + 260 * ((k * 7) % 5)) for k, s in enumerate(pops)])
    ring = render_blob(d * 1.6, d * 1.6, color=th["accent"], alpha=230, blur=0.18)
    out_path = os.path.join(out_dir, f"{job['name']}_{seed}.mp4")
    proc, wav = open_writer(out_path, T_END, ev, seed)
    cover = None
    for fi in range(int(T_END * FPS)):
        t = fi / FPS
        tt = t - T_GO
        fr = bg.copy()
        rev = t >= T_REV and not nr
        if rev: paste_c(fr, ring, *centers[target], scale=1 + 0.08 * math.sin((t - T_REV) * 8), alpha=min(1, (t - T_REV) / 0.3))
        for i in range(n):
            a = amount(i, tt) if 0 <= tt <= D else 0.0
            dim = 1.0
            if rev and i != target: dim = max(0.25, 1 - (t - T_REV) / 0.4 * 0.75)
            paste_c(fr, spr(i, a), *centers[i], alpha=dim)
        tx.draw(fr, t, T_CD, T_GO, T_Q, T_REV, rh0)
        if cover is None and t >= 0.5: cover = fr.copy()
        proc.stdin.write(fr.tobytes())
    return finish(proc, wav, out_path, cover, dict(file=os.path.basename(out_path), title=job["title"], format=f"blink-{mode}",
                  seed=seed, answer=[answer], duration=round(T_END, 1), caption=job["caption"] + "\n\n" + TAGS))


# ---------------------------------------------------------------- WANDER: lock on to the one that was gold
def make_wander(job, out_dir, seed):
    rng = random.Random(seed)
    th, n = job["theme"], job.get("n", 12)
    R = 360
    cx, cy = W / 2, 905
    D = job.get("dur", 15.0)
    homes = [(0.78 * math.sin(2 * math.pi * i / n), -0.78 * math.cos(2 * math.pi * i / n)) for i in range(n)]
    speed = job.get("speed", 1.0)
    d = job.get("size", 70)
    def pos(i, t):
        if t <= 0: x, y = homes[i]
        else:
            tau = speed * (t + 0.035 * t * t)
            blend = smooth(t / 1.5)
            x = y = 0.0
            for fx, fy, px, py, amp in waves[i]:
                x += amp * math.sin(fx * tau * 2.2 + px); y += amp * math.sin(fy * tau * 2.2 + py)
            r = math.hypot(x, y)
            if r > 0.84: x, y = x / r * 0.84, y / r * 0.84
            hx, hy = homes[i]
            x, y = hx * (1 - blend) + x * blend, hy * (1 - blend) + y * blend
        return cx + x * R, cy + y * R
    for attempt in range(200):  # re-roll until no two orbs overlap at the final freeze
        waves = [[(rng.uniform(0.25, 0.75), rng.uniform(0.25, 0.75), rng.uniform(0, 6.3), rng.uniform(0, 6.3), rng.uniform(0.35, 0.55))
                  for _ in range(3)] for _ in range(n)]
        final = [pos(i, D) for i in range(n)]
        gap = min(math.dist(final[i], final[j]) for i in range(n) for j in range(i + 1, n))
        if gap > d * 1.25: break
    target = rng.randrange(n)
    order = sorted(range(n), key=lambda i: (round(final[i][1] / 70), final[i][0]))
    num = {i: k + 1 for k, i in enumerate(order)}
    base_col, hi_col = BALLS[job.get("ball", "cyan")], BALLS[job.get("hi", "gold")]
    orb = render_ball(d, base_col)
    gold = render_ball(d, hi_col)
    glow = render_blob(d * 1.8, d * 1.8, color=hi_col, alpha=200, blur=0.25)
    numbered = {}
    def num_orb(k):
        if k not in numbered:
            im = orb.copy()
            ImageDraw.Draw(im).text((im.width / 2, im.height / 2 + 1), str(k), font=font(FONT_BOLD, int(d * 0.45)), fill=(8, 20, 30), anchor="mm")
            numbered[k] = im
        return numbered[k]

    bg = base_bg(th, job["title"], job["sub"], cy, badge=job.get("badge", f"{n} IDENTICAL DECOYS"))
    ImageDraw.Draw(bg).ellipse([cx - R - 10, cy - R - 10, cx + R + 10, cy + R + 10], outline=tuple(th["accent"]), width=3)
    T_HOLD = 2.0
    T_CD = T_HOLD + 0.5
    T_GO = T_CD + 1.8
    T_Q = T_GO + D + 0.3
    nr = job.get("no_reveal", sg.NO_REVEAL)
    T_REV = T_Q + 3.4
    T_END = T_REV + (2.2 if nr else 2.8)
    tx = Texts(th, rng, job.get("hook"), job.get("q", "WHICH ONE WAS GOLD?"), "Comment the number",
               "COMMENT YOUR ANSWER" if nr else f"IT WAS NUMBER {num[target]}", rng.choice(sg.END_LINES) if nr else None)
    rh0 = T_GO + D * 0.5
    ev = std_events(T_HOLD, T_CD, T_GO, T_GO + D, T_Q, T_REV, [("zap", T_HOLD)])
    ev += [("whoosh", T_GO + k * 1.6) for k in range(int(D / 1.6))]
    out_path = os.path.join(out_dir, f"{job['name']}_{seed}.mp4")
    proc, wav = open_writer(out_path, T_END, ev, seed)
    cover = None
    for fi in range(int(T_END * FPS)):
        t = fi / FPS
        tt = min(max(t - T_GO, 0), D)
        fr = bg.copy()
        hi = 1.0 if t < T_HOLD else max(0.0, 1 - (t - T_HOLD) / 0.5)
        if t >= T_REV and not nr: hi = min(1.0, (t - T_REV) / 0.3)
        for i in range(n):
            x, y = pos(i, tt)
            if i == target and hi > 0:
                paste_c(fr, glow, x, y, alpha=hi * (0.75 + 0.25 * math.sin(t * 9)))
                paste_c(fr, gold, x, y, alpha=hi)
                if hi < 1: paste_c(fr, orb, x, y, alpha=1 - hi)
            else:
                paste_c(fr, num_orb(num[i]) if t >= T_Q - 0.05 else orb, x, y)
            if t >= T_REV and not nr and i == target:
                paste_c(fr, num_orb(num[i]), x, y, alpha=0.0)
        if t >= T_REV and not nr:
            x, y = pos(target, tt)
            lab = text_sprite(str(num[target]), font(FONT_BOLD, int(d * 0.45)), (20, 14, 0), shadow=False)
            paste_c(fr, lab, x, y + 1)
        tx.draw(fr, t, T_CD, T_GO, T_Q, T_REV, rh0)
        if cover is None and t >= 0.5: cover = fr.copy()
        proc.stdin.write(fr.tobytes())
    return finish(proc, wav, out_path, cover, dict(file=os.path.basename(out_path), title=job["title"], format="wander",
                  seed=seed, answer=[str(num[target])], duration=round(T_END, 1), caption=job["caption"] + "\n\n" + TAGS))


RENDERERS = dict(split=make_split, blink=make_blink, wander=make_wander)
