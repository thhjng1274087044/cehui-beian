#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工程备案：级联器单选 → 按台账「类别」为归大类总开关收敛 项目类型_填报(大类/小类)。
类别是合同人工分类(最可靠)，OCR作业类别仅用于在同大类内挑小类；非测绘类→非测绘(无子项)。"""
import csv, os, collections, json

HERE = os.path.dirname(os.path.abspath(__file__))
CSV = os.path.join(HERE, "工程备案_精修.csv")
TREE = os.path.join(HERE, "_projtype_live.json")

# 小类 -> 大类 (来自网页真实级联树)
TREE_DATA = json.load(open(TREE, encoding="utf-8")) if os.path.exists(TREE) else []
SUB2BIG = {}
for t in TREE_DATA:
    for s in t["小类"]:
        SUB2BIG[s] = t["大类"]

NON_CE = {"技术服务", "用地报批", "资料整理", "新型测绘"}
CAT2BIG = {
    "房产测绘": "房产测绘", "不动产测绘": "房产测绘", "房产测量": "房产测绘",
    "地籍测绘": "地籍测绘",
    "行政区域界线测绘": "行政区域界线测绘",
    "工程测绘": "工程测量", "综合测绘": "工程测量",
}
CAT2SUB_DEFAULT = {
    "房产测绘": "房产测绘", "不动产测绘": "房产测绘", "房产测量": "房产测绘",
    "地籍测绘": "地籍测绘",
    "行政区域界线测绘": "行政区域界线测绘",
    "工程测绘": "建筑工程测量", "综合测绘": "建筑工程测量",
}

def parse_subs(s):
    out = []
    for part in (s or "").split(";"):
        part = part.strip()
        if not part:
            continue
        if "/" in part:
            c, z = part.split("/", 1)
            out.append((c.strip(), z.strip()))
        else:
            out.append((part.strip(), ""))
    return out

def resolve(类别, subs, judge):
    if 类别 in NON_CE:
        return ("非测绘", "", "非测绘类(技术服务/用地报批等)，无子项")
    if 类别 in CAT2BIG:
        big = CAT2BIG[类别]
        default_z = CAT2SUB_DEFAULT[类别]
        matching = [(c, z) for c, z in subs if c == big and z]
        if big == "工程测量":
            hit = next((z for c, z in matching if z == "建筑工程测量"), None)
            if hit is None and matching:
                hit = matching[0][1]
            z = hit or default_z
            note = "按台账类别工程测绘→工程测量" + ("+作业类别命中" if matching else "→建筑工程测量(默认,待核定)")
        else:
            z = matching[0][1] if matching else default_z
            note = f"按台账类别→{big}/{z}" + ("" if matching else "(默认,待核定)")
        return (big, z, note)
    # 类别未识别：退回首个OCR子项
    if subs:
        c, z = subs[0]
        if c in SUB2BIG:  # c 实际是小类名
            return (SUB2BIG[c], c, "类别未识别,按网页树反查大类(待核定)")
        if c in CAT2BIG.values():  # c 是大类名
            first_sub = next((t["小类"][0] for t in TREE_DATA if t["大类"] == c and t["小类"]), "")
            return (c, first_sub, "类别未识别,退回首个OCR大类(待核定)")
        if z and z in SUB2BIG:
            return (SUB2BIG[z], z, "类别未识别,仅含小类,按网页树补大类(待核定)")
        return (c, z, "类别未识别,退回首个OCR子项(待核定)")
    return ("", "", "无数据")

rows = list(csv.DictReader(open(CSV, encoding="utf-8-sig", newline="")))
fns = list(rows[0].keys())
for c in ["项目类型_填报", "项目类型_填报依据", "项目类型_待核定"]:
    if c not in fns:
        fns.append(c)

unmatched_jbr = []
for r in rows:
    if not (r.get("经办人") or "").strip():
        unmatched_jbr.append(r.get("合同号"))
    类别 = (r.get("类别") or "").strip()
    subs = parse_subs(r.get("平台子项"))
    judge = (r.get("子项判定") or "").strip()
    big, z, note = resolve(类别, subs, judge)
    r["项目类型_填报"] = f"{big}/{z}" if (big and z) else (big or "")
    r["项目类型_填报依据"] = note
    # 待核定：多选收敛 / 默认兜底 / 类别未识别 / 非测绘待确认 一律待复核
    r["项目类型_待核定"] = "是" if (judge in ("多", "测绘默认(待核定)") or "待核定" in note or "未识别" in note) else "否"

with open(CSV, "w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, fieldnames=fns)
    w.writeheader(); w.writerows(rows)

print(f"总行数 {len(rows)} | 项目类型_填报 生成完成")
cnt = collections.Counter(r["项目类型_填报"] for r in rows)
print("\n项目类型_填报 分布:")
for k, v in cnt.most_common():
    print(f"  {k or '(空)'}: {v}")

print(f"\n未匹配经办人合同号({len(unmatched_jbr)}): {unmatched_jbr}")

print("\n抽样 工程测绘合同收敛(前6):")
n=0
for r in rows:
    if (r.get("类别") or "") in ("工程测绘", "综合测绘"):
        print(f"  {r['合同号']} | 类别:{r['类别']} | 原OCR:{r['平台子项'][:45]} => 填报:{r['项目类型_填报']}")
        n+=1
        if n>=6: break
print("\n抽样 房产类合同(前4):")
n=0
for r in rows:
    if (r.get("类别") or "") in ("房产测绘","不动产测绘","房产测量"):
        print(f"  {r['合同号']} | 类别:{r['类别']} => 填报:{r['项目类型_填报']}")
        n+=1
        if n>=4: break
