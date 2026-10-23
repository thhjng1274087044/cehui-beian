#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
备案登记台账 + 去重 + 合同附件 + 上传后清理模块
==============================================
提取(房测报告字段) → 定位合同附件 → 去重 → 填表上传 → 成功后删本地文件只留标记

加速策略（经基准测试验证）:
  1. 只提取前 MAX_PAGES 页（诊断确认：1月份47份字段100%落在前6页）
  2. 解析引擎 PyMuPDF(fitz) get_text(sort=True) —— 本地解析亚秒级
  3. 本地缓存层：网络盘 PDF/合同 按修改时间增量同步到 .pdf_cache，去 SMB+Defender 抖动
  4. 兜底：关键字段缺失 → 自动回退全量提取该份

【合同附件】
  合同是图片(合同*.jpg)，与房测报告同目录(人名子目录)，一一对应；少数项目多份(出让合同1~n)
  extract 阶段定位合同相对路径；sync 阶段同步到缓存；上传后随房测报告一起删除

【上传后清理 — 防数据库/磁盘爆】
  mark <no> 标记为「已登记(done)」时，自动删除 .pdf_cache 中该条的
  房测报告PDF + 全部合同图片，台账仅保留 报告编号 + 状态 + 字段摘要(供核对)
  → 下次重跑：done 条直接跳过，绝不重复登记，也不重新下载

用法:
    python beian_ledger.py                      # 扫描+去重+写台账+生成Excel（默认开缓存）
    python beian_ledger.py --pages 6            # 指定提取前N页
    python beian_ledger.py --no-cache           # 不走缓存，直接读网络盘
    python beian_ledger.py --local              # 纯本地模式：不碰网络盘，只跑缓存(亚秒级)
    python beian_ledger.py --workers 4          # 大批量(数百份+)开启多进程
    python beian_ledger.py stats                # 打印台账统计
    python beian_ledger.py mark XH202312059     # 标记「已登记」并删除本地文件(只留标记)
    python beian_ledger.py unmark XH202312059   # 撤销(变回待登记，下次重跑会重新下载)
    python beian_ledger.py fail XH202312059     # 标记「登记失败」
"""
import re, os, glob, json, sys, datetime, shutil, time, contextlib
from openpyxl import Workbook
import beian_config as _cfg

# 数据源根（部署时由 config.json 的 "root" 覆盖；离线包用缓存即可，无需此盘）
ROOT    = _cfg.CFG.get("root", r"W:/2020备案")
# 台账 / Excel / 缓存：全部来自 config，自动相对部署根解析
LEDGER = _cfg.LEDGER_PATH
XLSX   = _cfg.XLSX_PATH
CACHE  = _cfg.CACHE_PATH
MAX_PAGES = 6   # 诊断确定：前6页覆盖100%字段；其他月份模板若页码变化，靠 fallback 兜底

# ---- 解析引擎选择：优先 PyMuPDF，缺失则 pdfplumber ----
ENGINE = "fitz"
try:
    import pymupdf as _fitz
except ImportError:
    try:
        import fitz as _fitz
    except ImportError:
        ENGINE = "pdfplumber"
        import pdfplumber

CN = {'零':0,'〇':0,'一':1,'二':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9,
      '十':10,'百':100,'千':1000,'○':0,'０':0,'１':1,'２':2,'３':3,'４':4,'５':5,'６':6,'７':7,'８':8,'９':9}
def cn_num(s):
    s=s.strip()
    if re.fullmatch(r'\d+', s): return int(s)
    total=0; cur=0
    for ch in s:
        if ch in '十百千':
            unit=CN[ch]; cur=(cur if cur else 1)*unit; total+=cur; cur=0
        elif ch in CN: cur=CN[ch]
        else: break
    return total+cur
def cn_to_digits(s):
    out=""
    for ch in s:
        if ch in CN: out += str(CN[ch])
        elif ch.isdigit(): out += ch
    return out
def cn_date(s):
    m=re.search(r'([零〇一二三四五六七八九十百千○０-９\d]+)年\s*([零〇一二三四五六七八九十○０-９\d]+)月\s*([零〇一二三四五六七八九十○０-９\d]+)日', s)
    if not m: return None
    y=cn_to_digits(m.group(1)); mo=cn_num(m.group(2)); d=cn_num(m.group(3))
    try: return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
    except: return None

def parse_fields(rec, text):
    """把文本中的字段解析写入 rec（仅填值，不覆盖已有）"""
    m=re.search(r'编号\s*[:：]\s*([A-Za-z]{2,}\d{6,})', text);        rec["report_no"]=rec.get("report_no") or (m.group(1) if m else "")
    m=re.search(r'委\s*托\s*方\s*[:：]\s*([^\n]{1,30}?)\s*(?:\n|$)', text); rec["委托方"]=rec.get("委托方") or (m.group(1).strip() if m else "")
    m=re.search(r'项目名称\s*[:：]\s*([^\n]{1,30}?)\s*(?:\n|$)', text);         rec["项目名称"]=rec.get("项目名称") or (m.group(1).strip() if m else "")
    m=re.search(r'总建筑面积[\s:：]{0,60}?([0-9]+(?:\.[0-9]+)?)', text);         rec["总建筑面积"]=rec.get("总建筑面积") or (m.group(1) if m else "")
    m=re.search(r'施测时间\s*[:：]\s*([0-9]{4}年[0-9]{1,2}月[0-9]{1,2}日)', text)
    if not m: m=re.search(r'施测日期\s*[:：]\s*([0-9]{4}年[0-9]{1,2}月[0-9]{1,2}日)', text)
    if m: rec["施测日期"]=rec.get("施测日期") or m.group(1)
    else:
        m=re.search(r'测绘日期\s*[:：]\s*([^\n]{4,40}?日)', text)
        if m: rec["施测日期"]=rec.get("施测日期") or (cn_date(m.group(1)) or m.group(1))
    m=re.search(r'房屋座落\s*[:：]\s*([^\n]{2,40}?)\s*(?:\n|$)', text);         rec["房屋座落"]=rec.get("房屋座落") or (m.group(1).strip() if m else "")
    m=re.search(r'测绘单位\s*[:：]\s*([^\n]{2,40}?)\s*(?:\n|$)', text);         rec["测绘单位"]=rec.get("测绘单位") or (m.group(1).strip() if m else "")
    return rec

def _pdf_text(path, max_pages):
    """返回 (text, total_pages)，只取前 max_pages 页"""
    if ENGINE == "fitz":
        doc=_fitz.open(path)
        np=doc.page_count
        n=min(np, max_pages)
        parts=[doc.load_page(i).get_text("text", sort=True) for i in range(n)]
        doc.close()
        return "\n".join(parts), np
    else:
        with pdfplumber.open(path) as pdf:
            np=len(pdf.pages)
            n=min(np, max_pages)
            parts=[pdf.pages[i].extract_text() or "" for i in range(n)]
            return "\n".join(parts), np

def _contract_stem_norm(stem: str) -> str:
    """去掉末尾「 (2)」「（2）」编号，便于匹配「合同 (2)」/「李贤华合同 (2)」。"""
    return re.sub(r"\s*[\(（]\d+[\)）]\s*$", "", (stem or "").strip()).strip()


def _score_contracts_in_dir(base_dir):
    """在单个目录内按规则打分找合同，返回 scored 列表或 []。"""
    BAD = ("出让", "测绘", "施工", "规划", "用地")
    IMG = {".jpg", ".jpeg", ".png"}
    OK_EXT = IMG | {".pdf"}
    scored = []  # (priority, ext_rank, namelen, path)
    if not os.path.isdir(base_dir):
        return scored
    for fn in os.listdir(base_dir):
        stem, ext = os.path.splitext(fn)
        ext_l = ext.lower()
        if ext_l not in OK_EXT:
            continue
        if any(b in stem for b in BAD):
            continue
        norm = _contract_stem_norm(stem)
        # P0 标准名：合同.jpg / 合同 (2).jpg
        if norm == "合同":
            pri = 0
        # P1 人名合同：李贤华合同.jpg
        elif norm.endswith("合同") and len(norm) >= 2:
            pri = 1
        # P2 常见笔误：全同.jpg（应为「合同」）
        elif norm == "全同":
            pri = 2
        # P3 委托书：委托书.jpg / xx委托书.pdf
        elif norm == "委托书" or norm.endswith("委托书"):
            pri = 3
        else:
            continue
        ext_rank = 0 if ext_l in IMG else 1
        scored.append((pri, ext_rank, len(fn), os.path.join(base_dir, fn)))
    return scored


def find_contracts(source_rel, use_cache_dir=False):
    """定位合同附件相对路径(相对 ROOT)。合同与房测报告同目录(人名子目录)。

    匹配规则（按优先级，命中高优先级后不再用低优先级）：
      P0  标准名：合同.jpg / 合同 (2).jpg（norm==「合同」）
      P1  人名合同：李贤华合同.jpg / 何三玉合同.pdf（norm 以「合同」结尾）
      P2  笔误：全同.jpg
      P3  委托书：委托书.jpg / xx委托书.pdf
    排除：文件名含 出让/测绘/施工/规划/用地（如「出让合同 (1).jpg」）
    同级无命中时，再查上一级目录一次（如 PDF 在「不要」子目录、合同在人名目录）。
    同级内优先图片(.jpg/.jpeg/.png)再 pdf；同优先级取文件名较短者。
    默认只返回「最佳一条」（上传位只收一份委托书/合同）。
    """
    if use_cache_dir:
        base = os.path.join(CACHE, os.path.dirname(source_rel))
    else:
        base = os.path.join(ROOT, os.path.dirname(source_rel))
    scored = _score_contracts_in_dir(base)
    if not scored:
        parent = os.path.dirname(base)
        if parent and parent != base:
            scored = _score_contracts_in_dir(parent)
    if not scored:
        return []
    scored.sort()
    # 同优先级可有「合同.jpg」+「合同 (2).jpg」——只取排序第一（优先无编号、图片）
    best = [scored[0][3]]
    base_ref = CACHE if use_cache_dir else ROOT
    return [os.path.relpath(c, base_ref) for c in best]

def extract_record(path, source_rel=None, max_pages=MAX_PAGES, fallback_full=True, use_cache_dir=False):
    rec={"report_no":"","委托方":"","项目名称":"","房屋座落":"","总建筑面积":"",
         "施测日期":"","测绘单位":"","source_pdf":"","合同":[]}
    text, np=_pdf_text(path, max_pages)
    parse_fields(rec, text)
    # 兜底：关键字段缺失 → 回退全量提取该份（防止其他月份模板页码变化漏数据）
    if fallback_full and (not rec["委托方"] or not rec["总建筑面积"] or not rec["施测日期"]):
        if np > max_pages:
            text2,_=_pdf_text(path, np)
            parse_fields(rec, text2)
    # 定位合同附件（基于网络盘真实目录，最可靠）
    if source_rel:
        rec["合同"]=find_contracts(source_rel, use_cache_dir=use_cache_dir)
    return rec

# ---- 提取验证：N次一致性 + 字段规则校验 ----
# 仅比对这些“解析出来”的核心字段（不含 source_pdf/合同等路径字段）
VERIFY_FIELDS = ["report_no","委托方","项目名称","房屋座落","总建筑面积","施测日期","测绘单位"]

def extract_with_verify(path, source_rel=None, n=2, max_pages=MAX_PAGES,
                        fallback_full=True, use_cache_dir=False):
    """同一份PDF提取 n 次并交叉比对（防偶发异常：缓存损坏/读取中断/并发写冲突）。
    返回 (rec, consistent, rule_issues, diffs)
      consistent : 所有次提取逐字段一致
      rule_issues: 字段规则校验问题（面积/日期/编号/必填/空文本）
      diffs      : 不一致字段及每次取值列表
    """
    recs = [extract_record(path, source_rel, max_pages, fallback_full, use_cache_dir)
            for _ in range(max(n, 1))]
    base = recs[0]
    diffs = []
    for f in VERIFY_FIELDS:
        vals = [r.get(f) for r in recs]
        if len(set(vals)) > 1:
            diffs.append((f, vals))
    consistent = len(diffs) == 0
    return base, consistent, validate_fields(base), diffs

def validate_fields(rec):
    """字段规则校验——抓“持续错误”（确定性解析也救不了的逻辑问题）。"""
    issues = []
    rn = (rec.get("report_no") or "").strip()
    if not rn:
        issues.append("报告编号缺失")
    elif not re.match(r"^[A-Za-z]{2,}\d{6,}$", rn):
        issues.append(f"报告编号格式异常:{rn}")
    if not (rec.get("委托方") or "").strip():
        issues.append("委托方缺失")
    if not (rec.get("项目名称") or "").strip():
        issues.append("项目名称缺失")
    area = rec.get("总建筑面积") or ""
    try:
        af = float(area)
        if af <= 0 or af > 1_000_000:
            issues.append(f"建筑面积异常:{area}")
    except (ValueError, TypeError):
        issues.append(f"建筑面积非数值:{area}")
    sd = (rec.get("施测日期") or "").strip()
    if not sd:
        issues.append("施测日期缺失")
    elif not (re.search(r"\d{4}年\d{1,2}月\d{1,2}日", sd) or re.match(r"\d{4}-\d{2}-\d{2}", sd)):
        issues.append(f"施测日期格式异常:{sd}")
    if not (rec.get("房屋座落") or "").strip():
        issues.append("房屋座落缺失")
    if not (rec.get("测绘单位") or "").strip():
        issues.append("测绘单位缺失")
    filled = sum(1 for f in VERIFY_FIELDS if (rec.get(f) or "").strip())
    if filled < 4:
        issues.append(f"疑似扫描件/空文本(有效字段仅{filled}/{len(VERIFY_FIELDS)})")
    return issues

# ---- 跨进程文件锁（保证提取进程与上传进程并发读写台账时串行化）----
LOCK_FILE = LEDGER + ".lock"

@contextlib.contextmanager
def ledger_lock(timeout=60, stale=120):
    """原子创建 .lock 文件获得互斥锁，跨进程有效（Windows 下 O_EXCL 创建即独占）。

    - 若锁文件存在但已超过 stale 秒（持有进程已崩溃），自动删除自愈，避免死锁。
    - 临超时兜底强制清理：活跃持有者单次持锁 <1s，等满 timeout 仍拿不到必然是死锁残留。
    - 释放时对 os.remove 失败重试，规避 Windows/Defender 文件锁竞争导致的残留。
    """
    deadline = time.time() + timeout
    fd = None
    while True:
        try:
            fd = os.open(LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_RDWR)
            break
        except FileExistsError:
            # 陈旧锁（持有进程已崩溃）自愈
            try:
                if time.time() - os.path.getmtime(LOCK_FILE) > stale:
                    os.remove(LOCK_FILE)
                    continue
            except OSError:
                pass
            # 临超时兜底：几乎必然是死锁残留，强制清后重建
            if time.time() > deadline - 5:
                try:
                    os.remove(LOCK_FILE)
                except OSError:
                    pass
                try:
                    fd = os.open(LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_RDWR)
                    break
                except FileExistsError:
                    pass
            if time.time() > deadline:
                raise TimeoutError(f"等待台账锁超时({timeout}s)")
            time.sleep(0.2)
    try:
        yield
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except Exception:
                pass
        # 释放重试：规避 Windows/Defender 文件锁竞争导致的残留
        for _ in range(50):
            try:
                os.remove(LOCK_FILE)
                break
            except OSError:
                time.sleep(0.1)

def locked_read_ledger():
    """带锁读取台账，避免读到另一进程写了一半的内容。"""
    with ledger_lock():
        return load_ledger()

def locked_write_ledger(ledger):
    """带锁写回台账。"""
    with ledger_lock():
        save_ledger(ledger)

def load_manifest():
    mp=os.path.join(CACHE,"manifest.json")
    if os.path.exists(mp):
        try: return json.load(open(mp,encoding="utf-8"))
        except: return {}
    return {}
def save_manifest(m):
    os.makedirs(CACHE, exist_ok=True)
    json.dump(m, open(os.path.join(CACHE,"manifest.json"),"w",encoding="utf-8"), ensure_ascii=False)

def sync_cache(pdfs, extra_rels=None):
    """把网络盘文件按修改时间增量同步到本地缓存。
    pdfs: 房测报告路径列表；extra_rels: 额外需同步的相对路径(如合同)"""
    manifest=load_manifest()
    local=[]; changed=0
    def _sync_one(rel):
        nonlocal changed
        src=os.path.join(ROOT, rel); dst=os.path.join(CACHE, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        try:
            mt=os.path.getmtime(src)
        except FileNotFoundError:
            return None
        if (not os.path.exists(dst)) or manifest.get(rel,{}).get("mtime",0)!=mt:
            shutil.copy2(src, dst); changed+=1
            manifest[rel]={"mtime":mt,"size":os.path.getsize(src)}
        return dst
    for p in pdfs:
        rel=os.path.relpath(p, ROOT)
        local.append(_sync_one(rel))
    for rel in (extra_rels or []):
        _sync_one(rel)
    save_manifest(manifest)
    return local

def load_ledger():
    if os.path.exists(LEDGER):
        try:
            data = json.load(open(LEDGER, encoding="utf-8"))
            # 把台账里写死的旧缓存绝对路径翻译成当前配置的缓存根（离线部署关键）
            for _rec in data.values():
                if not isinstance(_rec, dict):
                    continue
                if _rec.get("合同"):
                    _rec["合同"] = [_cfg.norm_cache_path(x) for x in _rec["合同"]]
                if _rec.get("source_pdf"):
                    _rec["source_pdf"] = _cfg.norm_cache_path(_rec["source_pdf"])
            return data
        except: return {}
    return {}

def save_ledger(ledger):
    # 原子写：先写 .tmp 再 os.replace，读方永远拿到完整文件（双进程无锁安全）
    tmp = LEDGER + ".tmp"
    json.dump(ledger, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    os.replace(tmp, LEDGER)

STATUS_CN={"pending":"待登记","done":"已登记","failed":"登记失败"}

def build_xlsx(ledger):
    wb=Workbook(); ws=wb.active; ws.title="备案台账"
    headers=["报告编号","委托方","项目名称","房屋座落","总建筑面积","施测日期","测绘单位",
             "合同数","合同已清理","登记状态","首次提取","最近更新","来源PDF","备注"]
    ws.append(headers)
    for k,v in ledger.items():
        ws.append([k, v.get("委托方",""), v.get("项目名称",""), v.get("房屋座落",""),
                   v.get("总建筑面积",""), v.get("施测日期",""), v.get("测绘单位",""),
                   len(v.get("合同",[]) or []), "是" if v.get("_cleaned") else "否",
                   STATUS_CN.get(v.get("status","pending"),"待登记"),
                   v.get("first_seen",""), v.get("last_updated",""),
                   v.get("source_pdf",""), v.get("note","")])
    wb.save(XLSX)

def process(max_pages=MAX_PAGES, workers=1, use_cache=True, local_only=False):
    t0=datetime.datetime.now()
    if local_only:
        manifest=load_manifest()
        if not manifest:
            print("⚠️ 本地缓存为空，请先正常运行一次（或去掉 --local）"); return
        parsed_paths=[os.path.join(CACHE,r) for r in manifest if r.lower().endswith(".pdf")]
        source_rels=[r for r in manifest if r.lower().endswith(".pdf")]
        pdfs=parsed_paths
        cache_note="纯本地(--local, 不碰网络盘)"
        use_cache_dir_for_contract=True
    else:
        pdfs=sorted(glob.glob(os.path.join(ROOT,"**","*房测报告*.pdf"),recursive=True))
        if use_cache:
            parsed_paths=sync_cache(pdfs)
            cache_note=f"本地缓存({CACHE})"
        else:
            parsed_paths=pdfs
            cache_note="直读网络盘"
        source_rels=[os.path.relpath(p, ROOT) for p in pdfs]
        use_cache_dir_for_contract=False
    ledger=load_ledger()
    now=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # ---- 提取（fitz引擎 + 只提前N页；workers>1 适合数百份以上大批量）----
    if workers and workers > 1:
        from concurrent.futures import ProcessPoolExecutor
        with ProcessPoolExecutor(max_workers=workers) as ex:
            recs=list(ex.map(lambda a: extract_record(a[0], a[1], max_pages, True, use_cache_dir_for_contract),
                             list(zip(parsed_paths, source_rels))))
    else:
        recs=[extract_record(p, rel, max_pages, True, use_cache_dir_for_contract)
              for p, rel in zip(parsed_paths, source_rels)]
    # source_pdf 记录相对网络盘路径（便于溯源/清理）
    for rec, rel in zip(recs, source_rels):
        rec["source_pdf"]=rel
    # ---- 同步合同到缓存（正常模式才同步；--local 假设已同步）----
    if not local_only and use_cache:
        contract_rels=set()
        for rec in recs:
            for cr in rec.get("合同",[]):
                contract_rels.add(cr)
        if contract_rels:
            sync_cache([], extra_rels=list(contract_rels))
    # ---- 串行去重 ----
    new=[]; skipped_done=[]; reopen=[]
    n_contract=0
    for rec in recs:
        key=rec["report_no"] or os.path.basename(rec["source_pdf"])
        n_contract+=len(rec.get("合同",[]))
        if key in ledger:
            ex_=ledger[key]
            if ex_.get("status")=="done":
                skipped_done.append(key); continue
            else:
                reopen.append(key)
                ex_.update({kk:vv for kk,vv in rec.items() if kk!="status"})
                ex_["last_updated"]=now; ledger[key]=ex_
        else:
            rec["status"]="pending"; rec["first_seen"]=now; rec["last_updated"]=now
            ledger[key]=rec; new.append(key)
    save_ledger(ledger); build_xlsx(ledger)
    dt=(datetime.datetime.now()-t0).total_seconds()
    print(f"=== 扫描完成（目录: 1月份, 共 {len(pdfs)} 份PDF, 引擎={ENGINE}, 前 {max_pages} 页, {cache_note}）===")
    print(f"  ✅ 新增待登记 : {len(new)} 条")
    print(f"  🔄 重新待登记 : {len(reopen)} 条（曾提取但未登记完成）")
    print(f"  ⏭️  已登记跳过 : {len(skipped_done)} 条（不会重复登记）")
    print(f"  📎 定位合同附件 : {n_contract} 份（随房测报告一并上传）")
    print(f"  📒 台账总计   : {len(ledger)} 条  → {LEDGER}")
    print(f"  📊 Excel 台账 : {XLSX}")
    print(f"  ⏱️  耗时       : {dt:.2f}s")

def stats():
    ledger=load_ledger()
    from collections import Counter
    c=Counter(v.get("status","pending") for v in ledger.values())
    nc=sum(len(v.get("合同",[]) or []) for v in ledger.values())
    cleaned=sum(1 for v in ledger.values() if v.get("_cleaned"))
    print(f"台账总数: {len(ledger)}")
    for s in ("pending","done","failed"):
        print(f"  {STATUS_CN[s]}: {c.get(s,0)}")
    print(f"  合同附件总数: {nc}（其中已清理缓存: {cleaned} 条记录的本地文件已删）")

def mark(report_no, status):
    """标记状态；done 时删除本地缓存文件(房测报告+合同)，台账只留标记。"""
    ledger=locked_read_ledger()
    if report_no not in ledger:
        print(f"⚠️ 台账中无此编号: {report_no}"); return
    rec=ledger[report_no]
    rec["status"]=status
    rec["last_updated"]=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    deleted=[]
    if status=="done":
        # 删除缓存中的房测报告 + 全部合同图片
        rels=[rec.get("source_pdf")] + list(rec.get("合同",[]) or [])
        manifest=load_manifest()
        for rel in rels:
            if not rel: continue
            lp=os.path.join(CACHE, rel)
            if os.path.exists(lp):
                try: os.remove(lp); deleted.append(lp)
                except Exception as e: print(f"  ⚠️ 删除失败 {lp}: {e}")
            manifest.pop(rel, None)
        save_manifest(manifest)
        # 台账只留标记（清空文件路径，保留编号+字段摘要供核对）
        rec["source_pdf"]=""
        rec["合同"]=[]
        rec["_cleaned"]=True
        print(f"🗑️ 已删除本地缓存 {len(deleted)} 个文件（房测报告+合同），台账仅保留标记")
    else:
        rec.pop("_cleaned", None)
    locked_write_ledger(ledger); build_xlsx(ledger)
    print(f"✔ 已将 {report_no} 标记为「{STATUS_CN[status]}」")

# ---- 上传日志（独立文件，上传进程独占写；与台账分离 → 双进程零写冲突）----
UPLOAD_LOG = os.path.join(os.path.dirname(LEDGER), "beian_upload_log.json")

def load_upload_log():
    if os.path.exists(UPLOAD_LOG):
        try:
            return json.load(open(UPLOAD_LOG, encoding="utf-8"))
        except Exception:
            return {}
    return {}

def save_upload_log(log):
    tmp = UPLOAD_LOG + ".tmp"
    json.dump(log, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    os.replace(tmp, UPLOAD_LOG)

def mark_uploaded(report_no, rec=None):
    """上传成功后：记录到 upload_log（独立文件），并清理本地缓存文件防磁盘爆。
    台账 status 由提取进程维护，此处不改台账，仅记录上传完成态。"""
    log = load_upload_log()
    log[report_no] = {"status": "done",
                      "ts": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    save_upload_log(log)
    deleted = []
    if rec:
        rels = [rec.get("source_pdf")] + list(rec.get("合同", []) or [])
        manifest = load_manifest()
        for rel in rels:
            if not rel:
                continue
            lp = rel if os.path.isabs(rel) else os.path.join(CACHE, rel)
            if os.path.exists(lp):
                try:
                    os.remove(lp)
                    deleted.append(lp)
                except Exception:
                    pass
            rel_cache = os.path.relpath(lp, CACHE) if os.path.isabs(lp) else rel
            manifest.pop(rel_cache, None)
        save_manifest(manifest)
    print(f"✔ 上传完成并清理缓存 {len(deleted)} 个文件: {report_no}")


if __name__=="__main__":
    args=sys.argv[1:]
    pages=MAX_PAGES; workers=1; use_cache=True
    if "--pages" in args:
        i=args.index("--pages"); pages=int(args[i+1]); args=args[:i]+args[i+2:]
    if "--workers" in args:
        i=args.index("--workers"); workers=int(args[i+1]); args=args[:i]+args[i+2:]
    if "--no-cache" in args:
        use_cache=False; args=[a for a in args if a!="--no-cache"]
    if "--local" in args:
        local_only=True; args=[a for a in args if a!="--local"]
    else:
        local_only=False
    if not args:
        process(pages, workers, use_cache, local_only)
    elif args[0]=="stats":
        stats()
    elif args[0]=="mark" and len(args)>1:
        mark(args[1], "done")
    elif args[0]=="unmark" and len(args)>1:
        mark(args[1], "pending")
    elif args[0]=="fail" and len(args)>1:
        mark(args[1], "failed")
    else:
        print(__doc__)
