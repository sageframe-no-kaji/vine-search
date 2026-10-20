"""In-container health check without credentials in process arguments."""

import os
import sys
import urllib.request

role = sys.argv[1]
port = 8766 if role == "collector" else 8765
headers = (
    {"X-Collector-Secret": os.environ["VINE_SEARCH_COLLECTOR_SECRET"]}
    if role == "collector"
    else {}
)
request = urllib.request.Request(f"http://127.0.0.1:{port}/health", headers=headers)
with urllib.request.urlopen(request, timeout=4) as response:
    if response.status != 200:
        raise SystemExit(1)
