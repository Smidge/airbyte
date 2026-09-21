"""Aggregate HTTP measurements for isolated Slack trials. Never log credentials or records."""
import atexit
import collections
import json
import runpy
import threading
import time
from urllib.parse import urlparse

import requests

started = time.monotonic()
counts = collections.Counter()
lock = threading.Lock()
original = requests.adapters.HTTPAdapter.send


def report():
    with lock:
        summary = {"elapsed_seconds": round(time.monotonic() - started, 3), "http": dict(counts)}
    print(json.dumps({"type": "LOG", "log": {"level": "INFO", "message": "SLACK_TRIAL_METRICS " + json.dumps(summary)}}), flush=True)


def measured_send(self, request, **kwargs):
    response = original(self, request, **kwargs)
    parsed = urlparse(request.url)
    if parsed.hostname == "slack.com":
        with lock:
            counts[parsed.path + ":" + str(response.status_code)] += 1
            if response.status_code == 429:
                counts["retry_after_seconds"] += float(response.headers.get("Retry-After", 0))
            try:
                error = response.json().get("error")
                if error in ("not_in_channel", "is_archived", "channel_not_found"):
                    counts[error] += 1
            except (ValueError, AttributeError):
                pass
        report()
    return response


requests.adapters.HTTPAdapter.send = measured_send
atexit.register(report)
runpy.run_path("/airbyte/integration_code/main.py", run_name="__main__")
