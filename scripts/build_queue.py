#!/usr/bin/env python3
"""
Build posts.json (the posting queue) from cupnotic_reels/captions_and_answers.txt.

The "Answer:" lines are dropped so answers never reach the public caption or the repo.
Queue order = the number at the end of each filename (strike_zone_100, golden_egg_201, ...).
Edit posts.json afterwards to reorder or tweak captions.

  python scripts/build_queue.py
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REELS = "cupnotic_reels"
SRC = ROOT / REELS / "captions_and_answers.txt"
OUT = ROOT / "posts.json"

HEADER = re.compile(r"^.+\(\s*([\w\-]+)\.mp4\s*\)\s*$")


def parse(text):
    posts, current, lines = [], None, []

    def flush():
        if current:
            caption = "\n".join(lines).strip()
            posts.append({"id": current, "caption": caption})

    for raw in text.splitlines():
        m = HEADER.match(raw.strip())
        if m:
            flush()
            current, lines = m.group(1), []
        elif current and not raw.strip().lower().startswith("answer:"):
            lines.append(raw.rstrip())
    flush()
    return posts


def main():
    posts = parse(SRC.read_text(encoding="utf-8"))
    queue = []
    for p in posts:
        video = f"{REELS}/{p['id']}.mp4"
        cover = f"{REELS}/covers/{p['id']}_cover.jpg"
        for f in (video, cover):
            if not (ROOT / f).exists():
                sys.exit(f"missing file: {f}")
        if len(p["caption"]) > 2200:
            sys.exit(f"{p['id']}: caption over 2200 chars")
        queue.append({"id": p["id"], "video": video, "cover": cover, "caption": p["caption"]})

    queue.sort(key=lambda q: int(re.search(r"(\d+)$", q["id"]).group(1)))
    OUT.write_text(json.dumps(queue, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {len(queue)} posts to {OUT.name}")


if __name__ == "__main__":
    main()
