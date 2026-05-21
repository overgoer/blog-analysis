#!/usr/bin/env python3
"""Content Analyzer — main pipeline. Runs nightly via cron."""
import time, sys
from datetime import date

sys.path.insert(0, "/root/blog-analysis/agents/content_analyzer")

from db import init_db, ensure_channels, get_channel_by_name, get_posts_for_analysis
from config import DEFAULT_CHANNELS
from scraper import scrape_channel
from insights import analyze_channel
from reporter import build_daily_report, save_report


def run():
    print(f"[{date.today()}] Content Analyzer — start")

    # Phase 0: Init
    init_db()
    ensure_channels(DEFAULT_CHANNELS)
    channels = [get_channel_by_name(c) for c in DEFAULT_CHANNELS]
    channels = [c for c in channels if c and c["active"]]
    print(f"[Phase 0] OK: {len(channels)} channels")

    # Phase 1: Scrape
    t0 = time.time()
    total_new = 0
    for ch in channels:
        try:
            new, total = scrape_channel(ch["name"])
            total_new += new
            print(f"  {ch['name']}: +{new} new, {total} total")
        except Exception as e:
            print(f"  {ch['name']}: ERROR — {e}")
    print(f"[Phase 1] Done: {total_new} new posts, {time.time()-t0:.1f}s")

    # Phase 2: Classify + insight
    t0 = time.time()
    total_notable = 0
    for ch in channels:
        try:
            posts = get_posts_for_analysis(ch["id"], limit=50)
            notable = analyze_channel(ch["id"], ch["name"], posts)
            total_notable += len(notable)
        except Exception as e:
            print(f"  {ch['name']}: insight error — {e}")
    print(f"[Phase 2] Done: {total_notable} notable, {time.time()-t0:.1f}s")

    # Phase 3: Report
    t0 = time.time()
    report = build_daily_report()
    fpath = save_report(report)
    print(f"[Phase 3] Report saved to {fpath}, {time.time()-t0:.1f}s")

    print(f"[{date.today()}] Content Analyzer — done")


if __name__ == "__main__":
    run()
