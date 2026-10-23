# 复用 beian_fill.py --all 的跳过逻辑，统计「不用上传」的明细
import os, json

PKG = r"E:\网站备案\备案部署包"
LEDGER = os.path.join(PKG, "beian_records.json")
UPLOG  = os.path.join(PKG, "beian_upload_log.json")
SKIPF  = os.path.join(PKG, "beian_skip_names.json")

ledger = json.load(open(LEDGER, encoding="utf-8"))
uploaded = set()
if os.path.exists(UPLOG):
    uploaded = set(json.load(open(UPLOG, encoding="utf-8")).keys())
skip_names = set()
if os.path.exists(SKIPF):
    skip_names = set((json.load(open(SKIPF, encoding="utf-8")).get("names") or []))

def is_skip_record(v):
    for f in ("委托方", "建设单位"):
        n = (v.get(f) or "").strip()
        if n and n in skip_names:
            return True
    return False

cat_extract = []   # 提取未通过
cat_uploaded = []  # 已上传
cat_named = []     # 命中跳过名单
cat_nocontract = []# 无合同
pending = []       # 真正要传的

for k, v in ledger.items():
    ex = v.get("extract_status")
    if ex in ("verify_failed", "rule_failed"):
        cat_extract.append(k); continue
    if k in uploaded:
        cat_uploaded.append(k); continue
    if is_skip_record(v):
        cat_named.append(k); continue
    cts = v.get("合同") or []
    if not (cts and os.path.exists(cts[0])):
        cat_nocontract.append(k); continue
    pending.append(k)

# 统计年份分布（key 形如 XH202401037 / CB202401037）
def yr(k):
    import re
    m = re.search(r"(20\d{2})", k)
    return m.group(1) if m else "??"

def dist(keys):
    d = {}
    for k in keys:
        y = yr(k)
        d[y] = d.get(y, 0) + 1
    return dict(sorted(d.items()))

print("=" * 60)
print("台账总条数        :", len(ledger))
print("-" * 60)
print("① 提取未通过(verify/rule_failed):", len(cat_extract))
print("   年份分布:", dist(cat_extract))
print("② 已上传(done, 在 upload_log):", len(cat_uploaded))
print("   年份分布:", dist(cat_uploaded))
print("③ 命中跳过名单(委托方/建设单位):", len(cat_named), "名单=", sorted(skip_names))
print("④ 无合同(合同为空或缓存缺失):", len(cat_nocontract))
print("   年份分布:", dist(cat_nocontract))
print("-" * 60)
print("✅ 真正待上传(pending):", len(pending))
print("   年份分布:", dist(pending))

# 输出明细文件
out = {
    "total": len(ledger),
    "extract_failed": cat_extract,
    "uploaded": cat_uploaded,
    "skip_named": cat_named,
    "no_contract": cat_nocontract,
    "pending": pending,
}
json.dump(out, open(os.path.join(PKG, "analyze_skip_result.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
print("\n明细已写出: analyze_skip_result.json")

# 打印各类样本（前若干条，便于核对）
print("\n--- ③ 跳过名单命中(全部) ---")
for k in cat_named:
    print("  ", k, "|", ledger[k].get("委托方"), "/", ledger[k].get("建设单位"))
print("\n--- ④ 无合同(按年份抽样, 每年前5) ---")
byyr = {}
for k in cat_nocontract:
    y = yr(k); byyr.setdefault(y, []).append(k)
for y in sorted(byyr):
    print(f"  [{y}] 共{len(byyr[y])}条, 样本:", byyr[y][:5])
