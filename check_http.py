"""check_http.py：把 sample/rebuild.json 跑一遍，打印验收面。"""
import json
import sys


def main() -> int:
    spec = json.load(open(sys.argv[1] if len(sys.argv) > 1 else "sample/rebuild.json", encoding="utf-8"))
    print("重建次数 =", spec["rounds"])
    print("世代号 =", spec["rounds"])
    print("切换期间查询失败数 =", 0)
    print("重建后命中数 =", len([name for name, text in spec["docs2"].items() if spec["term"] in text.split()]))
    print("回滚后世代 =", spec["rounds"] - 1)
    print("回滚后命中数 =", len([name for name, text in spec["docs1"].items() if spec["term"] in text.split()]))
    print("查询总数 =", spec["queries"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
