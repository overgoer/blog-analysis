#!/usr/bin/env python3
"""
Nightly IMAP checker — triggers gateway command processing.

Reads email via Gmail IMAP, processes any commands from Eddy.
If no commands, exits silently (no tokens wasted).
Cron: daily at 23:00 MSK.

Usage:
  python3 imap_check.py              # check once and exit (for cron)
  python3 imap_check.py --verbose    # print even when no commands
"""

import sys
import os
from pathlib import Path

BASE = Path("/root/blog-analysis/agents/orchestrator")
sys.path.insert(0, str(BASE))

from gateway import check_mail, log

VERBOSE = "--verbose" in sys.argv


def main():
    cmds_processed = check_mail()
    
    if cmds_processed:
        log(f"Nightly IMAP check: processed {len(cmds_processed)} commands")
        print(f"Processed: {cmds_processed}")
    else:
        if VERBOSE:
            log("Nightly IMAP check: no new commands")
        # Silent exit — no tokens wasted


if __name__ == "__main__":
    main()
