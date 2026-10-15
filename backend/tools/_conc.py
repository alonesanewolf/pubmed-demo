"""临时：服务器本机并发对照测试（跑完即删）"""
import concurrent.futures
import time
import urllib.request


def hit(url):
    t0 = time.perf_counter()
    with urllib.request.urlopen(url, timeout=20) as r:
        r.read()
    return round(time.perf_counter() - t0, 3)


for label, url in [
    ("uvicorn-direct x8", "http://127.0.0.1:8000/api/health"),
    ("via-nginx     x8", "http://127.0.0.1:5300/api/health"),
    ("dataset       x4", "http://127.0.0.1:8000/api/datasets/crispr-gene-editing"),
]:
    with concurrent.futures.ThreadPoolExecutor(8) as ex:
        res = sorted(ex.map(hit, [url] * 8))
    print(f"{label}: {res}")
