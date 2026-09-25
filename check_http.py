"""check_http.py：启动本机 HTTP 服务，按 sample/rebuild.json 跑重建/回滚验收。"""
import json
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_ready(base: str, proc: subprocess.Popen, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError("server exited early: %s" % proc.stderr.read())
        try:
            with urllib.request.urlopen(base + "/status", timeout=0.5) as resp:
                if resp.status == 200:
                    return
        except (OSError, urllib.error.URLError):
            time.sleep(0.05)
    raise RuntimeError("server not ready within %ss" % timeout)


def _request(base: str, method: str, path: str, payload=None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(base + path, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=5) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def _names(hits) -> list:
    if hits and isinstance(hits[0], dict):
        return [item.get("name") for item in hits]
    return list(hits)


def main() -> int:
    spec_path = sys.argv[1] if len(sys.argv) > 1 else "sample/rebuild.json"
    spec = json.load(open(spec_path, encoding="utf-8"))
    term, rounds = spec["term"], spec["rounds"]

    port = _free_port()
    base = "http://127.0.0.1:%d" % port
    proc = subprocess.Popen(
        [sys.executable, "server.py", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        _wait_ready(base, proc)

        # 第 1 次重建：建立世代 1（docs1）
        _request(base, "POST", "/rebuild", {"docs": spec["docs1"]})

        # 第 2 次重建期间并发查询，旧世代必须始终可用（不空、不报错）
        failures = 0

        def query_worker() -> None:
            nonlocal failures
            try:
                status, result = _request(base, "GET", "/search?q=" + term)
                if status != 200 or not result.get("hits"):
                    failures += 1
            except (OSError, urllib.error.URLError, ValueError):
                failures += 1

        workers = [threading.Thread(target=query_worker) for _ in range(rounds * 2)]
        for worker in workers:
            worker.start()
        time.sleep(0.1)
        _request(base, "POST", "/rebuild", {"docs": spec["docs2"]})
        for worker in workers:
            worker.join()

        _, after = _request(base, "GET", "/search?q=" + term)
        generation_after_rebuild = after["generation"]
        _, rolled = _request(base, "POST", "/rollback")
        rollback_generation = rolled["generation"]
        _, before = _request(base, "GET", "/search?q=" + term)
        _, status = _request(base, "GET", "/status")

        rebuild_count = status["builds"]
        generation = generation_after_rebuild
        after_names = _names(after["hits"])
        before_names = _names(before["hits"])
        query_total = status["queries"]
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

    print("重建次数 =", rebuild_count)
    print("世代号 =", generation)
    print("切换期间查询失败数 =", failures)
    print("重建后命中数 =", len(after_names))
    print("回滚后世代 =", rollback_generation)
    print("回滚后命中数 =", len(before_names))
    print("查询总数 =", query_total)
    print("重建后命中文档 =", after_names)
    print("回滚后命中文档 =", before_names)

    checks = {
        "重建次数": rebuild_count == rounds,
        "世代号": generation == rounds,
        "切换期间查询失败数": failures == 0,
        "重建后命中数": len(after_names) == 1,
        "回滚后世代": rollback_generation == rounds - 1,
        "回滚后命中数": len(before_names) == 1,
        "查询总数": query_total == spec["queries"],
        "重建后命中文档": after_names == ["d3"],
        "回滚后命中文档": before_names == ["d1"],
    }
    failed = [name for name, ok in checks.items() if not ok]
    if failed:
        print("验收失败：%s" % "、".join(failed), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
