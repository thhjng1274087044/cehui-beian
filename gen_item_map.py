# -*- coding: utf-8 -*-
"""
生成「合同出现项 -> 平台子项」对照表
  · 工程备案_子项映射表_待确认.csv   (可编辑，供人工逐条改)
  · 合同项_平台子项对照表.html       (可视化审阅页)
数据源: _gc_ocr_cache.json (合同OCR正文) + _projtype_live.json (平台真实项目类型树)
"""
import json, os, re, csv, collections

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "_gc_ocr_cache.json")
TREE  = os.path.join(HERE, "_projtype_live.json")
CSV_OUT  = os.path.join(HERE, "工程备案_子项映射表_待确认.csv")
HTML_OUT = os.path.join(HERE, "合同项_平台子项对照表.html")

TREE_DATA = json.load(open(TREE, encoding="utf-8"))
BIG_LIST = [t["大类"] for t in TREE_DATA]
SUB2BIG = {}
for t in TREE_DATA:
    for s in (t.get("小类") or []):
        SUB2BIG.setdefault(s, t["大类"])

# ============================================================
# 合同项名 -> (平台大类, 平台子项, 把握, 说明)
#   把握: OK=一一对应无歧义 / WARN=平台无同名子项,按语义就近 / TODO=残片或无从判断
# ============================================================
M = {
# ---- 放样 类 ----
"放样": ("工程测量", "建筑工程测量", "OK", "施工放样=建筑工程测量口径;控制测量是建控制网(放样的依据)不是放样"),
"放样等": ("工程测量", "建筑工程测量", "OK", ""),
"放样测量": ("工程测量", "建筑工程测量", "OK", ""),
"红线放样": ("工程测量", "建筑工程测量", "WARN", "规划红线放线,也可能归规划测量(规划测量含建筑放线/验线)"),
"围墙放样": ("工程测量", "建筑工程测量", "OK", ""),
"建筑物放样": ("工程测量", "建筑工程测量", "OK", ""),
"界址点放样": ("工程测量", "建筑工程测量", "WARN", "界址点属权属界线,也可能归地籍测绘;待定"),
"个人建房放样": ("工程测量", "建筑工程测量", "OK", ""),
# ---- 控制测量 类 ----
"控制测量": ("工程测量", "控制测量", "OK", ""),
"控制点引测": ("工程测量", "控制测量", "OK", "引测控制点=做控制网"),
"控制引测": ("工程测量", "控制测量", "OK", ""),
"水准点测量": ("工程测量", "控制测量", "WARN", "埋设水准点=高程控制;也可归大地测量/水准测量"),
# ---- 变形形变 类 ----
"沉降观测": ("工程测量", "变形形变与精密测量", "OK", ""),
"沉降测量": ("工程测量", "变形形变与精密测量", "OK", ""),
"沉降做点": ("工程测量", "变形形变与精密测量", "OK", "埋设沉降观测点"),
"沉降倾斜观测": ("工程测量", "变形形变与精密测量", "OK", ""),
"其他沉降观测": ("工程测量", "变形形变与精密测量", "OK", ""),
"倾斜测量": ("工程测量", "变形形变与精密测量", "OK", ""),
"位移观测": ("工程测量", "变形形变与精密测量", "OK", ""),
"变形测量": ("工程测量", "变形形变与精密测量", "OK", ""),
# ---- 竣工/建筑 类 ----
"竣工测量": ("工程测量", "建筑工程测量", "OK", ""),
"峻工测量": ("工程测量", "建筑工程测量", "OK", "OCR错字:竣工测量"),
"工程竣工测量": ("工程测量", "建筑工程测量", "OK", ""),
"工程量竣工测量": ("工程测量", "建筑工程测量", "OK", ""),
"工程量竣工": ("工程测量", "建筑工程测量", "OK", "残缺=工程量竣工测量"),
"工程量工测量": ("工程测量", "建筑工程测量", "OK", "OCR错字:工程量竣工测量"),
"工程量竣工测绘": ("工程测量", "建筑工程测量", "OK", ""),
"工程工测量": ("工程测量", "建筑工程测量", "OK", "残片"),
"面积竣工测量": ("工程测量", "建筑工程测量", "WARN", "也可能归房产测绘"),
"工程量竣工面积测量": ("工程测量", "建筑工程测量", "WARN", "也可能归房产测绘"),
"现状竣工": ("工程测量", "建筑工程测量", "WARN", "含义模糊,待定"),
"零星测量": ("工程测量", "建筑工程测量", "WARN", "平台无此子项,按就近挂建筑工程测量"),
"零星工程": ("工程测量", "建筑工程测量", "WARN", ""),
"零星工程测量": ("工程测量", "建筑工程测量", "WARN", ""),
"2米征地红线外零星工程测量": ("工程测量", "建筑工程测量", "WARN", ""),
"土地征用零星测量": ("工程测量", "建筑工程测量", "WARN", ""),
"立面测量": ("工程测量", "建筑工程测量", "WARN", "平台无立面测量"),
"标高测量": ("工程测量", "建筑工程测量", "WARN", "高频(27次)!平台无标高测量,按就近挂建筑工程测量"),
"标高": ("工程测量", "建筑工程测量", "WARN", "残缺=标高测量"),
"标高核测": ("工程测量", "建筑工程测量", "WARN", ""),
"标高核测量": ("工程测量", "建筑工程测量", "WARN", ""),
"原始标高测量": ("工程测量", "建筑工程测量", "WARN", ""),
"原地面标高测量": ("工程测量", "建筑工程测量", "WARN", ""),
"放样及原地面标高测量": ("工程测量", "建筑工程测量", "WARN", ""),
"周边标高测量": ("工程测量", "建筑工程测量", "WARN", ""),
"挖后标高测量": ("工程测量", "建筑工程测量", "WARN", ""),
"沥青完成面标高测量": ("工程测量", "建筑工程测量", "WARN", ""),
"工测量": ("", "", "TODO", "残片,无法判断"),
# ---- 地形/现状 类 ----
"地形测量": ("工程测量", "地形测量", "OK", ""),
"现状测量": ("工程测量", "地形测量", "OK", ""),
"现状": ("工程测量", "地形测量", "WARN", "残缺=现状测量"),
"现状地形测量": ("工程测量", "地形测量", "OK", ""),
"现状地形补测": ("工程测量", "地形测量", "OK", ""),
"现状及标高": ("工程测量", "地形测量", "WARN", "含标高,两义"),
"现状设计测量": ("工程测量", "地形测量", "WARN", ""),
"设计地形测量": ("工程测量", "地形测量", "OK", ""),
"土地现状": ("工程测量", "地形测量", "WARN", ""),
# ---- 规划 类 ----
"规划测量": ("工程测量", "规划测量", "OK", ""),
"规划竣工测量": ("工程测量", "规划测量", "OK", ""),
"规划竣工": ("工程测量", "规划测量", "OK", "残缺=规划竣工测量"),
"规划验收竣工测量": ("工程测量", "规划测量", "OK", ""),
"规划歧工测量": ("工程测量", "规划测量", "OK", "OCR错字:规划竣工测量"),
# ---- 管线 类 ----
"管线测量": ("工程测量", "地下管线测量", "OK", ""),
"地下管线测量": ("工程测量", "地下管线测量", "OK", ""),
"管线竣工": ("工程测量", "地下管线测量", "OK", "残缺=管线竣工测量"),
"管线竣工测量": ("工程测量", "地下管线测量", "OK", ""),
"管线工": ("工程测量", "地下管线测量", "OK", "残片"),
"管线工测量": ("工程测量", "地下管线测量", "OK", "残片"),
"管并测量": ("工程测量", "地下管线测量", "OK", "OCR错字:管线测量"),
"PVC管线测量": ("工程测量", "地下管线测量", "OK", ""),
"雨污水管线工测量": ("工程测量", "地下管线测量", "OK", ""),
"管线沟渠竣工": ("工程测量", "地下管线测量", "OK", ""),
# ---- 市政/水利/线路 类 ----
"海绵城市测量": ("工程测量", "市政工程测量", "WARN", ""),
"上山路测量": ("工程测量", "市政工程测量", "WARN", "也可归线路与桥隧测量"),
"温岭市大溪镇相公渭村美丽乡村微提升工程测量": ("工程测量", "市政工程测量", "WARN", "村道/微提升,待定"),
"水面拦污帘测量": ("工程测量", "水利工程测量", "WARN", "水利设施"),
"断面测量": ("工程测量", "线路与桥隧测量", "WARN", "原挂地形测量;道路/河道断面更贴线路与桥隧"),
"横断面测量": ("工程测量", "线路与桥隧测量", "WARN", ""),
"纵断面测量": ("工程测量", "线路与桥隧测量", "WARN", ""),
"走向测量": ("工程测量", "线路与桥隧测量", "WARN", "待定"),
# ---- 矿山 类 ----
"温岭市泽太采石场废弃矿山生态环境治理工程建筑用石料（凝灰岩": ("工程测量", "矿山测量", "WARN", "采石场治理"),
# ---- 房产 类 ----
"房产测绘": ("房产测绘", "房产测绘", "OK", ""),
"房产测量": ("房产测绘", "房产测绘", "OK", ""),
"房产实测": ("房产测绘", "房产测绘", "OK", ""),
"房产面积实测": ("房产测绘", "房产测绘", "OK", ""),
"房产面积测量": ("房产测绘", "房产测绘", "OK", ""),
"房测": ("房产测绘", "房产测绘", "OK", "简称"),
"房产预测": ("房产测绘", "房产测绘", "OK", ""),
"预测方案": ("房产测绘", "房产测绘", "WARN", "疑=房产预测"),
"面积测量": ("房产测绘", "房产测绘", "WARN", "未限定对象,待定"),
"分户面积测量": ("房产测绘", "房产测绘", "WARN", ""),
"房产分割测绘": ("房产测绘", "房产测绘", "WARN", ""),
"房产违章测量": ("房产测绘", "房产测绘", "WARN", ""),
"现状面积测量": ("房产测绘", "房产测绘", "WARN", "也可能=地形测量"),
"厂房面积测量": ("房产测绘", "房产测绘", "WARN", ""),
"水泥面积测量": ("房产测绘", "房产测绘", "WARN", "疑OCR残片"),
"工面积测量": ("房产测绘", "房产测绘", "WARN", "残片"),
# ---- 地籍 类 ----
"地籍测量": ("地籍测绘", "地籍测绘", "OK", ""),
"宗地测量": ("地籍测绘", "地籍测绘", "OK", ""),
"宗地角点测量": ("地籍测绘", "地籍测绘", "OK", ""),
"勘测定界": ("地籍测绘", "地籍测绘", "OK", ""),
"土地勘测定界": ("地籍测绘", "地籍测绘", "OK", ""),
"权属调查": ("地籍测绘", "地籍测绘", "OK", ""),
"权调": ("地籍测绘", "地籍测绘", "OK", "权属调查简称"),
"农转用权属调查": ("地籍测绘", "地籍测绘", "OK", ""),
"农房确权登记": ("地籍测绘", "地籍测绘", "OK", ""),
"分地测量": ("地籍测绘", "地籍测绘", "WARN", ""),
"违法用地测量": ("地籍测绘", "地籍测绘", "WARN", ""),
"出让测量": ("地籍测绘", "地籍测绘", "WARN", ""),
"供地测量": ("地籍测绘", "地籍测绘", "WARN", "也可能归非测绘(供地流程)"),
"调查": ("地籍测绘", "地籍测绘", "TODO", "单独'调查'无法判断"),
# ---- 航摄/遥感 类 ----
"航拍": ("测绘航空摄影", "无人飞行器航摄", "WARN", ""),
"航拍建模": ("测绘航空摄影", "无人飞行器航摄", "WARN", ""),
"航拍正射": ("测绘航空摄影", "无人飞行器航摄", "WARN", "也可能归摄影测量与遥感内业"),
"室内影像观测": ("摄影测量与遥感", "摄影测量与遥感外业", "WARN", "平台无同名子项,待定"),
"影像测量": ("摄影测量与遥感", "摄影测量与遥感外业", "WARN", ""),
# ---- GIS 数据类 ----
"数据处理": ("地理信息系统工程", "地理信息数据处理", "WARN", ""),
"入库": ("地理信息系统工程", "地理信息系统及数据库建设", "WARN", "也可能归非测绘"),
"不动产入库": ("地理信息系统工程", "地理信息系统及数据库建设", "WARN", ""),
"不动产数据入库": ("地理信息系统工程", "地理信息系统及数据库建设", "WARN", ""),
"办证数据入库": ("地理信息系统工程", "地理信息系统及数据库建设", "WARN", ""),
"管线入库": ("地理信息系统工程", "地理信息系统及数据库建设", "WARN", ""),
"房产数据录入": ("地理信息系统工程", "地理信息数据处理", "WARN", "纯录入,也可能=非测绘"),
"根据提供的清单完成相关企业范围勾绘": ("地理信息系统工程", "地理信息数据采集", "WARN", "勾绘范围图,待定"),
"输出成果图": ("地理信息系统工程", "地理信息数据处理", "TODO", "可能是任何项目的附带成果,待定"),
# ---- 非测绘 类 ----
"供地": ("非测绘", "", "OK", "用地流程,非测绘作业"),
"供地报告": ("非测绘", "", "OK", ""),
"预审": ("非测绘", "", "OK", "用地预审"),
"农转用报件": ("非测绘", "", "OK", ""),
"个人建房农转用": ("非测绘", "", "OK", ""),
"建设用地出让": ("非测绘", "", "OK", ""),
"选址": ("非测绘", "", "OK", ""),
"土地分割": ("非测绘", "", "OK", ""),
"地类分析": ("非测绘", "", "OK", ""),
"未办证房产备案": ("非测绘", "", "OK", ""),
"收回报告": ("非测绘", "", "WARN", ""),
"日照分析测量": ("非测绘", "", "WARN", "日照分析非测绘作业"),
"日照分析定界": ("非测绘", "", "WARN", ""),
"考古": ("非测绘", "", "WARN", ""),
"考古数据": ("非测绘", "", "WARN", ""),
"增量空间": ("非测绘", "", "WARN", "空间规划用语"),
"存量空间（批而未供": ("非测绘", "", "WARN", ""),
"低效用地": ("非测绘", "", "WARN", ""),
"转量空间": ("非测绘", "", "WARN", "疑OCR错字:增量空间"),
"拓量空间": ("非测绘", "", "WARN", ""),
"温岭市城北街道两高联络线城北枢纽区块农转用项具": ("非测绘", "", "WARN", "农转用"),
# ---- 残片 ----
"测量": ("", "", "TODO", "切分残片,无信息量"),
"测量等相关业务": ("", "", "TODO", "套话残片"),
"工程测量": ("", "", "TODO", "大类名,非具体作业项"),
"位置测量": ("", "", "TODO", "无主语"),
"预建位置测量": ("", "", "TODO", ""),
"特征点测量": ("", "", "TODO", ""),
"村部设计测量": ("", "", "TODO", ""),
}

# ============================================================
# 统计合同项实际出现次数
# ============================================================
cache = json.load(open(CACHE, encoding="utf-8"))
cnt = collections.Counter()
srcform = collections.defaultdict(set)   # 项名 -> 来源形态集合

for k, v in cache.items():
    t = v.get("text") or ""
    if re.search(r"【[√✓]", t):
        for m in re.finditer(r"([\u4e00-\u9fa5]{2,12})【([^】]{0,3})】", t):
            if m.group(2).strip() and any(c in m.group(2) for c in "√✓vV对Y"):
                cnt[m.group(1)] += 1
                srcform[m.group(1)].add("勾选清单")
    m2 = re.search(r"项目内容[：:]\s*([^\n]{2,80})", t)
    if m2:
        for seg in re.split(r"[、,，;；]", m2.group(1)):
            seg = seg.strip()
            if 2 <= len(seg) <= 12:
                cnt[seg] += 1
                srcform[seg].add("项目内容")

# 合并草稿里的历史计数(取大者,兼容L3/L4来的项)
old = os.path.join(HERE, "工程备案_子项映射表_待确认.csv.bak_20261013")
if os.path.exists(old):
    for r in csv.DictReader(open(old, encoding="utf-8-sig", newline="")):
        n = r["合同项名"]
        try: c = int(r["合同中出现次数"])
        except: c = 0
        if c > cnt.get(n, 0):
            cnt[n] = c

# 全覆盖: 旧表里有但M里没的也补进来
allnames = set(M) | set(cnt)
for n in allnames:
    if n not in M:
        M[n] = ("", "", "TODO", "未判定")

rows = []
for n in allnames:
    big, small, conf, note = M[n]
    rows.append({"名": n, "次": cnt.get(n, 0),
                 "大类": big, "子项": small,
                 "把握": {"OK": "✓", "WARN": "⚠️", "TODO": "❌"}.get(conf, "❌"),
                 "形态": "/".join(sorted(srcform.get(n, set()))),
                 "说明": note})
rows.sort(key=lambda r: (-r["次"], r["大类"], r["子项"], r["名"]))

# ---------- 写 CSV ----------
with open(CSV_OUT, "w", encoding="utf-8-sig", newline="") as f:
    w = csv.writer(f)
    w.writerow(["合同项名", "合同中出现次数", "来源", "拟-平台大类", "拟-平台子项",
                "把握", "改后大类", "改后子项", "备注"])
    for r in rows:
        w.writerow([r["名"], r["次"], r["形态"], r["大类"], r["子项"], r["把握"], "", "", r["说明"]])

# ---------- 统计 ----------
tot = len(rows); ok = sum(1 for r in rows if r["把握"] == "✓")
warn = sum(1 for r in rows if r["把握"] == "⚠️")
todo = sum(1 for r in rows if r["把握"] == "❌")
hit = sum(r["次"] for r in rows if r["次"])

# 按平台大类分组
groups = collections.defaultdict(list)
for r in rows:
    if r["大类"]:
        groups[r["大类"]].append(r)
ungrouped = [r for r in rows if not r["大类"]]

# ---------- 写 HTML ----------
def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))

CF = {"✓": ("#0a7d32", "#e6f6ec"), "⚠️": ("#a05a00", "#fdf3e2"), "❌": ("#b3261e", "#fdecea")}

plat_rows = ""
for t in TREE_DATA:
    subs = t.get("小类") or []
    subhtml = "".join(f'<span class="chip">{esc(s)}</span>' for s in subs) or '<span class="chip leaf">（叶子大类·无下级）</span>'
    n_map = len(groups.get(t["大类"], []))
    plat_rows += (f'<tr><td class="big">{esc(t["大类"])}</td>'
                  f'<td class="subs">{subhtml}</td>'
                  f'<td class="num">{len(subs)}</td>'
                  f'<td class="num">{n_map}</td></tr>')

map_rows = ""
for big in BIG_LIST:
    if big not in groups:
        continue
    items = groups[big]
    first = True
    # 按子项聚合
    bysub = collections.defaultdict(list)
    for r in items:
        bysub[r["子项"] or "（无子项·叶子大类）"].append(r)
    for sub, arr in sorted(bysub.items(), key=lambda x: -sum(i["次"] for i in x[1])):
        arr.sort(key=lambda r: -r["次"])
        for i, r in enumerate(arr):
            c, bg = CF[r["把握"]]
            bigcell = f'<td rowspan="{len(items)}" class="big">{esc(big)}</td>' if (first and i == 0) else ""
            subcell = ""
            if i == 0:
                subcell = f'<td rowspan="{len(arr)}" class="sub">{esc(sub)}</td>'
            map_rows += (f'<tr>{bigcell}{subcell}'
                         f'<td class="item">{esc(r["名"])}</td>'
                         f'<td class="num">{r["次"]}</td>'
                         f'<td class="src">{esc(r["形态"] or "-")}</td>'
                         f'<td class="conf" style="color:{c};background:{bg}">{r["把握"]}</td>'
                         f'<td class="note">{esc(r["说明"])}</td></tr>')
        first = False

# 未归类
ung_html = ""
for r in sorted(ungrouped, key=lambda r: -r["次"]):
    ungrouped_ok = True
    ung_html += (f'<tr><td class="item">{esc(r["名"])}</td><td class="num">{r["次"]}</td>'
                 f'<td class="src">{esc(r["形态"] or "-")}</td>'
                 f'<td class="note">{esc(r["说明"])}</td></tr>')

html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>合同项名 × 平台项目子项 对照表</title>
<style>
 *{{box-sizing:border-box}}
 body{{margin:0;padding:28px 34px 60px;background:#f6f7f9;color:#1f2328;
      font:14px/1.65 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif}}
 h1{{font-size:22px;margin:0 0 6px}}
 .meta{{color:#636c76;font-size:13px;margin-bottom:22px}}
 h2{{font-size:17px;margin:34px 0 12px;padding-left:10px;border-left:4px solid #3b6fd4}}
 .card{{background:#fff;border:1px solid #e3e6ea;border-radius:10px;padding:0;overflow:hidden;
        box-shadow:0 1px 2px rgba(16,24,40,.04)}}
 table{{width:100%;border-collapse:collapse;font-size:13.5px}}
 th{{background:#eef1f5;text-align:left;padding:9px 10px;font-weight:600;color:#3a4149;
     border-bottom:1px solid #dde1e6;position:sticky;top:0;z-index:2}}
 td{{padding:8px 10px;border-bottom:1px solid #eef0f3;vertical-align:top}}
 tr:hover td{{background:#fafbfd}}
 td.big{{font-weight:600;color:#1a3f8f;white-space:nowrap;background:#f8faff}}
 td.sub{{font-weight:600;white-space:nowrap}}
 td.item{{font-weight:500}}
 td.num{{text-align:right;font-variant-numeric:tabular-nums;color:#41474d}}
 td.src{{color:#7a828b;font-size:12.5px;white-space:nowrap}}
 td.note{{color:#6b727b;font-size:12.5px}}
 td.conf{{text-align:center;font-weight:700;border-radius:4px}}
 .chip{{display:inline-block;margin:2px 4px 2px 0;padding:1px 8px;border-radius:11px;
        background:#eef3fc;color:#26456f;border:1px solid #d6e2f5;font-size:12.5px;white-space:nowrap}}
 .chip.leaf{{background:#f2f4f6;color:#7a828b;border-color:#e3e6ea}}
 .kpi{{display:flex;gap:14px;flex-wrap:wrap;margin:0 0 6px}}
 .kpi div{{background:#fff;border:1px solid #e3e6ea;border-radius:10px;padding:12px 18px;min-width:120px}}
 .kpi b{{display:block;font-size:22px;line-height:1.3}}
 .kpi span{{color:#6b727b;font-size:12.5px}}
 .warnbox{{background:#fff8e6;border:1px solid #f0dfae;border-radius:9px;padding:14px 18px;margin:14px 0 0}}
 .warnbox b{{color:#8a5a00}}
 code{{background:#f1f3f5;padding:1px 5px;border-radius:4px;font-size:12.5px}}
</style></head><body>
<h1>合同项名 × 平台「项目类型」子项 对照表</h1>
<div class="meta">源：{len(cache)} 份合同 OCR 正文（勾选清单 +「项目内容」段） × 网页真实项目类型树（{len(TREE_DATA)} 大类 / {sum(len(t.get('小类') or []) for t in TREE_DATA)} 小类）</div>

<div class="kpi">
 <div><b>{tot}</b><span>合同项名总数</span></div>
 <div><b>{ok}</b><span>✓ 一一对应</span></div>
 <div><b>{warn}</b><span>⚠️ 平台无同名子项·就近挂</span></div>
 <div><b>{todo}</b><span>❌ 残片/无法判断</span></div>
 <div><b>{hit}</b><span>被引用总次数</span></div>
</div>

<h2>一、平台真实「项目类型」全表（{len(TREE_DATA)} 大类 / {sum(len(t.get('小类') or []) for t in TREE_DATA)} 小类）</h2>
<div class="card"><table>
<thead><tr><th style="width:150px">大类</th><th>小类（子项）</th><th style="width:60px">小类数</th><th style="width:110px">合同项挂靠数</th></tr></thead>
<tbody>{plat_rows}</tbody></table></div>

<h2>二、合同出现项 → 平台子项 对照（按平台大/小类归组）</h2>
<div class="card"><table>
<thead><tr><th style="width:110px">平台大类</th><th style="width:150px">平台子项</th><th style="width:220px">合同项名</th><th style="width:56px">次数</th><th style="width:96px">来源</th><th style="width:52px">把握</th><th>说明</th></tr></thead>
<tbody>{map_rows}</tbody></table></div>

<h2>三、❌ 未归类（切分残片 / 无主语，需人工或规则清掉）</h2>
<div class="card"><table>
<thead><tr><th style="width:220px">合同项名</th><th style="width:56px">次数</th><th style="width:96px">来源</th><th>说明</th></tr></thead>
<tbody>{ung_html}</tbody></table></div>

<div class="warnbox">
<b>关于「放样是不是控制测量」——不是。</b><br>
官方口径（测绘资质分类分级标准 · 工程测量 11 子项定义）：<br>
· <b>控制测量</b> = 在测区内测定一系列控制点的平面位置和高程、<b>建立测量控制网</b>，作为各项测量的基础；它是「施工放样和变形观测的<b>依据</b>」。<br>
· <b>建筑工程测量</b> = <b>施工放样</b>、安装测量、变形观测等建筑施工配套测量。<br>
· <b>规划测量</b> = 建筑放线、验线、<b>（规划）竣工测量</b>，规划审批的必备环节。<br>
所以控制测量与放样是「<b>做控制点</b>」vs「<b>用控制点</b>」的层级关系，不是同一回事；本表把纯「控制点引测/控制测量/水准点」挂 <code>控制测量</code>，把放样类挂 <code>建筑工程测量</code>。<br>
<b>一个真实的歧义点（需你按本地监管口径定）</b>：「红线放样 / 界址点放样 / 道路放线」这类<b>放线验线</b>，既可挂 <code>建筑工程测量</code>（施工放样），也可挂 <code>规划测量</code>（规划放线验线）或 <code>地籍测绘</code>（界址点）。表中已把这几条标 ⚠️。改法：直接在 CSV 的 <code>改后大类 / 改后子项</code> 两列填写。
</div>
</body></html>"""

open(HTML_OUT, "w", encoding="utf-8").write(html)

print("合同项名总数:", tot, "| OK:", ok, "WARN:", warn, "TODO:", todo)
print("CSV:", CSV_OUT)
print("HTML:", HTML_OUT)
print("\n各平台大类挂靠数:")
for big in BIG_LIST:
    if big in groups:
        print(f"  {big}: {len(groups[big])} 项 / {sum(r['次'] for r in groups[big])} 次")
print("未归类:", len(ungrouped))
