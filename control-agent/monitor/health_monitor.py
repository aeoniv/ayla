#!/usr/bin/env python3
"""Ayla control-agent — read-only health monitor.

Long-running process. Polls each service's /healthz on an interval and DMs the
owner after N consecutive failures. Recovery is also reported. This process is
STRICTLY READ-ONLY: it has no ability to restart, deploy, or mutate anything —
it only performs HTTP GETs and sends Telegram messages. Stdlib only, no deps.

State (consecutive-failure counts) is kept in memory, so run it as a persistent
service (e.g. systemd), not as a cron job.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request

POLL_INTERVAL = int(os.environ.get("POLL_INTERVAL", "300"))   # 5 min
FAIL_THRESHOLD = int(os.environ.get("FAIL_THRESHOLD", "2"))    # 2 consecutive
HTTP_TIMEOUT = int(os.environ.get("HTTP_TIMEOUT", "10"))
BOT_TOKEN = os.environ.get("CONTROL_BOT_TOKEN", "")
OWNER_CHAT_ID = os.environ.get("OWNER_CHAT_ID", "")


def _services() -> list[dict]:
    """SERVICES is a JSON array of {name, url}. Blank/missing entries skipped.

    coaching-agent-service is Phase 5 — leave its url blank until deployed and
    the monitor simply won't poll it.
    """
    raw = os.environ.get("SERVICES", "[]")
    out = []
    for s in json.loads(raw):
        if s.get("url"):
            out.append({"name": s["name"], "url": s["url"].rstrip("/") + "/healthz"})
    return out


def send_dm(text: str) -> None:
    if not BOT_TOKEN or not OWNER_CHAT_ID:
        print(f"[alert-not-sent: no bot config] {text}", file=sys.stderr)
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = json.dumps({"chat_id": OWNER_CHAT_ID, "text": text}).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=HTTP_TIMEOUT).read()
    except Exception as e:  # never let alerting crash the monitor
        print(f"[alert-failed] {e}: {text}", file=sys.stderr)


def check(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=HTTP_TIMEOUT) as resp:
            if resp.status != 200:
                return False
            body = json.loads(resp.read() or b"{}")
            return body.get("status") == "ok"
    except Exception:
        return False


def main() -> None:
    services = _services()
    if not services:
        print("no SERVICES configured; nothing to monitor", file=sys.stderr)
    fails: dict[str, int] = {s["name"]: 0 for s in services}
    alerted: dict[str, bool] = {s["name"]: False for s in services}
    print(f"monitor start: {len(services)} services, every {POLL_INTERVAL}s, "
          f"threshold {FAIL_THRESHOLD}")

    while True:
        for s in services:
            ok = check(s["url"])
            name = s["name"]
            if ok:
                if alerted[name]:
                    send_dm(f"✅ Ayla: {name} recovered ({s['url']}).")
                fails[name] = 0
                alerted[name] = False
            else:
                fails[name] += 1
                if fails[name] >= FAIL_THRESHOLD and not alerted[name]:
                    send_dm(
                        f"🚨 Ayla: {name} DOWN — {fails[name]} consecutive "
                        f"failed health checks ({s['url']})."
                    )
                    alerted[name] = True
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
