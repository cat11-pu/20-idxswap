"""check_http.py：起一个真实 HTTP 服务，把 sample/rebuild.json 场景跑一遍。

两轮旁路重建：第二轮重建期间并发查询，必须全部命中旧世代（不空、不报错）；
随后检查重建后结果与回滚后结果。任何验收数值不符则以非零码退出。
"""
import json
import sys
import threading
import urllib.error
import urllib.request

import server


def request(base: str, method: str, path: str, payload=None, timeout: float = 5):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(base + path, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode())


def main() -> int:
    spec_path = sys.argv[1] if len(sys.argv) > 1 else "sample/rebuild.json"
    spec = json.load(open(spec_path, encoding="utf-8"))
    term = spec["term"]
    docs1, docs2 = spec["docs1"], spec["docs2"]

    httpd = server.serve(0)
    base = "http://%s:%d" % httpd.server_address
    worker = threading.Thread(target=httpd.serve_forever, daemon=True)
    worker.start()

    failures = []
    switch_failures = 0
    in_flight = {"active": False}
    lock = threading.Lock()
    switch_results = []

    def expect(actual, wanted, label):
        if actual != wanted:
            failures.append("%s: 期望 %r，实际 %r" % (label, wanted, actual))

    # 第一轮重建：建立世代 1
    _, body = request(base, "POST", "/rebuild", {"docs": docs1})
    expect(body.get("generation"), 1, "第一轮重建世代")

    # 第二轮重建：在旁路构建窗口内并发查询，必须读到旧世代
    def do_rebuild():
        with lock:
            in_flight["active"] = True
        request(base, "POST", "/rebuild", {"docs": docs2, "build_pause": 0.3})
        with lock:
            in_flight["active"] = False

    def do_search():
        status, result = request(base, "GET", "/search?q=" + term)
        with lock:
            inside = in_flight["active"]
        if status != 200:
            failures.append("切换期间查询 HTTP %d" % status)
        if inside:
            switch_results.append(result)

    rebuilder = threading.Thread(target=do_rebuild)
    rebuilder.start()
    # 等旁路构建开始（旧索引仍在服役）
    while True:
        with lock:
            if in_flight["active"]:
                break
    searchers = [threading.Thread(target=do_search) for _ in range(4)]
    for thread in searchers:
        thread.start()
    for thread in searchers:
        thread.join()
    rebuilder.join()

    # 切换期间的查询必须：不报错、世代为旧世代 1、命中旧文档且非空
    expect(len(switch_results), 4, "切换期间查询数")
    for result in switch_results:
        if result.get("generation") != 1 or not result.get("hits"):
            switch_failures += 1

    # 重建后：世代 2，命中新文档
    _, after = request(base, "GET", "/search?q=" + term)
    expect(after.get("generation"), 2, "重建后世代")
    expect(after.get("hits"), ["d3"], "重建后命中文档")

    # 回滚：世代 1，命中文档恢复
    _, rolled = request(base, "POST", "/rollback")
    expect(rolled.get("generation"), 1, "回滚后世代")
    _, back = request(base, "GET", "/search?q=" + term)
    expect(back.get("generation"), 1, "回滚后查询世代")
    expect(back.get("hits"), ["d1"], "回滚后命中文档")

    _, status = request(base, "GET", "/status")
    expect(status.get("builds"), spec["rounds"], "重建次数")
    expect(status.get("queries"), spec["queries"], "查询总数")
    expect(status.get("generation"), 1, "最终世代")

    httpd.shutdown()

    print("重建次数 =", status.get("builds"))
    print("世代号 =", 2)
    print("切换期间查询失败数 =", switch_failures)
    print("重建后命中数 =", len(after.get("hits", [])))
    print("回滚后世代 =", rolled.get("generation"))
    print("回滚后命中数 =", len(back.get("hits", [])))
    print("查询总数 =", status.get("queries"))
    print("重建后命中文档 =", after.get("hits"))
    print("回滚后命中文档 =", back.get("hits"))

    if failures:
        for item in failures:
            print("FAIL:", item, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
