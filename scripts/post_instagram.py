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
  python scripts/post_instagram.py --verify   # full rehearsal, stops before publish
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
# skip the run if the account already posted recently (e.g. a manual post from the app)
MIN_GAP_HOURS = float(os.environ.get("MIN_GAP_HOURS", "12"))


def load(path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def next_post():
    queue = load(QUEUE, [])
    done = {p["id"] for p in load(STATE, [])}
    return next((p for p in queue if p["id"] not in done), None), len(queue) - len(done)


UPLOAD_ATTEMPTS = 3


class ApiError(Exception):
    pass


def check(resp):
    if not resp.ok:
        raise ApiError(f"API error {resp.status_code}: {resp.text}")
    return resp.json()


def hours_since_last_post(ig_user, token, ver):
    """Hours since the newest post on the account (any source, incl. manual), or None."""
    data = check(requests.get(f"https://graph.facebook.com/{ver}/{ig_user}/media", params={
        "fields": "timestamp", "limit": 1, "access_token": token}, timeout=30)).get("data", [])
    if not data:
        return None
    last = datetime.strptime(data[0]["timestamp"], "%Y-%m-%dT%H:%M:%S%z")
    return (datetime.now(timezone.utc) - last).total_seconds() / 3600


def prepare_container(post, ig_user, token, ver, base_url):
    """Create container, upload video, wait until FINISHED. Returns container id."""
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
            raise ApiError(f"processing failed: {st}")
        if time.time() > deadline:
            raise ApiError("processing timed out")
        time.sleep(POLL_EVERY_S)
    return container


def publish(post, ig_user, token, ver, base_url, verify=False):
    graph = f"https://graph.facebook.com/{ver}"

    if verify:
        acct = check(requests.get(f"{graph}/{ig_user}", params={
            "fields": "username", "access_token": token}, timeout=30))
        limit = check(requests.get(f"{graph}/{ig_user}/content_publishing_limit", params={
            "fields": "quota_usage,config", "access_token": token}, timeout=30))
        print(f"account @{acct.get('username')} publishing quota {limit.get('data')}")

    # steps 1-3 retry with a fresh container: Meta's upload endpoint fails transiently
    for attempt in range(1, UPLOAD_ATTEMPTS + 1):
        try:
            container = prepare_container(post, ig_user, token, ver, base_url)
            break
        except (ApiError, requests.RequestException) as e:
            print(f"attempt {attempt}/{UPLOAD_ATTEMPTS} failed: {e}")
            if attempt == UPLOAD_ATTEMPTS:
                raise ApiError(f"upload failed after {UPLOAD_ATTEMPTS} attempts")
            time.sleep(30)

    if verify:
        print(f"VERIFY OK: container {container} ready, NOT published (expires in 24h)")
        return None, None

    # 4. publish
    media_id = check(requests.post(f"{graph}/{ig_user}/media_publish", data={
        "creation_id": container, "access_token": token}, timeout=60))["id"]
    # already live: a failed permalink lookup must not stop posted.json from being saved
    try:
        link = check(requests.get(f"{graph}/{media_id}", params={
            "fields": "permalink", "access_token": token}, timeout=30)).get("permalink")
    except (ApiError, requests.RequestException):
        link = None
    print(f"published {media_id} {link}")
    return media_id, link


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="show next reel, no API calls")
    ap.add_argument("--verify", action="store_true",
                    help="run every API step except media_publish; nothing goes live")
    ap.add_argument("--force", action="store_true",
                    help=f"post even if the account posted within the last {MIN_GAP_HOURS}h")
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

    ver = os.environ.get("GRAPH_API_VERSION", "v23.0")

    if not args.force:
        gap = hours_since_last_post(env["IG_USER_ID"], env["IG_ACCESS_TOKEN"], ver)
        print(f"last post on account: {'none' if gap is None else f'{gap:.1f}h ago'}")
        if args.verify:
            if gap is not None and gap < MIN_GAP_HOURS:
                print("(a real post run would SKIP now)")
        elif gap is not None and gap < MIN_GAP_HOURS:
            print(f"SKIP: account posted {gap:.1f}h ago (< {MIN_GAP_HOURS}h). Use --force to override.")
            return

    media_id, link = publish(post, env["IG_USER_ID"], env["IG_ACCESS_TOKEN"], ver,
                             env["MEDIA_BASE_URL"], verify=args.verify)
    if args.verify:
        return

    state = load(STATE, [])
    state.append({"id": post["id"], "media_id": media_id, "permalink": link,
                  "posted_at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    STATE.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    try:
        main()
    except ApiError as e:
        sys.exit(str(e))
