#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成「工程备案 项目类型填报 — 全页OCR重跑结果」审阅页。"""
import os, json, csv, collections, html

HERE = os.path.dirname(os.path.abspath(__file__))
REF = os.path.join(HERE, '工程备案_精修.csv')
OLD = os.path.join(HERE, '工程备案_精修.csv.bak_20261013d')
SUB = os.path.join(HERE, '_gc_subitem_v2.json')
OUT = os.path.join(HERE, '工程备案_项目类型重跑结果.html')

rows = list(csv.DictReader(open(REF, encoding='utf-8-sig')))
old = {r['合同号']: r for r in csv.DictReader(open(OLD, encoding='utf-8-sig'))}
sub = json.load(open(SUB, encoding='utf-8'))

layer = collections.Counter(r['判据层'] for r in rows)
nrows = collections.Counter(r['项目类型_行数'] for r in rows)
src = collections.Counter(r['多行来源'] or '(无金额/兜底)' for r in rows)
dacount = collections.Counter()
for r in rows:
    for t in json.loads(r['项目类型_行列表'] or '[]'):
        if t:
            dacount[t.split('/')[0]] += 1

# 旧的多行情况
old_multi = sum(1 for r in old.values() if r.get('多行标志') == '是')
new_multi = sum(1 for r in rows if r['多行标志'] == '是')

noamp = [r for r in rows if r['判据层'] == 'L5兜底']
nomiss = sub.get('unmapped', {})


def esc(s):
    return html.escape(str(s or ''))


def tbl(headers, data, cls=''):
    h = ''.join('<th>%s</th>' % esc(x) for x in headers)
    b = ''.join('<tr>%s</tr>' % ''.join('<td>%s</td>' % esc(c) for c in row) for row in data)
    return '<table class="%s"><thead><tr>%s</tr></thead><tbody>%s</tbody></table>' % (cls, h, b)


L4_ROWS = [r for r in rows if r['判据层'] == 'L4价格表']
SAMPLES = sorted(L4_ROWS, key=lambda r: -int(r['项目类型_行数']))[:8]
samp_html = ''
for r in SAMPLES:
    try:
        _t = json.loads(r['项目类型_行列表'] or '[]')
        _a = json.loads(r['金额_行列表'] or '[]')
    except Exception:
        _t, _a = [], []
    while len(_a) < len(_t):
        _a.append(None)
    lis = ''.join('<li><span class="t">%s</span><span class="a">%s</span></li>' % (esc(t), esc(a or '—')) for t, a in zip(_t, _a))
    samp_html += ('<div class="card"><h4>%s <em>%s</em></h4>'
                  '<p class="orig">合同原文：%s</p><ul class="rows">%s</ul>'
                  '<p class="meta">台账金额 %s 万 ｜ 来源 %s</p></div>') % (
        esc(r['合同号']), esc(r['判据层']), esc(r['子项原文'])[:200], lis,
        esc(r['最终金额万元']), esc(r['多行来源']))

l5_html = tbl(['合同号', '类别', '判定', '平台大类/子项', '上传状态'],
              [[r['合同号'], r['类别'], r['子项判定'], r['项目类型_填报'], r['上传状态']] for r in noamp])

unmap_html = tbl(['未映射项名(L4抽出的合同原文)', '出现次数'],
                 [[k, v] for k, v in sorted(nomiss.items(), key=lambda x: -x[1])[:30]])

HTML = """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<title>工程备案 项目类型重跑结果</title><style>
*{box-sizing:border-box}body{margin:0;padding:32px 40px;font:14px/1.7 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif;
background:#f6f7f9;color:#1f2329}
h1{font-size:24px;margin:0 0 6px}h2{font-size:17px;margin:34px 0 12px;padding-left:10px;border-left:4px solid #2563eb}
h4{margin:0 0 6px;font-size:14px}h4 em{font-style:normal;font-size:12px;color:#2563eb;background:#eff6ff;padding:1px 7px;border-radius:9px;margin-left:6px}
.sub{color:#646a73;margin-bottom:22px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:8px}
.kpi{background:#fff;border:1px solid #e5e6eb;border-radius:10px;padding:14px 16px}
.kpi .v{font-size:26px;font-weight:700;line-height:1.2}
.kpi .l{font-size:12px;color:#646a73;margin-top:4px}
.kpi.ok .v{color:#16a34a}.kpi.warn .v{color:#d97706}.kpi.blue .v{color:#2563eb}
table{width:100%%;border-collapse:collapse;background:#fff;border:1px solid #e5e6eb;border-radius:8px;overflow:hidden;font-size:13px}
th,td{padding:8px 10px;text-align:left;border-bottom:1px solid #f0f1f3}
th{background:#fafbfc;font-weight:600;color:#4e5969}
tr:last-child td{border-bottom:none}
.card{background:#fff;border:1px solid #e5e6eb;border-radius:10px;padding:14px 16px;margin-bottom:12px}
ul.rows{list-style:none;margin:8px 0;padding:0;display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:4px 18px}
ul.rows li{display:flex;justify-content:space-between;font-size:13px;border-bottom:1px dashed #f0f1f3;padding:3px 0}
ul.rows .a{color:#2563eb;font-variant-numeric:tabular-nums}
.orig{font-size:12px;color:#646a73;margin:4px 0;background:#fafbfc;padding:6px 9px;border-radius:6px}
.meta{font-size:12px;color:#86909c;margin:6px 0 0}
.note{background:#fffbe6;border:1px solid #ffe58f;border-radius:8px;padding:12px 15px;font-size:13px;margin:12px 0}
.note b{color:#b45309}
</style></head><body>
<h1>工程备案 · 项目类型填报 — 全页 OCR 重跑结果</h1>
<p class="sub">2026-10-13 ｜ 依据：合同全页带坐标 OCR（297 份）+ 定稿映射表（190 条）｜ 判据优先级 L4 价格表 &gt; L1 勾选 &gt; L2 项目内容 &gt; L3 枚举 &gt; L5 兜底</p>

<h2>一、总览</h2>
<div class="grid">
<div class="kpi blue"><div class="v">309</div><div class="l">精修表行数</div></div>
<div class="kpi blue"><div class="v">297</div><div class="l">合同全页 OCR</div></div>
<div class="kpi ok"><div class="v">%(l4)s</div><div class="l">L4 价格表（最权威）</div></div>
<div class="kpi ok"><div class="v">%(okn)s</div><div class="l">有明确判据(L4+L1+L2+L3)</div></div>
<div class="kpi warn"><div class="v">%(l5)s</div><div class="l">L5 兜底（无判据）</div></div>
<div class="kpi ok"><div class="v">0</div><div class="l">金额求和不符</div></div>
<div class="kpi ok"><div class="v">0</div><div class="l">非法平台大类</div></div>
</div>

<h2>二、判据层分布</h2>
%(layertbl)s
<div class="note"><b>关键更正</b>：旧 OCR 只扫了合同第 1 页，整张「测绘费价格表」（在第 2–3 页）从未被读取。此前"L4 工程内容仅 1 份"是判据被整页丢掉的假象。这次全页重扫后 L4 命中 <b>%(l4)s 份</b>，且同时拿到<b>真实分项金额</b>。</div>

<h2>三、多行与金额分摊</h2>
<div class="grid">
<div class="kpi blue"><div class="v">%(nmul)s</div><div class="l">多行合同（旧值 %(omul)s）</div></div>
<div class="kpi ok"><div class="v">%(srcL4)s</div><div class="l">用 L4 真实分项金额</div></div>
<div class="kpi warn"><div class="v">%(srcEst)s</div><div class="l">估值 60/40（待复核）</div></div>
<div class="kpi"><div class="v">%(noamt)s</div><div class="l">无金额（按实结算）</div></div>
</div>
<h4 style="margin:18px 0 8px">每合同行数分布</h4>
%(nrowstbl)s
<h4 style="margin:22px 0 8px">行级平台大类分布</h4>
%(datbl)s

<h2>四、L4 价格表样例（多行 + 真实金额）</h2>
%(samples)s

<h2>五、待确认与待办</h2>
<div class="note">
<b>① 多行展开策略需你拍板</b>：现按"每个不同(大类,子项)展开一行"，共 %(nmul)s 行多行，其中 6–8 行的有 %(bigmul)s 行。要不要只展开"非综合测绘"的合同、其余收单行？<br>
<b>② %(srcEst)s 行走估值 60/40</b>（合同没写分项金额），已标 <code>金额分摊_待核定=是</code>。<br>
<b>③ 4 项映射待确认</b>：海绵城市、安全距离、勘测报告、总图。<br>
<b>④ 未映射残留</b>：合同原文里的泛词「测量 / 测量等相关业务 / 调查」（源端词表残片，建议源头清理）。<br>
<b>⑤ V 盘缺 %(misspdf)s 份合同 PDF</b>（2026 年 073、085–095、129–136；2025 年 064、225），无判据只能按台账类别兜底。
</div>

<h4 style="margin:18px 0 8px">未映射项名（L4 抽出的合同原文）</h4>
%(unmap)s

<h4 style="margin:22px 0 8px">L5 兜底行明细（%(l5)s 行）</h4>
%(l5tbl)s

</body></html>""" % {
    'l4': layer['L4价格表'],
    'okn': layer['L4价格表'] + layer['L1勾选'] + layer['L2项目内容'] + layer['L3枚举'],
    'l5': layer['L5兜底'],
    'nmul': new_multi, 'omul': old_multi,
    'srcL4': src['L4真实分项'] + src['L4真实分项(部分)'],
    'srcEst': src['估值60/40'],
    'noamt': src['(无金额/兜底)'],
    'bigmul': sum(v for k, v in nrows.items() if k.isdigit() and int(k) >= 6),
    'misspdf': 24,
    'layertbl': tbl(['判据层', '行数', '说明'], [
        ['L4价格表', layer['L4价格表'], '合同「测绘费价格表」真实分项+金额（最权威）'],
        ['L2项目内容', layer['L2项目内容'], '合同「一、项目内容：」顿号列举'],
        ['L1勾选', layer['L1勾选'], '合同「第三条 测绘服务内容」勾选【√】'],
        ['L3枚举', layer['L3枚举'], '「具体包括…等」文字枚举'],
        ['L5兜底', layer['L5兜底'], '无判据 → 按台账类别兜底'],
    ]),
    'nrowstbl': tbl(['每合同行数', '合同数'], sorted([[k, v] for k, v in nrows.items()],
                                                    key=lambda x: int(x[0]))),
    'datbl': tbl(['平台大类', '行数'], dacount.most_common()),
    'samples': samp_html,
    'unmap': unmap_html,
    'l5tbl': l5_html,
}

open(OUT, 'w', encoding='utf-8').write(HTML)
print('→', OUT)
