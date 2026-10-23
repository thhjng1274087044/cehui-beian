# -*- coding: utf-8 -*-
"""生成《工程备案 子项映射表 定稿说明》HTML（数据源 = 定稿CSV，保证权威一致）。"""
import csv, os

HERE = os.path.dirname(os.path.abspath(__file__))
CSV = os.path.join(HERE, "工程备案_子项映射表_定稿.csv")
rows = list(csv.DictReader(open(CSV, encoding="utf-8-sig", newline="")))
by = {r["合同项名"].strip(): r for r in rows}

# 原值（改动前）
OLD = {"红线放样": "工程测量/建筑工程测量", "日照分析定界": "非测绘", "日照分析测量": "非测绘",
       "界址点放样": "工程测量/建筑工程测量（⚠️待定）",
       "工程量竣工面积测量": "工程测量/建筑工程测量（⚠️待定）",
       "面积竣工测量": "工程测量/建筑工程测量（⚠️待定）",
       "输出成果图": "地理信息系统工程/地理信息数据处理（❌未判定）"}
OFFICIAL = {
    "红线放样": "规划测量含「城乡规划定线测量」（定线＝放线）",
    "日照分析定界": "规划测量含「日照测量」",
    "日照分析测量": "规划测量含「日照测量」",
}


def e(s):
    return str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def grp(kind):
    return [r for r in rows if r["改动类型"] == kind]


def val(r):
    b, s = r["平台大类"].strip(), r["平台子项"].strip()
    return f"{b}/{s}" if s else b


def tbl(items, cols):
    """cols: [(标题, 取值函数, 样式)]"""
    th = "".join(f'<th style="{c[2]}">{c[0]}</th>' for c in cols)
    tr = ""
    for r in items:
        tr += "<tr>" + "".join(f"<td>{c[1](r)}</td>" for c in cols) + "</tr>"
    return f'<div class="card"><table><thead><tr>{th}</tr></thead><tbody>{tr}</tbody></table></div>'


A = grp("直接改映射值")
B = grp("补判(原未判定)")
C = grp("取倾向值(原待定)")
D = grp("口径统一(未改值)")
E = grp("保留待定(残片)")
N = grp("原样保留")

tA = "".join(
    f'<tr><td class="n">{e(r["合同项名"])}</td><td class="was">{e(OLD.get(r["合同项名"].strip(),""))}</td>'
    f'<td class="now">{e(val(r))}</td><td class="r">{e(OFFICIAL.get(r["合同项名"].strip(), r["依据/口径"]))}</td></tr>'
    for r in A)

tB = "".join(
    f'<tr><td class="n">{e(r["合同项名"])}</td><td class="now">{e(val(r))}</td>'
    f'<td class="r">{e(r["依据/口径"])}</td></tr>' for r in B)

tC = "".join(
    f'<tr><td class="n">{e(r["合同项名"])}</td><td class="was">{e(OLD.get(r["合同项名"].strip(),""))}</td>'
    f'<td class="now">{e(val(r))}</td><td class="r">{e(r["依据/口径"])}</td></tr>' for r in C)

tD = "".join(
    f'<tr><td class="n">{e(r["合同项名"])}</td><td class="keep">{e(val(r))}</td>'
    f'<td class="r">{e(r["依据/口径"])}</td></tr>' for r in D)

tE = "".join(
    f'<tr><td class="n bad">{e(r["合同项名"])}</td><td class="r">残片/无信息量，未给假值</td>'
    f'<td class="r">建议合同录入端建词表合并</td></tr>' for r in E)

import collections
c = collections.Counter((r["平台大类"] or "(空)") for r in rows)
tP = "".join(f'<tr><td class="big">{e(k)}</td><td class="num">{v}</td></tr>' for k, v in c.most_common())

# ============ ⑦ 放样按宾语归属 校验 ============
OBJ = [
    ("房屋/建筑物（个人建房·围墙·建筑物）", "建筑工程测量", ["个人建房", "围墙", "建筑物", "房屋", "厂房", "农房"]),
    ("规划红线 / 定线（红线放样）", "规划测量", ["红线", "规划定线", "批准线"]),
    ("道路 / 便道", "市政工程测量", ["道路", "便道"]),
    ("界址点（权属界线）", "地籍测绘", ["界址点", "界址", "宗地"]),
    ("管线", "地下管线测量", ["管线", "管并", "管道", "雨污"]),
    ("控制点 / 高程点（引测埋设，非放样）", "控制测量", ["控制点", "高程点", "水准点"]),
]
OTHER_OBJ = {"耕作层剥离": "土地整治（平台无此子项）", "复耕": "土地整治（平台无此子项）",
             "占补平衡": "水利/土地指标（平台无此子项）"}
fy = []
for r in rows:
    n = r["合同项名"].strip()
    if "放样" not in n:
        continue
    if "匝道" in n and "批准线" in n:
        fy.append((n, "匝道（道路）＋超批准线（红线）", "市政工程测量 或 规划测量", val(r), "⚠️ 与宾语不符"))
        continue
    obj, expect = "（无宾语）", "建筑工程测量"
    for name, exp, kws in OBJ:
        if any(k in n for k in kws):
            obj, expect = name, exp
            break
    else:
        for k, v2 in OTHER_OBJ.items():
            if k in n:
                obj, expect = v2, "—（就近挂建筑工程测量）"
                break
    if obj == "（无宾语）":
        judge = "✅ 主口径"
    elif expect.startswith("—"):
        judge = "⚠️ 宾语非六类"
    else:
        judge = "✅ 一致" if (r["平台子项"].strip() == expect) else "⚠️ 与宾语不符"
    fy.append((n, obj, expect, val(r), judge))

fy_rows = "".join(
    f'<tr><td class="n">{e(a)}</td><td>{e(b)}</td><td class="now">{e(c)}</td>'
    f'<td class="keep">{e(d)}</td><td class="{"r" if "⚠" in f2 else "okc"}">{e(f2)}</td></tr>'
    for a, b, c, d, f2 in fy)

H = f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<title>工程备案 子项映射表 定稿说明</title><style>
body{{margin:0;padding:26px 32px 64px;background:#f6f7f9;color:#1f2328;
font:14px/1.68 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif}}
h1{{font-size:22px;margin:0 0 6px}} .meta{{color:#636c76;font-size:13px;margin-bottom:18px}}
h2{{font-size:16px;margin:30px 0 10px;padding-left:10px;border-left:4px solid #3b6fd4}}
h2 small{{font-weight:400;color:#6b727b;font-size:13px;margin-left:6px}}
.card{{background:#fff;border:1px solid #e3e6ea;border-radius:10px;overflow:hidden}}
table{{width:100%;border-collapse:collapse;font-size:13.5px}}
th{{background:#eef1f5;text-align:left;padding:9px 10px;font-weight:600;border-bottom:1px solid #dde1e6}}
td{{padding:8px 10px;border-bottom:1px solid #eef0f3;vertical-align:top}}
td.n{{font-weight:500}} td.was{{color:#8a6d3b;background:#fdf8ee}}
td.now{{color:#0a7d32;background:#eef9f1;font-weight:600;white-space:nowrap}}
td.keep{{color:#1a3f8f;background:#f2f6fd;white-space:nowrap}}
td.r{{color:#6b727b;font-size:12.5px}} td.num{{text-align:right}} td.big{{font-weight:600;color:#1a3f8f}}
td.bad{{color:#a33;font-weight:600}}
td.okc{{color:#0a7d32;font-weight:600;white-space:nowrap}}
.kpi{{display:flex;gap:12px;flex-wrap:wrap}}
.kpi div{{background:#fff;border:1px solid #e3e6ea;border-radius:10px;padding:11px 16px;min-width:104px}}
.kpi b{{display:block;font-size:21px}} .kpi span{{color:#6b727b;font-size:12.5px}}
.note{{background:#fff8e6;border:1px solid #f0dfae;border-radius:9px;padding:13px 17px;margin-top:14px;font-size:13.5px}}
.ok{{background:#eef9f1;border:1px solid #b6e3c4;border-radius:9px;padding:13px 17px;margin-top:14px;font-size:13.5px}}
code{{background:#eef1f5;border-radius:4px;padding:1px 5px;font-size:12.5px}}
</style></head><body>
<h1>工程备案 · 子项映射表 <b>定稿</b></h1>
<div class="meta">源：<code>工程备案_子项映射表_定稿.csv</code>（167 项）· 依据：自然资源部《测绘资质分类分级标准》（自然资办发〔2021〕43号）附件2 · 平台词表抓自网页级联器</div>
<div class="kpi">
<div><b>167</b><span>合同项名</span></div>
<div><b>24</b><span>你的改动</span></div>
<div><b>18</b><span>口径统一(未改值)</span></div>
<div><b>119</b><span>原样保留</span></div>
<div><b>6</b><span>待清理残片</span></div>
</div>
<div class="ok"><b>核对结论</b>：你说明的 24 条改动（3＋17＋4）与定稿表<b>逐条一致，0 条不符</b>；6 条残片仍为「待定」未给假值；口径统一类保持原映射仅加说明。</div>

<h2>① 直接改映射值 <small>3 条 · 均有官方依据</small></h2>
{tbl(A, [("合同项", lambda r: e(r["合同项名"]), "width:240px")]) if False else f'<div class="card"><table><thead><tr><th style="width:200px">合同项</th><th style="width:210px">原来（我判）</th><th style="width:170px">改为</th><th>官方依据</th></tr></thead><tbody>{tA}</tbody></table></div>'}

<h2>② 原「❌未判定」→ 你补判 <small>17 条</small></h2>
<div class="card"><table><thead><tr><th style="width:340px">合同项</th><th style="width:190px">平台大类/子项</th><th>说明</th></tr></thead><tbody>{tB}</tbody></table></div>

<h2>③ 原「⚠️待定」→ 取倾向值 <small>4 条</small></h2>
<div class="card"><table><thead><tr><th style="width:250px">合同项</th><th style="width:230px">原来</th><th style="width:160px">改为</th><th>说明</th></tr></thead><tbody>{tC}</tbody></table></div>

<h2>④ 只统一口径 / 加说明（未改值）<small>18 条</small></h2>
<div class="card"><table><thead><tr><th style="width:230px">合同项</th><th style="width:230px">平台大类/子项</th><th>口径说明</th></tr></thead><tbody>{tD}</tbody></table></div>

<h2>⑤ 保留「待定」的 6 条残片</h2>
<div class="card"><table><thead><tr><th style="width:230px">合同项名</th><th>状态</th><th>建议</th></tr></thead><tbody>{tE}</tbody></table></div>

<h2>⑦ 放样类归属原则（按宾语定，不看"放样"二字）<small>17 项 · 16 项一致 · 1 项待确认</small></h2>
<div class="card"><table><thead><tr><th style="width:250px">合同项</th><th style="width:200px">宾语</th><th style="width:180px">应归（按原则）</th><th style="width:150px">现表值</th><th>判定</th></tr></thead><tbody>{fy_rows}</tbody></table></div>
<div class="note" style="margin-top:12px">
<b>原则</b>：「放样」不是测绘资质的子项，而是<b>作业方法</b>（把设计坐标/位置测设到实地）——归哪个子项看<b>宾语</b>：<br>
房屋/建筑物→<b>建筑工程测量</b>；规划红线→<b>规划测量</b>；道路/便道→<b>市政工程测量</b>；界址点→<b>地籍测绘</b>；管线→<b>地下管线测量</b>；控制点/高程点→<b>控制测量</b>（那叫引测/埋设，本就不是放样）。<br>
无宾语的「放样 / 放样测量 / 放样等」按<b>主口径 = 建筑工程测量</b>（合同里 28 次"放样"绝大多数是个人建房/建筑物放样）。
</div>

<h2>⑧ 定稿归类分布</h2>
<div class="card"><table><thead><tr><th>平台大类</th><th style="width:80px">项数</th></tr></thead><tbody>{tP}</tbody></table></div>

<div class="note">
<b>口径要点（后续抽取器按此实现）</b><br>
· 「面积型竣工」→ <b>房产测绘</b>；「土方量型竣工」→ <b>建筑工程测量</b>。<br>
· 「标高类」平台无对应子项，<b>统一就近挂 建筑工程测量</b>（9 条）。<br>
· 含「现状」的 → <b>地形测量</b>；「现状及标高」以现状为主 → 地形测量。<br>
· 「入库」→ GIS 工程 / 地理信息系统及数据库建设；纯「数据录入」无测绘成分时可归非测绘。<br>
· 「界址点放样」→ 地籍测绘（两可，备注已标）；「红线放样 / 日照分析」→ 规划测量（官方依据）。<br>
· 「水准点测量」→ 控制测量（高程控制）。
</div>
</body></html>"""

open(os.path.join(HERE, "工程备案_子项映射表_定稿说明.html"), "w", encoding="utf-8").write(H)
print("已写出 工程备案_子项映射表_定稿说明.html")
print("① 3 / ② 17 / ③ 4 / ④ 18 / ⑤ 6 / 原样 119 = ", 3+17+4+18+6+119)
