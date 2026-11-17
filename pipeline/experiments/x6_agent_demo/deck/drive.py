"""Send one request to the running demo and print every step: python drive.py SESSION "prompt" """
import json
import sys
import time
import urllib.request

BASE = "http://localhost:8765"
sid, prompt = sys.argv[1], sys.argv[2]


def call(path, body=None):
    req = urllib.request.Request(BASE + path, data=None if body is None else json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


print(call("/api/chat", {"session": sid, "prompt": prompt}), flush=True)
n, t0 = 0, time.time()
while True:
    r = call(f"/api/events?session={sid}&since={n}")
    for e in r["events"]:
        t = e["type"]
        if t in ("thinking", "text"):
            print(t.upper() + ":", e["text"].replace("\n", " / ")[:1500], flush=True)
        elif t == "tool":
            print("TOOL", e["name"], json.dumps(e["input"], ensure_ascii=False), flush=True)
        elif t == "tool_done":
            print("   ->", "ok" if e["ok"] else "FAILED", e["seconds"], "s:", e["brief"][:300], flush=True)
        elif t == "artifact":
            print("   ART", e["title"], flush=True)
        elif t == "usage":
            print(f"   round {e['round']}: {e['seconds']} s, {e['model']}, in {e['input_tokens']} / out {e['output_tokens']}", flush=True)
        elif t in ("error", "done", "idle", "user"):
            print(t.upper(), e.get("text", "")[:400], flush=True)
    n = r["next"]
    if not r["busy"] and any(e["type"] == "idle" for e in r["events"]):
        break
    if time.time() - t0 > 900:
        print("TIMEOUT")
        break
    time.sleep(2)
print(f"total {time.time() - t0:.0f} s")
