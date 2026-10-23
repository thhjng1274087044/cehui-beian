# -*- coding: utf-8 -*-
"""把「放样按宾语归属」原则的校验结果标注进 定稿CSV。"""
import csv, os

HERE = os.path.dirname(os.path.abspath(__file__))
CSV = os.path.join(HERE, "工程备案_子项映射表_定稿.csv")

# 4 条需确认 / 需标注的放样项
NOTE = {
    "温岭市城北街道琅岙匝道超批准线放样":
        "⚠️待确认:宾语='匝道'(道路)→宜 市政工程测量;或'超批准线'(用地红线)→规划测量。现值建筑工程测量与宾语不符",
    "温岭市城北街道2022-04-01地块耕作层剥离放样":
        "宾语='耕作层剥离'(土地整治,非六类标准宾语);平台无土地整治子项,就近挂建筑工程测量",
    "温岭市城北街道东普村等复耕地块放样":
        "宾语='复耕地块'(土地整治,非六类标准宾语);平台无土地整治子项,就近挂建筑工程测量",
    "温岭市城北街道水域占补平衡位置放样":
        "宾语='水域占补平衡'(水利/土地指标,非六类标准宾语);平台无对应子项,就近挂建筑工程测量(也可议归水利工程测量)",
}
STATUS = {"温岭市城北街道琅岙匝道超批准线放样": "待确认"}

rows = list(csv.DictReader(open(CSV, encoding="utf-8-sig", newline="")))
fns = list(rows[0].keys())
cnt = 0
for r in rows:
    n = r["合同项名"].strip()
    if n in NOTE:
        old = (r.get("依据/口径") or "").strip()
        r["依据/口径"] = (old + "；" + NOTE[n]) if old else NOTE[n]
        if n in STATUS:
            r["状态"] = STATUS[n]
        cnt += 1

with open(CSV, "w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, fieldnames=fns)
    w.writeheader()
    w.writerows(rows)
print("已标注行数:", cnt)
for r in rows:
    if r["合同项名"].strip() in NOTE:
        print(f"  {r['合同项名']} | {r['状态']} | {r['依据/口径'][:60]}...")
