#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
提取进程（独立运行，可常驻后台）
=================================
扫描网络盘房测报告PDF → 同步本地缓存 → N次一致性提取 + 字段规则校验
→ 写台账(beian_records.json)作为「上传队列」。

与上传进程(beian_fill.py --all)通过台账两个字段协作，互不阻塞浏览器：
  extract_status : 本进程写入  ok / verify_failed / rule_failed
  status         : 上传进程写入  pending / done / failed

用法:
  python beian_extract_worker.py --root "W:/2020备案"        # 单次全量扫描
  python beian_extract_worker.py --root "W:/2020备案" --loop # 持续轮询新文件
  python beian_extract_worker.py --verify 3                  # 每份提取3次交叉比对
  python beian_extract_worker.py --retry                     # 重提 verify/rule 失败条
"""
import os, re, sys, time, datetime, glob, argparse
import beian_ledger as L
import beian_config as _cfg

def scan_pdfs(root):
    """扫描所有房测报告PDF（文件名含'房测报告'）。"""
    return sorted(glob.glob(os.path.join(root, "**", "*房测报告*.pdf"), recursive=True))

def filename_report_no(pdf):
    """从文件名推断报告编号，用于增量跳过（无需打开PDF）。"""
    m = re.search(r"([A-Za-z]{2,}\d{6,})", os.path.basename(pdf))
    return m.group(1) if m else os.path.splitext(os.path.basename(pdf))[0]

def extract_one(pdf, verify_n, pages):
    """单份：网络盘轻量定位合同 → 同步缓存 → 缓存N次验证提取。"""
    rel = os.path.relpath(pdf, L.ROOT)
    # 1) 网络盘轻量解析，先拿到合同相对路径
    tmp = L.extract_record(pdf, rel, pages, True, use_cache_dir=False)
    contract_rels = tmp.get("合同", [])
    # 2) 同步 PDF + 合同到本地缓存（去 SMB 抖动）
    cache_pdf = L.sync_cache([pdf])[0]
    if contract_rels:
        L.sync_cache([], extra_rels=contract_rels)
    # 3) 在缓存上做 N 次提取 + 一致性 + 规则校验
    rec, consistent, rule_issues, diffs = L.extract_with_verify(
        cache_pdf, rel, n=verify_n, max_pages=pages, use_cache_dir=True)
    # 4) 把路径改写为缓存绝对路径（上传进程直接 exists 通过，无需再扫网络盘）
    rec["source_pdf"] = cache_pdf
    rec["合同"] = [os.path.join(L.CACHE, c) for c in contract_rels]
    # 5) 判定提取状态
    if not consistent:
        rec["extract_status"] = "verify_failed"
    elif rule_issues:
        rec["extract_status"] = "rule_failed"
    else:
        rec["extract_status"] = "ok"
    rec["extract_detail"] = {
        "consistent": consistent,
        "rule_issues": rule_issues,
        "diffs": diffs,
    }
    return rec

def run(root, verify_n=2, pages=L.MAX_PAGES, retry=False, oneshot=True, loop_interval=300):
    L.ROOT = root  # 让 relpath / 合同定位与扫描根一致
    loop = not oneshot
    while True:
        print(f"[提取] 扫描 PDF: {root} ...", flush=True)
        t0 = time.time()
        pdfs = scan_pdfs(root)
        print(f"[提取] 找到 {len(pdfs)} 份，用时 {time.time()-t0:.0f}s", flush=True)
        ledger = L.load_ledger()
        # ok_keys 基于 extract_status；上传进程只写独立 upload_log，不改台账，故内存判断安全
        ok_keys = {k for k, v in ledger.items() if v.get("extract_status") == "ok"}
        try:
            uploaded = set(L.load_upload_log().keys())
        except Exception:
            uploaded = set()
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        new = skipped = failed = 0
        todo = []
        for pdf in pdfs:
            fkey = filename_report_no(pdf)
            existing = ledger.get(fkey)
            if fkey in ok_keys or fkey in uploaded:
                skipped += 1
                continue
            if existing and existing.get("extract_status") in ("verify_failed", "rule_failed") and not retry:
                skipped += 1
                continue
            todo.append(pdf)
        print(f"[提取] 需处理 {len(todo)} 份（跳过已OK/已上传 {skipped}）", flush=True)
        for i, pdf in enumerate(todo, 1):
            fkey = filename_report_no(pdf)
            print(f"  [{i}/{len(todo)}] {fkey}  {os.path.basename(pdf)}", flush=True)
            try:
                rec = extract_one(pdf, verify_n, pages)
            except Exception as e:
                print(f"  FAIL 提取异常 {fkey}: {e}", flush=True)
                failed += 1
                continue
            key = rec["report_no"] or fkey
            rec["last_updated"] = now
            # 原子写台账（提取进程独占写；上传进程只读台账+独立日志，零冲突）
            prev = ledger.get(key, {})
            rec["first_seen"] = prev.get("first_seen") or now
            rec["status"] = prev.get("status", "pending") if key == fkey else "pending"
            ledger[key] = rec
            L.save_ledger(ledger)
            if rec["extract_status"] == "ok":
                new += 1
                print(f"    OK  委托方={rec.get('委托方','')} 面积={rec.get('建筑面积','')}", flush=True)
            else:
                failed += 1
                print(f"  WARN {key} 提取状态={rec['extract_status']} 问题={rec['extract_detail']}", flush=True)
        L.build_xlsx(ledger)
        print(f"[提取] 扫描{len(pdfs)}份 | 新增OK {new} | 跳过 {skipped} | 异常/待处理 {failed} | 台账{len(ledger)}条", flush=True)
        if not loop:
            break
        print(f"  ... 休眠 {loop_interval}s 后继续轮询（Ctrl+C 退出）", flush=True)
        time.sleep(loop_interval)

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=_cfg.CFG.get("root", r"W:/2020备案"), help="扫描根目录（网络盘）")
    ap.add_argument("--verify", type=int, default=2, help="每份提取次数做一致性比对")
    ap.add_argument("--pages", type=int, default=L.MAX_PAGES)
    ap.add_argument("--retry", action="store_true", help="重提 verify/rule 失败条")
    ap.add_argument("--loop", action="store_true", help="持续轮询新文件")
    ap.add_argument("--interval", type=int, default=300, help="--loop 轮询间隔秒")
    args = ap.parse_args()
    try:
        run(args.root, args.verify, args.pages, args.retry,
            oneshot=not args.loop, loop_interval=args.interval)
    except KeyboardInterrupt:
        print("\n提取进程已退出")
