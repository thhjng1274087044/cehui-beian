import os, json, re

PKG = os.path.dirname(os.path.abspath(__file__))
LEDGER = os.path.join(PKG, "beian_records.json")
SKIPF = os.path.join(PKG, "beian_skip_names.json")

ledger = json.load(open(LEDGER, encoding="utf-8"))
skip = json.load(open(SKIPF, encoding="utf-8"))
names = set(skip.get("names") or [])

# 台账可能是 list 或 dict
if isinstance(ledger, dict):
    recs = list(ledger.values())
else:
    recs = ledger

def year_of(r):
    no = r.get("报告编号") or r.get("report_no") or r.get("no") or ""
    d = r.get("施测日期") or r.get("date") or r.get("测绘日期") or ""
    m = re.search(r"(20\d{2})", str(no))
    if m:
        return m.group(1)
    m = re.search(r"(20\d{2})[-/年.]", str(d))
    if m:
        return m.group(1)
    return "?"

# 探测字段键
sample_keys = list(recs[0].keys()) if recs else []
print("== 台账记录字段示例 ==")
print(sample_keys)
print("== 总记录数:", len(recs), "==\n")

# 用于匹配委托方的键
def get_name(r):
    for k in ("委托方", "委托单位", "client", "owner", "name"):
        if k in r and r[k]:
            return r[k]
    return ""

name_key = None
for k in ("委托方", "委托单位", "client", "owner"):
    if k in sample_keys:
        name_key = k
        break

hits = {n: [] for n in names}
for r in recs:
    nm = get_name(r)
    if nm in names:
        hits[nm].append(r)

for n in sorted(names):
    rs = hits[n]
    yrs = {}
    for r in rs:
        y = year_of(r)
        yrs.setdefault(y, 0)
        yrs[y] += 1
    print(f"### {n}  （命中 {len(rs)} 条） 年份分布: {dict(sorted(yrs.items()))}")
    for r in rs:
        no = r.get("报告编号") or r.get("report_no") or r.get("no") or "?"
        y = year_of(r)
        proj = r.get("项目名称") or r.get("project") or ""
        print(f"   [{y}] {no}  | {proj}")
    print()
