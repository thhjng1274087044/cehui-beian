#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工程备案上传 runner —— 以 `工程备案_精修.csv` 为队列，驱动 BeianFiller 逐条填报上传。
================================================================================
与房产备案（beian_fill.py --all 消费 beian_ledger）并行且完全独立：

  队列源   = 工程备案_精修.csv（默认只取「待上传(可传)」）
  附件     = V 盘合同 PDF —— 按 CHHTYYYY-NNN / XDL-YYYY-NNN token 解析到实文件
  回写     = 同 CSV 的「上传状态 / 上传备注 / 上传时间」（**不调 mark_uploaded**，
             因为那会按 rec['合同'] 删除源文件，工程备案的源文件在 V 盘归档，绝不能删）
  断点续跑 = beian_gc_progress.json（独立于房产的 beian_progress.json，互不干扰）

复用的通用能力（均已在房产链路上验证）：
  BeianFiller.fill_one_record(record, pdf_path, contract_paths)
      —— 30+ 字段 + 多行「项目类型/金额」+ 保存 + 返回
  BeianFiller.complete_via_modify(...) 中「测绘项目合同或委托书」附件上传 + 参与人员分配
  BeianFiller.is_logged_in() / wait_for_login()  —— 掉线自动暂停等待人工重新登录

用法：
  python beian_gc_runner.py --dry-run --limit=3          # 离线预演，不碰浏览器
  python beian_gc_runner.py --only=XDL-2025-005          # 只跑指定合同号（逗号分隔）
  python beian_gc_runner.py --all                        # 全量跑「待上传(可传)」95 条
  python beian_gc_runner.py --all --include-gap          # 连「缺口暂跳」一起跑（有缺字段风险）
  python beian_gc_runner.py --rebuild-index              # 强制重建 V 盘 PDF 索引
"""
import os
import sys
import csv
import json
import time
import random
import logging
import datetime

HERE = os.path.dirname(os.path.abspath(__file__))

CSV_PATH = os.path.join(HERE, "工程备案_精修.csv")
INDEX_FILE = os.path.join(HERE, "_gc_pdf_index.json")
PROG_FILE = os.path.join(HERE, "beian_gc_progress.json")
LOG_FILE = os.path.join(HERE, "beian_gc_fill.log")

# V 盘合同归档根（只扫这两年的子目录）
V_ROOTS = [
    r"V:\2、合同类归档\1、新大陆测绘合同归档\2025年",
    r"V:\2、合同类归档\1、新大陆测绘合同归档\2026年",
]

QUEUE_READY = "待上传(可传)"
QUEUE_GAP = "待上传(缺口暂跳)"

# ================================================================
#  日志
# ================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ],
)
log = logging.getLogger("gc_runner")


# ================================================================
#  合同号 token ↔ V 盘实文件
# ================================================================
def tokens(s: str):
    """从任意字符串抽出归档号 token：('C',年,序号) / ('X',年,序号)。
    兼容 `（XDL-CHHT-2025-002）XDL-2025-005-项目名.pdf` 与 `XDL-CHHT2025-002.pdf`。"""
    import re
    n = re.sub(r"[^0-9A-Za-z]", "", s or "").upper()
    out = set()
    for m in re.finditer(r"CHHT(\d{4})(\d{3})", n):
        out.add(("C", m.group(1), m.group(2)))
    for m in re.finditer(r"XDL(\d{4})(\d{3})", n):
        out.add(("X", m.group(1), m.group(2)))
    return out


def build_index(rebuild=False):
    """扫描 V 盘归档目录，建 token→实文件路径 索引（缓存到 _gc_pdf_index.json）。"""
    if not rebuild and os.path.exists(INDEX_FILE):
        try:
            idx = json.load(open(INDEX_FILE, encoding="utf-8"))
            if idx.get("roots") == V_ROOTS and idx.get("files"):
                return idx
        except Exception:
            pass

    import glob
    files = []
    for root in V_ROOTS:
        if not os.path.isdir(root):
            log.warning(f"  ⚠️ 归档目录不可达: {root}")
            continue
        files += glob.glob(os.path.join(root, "**", "*.pdf"), recursive=True)
    log.info(f"  📇 V 盘合同 PDF 共 {len(files)} 份，建立 token 索引…")

    tok = {}
    for p in files:
        for t in tokens(os.path.basename(p)):
            # 同一 token 多个文件时，保留路径更短/更靠前的（通常是正本）
            tok.setdefault(t, p)
    idx = {"roots": V_ROOTS, "built_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
           "files": len(files), "tok": {"|".join(k): v for k, v in tok.items()}}
    tmp = INDEX_FILE + ".tmp"
    json.dump(idx, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(tmp, INDEX_FILE)
    log.info(f"  ✅ 索引建成：{len(tok)} 个 token")
    return idx


def resolve_pdf(rec: dict, idx: dict):
    """把 `匹配PDF`（只有文件名）解析成 V 盘绝对路径。返回 (path|None, 说明)。"""
    tok = idx.get("tok") or {}
    cands = []
    if (rec.get("匹配PDF") or "").strip():
        cands.append(("匹配PDF", rec["匹配PDF"]))
    if (rec.get("合同号") or "").strip():
        cands.append(("合同号", rec["合同号"]))
    for src_name, src in cands:
        for t in sorted(tokens(src)):
            p = tok.get("|".join(t))
            if p and os.path.exists(p):
                return p, f"{src_name}>{t[0]}{t[1]}-{t[2]}"
    # 退化：按年份目录里模糊找合同号
    return None, "未解析到实文件"


# ================================================================
#  队列
# ================================================================
def load_rows():
    with open(CSV_PATH, encoding="utf-8-sig", newline="") as f:
        rd = csv.DictReader(f)
        rows = list(rd)
        cols = list(rd.fieldnames or [])
    if "上传时间" not in cols:
        cols.append("上传时间")
    for r in rows:
        r.setdefault("上传时间", "")
    return rows, cols


def save_rows(rows, cols):
    """原子写回 CSV（先写 tmp 再替换，避免中断损坏台账）。"""
    tmp = CSV_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, CSV_PATH)


def save_prog(p):
    p = dict(p)
    p["updated_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    tmp = PROG_FILE + ".tmp"
    json.dump(p, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    os.replace(tmp, PROG_FILE)


# ================================================================
#  主流程
# ================================================================
def main():
    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    include_gap = "--include-gap" in args
    do_all = "--all" in args
    rebuild = "--rebuild-index" in args
    limit = None
    only = set()
    for a in args:
        if a.startswith("--limit="):
            try:
                limit = int(a.split("=", 1)[1])
            except ValueError:
                pass
        elif a.startswith("--only="):
            only = {x.strip() for x in a.split("=", 1)[1].split(",") if x.strip()}
    keep_name = "--keep-filename" in args
    if not (do_all or only or limit):
        log.info("用法：--all | --only=合同号[,合同号] | --dry-run | --limit=N | "
                 "--include-gap | --rebuild-index | --keep-filename")
        return 0

    rows, cols = load_rows()
    idx = build_index(rebuild=rebuild)

    # ---- 组队 ----
    wanted = {QUEUE_READY} | ({QUEUE_GAP} if include_gap else set())
    queue = [r for r in rows if (r.get("上传状态") or "").strip() in wanted]
    if only:
        queue = [r for r in queue if r["合同号"] in only]
    queue.sort(key=lambda r: ((r.get("年份") or ""), r["合同号"]))

    # ---- 附件解析 + 预检 ----
    for r in queue:
        p, why = resolve_pdf(r, idx)
        r["_pdf"], r["_pdf_why"] = p, why
    no_pdf = [r for r in queue if not r["_pdf"]]
    ready = [r for r in queue if r["_pdf"]]
    if no_pdf:
        log.warning(f"  ⚠️ {len(no_pdf)} 条解析不到合同 PDF，跳过："
                    f"{', '.join(r['合同号'] for r in no_pdf[:8])}"
                    f"{' …' if len(no_pdf) > 8 else ''}")
    if limit:
        ready = ready[:limit]

    log.info(f"队列：{len(ready)} 条（状态={'/'.join(sorted(wanted))}"
             f"{'，含缺口' if include_gap else ''}{'，limit=%d' % limit if limit else ''}）")
    if not ready:
        return 0

    # ---- 打印预演 ----
    for i, r in enumerate(ready, 1):
        log.info(f"  [{i}/{len(ready)}] {r['合同号']} | {r.get('委托单位','')[:22]} | "
                 f"金额={r.get('最终金额万元') or r.get('打折后万元') or '(空)'}万 | "
                 f"项目类型={r.get('项目类型_行数','')}行 | PDF={os.path.basename(r['_pdf'])[:44]}")

    filler = None
    if dry_run:
        from beian_fill import BeianFiller
        filler = BeianFiller(dry_run=True)
        # dry-run：只校验表单数据能生成、结构正确
        from beian_form_mapper import generate_form_data
        bad = 0
        for r in ready:
            try:
                fd = generate_form_data(dict(r))
                mr = fd.get("项目类型_多行") or []
                assert isinstance(mr, list) and all("类型" in x and "金额" in x for x in mr), "多行结构错"
                if not any(x["类型"] for x in mr):
                    bad += 1
                    log.warning(f"  ⚠️ {r['合同号']} 项目类型为空")
            except Exception as e:
                bad += 1
                log.error(f"  ❌ {r['合同号']} 表单生成失败: {type(e).__name__}: {e}")
        log.info(f"✅ DRY-RUN 完成：{len(ready)} 条，问题 {bad} 条（未操作浏览器）")
        return 0

    from beian_fill import BeianFiller
    filler = BeianFiller(dry_run=False)

    done = failed = 0
    key = ""
    try:
        for i, r in enumerate(ready):
            key = r["合同号"]
            save_prog({"current_key": key, "current_index": i, "total": len(ready),
                       "done": done, "failed": failed, "state": "running"})
            if not filler.is_logged_in():
                log.warning("  🔒 登录态失效 —— 暂停等待人工重新登录…")
                filler.wait_for_login()

            rec = dict(r)                     # CSV 行字段名与 mapper 期望完全一致
            pdf = r["_pdf"]
            # 附件名规范：网站侧展示名要求为「合同」，且规避中文/超长路径的编码风险
            if not keep_name:
                try:
                    from beian_fill import _prepare_contract_upload_path
                    staged = _prepare_contract_upload_path(pdf)
                    if staged and os.path.exists(staged):
                        r["_pdf_staged"] = staged
                except Exception as e:
                    log.warning(f"  ⚠️ 附件名规范失败，按原名上传: {e}")
            pdf_up = r.get("_pdf_staged") or pdf
            log.info(f"\n######## [{i+1}/{len(ready)}] {key} | {rec.get('委托单位','')[:26]} ########")
            try:
                ok = filler.fill_one_record(rec, pdf_path="", contract_paths=[pdf_up])
            except Exception as e:
                log.error(f"  ❌ 异常: {type(e).__name__}: {e}")
                ok = False

            ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if ok:
                done += 1
                r["上传状态"] = "已上传"
                r["上传备注"] = f"runner {ts} 成功"
            else:
                failed += 1
                r["上传备注"] = f"runner {ts} 失败（状态保持待上传，下次自动重试）"
                log.error(f"  ❌ {key} 未完成")
            r["上传时间"] = ts if ok else r.get("上传时间", "")
            save_rows(rows, cols)             # 逐条回写，断点不丢
            save_prog({"current_key": key, "current_index": i + 1, "total": len(ready),
                       "done": done, "failed": failed, "state": "running"})
            time.sleep(random.uniform(3, 8))  # 条间拟人停顿

        save_prog({"current_key": "", "current_index": len(ready), "total": len(ready),
                   "done": done, "failed": failed, "state": "finished"})
        log.info(f"\n🎉 本批完成：成功 {done} / 失败 {failed} / 共 {len(ready)}")
    except KeyboardInterrupt:
        save_rows(rows, cols)
        save_prog({"current_key": key, "current_index": None, "total": len(ready),
                   "done": done, "failed": failed, "state": "interrupted"})
        log.warning(f"🛑 已中断（已成功 {done} 条）。进度与台账均已保存，重跑自动跳过已上传。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
