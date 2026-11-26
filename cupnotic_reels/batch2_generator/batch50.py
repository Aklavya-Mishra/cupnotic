#!/usr/bin/env python3
"""
Cupnotic batch of 50 reels: classic shell games with new titles, comment-driven reels, split screen,
blink grids and lock-on orbs. Every reel has a retention hook line, a mid-video re-hook and SFX.

  python3 batch50.py --list
  python3 batch50.py --part 1/2 --out batch50     # render half (run 1/2 and 2/2 in parallel)
"""
import argparse, os, shutil
import shellgame as sg
from shellgame import T, PRESETS
from formats2 import RENDERERS

GOLD, PINK, CYAN, LIME, RED, BLUE = (255, 196, 58), (255, 110, 170), (90, 225, 250), (168, 245, 74), (255, 92, 92), (110, 150, 255)
VIOLET = (190, 170, 255)

# --- classic and comment formats, re-titled (base preset, new title, hook)
CLASSIC = [
    ("final_boss", "NO MERCY", "ONE SLIP AND IT'S OVER"),
    ("twin_trouble", "DOUBLE VISION", "TWO BALLS. ONE BRAIN. GOOD LUCK."),
    ("red_herring", "DON'T GET FOOLED", "THE RED ONE IS LYING TO YOU"),
    ("dizzy_table", "MERRY-GO-ROUND", "YOU'LL LOSE IT AT THE SPIN"),
    ("blackout", "POWER CUT", "WAIT FOR THE DARK..."),
    ("cone_zone", "ROADBLOCK", "IT'S NOT OVER WHEN YOU THINK"),
    ("ghost_cup", "NOTHING INSIDE", "ONE CUP IS EMPTY. WATCH CLOSELY."),
    ("hat_trick", "MAGIC SHOW", "THE LAST SWAP FOOLS EVERYONE"),
    ("strike_zone", "SPARE ME", "REMEMBER THE RED PIN. THAT'S IT."),
    ("golden_egg", "EGG HUNT", "SIMPLE? WAIT FOR IT."),
    ("threes_a_crowd", "TRIPLE TRACK", "THREE BALLS. NO EXCUSES."),
    ("spin_doctor", "TABLE TURNER", "THE TABLE SPINS. YOU DON'T."),
    ("speed_demon", "BLINK SPEED", "ONLY 3 CUPS. TOO EASY?"),
    ("encore", "ONE MORE TIME", "WATCH TILL THE END. IT'S A TRAP."),
    ("brain_melt", "GENIUS ONLY", "PROVE YOU'RE NOT A BOT"),
    ("pin_wheel", "BOWLED OVER", "THE LANE SPINS. KEEP UP."),
    ("birth_month", "MONTH CHECK", "IS IT UNDER YOUR MONTH? WATCH."),
    ("city_pride", "WHICH CITY WINS?", "YOUR CITY COULD WIN THIS"),
    ("tricolour", "INDIA'S SHARPEST", "ONLY SHARP EYES GET THIS"),
    ("howzat", "CRICKET CRAZY", "EYES ON THE BALL. LIKE A KEEPER."),
    ("pick_a_side", "RED VS BLUE", "PICK YOUR TEAM NOW. NO SWITCHING."),
    ("dice_trick", "ROLL THE DICE", "REMEMBER THE NUMBER. AND THE CUP."),
    ("count_it", "KEEP COUNT", "COUNT EVERY MOVE. EVERY ONE."),
    ("birth_year", "YEAR CHECK", "IS IT UNDER YOUR DIGIT? WATCH."),
    ("no_spoilers", "HONEST ANSWERS ONLY", "NO REVEAL. NO CHEATING."),
    ("cup_winner", "WORLD CHAMPIONS?", "COMMENT YOUR TEAM BEFORE THE END"),
]

th_split = [
    (T((24, 40, 60), (4, 6, 12), (0, 0, 0), accent=GOLD), [((22, 172, 150), "gold"), ((200, 70, 140), "pink")]),
    (T((50, 24, 64), (8, 4, 12), (0, 0, 0), accent=CYAN), [((150, 96, 230), "cyan"), ((240, 126, 40), "white")]),
    (T((20, 44, 30), (3, 9, 5), (0, 0, 0), accent=LIME), [((80, 200, 90), "lime"), ((60, 110, 230), "gold")]),
    (T((60, 20, 26), (10, 3, 5), (0, 0, 0), accent=GOLD), [((220, 60, 70), "gold"), ((230, 230, 236), "red")]),
]
SPLIT = [
    dict(title="BRAIN SPLIT", hook="TWO GAMES. ONE BRAIN.", t=0, per=3),
    dict(title="HALF AND HALF", hook="WATCH BOTH. NOT JUST ONE.", t=1, per=3),
    dict(title="TWO AT ONCE", hook="YOUR EYES CAN'T BE IN TWO PLACES", t=2, per=3),
    dict(title="MULTITASKER", hook="BET YOU LOSE ONE OF THEM", t=3, per=3),
    dict(title="DUAL CORE", hook="ONLY MULTITASKERS SURVIVE", t=0, per=4, speed=(0.66, 0.46)),
    dict(title="UP AND DOWN", hook="TOP OR BOTTOM? YOU NEED BOTH.", t=1, per=3, speed=(0.56, 0.36)),
    dict(title="BOTH OR NOTHING", hook="ONE RIGHT IS STILL WRONG", t=2, per=4, speed=(0.66, 0.46)),
    dict(title="MIND SPLIT", hook="THE LAST SWAP FOOLS EVERYONE", t=3, per=3, speed=(0.54, 0.34)),
]
SPLIT_CAPS = ["🧠 Two games at the same time. Track BOTH balls and comment both cup numbers 👇",
              "Your brain vs two shuffles at once 😵 Comment top cup AND bottom cup 👇",
              "Most people only follow one. Did you get both? Comment like '2 & 5' 👇",
              "Multitasking test 🔥 Two balls, two games, zero excuses. Both numbers below 👇"]

BLINK_THEMES = dict(night=T((26, 24, 60), (5, 4, 14), (0, 0, 0), accent=GOLD), ghost=T((20, 22, 58), (4, 4, 12), (0, 0, 0), accent=VIOLET),
                    warm=T((60, 36, 20), (10, 6, 3), (0, 0, 0), accent=GOLD), teal=T((16, 56, 64), (3, 10, 12), (0, 0, 0), accent=CYAN))
BLINK = [
    dict(title="STARING CONTEST", item="eye", sub="ONE EYE NEVER BLINKS", th="night", hook="DON'T BLINK FIRST"),
    dict(title="EYE SPY", item="eye", sub="FIND THE ONE THAT NEVER BLINKS", th="teal", hook="WATCH EVERY EYE. ALL OF THEM."),
    dict(title="DOUBLE BLINK", item="eye", mode="twice", sub="ONE EYE BLINKS TWICE", th="night", hook="EVERY EYE BLINKS ONCE. EXCEPT ONE."),
    dict(title="GHOST HOUR", item="ghost", sub="ONE GHOST NEVER DISAPPEARS", th="ghost", hook="THE ENDING WILL GET YOU"),
    dict(title="HAUNTED GRID", item="ghost", sub="WHICH ONE STAYS?", th="ghost", hook="ONE OF THEM IS NOT A GHOST"),
    dict(title="POWER SAVER", item="bulb", sub="ONE BULB NEVER LIGHTS UP", th="warm", hook="WATCH THE WHOLE GRID. NO SHORTCUTS."),
    dict(title="LIGHTS ON", item="bulb", sub="FIND THE DEAD BULB", th="night", hook="ONE BULB IS BROKEN. FIND IT."),
    dict(title="STARGAZER", item="star", sub="ONE STAR NEVER TWINKLES", th="night", hook="EYES ON THE SKY. ALL OF IT."),
    dict(title="SHOOTING STAR", item="star", mode="twice", sub="ONE STAR TWINKLES TWICE", th="teal", hook="EVERY STAR SHINES ONCE. ONE CHEATS."),
    dict(title="NOW YOU SEE ME", item="orb", sub="ONE ORB NEVER VANISHES", th="teal", hook="KEEP WATCHING. IT GETS SNEAKY."),
]
BLINK_CAPS = ["👀 Watch the WHOLE grid. Which one is different? Comment its letter + number (like C4) 👇",
              "Only sharp eyes catch this one. Comment the letter + number 👇 No rewatching!",
              "Your focus vs 42 tiny distractions 🧠 Found it? Drop the letter + number below 👇"]

WANDER = [
    dict(title="TARGET LOCK", n=12, th=T((10, 20, 30), (0, 0, 0), (0, 0, 0), accent=GOLD), ball="cyan", hi="gold", hook="LOCK ON. DON'T LET GO."),
    dict(title="SWARM", n=16, size=62, th=T((30, 14, 40), (5, 2, 8), (0, 0, 0), accent=PINK), ball="blue", hi="pink", hook="16 OF THEM. ONLY 1 MATTERS."),
    dict(title="LOST IN THE CROWD", n=20, size=54, th=T((14, 30, 22), (2, 6, 4), (0, 0, 0), accent=LIME), ball="white", hi="lime", hook="IT BLENDS IN. YOU CAN'T."),
    dict(title="FIREFLIES", n=14, th=T((10, 18, 12), (0, 2, 0), (0, 0, 0), accent=PINK), ball="lime", hi="pink", hook="IT GETS FASTER. STAY WITH IT."),
    dict(title="BUBBLE TROUBLE", n=12, speed=1.25, th=T((12, 34, 60), (2, 6, 12), (0, 0, 0), accent=GOLD), ball="cyan", hi="gold", hook="FAST MODE. NO MERCY."),
    dict(title="PINBALL", n=15, size=60, speed=1.15, th=T((40, 16, 20), (6, 2, 3), (0, 0, 0), accent=CYAN), ball="red", hi="cyan", hook="BET YOU CAN'T KEEP UP"),
]
WANDER_CAPS = ["🎯 One turns gold for 2 seconds, then looks exactly like the rest. Which number was it? 👇",
               "Lock on and don't let go 👀 Which one was it? Comment the number 👇"]


def jobs():
    out = []
    for base, title, hook in CLASSIC:
        out.append(dict(kind="classic", base=base, name=title.lower().replace(" ", "_").replace("'", "").replace("?", "").replace("-", "_"),
                        title=title, hook=hook))
    for i, s in enumerate(SPLIT):
        th, halves = th_split[s["t"]]
        a, b = sg.BALLS, None
        n1, n2 = halves[0][1].upper(), halves[1][1].upper()
        out.append(dict(kind="split", name=s["title"].lower().replace(" ", "_"), title=s["title"], hook=s["hook"], per=s["per"],
                        speed=s.get("speed", (0.62, 0.40)), theme=th, halves=halves,
                        sub=[("TRACK ", None), (n1, th["accent"] if i % 2 == 0 else None), (" AND ", None), (n2, None), (" AT ONCE", None)],
                        caption=SPLIT_CAPS[i % len(SPLIT_CAPS)]))
    for i, b in enumerate(BLINK):
        out.append(dict(kind="blink", name=b["title"].lower().replace(" ", "_"), title=b["title"], item=b["item"], mode=b.get("mode", "never"),
                        sub=b["sub"], theme=BLINK_THEMES[b["th"]], hook=b["hook"], caption=BLINK_CAPS[i % len(BLINK_CAPS)]))
    for i, w in enumerate(WANDER):
        hi = w["hi"].upper()
        out.append(dict(kind="wander", name=w["title"].lower().replace(" ", "_"), title=w["title"], n=w["n"], size=w.get("size", 70),
                        speed=w.get("speed", 1.0), theme=w["th"], ball=w["ball"], hi=w["hi"], hook=w["hook"],
                        q=f"WHICH ONE WAS {hi}?", sub=[("ONE IS ", None), (hi, w["th"]["accent"]), (". DON'T LOSE IT", None)],
                        caption=WANDER_CAPS[i % len(WANDER_CAPS)].replace("gold", w["hi"])))
    # interleave formats so consecutive posts differ
    by = {}
    for j in out: by.setdefault(j["kind"], []).append(j)
    order, keys = [], ["classic", "split", "classic", "blink", "classic", "wander"]
    while any(by.values()):
        for k in keys:
            if by.get(k): order.append(by[k].pop(0))
    for i, j in enumerate(order): j["no"] = i + 1
    return order


def render(job, out_dir, seed):
    if job["kind"] == "classic":
        key = "b50_" + job["name"]
        PRESETS[key] = dict(PRESETS[job["base"]], title=job["title"], hook=job["hook"])
        m = sg.make_video(key, "cupnotic", out_dir, seed)
        m["caption"] = PRESETS[key]["caption"]
    else:
        m = RENDERERS[job["kind"]](job, out_dir, seed)
    src = os.path.join(out_dir, m["file"])
    dst = os.path.join(out_dir, f"{job['no']:02d}_{job['name']}.mp4")
    for ext_src, ext_dst in ((src, dst), (src[:-4] + "_cover.jpg", dst[:-4] + "_cover.jpg"), (src[:-4] + ".json", dst[:-4] + ".json")):
        shutil.move(ext_src, ext_dst)
    m["file"] = os.path.basename(dst); m["hook"] = job["hook"]; m["no"] = job["no"]; m["title"] = job["title"]; m["kind"] = job["kind"]
    import json
    with open(dst[:-4] + ".json", "w", encoding="utf-8") as f: json.dump(m, f, ensure_ascii=False, indent=2)
    return m


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--part", default="1/1"); ap.add_argument("--out", default="batch50"); ap.add_argument("--list", action="store_true")
    ap.add_argument("--only", default=None, help="comma list of numbers")
    ap.add_argument("--no-reveal", action="store_true", help="end on 'comment your answer' instead of showing it")
    a = ap.parse_args()
    J = jobs()
    sg.NO_REVEAL = a.no_reveal
    if a.list:
        for j in J: print(f"{j['no']:02d} {j['kind']:8s} {j['title']:22s} {j['hook']}")
        raise SystemExit
    os.makedirs(a.out, exist_ok=True)
    k, N = map(int, a.part.split("/"))
    sel = [j for j in J if (j["no"] - 1) % N == k - 1]
    if a.only: sel = [j for j in J if str(j["no"]) in a.only.split(",")]
    for j in sel:
        m = render(j, a.out, 5000 + j["no"] * 13)
        print(f"{m['file']:34s} answer={m['answer']}", flush=True)
