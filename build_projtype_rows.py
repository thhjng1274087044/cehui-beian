# -*- coding: utf-8 -*-
"""
构建工程备案「项目类型多行 + 金额分摊」数据。
规则（与用户 2026-10-13 确认）：
  1) 多子项展开：只展开「非综合测绘 且 确实多子项」的合同。
  2) 去噪：工程测量合同正文常把整套服务列成条款 → OCR 全命中 5 项标准菜单
     {地下管线,变形形变,控制测量,地形,建筑工程测量}。完整命中这 5 项视为噪音，收成单行。
  3) 其余 2/4 项子集视为候选真多子项 → 展开多行（打 待核定 交人工复核）。
  4) 金额分摊（只有合同总额、无分项时）：主子项占 60%，其余均摊 40%；单行则全额。
  5) 综合测绘（用户此前定：先不上传/保持单主子项）一律单行。
"""
import csv, json, os

HERE = os.path.dirname(os.path.abspath(__file__))
CSV = os.path.join(HERE, "工程备案_精修.csv")
TREE_PATH = os.path.join(HERE, "_projtype_live.json")

# 网页真实项目类型树（用于判定裸值是大类还是小类）
BIG_SET = set()
SUB2BIG = {}
if os.path.exists(TREE_PATH):
    for t in json.load(open(TREE_PATH, encoding="utf-8")):
        BIG_SET.add(t["大类"])
        for s in t.get("小类", []):
            SUB2BIG[s] = t["大类"]

# 台账类别 -> 网页大类
CAT2BIG = {
    "工程测绘": "工程测量", "房产测绘": "房产测绘", "房产测量": "房产测绘",
    "地籍测绘": "地籍测绘", "地籍": "地籍测绘", "综合测绘": "工程测量",
    "用地报批": "非测绘", "技术服务": "非测绘", "不动产测绘": "不动产测绘", "其他": "非测绘",
}

# 工程测量标准服务菜单（OCR 常过度命中的那套）
STANDARD_MENU = {"地下管线测量", "变形形变与精密测量", "控制测量", "地形测量", "建筑工程测量"}

# 主子项优先级（越前越主）
PRIMARY_PRIORITY = [
    "建筑工程测量", "规划测量", "市政工程测量", "线路与桥隧测量",
    "地下管线测量", "变形形变与精密测量", "控制测量", "地形测量",
    "水利工程测量", "矿山测量", "工程测量监理",
]

def cat_big(类别):
    return CAT2BIG.get((类别 or "").strip())

def parse_subs(s):
    out = []
    for part in (s or "").split(";"):
        part = part.strip()
        if not part:
            continue
        if "/" in part:
            b, z = part.split("/", 1)
            out.append((b.strip(), z.strip()))
        else:
            # 裸值：用网页树判定是大类还是小类
            if part in BIG_SET:
                out.append((part, part))          # 同名叶大类
            elif part in SUB2BIG:
                out.append((SUB2BIG[part], part))  # 小类 → 补大类
            else:
                out.append((part, part))
    return out

def order_key(z):
    return PRIMARY_PRIORITY.index(z) if z in PRIMARY_PRIORITY else 99

def allocate(total, n):
    """返回 n 个金额（万元），求和≈total。total=None 时返回 [None]*n。"""
    if total is None:
        return [None] * n
    if n == 1:
        return [round(total, 4)]
    # 主子项 60%，其余均摊 40%
    primary = round(total * 0.6, 4)
    rest_each = (total - primary) / (n - 1)
    rest_each = round(rest_each, 4)
    amts = [primary] + [rest_each] * (n - 1)
    # 末项修正使求和精确
    diff = round(total - sum(amts), 4)
    amts[-1] = round(amts[-1] + diff, 4)
    return amts

rows = list(csv.DictReader(open(CSV, encoding="utf-8-sig", newline="")))
fns = list(rows[0].keys())
for c in ["项目类型_行列表", "金额_行列表", "项目类型_行数", "多行标志", "金额分摊_待核定", "分摊说明"]:
    if c not in fns:
        fns.append(c)

single_cnt = 0
multi_cnt = 0
boiler_cnt = 0
for r in rows:
    类别 = (r.get("类别") or "").strip()
    big = cat_big(类别)
    subs = parse_subs(r.get("平台子项"))
    # 优先保留与台账大类同类的子项（去跨类噪音）；若同类为空则回退用 OCR 原始子项（作业类别优先）
    same = [(b, z) for b, z in subs if b == big] if big else []
    cand = same if same else subs
    seen = set(); uniq = []
    for b, z in cand:
        if z not in seen:
            seen.add(z); uniq.append((b, z))

    total_raw = (r.get("打折后万元") or "").strip()
    total = float(total_raw) if total_raw else None

    rows_list = []   # 有序的 大类/小类
    amts = []
    multi = False
    note = ""
    待核定 = "否"

    NON_SURVEY = {"用地报批", "技术服务", "资料整理", "新型测绘", "其他"}
    BIG_DEFAULT = {
        "工程测量": "工程测量/建筑工程测量",
        "房产测绘": "房产测绘/房产测绘",
        "地籍测绘": "地籍测绘/地籍测绘",
        "不动产测绘": "不动产测绘/不动产测绘",
    }

    if 类别 in NON_SURVEY:
        # 非测绘：单行叶子
        rows_list = ["非测绘"]
        amts = allocate(total, 1)
        single_cnt += 1
    elif 类别 == "综合测绘":
        # 综合测绘：单主子项（不展开，用户定先不上传）
        if uniq:
            ordered = sorted(uniq, key=lambda x: order_key(x[1]))
            rows_list = [f"{ordered[0][0]}/{ordered[0][1]}"]
        else:
            rows_list = ["工程测量/建筑工程测量"]
        amts = allocate(total, 1)
        single_cnt += 1
    else:
        if len(uniq) <= 1:
            # 单子项（含 OCR 原始子项兜底）
            if uniq:
                rows_list = [f"{uniq[0][0]}/{uniq[0][1]}"]
            elif big:
                rows_list = [BIG_DEFAULT.get(big, big)]
            else:
                # 无类别且无 OCR 子项 → 无法判定，留空待人工核定
                rows_list = [""]
                待核定 = "是"
                note = "无类别且无OCR子项→待人工核定"
            amts = allocate(total, 1)
            single_cnt += 1
        else:
            zset = set(z for _, z in uniq)
            if zset == STANDARD_MENU:
                # 完整标准菜单 → 视为条款噪音，收单行
                rows_list = ["工程测量/建筑工程测量"]
                amts = allocate(total, 1)
                boiler_cnt += 1
                note = "5项标准菜单视为条款噪音→收单行"
            else:
                # 候选真多子项 → 展开
                ordered = sorted(uniq, key=lambda x: order_key(x[1]))
                rows_list = [f"{b}/{z}" for b, z in ordered]
                amts = allocate(total, len(rows_list))
                multi = True
                multi_cnt += 1
                待核定 = "是"
                note = "候选真多子项→展开多行(待人工复核);金额按主60%余均摊40%"

    r["项目类型_行列表"] = json.dumps(rows_list, ensure_ascii=False)
    r["金额_行列表"] = json.dumps(amts, ensure_ascii=False)
    r["项目类型_行数"] = str(len(rows_list))
    # 同步主列：项目类型_填报 = 首行（保持一致）
    r["项目类型_填报"] = rows_list[0]
    r["多行标志"] = "是" if multi else "否"
    r["金额分摊_待核定"] = 待核定
    r["分摊说明"] = note

with open(CSV, "w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, fieldnames=fns)
    w.writeheader()
    w.writerows(rows)

print(f"总行数: {len(rows)}")
print(f"单行: {single_cnt} (含综合测绘+非测绘+单子项)")
print(f"完整菜单收单行: {boiler_cnt}")
print(f"多行展开(候选真多子项): {multi_cnt}")
print("\n=== 多行展开清单 ===")
for r in rows:
    if r["多行标志"] == "是":
        print(f"  {r.get('合同号')} | {r.get('类别')} | 行:{r['项目类型_行列表']} | 额:{r['金额_行列表']} | {r['分摊说明']}")
