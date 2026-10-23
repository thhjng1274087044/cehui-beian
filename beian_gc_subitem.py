#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工程备案：合同全页 OCR → 五层判据 → 平台项目类型（子项）+ 分项金额。

判据优先级（2026-10-13 依 002 实证重排）：
  L4「第五条 测绘工程费 / 测绘费价格表」表头 序号·项目内容·单价·单位·工程量·金额（元）
     → 项名 = 实际委托内容；金额 = 真实分项金额。**最权威**（勾选清单会漏项）
  L1「第三条 测绘服务内容」勾选清单，取【√】/V
  L2「一、项目内容：」顿号列举（143 份，词表与映射表 100% 对齐）
  L3「具体包括…等」文字枚举
  L5 台账类别兜底

映射：定稿映射表（161 已定 + 6 源端残片）→ 精确 → 去修饰 → 最长子串包含。
未命中项名收集进 _gc_subitem_report.json 待确认。

用法： python beian_gc_subitem.py [--dry]
输出： _gc_subitem_v2.json（逐合同解析）+ 控制台摘要
"""
import os, re, sys, json, csv, collections

HERE = os.path.dirname(os.path.abspath(__file__))
PAGES = os.path.join(HERE, '_gc_ocr_pages.json')
MAPCSV = os.path.join(HERE, '工程备案_子项映射表_定稿.csv')
REFINE = os.path.join(HERE, '工程备案_精修.csv')
OUTJ = os.path.join(HERE, '_gc_subitem_v2.json')

CHECK_MARKS = {'√', 'V', 'v', '✓', '✔'}
SLASH_MARKS = {'／', '/', '\\'}
NOISE = re.compile(r'^(工程量|单价|单位|序号|金额|项目内容|工程内容|项目名称|合计|总计|价格|'
                   r'小计|数量|面积|备注|总图|工日|名称|编号|地址|位置|标准)$')
# 表格下方正文/结算条款误入的名
NOISE2 = re.compile(r'人民币|元整|万元|结算清单|收费|发票|税|政策|大写|暂定|标准收费|￥|¥|'
                    r'协商|总金额|达到|不足|执行|支付|开具|凡张|并由|'
                    r'^工程量|^收取费用|^勘测报告')


def norm(s):
    return re.sub(r'[\s【】（）()《》“”"\'\u3001\u3002\uff0c,.:：;；/\\\-—–_]+', '', s or '')


def norm_id(s):
    return re.sub(r'[^0-9A-Za-z]', '', s or '').upper()


# ---------------- 映射表 ----------------
def load_map():
    m = {}
    with open(MAPCSV, encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            k = norm(r['合同项名'])
            if not k:
                continue
            st = r['状态'].strip()
            # ⚠️ 排除"源端残片"（测量/调查/工测量…）：它们是词表切分噪音、超短通用词，
            #    参与匹配会吃掉"海绵城市测量/XXX测量"等具体项 → 映射到非法"待定"大类。
            if '待定(需源端清理)' in st or '待定' in st:
                continue
            if not r['平台大类'].strip() or r['平台大类'].strip() == '待定':
                continue
            m[k] = {'大': r['平台大类'].strip(), '小': r['平台子项'].strip(),
                    '状态': st, '原件': r['合同项名']}
    return m


DEFUZZ = ['面积', '场地', '原始', '周边', '新增', '临时', '设计前', '竣工', '工程', '项目']


def lookup(name, MAP, KEYS_BY_LEN):
    """精确 → 去修饰 → 最长子串包含。返回 (大类, 子项, 命中方式, 命中键) 或 None"""
    k = norm(name)
    if not k or NOISE.match(k):
        return None
    if k in MAP:
        v = MAP[k]; return v['大'], v['小'], '精确', v['原件']
    k2 = k
    for d in DEFUZZ:
        k2 = k2.replace(d, '')
    if k2 and k2 in MAP:
        v = MAP[k2]; return v['大'], v['小'], '去修饰', v['原件']
    # 最长子串：映射键出现在项名里
    best = None
    for kk in KEYS_BY_LEN:
        if len(kk) >= 2 and kk in k:
            if best is None or len(kk) > len(best):
                best = kk
    if best:
        v = MAP[best]; return v['大'], v['小'], '子串', v['原件']
    return None


# ---------------- 版面 ----------------
def page_lines(pg, ytol=14):
    items = sorted(pg['items'], key=lambda z: (z[1], z[0]))
    lines, cur, cy = [], [], None
    for it in items:
        x0, y0 = it[0], it[1]
        if cy is None or abs(y0 - cy) <= ytol:
            cur.append([x0, it[2], it[4]])
            cy = y0 if cy is None else cy
        else:
            lines.append(sorted(cur, key=lambda z: z[0]))
            cur, cy = [[x0, it[2], it[4]]], y0
    if cur:
        lines.append(sorted(cur, key=lambda z: z[0]))
    return lines


def bad_name(n):
    """判断表格 cell 是否为合法"项目内容"项名。"""
    s = (n or '').strip()
    if len(s) < 2 or len(s) > 18:
        return True
    if NOISE.match(norm(s)) or NOISE2.search(s):
        return True
    if re.search(r'\d+\s*元', s) or re.fullmatch(r'[\d\.,]+', s):
        return True
    if re.match(r'^[A-Za-z]+\d+', s):            # 地块编号等（XH02030302地块）
        return True
    if not re.search(r'[\u4e00-\u9fa5]', s):      # 必须含中文
        return True
    # 表格碎片：以"和/及/与"开头、或含"元"结尾的计量单位
    if re.match(r'^[和及与的]', s) or re.search(r'元(宗|点|平方|米|工日|幅|个|台|次)?$', s):
        return True
    return False


def parse_l4(pages):
    """→ ([(项名, 金额str|None)], 合计str|None) 或 (None, None)"""
    for pg in pages:
        lines = page_lines(pg)
        hdr_i = None
        for i, ln in enumerate(lines):
            j = ''.join(c[2] for c in ln)
            if ('项目内容' in j or '工程内容' in j or '项目名称' in j) and \
               ('金额' in j or '总价' in j or '单价' in j or '费用' in j):
                hdr_i = i; break
        if hdr_i is None:
            continue
        hdr = lines[hdr_i]
        col = {}
        for x0, x1, t in hdr:
            for name, kw in [('item', '项目内容'), ('item2', '工程内容'), ('item3', '项目名称'),
                             ('qty', '工程量'), ('price', '单价'), ('unit', '单位'),
                             ('amt', '金额'), ('amt2', '总价'), ('amt3', '费用'), ('no', '序号')]:
                if kw in t and name not in col:
                    col[name] = (x0 + x1) / 2.0
        item_x = col.get('item') or col.get('item2') or col.get('item3')
        amt_x = col.get('amt') or col.get('amt2') or col.get('amt3')
        if item_x is None:
            continue
        rows, started = [], False
        for ln in lines[hdr_i + 1:]:
            cells = [(float(c[0]), float(c[1]), c[2].strip()) for c in ln if c[2].strip()]
            if not cells:
                continue
            j = ''.join(c[2] for c in cells)
            if '合计' in j or '总计' in j or '小计' in j:
                nums = [c[2] for c in cells if re.fullmatch(r'[\d,\.]+', c[2])]
                total = nums[0].replace(',', '') if nums else None
                if len(rows) >= 1:
                    return rows, total
                break
            if re.search(r'第[一二三四五六七八九十]+条', j):
                break
            cand = [c for c in cells if re.search(r'[\u4e00-\u9fa5]', c[2]) and len(c[2]) >= 2]
            if not cand:
                continue
            nc = min(cand, key=lambda c: abs((c[0] + c[1]) / 2.0 - item_x))
            if abs((nc[0] + nc[1]) / 2.0 - item_x) > 260:
                continue
            name = nc[2]
            if bad_name(name):
                continue
            amt = None
            if amt_x is not None:
                nums = [c for c in cells if re.fullmatch(r'[\d,\.]+', c[2]) and c[0] > nc[1]]
                if nums:
                    amt = min(nums, key=lambda c: abs((c[0] + c[1]) / 2.0 - amt_x))[2].replace(',', '')
            rows.append((name, amt)); started = True
        # 表格有效性：至少 2 行，且至少 1 行带金额数字（防"历史建筑清单"类误判）
        if started and len(rows) >= 2 and any(a for _, a in rows):
            return rows, None
    return None, None


def parse_l1(pages):
    """→ [(项名, 标记)]（含无框项标记''）"""
    out, seen = [], False
    for pg in pages:
        for it in sorted(pg['items'], key=lambda z: z[1]):
            sx = (it[4] or '').strip()
            if '测绘服务内容' in sx:
                seen = True; continue
            if not seen:
                continue
            if re.search(r'第[四五六七八九十]+条', sx) or '执行技术标准' in sx:
                break
            for m in re.finditer(r'(\d{1,2})\s*[.、]\s*([^\s【】\d][^【】\n]{0,20}?)\s*(?:【\s*([^】\n]{0,6})\s*】)?$', sx):
                nm = m.group(2).strip()
                mk = (m.group(3) or '').strip()
                if nm and not NOISE.match(norm(nm)):
                    out.append((nm, mk))
        if seen:
            break
    # 去重保序
    dedup, seen_n = [], set()
    for n, m in out:
        if n in seen_n:
            continue
        seen_n.add(n); dedup.append((n, m))
    return dedup


def get_text(pages):
    return '\n'.join(''.join(c[2] for c in ln) for pg in pages for ln in page_lines(pg))


def parse_l2(text):
    m = re.search(r'一[、.]\s*项目内容\s*[：:]\s*([^\n]{1,200})', text)
    if not m:
        return None
    raw = re.split(r'\s*二[、.]|\s*项目要求', m.group(1))[0]
    items = [re.sub(r'^[等和及与\s]+|[等\s]+$', '', x.strip())
             for x in re.split(r'[、,，;；/]', raw) if x.strip()]
    return [x for x in items if 1 < len(x) < 30] or None


def parse_l3(text):
    m = re.search(r'具体(?:包括|内容为|为)\s*[：:]?\s*([^\n。]{2,200})', text)
    if not m:
        return None
    items = [x.strip() for x in re.split(r'[、,，;；/]|\s*和\s*|等', m.group(1)) if x.strip()]
    return [x for x in items if 1 < len(x) < 30] or None


# ---------------- 主流程 ----------------
def main():
    dry = '--dry' in sys.argv
    cache = json.load(open(PAGES, encoding='utf-8'))
    MAP = load_map()
    KEYS_BY_LEN = sorted(MAP.keys(), key=len, reverse=True)
    print('OCR 缓存:', len(cache), '| 映射表项:', len(MAP))

    # PDF 索引（按归档号）
    idx_chht, idx_xdl = {}, {}
    for fn, rec in cache.items():
        nid = norm_id(fn)
        m = re.search(r'CHHT(\d{4})(\d{3})', nid)
        if m:
            idx_chht[(m.group(1), m.group(2))] = fn
        m = re.search(r'XDL(\d{4})(\d{3})', nid)
        if m:
            idx_xdl.setdefault((m.group(1), m.group(2)), fn)
    print('PDF 索引 CHHT:', len(idx_chht), '| XDL:', len(idx_xdl))

    # 精修 CSV 行 → PDF
    with open(REFINE, encoding='utf-8-sig') as f:
        rd = csv.DictReader(f); rows = list(rd); cols = rd.fieldnames
    print('精修行:', len(rows))

    def find_pdf(row):
        for cand in (row.get('匹配PDF', ''), row.get('合同号', '')):
            nid = norm_id(cand)
            m = re.search(r'CHHT(\d{4})(\d{3})', nid)
            if m and (m.group(1), m.group(2)) in idx_chht:
                return idx_chht[(m.group(1), m.group(2))]
            m = re.search(r'XDL(\d{4})(\d{3})', nid)
            if m and (m.group(1), m.group(2)) in idx_xdl:
                return idx_xdl[(m.group(1), m.group(2))]
        return None

    layer_stat = collections.Counter()
    unmapped = collections.Counter()
    results = {}
    no_pdf = 0
    for r in rows:
        cno = r['合同号']
        fn = find_pdf(r)
        if not fn:
            no_pdf += 1
            continue
        rec = cache[fn]
        if not rec.get('ok'):
            continue
        pages = rec['pages']
        text = get_text(pages)

        layer, items, l4rows, l4total, l1raw = None, [], None, None, None
        l4rows, l4total = parse_l4(pages)
        l1raw = parse_l1(pages)

        # ★ L4 自校验：价格表抽出的项名若不像测绘服务项（映射命中率过低），
        #   说明命中的是"历史建筑名录"之类的非服务清单 → 弃用，降级走下一层。
        if l4rows:
            hit = sum(1 for n, a in l4rows if lookup(n, MAP, KEYS_BY_LEN))
            if len(l4rows) >= 2 and hit / len(l4rows) >= 0.5:
                layer, items = 'L4价格表', [n for n, a in l4rows]
            else:
                layer_stat['L4自校验未过'] += 1
        if not items and l1raw and any(m in CHECK_MARKS for _, m in l1raw):
            layer, items = 'L1勾选', [n for n, m in l1raw if m in CHECK_MARKS]
        if not items:
            it2 = parse_l2(text)
            if it2:
                layer, items = 'L2项目内容', it2
        if not items:
            it3 = parse_l3(text)
            if it3:
                layer, items = 'L3枚举', it3
        if not items:
            layer = 'L5兜底'

        mapped, miss = [], []
        for nm in items:
            hit = lookup(nm, MAP, KEYS_BY_LEN)
            if hit:
                mapped.append({'原文': nm, '大': hit[0], '小': hit[1], '方式': hit[2], '键': hit[3]})
            else:
                miss.append(nm)
                unmapped[norm(nm)] += 1
        layer_stat[layer] += 1

        results[cno] = {
            'pdf': fn, 'layer': layer, 'items': items, 'mapped': mapped, 'miss': miss,
            'l4rows': l4rows, 'l4total': l4total,
            'l1': [{'项': n, '标记': m} for n, m in (l1raw or [])],
        }

    print()
    print('=== 判据层分布 ===')
    for k, v in layer_stat.most_common():
        print('  %-10s %d' % (k, v))
    print('未找到 PDF 的精修行:', no_pdf)

    print()
    print('=== L4 未映射项名（需确认映射）===')
    for k, c in unmapped.most_common(60):
        print('  %-28s %d' % (k[:28], c))

    json.dump({'layer_stat': dict(layer_stat), 'results': results,
               'unmapped': dict(unmapped)},
              open(OUTJ, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print()
    print('→', OUTJ)


if __name__ == '__main__':
    main()
