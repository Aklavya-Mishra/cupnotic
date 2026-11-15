#!/usr/bin/env python3
"""
Publish the next unposted reel from posts.json to Instagram, then record it in posted.json.

Flow (Instagram Graph API, Facebook Login flavour):
  1. POST /{ig-user-id}/media  media_type=REELS, upload_type=resumable, caption, cover_url
  2. POST rupload.facebook.com/ig-api-upload/{ver}/{container-id}  (video bytes from disk)
  3. poll GET /{container-id}?fields=status_code until FINISHED
  4. POST /{ig-user-id}/media_publish  creation_id=container-id

Env:
  IG_USER_ID         Instagram professional account ID
  IG_ACCESS_TOKEN    long-lived token (system user token recommended)
  MEDIA_BASE_URL     public base URL where repo files are reachable (cover_url is built from it)
  GRAPH_API_VERSION  default v23.0

  python scripts/post_instagram.py            # post next reel
  python scripts/post_instagram.py --dry-run  # show what would be posted
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
QUEUE = ROOT / "posts.json"
STATE = ROOT / "posted.json"

POLL_EVERY_S = 10
POLL_TIMEOUT_S = 15 * 60


def load(path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def next_post():
    queue = load(QUEUE, [])
    done = {p["id"] for p in load(STATE, [])}
    return next((p for p in queue if p["id"] not in done), None), len(queue) - len(done)


def check(resp):
    if not resp.ok:
        sys.exit(f"API error {resp.status_code}: {resp.text}")
    return resp.json()


def publish(post, ig_user, token, ver, base_url):
    graph = f"https://graph.facebook.com/{ver}"
    video = ROOT / post["video"]
    cover_url = base_url.rstrip("/") + "/" + post["cover"]

    # 1. create container
    container = check(requests.post(f"{graph}/{ig_user}/media", data={
        "media_type": "REELS",
        "upload_type": "resumable",
        "caption": post["caption"],
        "cover_url": cover_url,
        "share_to_feed": "true",
        "access_token": token,
    }, timeout=60))["id"]
    print(f"container {container}")

    # 2. upload video bytes
    size = video.stat().st_size
    with video.open("rb") as f:
        up = requests.post(
            f"https://rupload.facebook.com/ig-api-upload/{ver}/{container}",
            headers={"Authorization": f"OAuth {token}", "offset": "0", "file_size": str(size)},
            data=f, timeout=300)
    check(up)
    print(f"uploaded {video.name} ({size} bytes)")

    # 3. wait for processing
    deadline = time.time() + POLL_TIMEOUT_S
    while True:
        st = check(requests.get(f"{graph}/{container}", params={
            "fields": "status_code,status", "access_token": token}, timeout=30))
        code = st.get("status_code")
        print(f"status {code}")
        if code == "FINISHED":
            break
        if code in ("ERROR", "EXPIRED"):
            sys.exit(f"processing failed: {st}")
        if time.time() > deadline:
            sys.exit("processing timed out")
        time.sleep(POLL_EVERY_S)

    # 4. publish
    media_id = check(requests.post(f"{graph}/{ig_user}/media_publish", data={
        "creation_id": container, "access_token": token}, timeout=60))["id"]
    link = check(requests.get(f"{graph}/{media_id}", params={
        "fields": "permalink", "access_token": token}, timeout=30)).get("permalink")
    print(f"published {media_id} {link}")
    return media_id, link


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    post, remaining = next_post()
    if not post:
        sys.exit("queue empty: add reels and rerun scripts/build_queue.py")
    print(f"next: {post['id']} ({remaining} left incl. this one)")

    if args.dry_run:
        print(json.dumps(post, indent=2, ensure_ascii=False))
        return

    env = {k: os.environ.get(k, "") for k in ("IG_USER_ID", "IG_ACCESS_TOKEN", "MEDIA_BASE_URL")}
    missing = [k for k, v in env.items() if not v]
    if missing:
        sys.exit(f"missing env: {', '.join(missing)}")

    media_id, link = publish(post, env["IG_USER_ID"], env["IG_ACCESS_TOKEN"],
                             os.environ.get("GRAPH_API_VERSION", "v23.0"), env["MEDIA_BASE_URL"])

    state = load(STATE, [])
    state.append({"id": post["id"], "media_id": media_id, "permalink": link,
                  "posted_at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    STATE.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
