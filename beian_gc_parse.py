#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工程备案：合同全页 OCR → 分层判据解析（诊断版，只读不写回业务 CSV）。

判据优先级（2026-10-13 依 002 实证调整）：
  L4 「测绘费价格表」  表头 序号/项目内容/单价/单位/工程量/金额（元） → 项名 + 真实分项金额（最权威）
  L1 「第三条 测绘服务内容」 勾选清单 取【√】
  L2 「一、项目内容：」 顿号列举
  L3 「具体包括…等」 文字枚举
  L5 台账类别兜底

输出 _gc_layer_report.json + 控制台摘要，供人工复核与映射表补充。
"""
import os, re, json, csv, collections

HERE = os.path.dirname(os.path.abspath(__file__))
PAGES = os.path.join(HERE, '_gc_ocr_pages.json')
MAPCSV = os.path.join(HERE, '工程备案_子项映射表_定稿.csv')

CHECK = {'√', 'V', 'v', '✓', '✔'}


def norm(s):
    return re.sub(r'[\s【】（）()《》“”"\'\u3001\u3002\uff0c,.:：;；/\\\-—]+', '', s or '')


def load_map():
    m = {}
    with open(MAPCSV, encoding='utf-8-sig') as f:
        for r in csv.DictReader(f):
            k = norm(r['合同项名'])
            if not k:
                continue
            m[k] = (r['平台大类'].strip(), r['平台子项'].strip(), r['状态'].strip())
    return m


def page_lines(pg, ytol=14):
    """把一页的 items 按 y 聚成行；每行按 x 排序返回 [(x0,x1,text)]。"""
    items = sorted(pg['items'], key=lambda z: (z[1], z[0]))
    lines, cur, cy = [], [], None
    for x0, y0, x1, y1, t, s in items:
        if cy is None or abs(y0 - cy) <= ytol:
            cur.append([x0, x1, t])
            cy = y0 if cy is None else cy
        else:
            lines.append(sorted(cur, key=lambda z: z[0]))
            cur, cy = [[x0, x1, t]], y0
    if cur:
        lines.append(sorted(cur, key=lambda z: z[0]))
    return lines


def parse_l4_price_table(pages):
    """价格表：返回 ([(项名, 金额或None)], 合计或None)。找不到返回 (None, None)。"""
    for pg in pages:
        lines = page_lines(pg)
        hdr_i = None
        for i, ln in enumerate(lines):
            txts = [c[2] for c in ln]
            joined = ''.join(txts)
            if '项目内容' in joined and ('金额' in joined or '单价' in joined):
                hdr_i = i
                break
        if hdr_i is None:
            continue
        hdr = lines[hdr_i]
        col = {}
        for x0, x1, t in hdr:
            tt = t.strip()
            for name, kw in [('item', '项目内容'), ('qty', '工程量'), ('price', '单价'),
                             ('unit', '单位'), ('amt', '金额'), ('no', '序号')]:
                if kw in tt and name not in col:
                    col[name] = (x0 + x1) / 2.0
        if 'item' not in col:
            continue
        item_x = col['item']
        amt_x = col.get('amt')
        rows = []
        started = False
        for ln in lines[hdr_i + 1:]:
            # 行内拆 cell
            cells = [(float(c[0]), float(c[1]), c[2].strip()) for c in ln if c[2].strip()]
            if not cells:
                continue
            joined = ''.join(c[2] for c in cells)
            if '合计' in joined or '总计' in joined:
                nums = [c[2] for c in cells if re.fullmatch(r'[\d,\.]+', c[2])]
                return rows, (nums[0] if nums else None)
            if re.search(r'第[一二三四五六七八九十]+条', joined):
                break
            # 项名 = 最接近 item_x 的含中文 cell
            cand = [c for c in cells if re.search(r'[\u4e00-\u9fa5]', c[2]) and len(c[2]) >= 2]
            if not cand:
                continue
            name_cell = min(cand, key=lambda c: abs((c[0] + c[1]) / 2.0 - item_x))
            if abs((name_cell[0] + name_cell[1]) / 2.0 - item_x) > 260:
                continue
            name = name_cell[2]
            amt = None
            if amt_x is not None:
                nums = [c for c in cells if re.fullmatch(r'[\d,\.]+', c[2])
                        and c[0] > name_cell[1]]
                if nums:
                    pick = min(nums, key=lambda c: abs((c[0] + c[1]) / 2.0 - amt_x))
                    amt = pick[2]
            rows.append((name, amt))
            started = True
        if started:
            return rows, None
    return None, None


def parse_l1_checklist(pages):
    """勾选清单：返回 {项名: 标记字符}。"""
    out, seen = {}, False
    for pg in pages:
        for x0, y0, x1, y1, t, s in sorted(pg['items'], key=lambda z: z[1]):
            sx = t.strip()
            if '测绘服务内容' in sx:
                seen = True
                continue
            if not seen:
                continue
            if re.search(r'第[四五六七八九十]+条', sx) or '执行技术标准' in sx:
                break
            for m in re.finditer(r'(\d{1,2})\s*[.、]\s*([^\s【】\d][^【】\n]{0,20}?)\s*【\s*([^】\n]{0,6})\s*】', sx):
                out[m.group(2).strip()] = m.group(3).strip()
        if seen:
            break
    return out


def get_full_text(pages):
    parts = []
    for pg in pages:
        for ln in page_lines(pg):
            parts.append(''.join(c[2] for c in ln))
    return '\n'.join(parts)


def parse_l2(text):
    m = re.search(r'一[、.]\s*项目内容\s*[：:]\s*([^\n]{1,200})', text)
    if not m:
        return None
    raw = m.group(1)
    raw = re.split(r'\s*二[、.]|\s*项目要求', raw)[0]
    items = [x.strip() for x in re.split(r'[、,，;；/]', raw) if x.strip()]
    items = [re.sub(r'^[等和及与\s]+|[等\s]+$', '', x) for x in items]
    return [x for x in items if 1 < len(x) < 30] or None


def parse_l3(text):
    m = re.search(r'具体(?:包括|内容为|为)\s*[：:]?\s*([^\n。]{2,200})', text)
    if not m:
        return None
    raw = m.group(1)
    items = [x.strip() for x in re.split(r'[、,，;；/]|\s*和\s*|等', raw) if x.strip()]
    return [x for x in items if 1 < len(x) < 30] or None


def main():
    cache = json.load(open(PAGES, encoding='utf-8'))
    mp = load_map()
    print('OCR 缓存:', len(cache), '| 映射表项:', len(mp))

    stat = collections.Counter()
    l4_names = collections.Counter()
    all_l4 = {}
    for fn, rec in cache.items():
        if not rec.get('ok'):
            stat['OCR失败'] += 1
            continue
        pages = rec['pages']
        stat['合同'] += 1
        rows, total = parse_l4_price_table(pages)
        if rows:
            stat['L4价格表'] += 1
            if total:
                stat['L4带合计'] += 1
            all_l4[fn] = {'rows': rows, 'total': total}
            for n, a in rows:
                l4_names[norm(n)] += 1
        else:
            stat['无价格表'] += 1
        ck = parse_l1_checklist(pages)
        if ck:
            stat['L1有清单'] += 1
            if any(v in CHECK for v in ck.values()):
                stat['L1有勾'] += 1
        txt = get_full_text(pages)
        if parse_l2(txt):
            stat['L2项目内容'] += 1
        if parse_l3(txt):
            stat['L3具体包括'] += 1

    print()
    for k, v in stat.most_common():
        print('  %-12s %d' % (k, v))

    print()
    print('=== L4 价格表项名频次（未映射标 ✗）===')
    unmapped = []
    for n, c in l4_names.most_common():
        ok = n in mp
        if not ok:
            unmapped.append((n, c))
        print('  %-28s %4d %s' % (n[:28], c, '' if ok else '✗未映射'))

    json.dump({'stat': dict(stat), 'l4': all_l4,
               'l4_names': dict(l4_names), 'unmapped': unmapped},
              open(os.path.join(HERE, '_gc_layer_report.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)
    print()
    print('未映射项名数:', len(unmapped), '→ _gc_layer_report.json')


if __name__ == '__main__':
    main()
