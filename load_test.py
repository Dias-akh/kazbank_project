import json
import urllib.request
from concurrent.futures import ThreadPoolExecutor

BASE = "http://127.0.0.1:5001"


def get(path):
    with urllib.request.urlopen(BASE + path) as r:
        return r.status


def post(path, body):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def job(i):
    if i % 2 == 0:
        return "GET /customers", get("/customers")
    src, dst = (1, 3) if i % 4 == 1 else (3, 1)
    return f"POST /transfer {src}->{dst}", post(
        "/transfer", {"from_account": src, "to_account": dst, "amount": 100}
    )


with ThreadPoolExecutor(max_workers=20) as ex:
    results = list(ex.map(job, range(20)))

for name, status in results:
    print(status, name)

with urllib.request.urlopen(BASE + "/health") as r:
    print(json.dumps(json.load(r), indent=2))