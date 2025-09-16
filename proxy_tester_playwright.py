#!/usr/bin/env python3
import os
import sys
import time
import json
from pathlib import Path
from typing import Optional, Dict, Any

from playwright.sync_api import sync_playwright


PROXIES = [
    "http://9e7b1f639e2da633cdbb:ffe484ea48b9a6e6@74.81.81.81:10000",
    "http://9e7b1f639e2da633cdbb:ffe484ea48b9a6e6@74.81.81.81:10001",
    "http://9e7b1f639e2da633cdbb:ffe484ea48b9a6e6@74.81.81.81:10002",
    "http://9e7b1f639e2da633cdbb:ffe484ea48b9a6e6@74.81.81.81:10003",
    "http://9e7b1f639e2da633cdbb:ffe484ea48b9a6e6@74.81.81.81:10004",
    "http://9e7b1f639e2da633cdbb:ffe484ea48b9a6e6@74.81.81.81:10005",
    "http://9e7b1f639e2da633cdbb:ffe484ea48b9a6e6@74.81.81.81:10006",
    "http://9e7b1f639e2da633cdbb:ffe484ea48b9a6e6@74.81.81.81:10007",
]

OUT_DIR = Path("proxy_tests")
OUT_DIR.mkdir(exist_ok=True)


def test_proxy(p, proxy_url: str) -> Dict[str, Any]:
    result: Dict[str, Any] = {"proxy": proxy_url, "ok": False, "error": None, "ipify": None, "whatismyip": None}
    try:
        browser = p.chromium.launch(
            headless=False,
            channel="chrome",
            proxy={"server": proxy_url},
            args=["--incognito"],
        )
    except Exception as e:
        # fallback to bundled chromium
        try:
            browser = p.chromium.launch(
                headless=False,
                proxy={"server": proxy_url},
                args=["--incognito"],
            )
        except Exception as e2:
            result["error"] = f"launch_failed: {e2}"
            return result

    context = browser.new_context(
        viewport={"width": 1280, "height": 800},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
    )
    page = context.new_page()

    try:
        # ipify first (quick JSON)
        page.goto("https://api.ipify.org?format=json", wait_until="domcontentloaded", timeout=15000)
        txt = page.text_content("body") or "{}"
        data = json.loads(txt)
        result["ipify"] = data.get("ip")
    except Exception as e:
        result["error"] = f"ipify_failed: {e}"

    try:
        page.goto("https://whatismyipaddress.com/", wait_until="domcontentloaded", timeout=20000)
        time.sleep(1.5)
        out_path = OUT_DIR / (proxy_url.split("@")[1].replace(":", "-") + ".png") if "@" in proxy_url else OUT_DIR / "noauth.png"
        page.screenshot(path=str(out_path))
        # try to extract displayed IP if present
        # new site layout: often shows IP inside an element with data-testid or h1/span
        ip_text = None
        candidates = [
            "text=IPv4",
            "h1",
            "div:has-text('IPv4')",
            "[data-testid]",
        ]
        for sel in candidates:
            try:
                t = page.locator(sel).first.inner_text(timeout=1000)
                if t and any(ch.isdigit() for ch in t):
                    ip_text = t
                    break
            except Exception:
                continue
        result["whatismyip"] = ip_text
        result["ok"] = bool(result["ipify"])  # treat ipify success as OK
    except Exception as e:
        result["error"] = (result.get("error") or "") + f"; whatismyip_failed: {e}"
    finally:
        try:
            context.close()
            browser.close()
        except Exception:
            pass

    return result


def main():
    results = []
    with sync_playwright() as p:
        for proxy in PROXIES:
            print(f"Testing proxy: {proxy}")
            r = test_proxy(p, proxy)
            results.append(r)
            print(r)
            time.sleep(1)
    out_file = OUT_DIR / "results.json"
    out_file.write_text(json.dumps(results, indent=2))
    print(f"Saved results to {out_file}")


if __name__ == "__main__":
    main()


