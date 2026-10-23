# -*- coding: utf-8 -*-
"""
测绘备案 · 环境一键自检

用途：任何 AI / 操作人员接手备案任务时，先跑这一条，就知道能不能开工。
用法：
    "C:\\Program Files\\Python312\\python.exe" precheck.py

退出码：
    0 = 就绪，可以跑 beian_fill.py
    2 = 未就绪，看输出里标 [X] 的那项

本脚本只读，不改任何台账、不启动浏览器、不操作政府网站。
"""
import io
import json
import os
import socket
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
CDP_PORT = 9333
CDP_HOST = "127.0.0.1"

results = []


def add(name, ok, detail, fix=""):
    results.append({"name": name, "ok": ok, "detail": detail, "fix": fix})


# ---------- 1. 解释器与依赖 ----------
def check_deps():
    ver = "%d.%d.%d" % sys.version_info[:3]
    missing = []
    for mod in ("playwright", "fitz", "openpyxl", "pdfplumber"):
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)
    if missing:
        add("依赖", False, "Python %s 缺 %s" % (ver, ", ".join(missing)),
            '换解释器：C:\\Program Files\\Python312\\python.exe')
    else:
        add("依赖", True, "Python %s，playwright/fitz/openpyxl/pdfplumber 齐全" % ver)


# ---------- 2. CDP 端口 ----------
def cdp_alive():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(1.5)
    try:
        s.connect((CDP_HOST, CDP_PORT))
        return True
    except Exception:
        return False
    finally:
        s.close()


def check_cdp():
    if cdp_alive():
        add("Chrome CDP", True, "端口 %d 在监听" % CDP_PORT)
        return True
    add("Chrome CDP", False, "端口 %d 无响应（Chrome 未启动或被回收）" % CDP_PORT,
        "让人双击 start_chrome.bat（不能由 AI 后台拉起）")
    return False


# ---------- 3. 登录态 ----------
def check_login():
    """
    直接走 CDP HTTP 接口查页面 URL 与 input[type=password] 是否存在，
    不依赖 playwright，未启动时也不会抛长 traceback。
    """
    import urllib.request
    try:
        with urllib.request.urlopen(
            "http://%s:%d/json/list" % (CDP_HOST, CDP_PORT), timeout=3
        ) as r:
            tabs = json.loads(r.read().decode("utf-8", "ignore"))
    except Exception as e:
        add("登录态", False, "查不到 CDP 页面列表：%s" % type(e).__name__,
            "先启动 start_chrome.bat")
        return

    pages = [t for t in tabs if t.get("type") == "page"]
    target = None
    for t in pages:
        if "zrzyt.zj.gov.cn" in (t.get("url") or ""):
            target = t
            break
    if not target:
        add("登录态", False, "没有打开备案网站的标签页（现有 %d 个页面）" % len(pages),
            "在 Chrome 里打开 https://hyjg.zrzyt.zj.gov.cn/main.htm")
        return

    url = target.get("url") or ""
    # 连的是 CDP 的 HTTP 端口，要拿 DOM 得用 ws；这里用轻量判据：
    # 备案站登录后在业务页，未登录会停在登录页
    if "login" in url.lower():
        add("登录态", False, "当前停在登录页 %s" % url[:80],
            "人工输账号+密码+图形验证码登录")
    else:
        add("登录态", True, "已进入业务页 %s" % url[:80])


# ---------- 4. 台账与队列 ----------
def load_json(name):
    p = os.path.join(HERE, name)
    with io.open(p, encoding="utf-8") as f:
        return json.load(f)


def check_ledger():
    try:
        ledger = load_json("beian_records.json")
        log = load_json("beian_upload_log.json")
    except Exception as e:
        add("台账", False, "读不到台账：%s" % e, "部署包不完整，先问人")
        return

    try:
        skip_names = set(load_json("beian_skip_names.json").get("names", []))
    except Exception:
        skip_names = set()

    total = len(ledger)
    uploaded = len(log)
    named = nocontract = pending = 0
    for k, v in ledger.items():
        if v.get("extract_status") in ("verify_failed", "rule_failed"):
            continue
        if k in log:
            continue
        name = str(v.get("委托方") or "")
        if any(s in name for s in skip_names):
            named += 1
            continue
        cts = v.get("合同") or []
        if not (cts and os.path.exists(cts[0])):
            nocontract += 1
            continue
        if v.get("status") == "pending" and v.get("extract_status") in (None, "ok"):
            pending += 1

    add("台账", True,
        "总数 %d / 已传 %d / 免备案跳过 %d / 无合同跳过 %d => 待传 %d 条"
        % (total, uploaded, named, nocontract, pending))

    if pending:
        hours = pending * 100 / 3600.0
        logins = (pending + 139) // 140
        add("排期", True,
            "约 %.0f 小时纯跑 + %d 次重新登录（登录态 4 小时/次）" % (hours, logins))


def main():
    print("=" * 62)
    print(" 测绘备案 · 环境自检")
    print(" 目录:", HERE)
    print("=" * 62)

    check_deps()
    alive = check_cdp()
    if alive:
        check_login()
    else:
        add("登录态", False, "跳过（Chrome 未启动）", "先双击 start_chrome.bat")
    check_ledger()

    print()
    bad = 0
    for r in results:
        flag = "[OK]" if r["ok"] else "[X] "
        print("%s %-10s %s" % (flag, r["name"], r["detail"]))
        if not r["ok"]:
            bad += 1
            if r.get("fix"):
                print("     ->", r["fix"])

    print()
    if bad == 0:
        print("结论：就绪。可以跑 beian_fill.py --all --dry-run 看队列。")
        print("=" * 62)
        return 0
    print("结论：未就绪，有 %d 项待处理（标 [X] 的）。" % bad)
    print("=" * 62)
    return 2


if __name__ == "__main__":
    sys.exit(main())
