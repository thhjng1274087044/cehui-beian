#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工程备案：把五层判据结果（_gc_subitem_v2.json）写回 工程备案_精修.csv，
并重算「项目类型行 × 金额分摊」。

规则：
- 平台大类/子项：来自映射表逐项换算；(大类,子项) 去重保序。
- 单行：唯一 (大类,子项) → 全额。
- 多行：多个 (大类,子项) → 展开；
    金额优先用 L4「测绘费价格表」真实分项金额（元→万元，截断 4 位）
    否则主子项 60% + 其余均摊 40%（末项修正使求和 = 台账打折后万元）。
- 无 PDF 的行走台账类别兜底（标 L5兜底(无合同PDF)）。
只改本副本 CSV，源 PDF/OCR 缓存不动。
"""
import os, re, json, csv, collections

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, '_gc_subitem_v2.json')
REFINE = os.path.join(HERE, '工程备案_精修.csv')

CAT_FALLBACK = [
    (['综合测绘', '工程测绘', '工程测量'], ('工程测量', '建筑工程测量')),
    (['不动产测绘', '房产'], ('房产测绘', '房产测绘')),
    (['地籍'], ('地籍测绘', '地籍测绘')),
    (['用地报批', '农转用', '征收'], ('非测绘', '')),
    (['技术服务', '资料整理', '录入', '数据'], ('非测绘', '')),
    (['新型测绘', '测绘航空', '摄影测量'], ('非测绘', '')),
]


def wan(yuan):
    """元 → 万元，截断 4 位（不四舍五入）。"""
    try:
        v = float(yuan)
    except Exception:
        return None
    return int(v / 10000.0 * 10000) / 10000.0


def trunc4(v):
    return int(v * 10000) / 10000.0


def main():
    data = json.load(open(SRC, encoding='utf-8'))
    res = data['results']

    with open(REFINE, encoding='utf-8-sig') as f:
        rd = csv.DictReader(f); rows = list(rd); cols = list(rd.fieldnames)
    for c in ['判据层', '子项原文', 'L4分项金额', 'L4合计', '多行来源']:
        if c not in cols:
            cols.append(c)

    layer_stat = collections.Counter()
    multi = 0
    for r in rows:
        cno = r['合同号']
        rec = res.get(cno)
        total_wan = None
        for k in ('最终金额万元', '打折后万元'):
            s = (r.get(k) or '').strip()
            if s:
                try:
                    total_wan = float(s); break
                except Exception:
                    pass

        if not rec:
            # 无合同 PDF → 台账类别兜底
            cat = (r.get('类别') or r.get('OCR类别') or '').strip()
            da, xiao = '', ''
            for kws, mp in CAT_FALLBACK:
                if any(k in cat for k in kws):
                    da, xiao = mp; break
            if da:
                r['平台大类'], r['平台子项'] = da, xiao
                r['子项判定'] = 'L5兜底(无合同PDF)'
                r['判据层'] = 'L5兜底'
                r['子项原文'] = ''
            else:
                r['子项判定'] = 'L5兜底(无合同PDF,类别空)'
                r['判据层'] = 'L5兜底'
                r['平台大类'], r['平台子项'] = '', ''
            r['L4分项金额'], r['L4合计'], r['多行来源'] = '', '', ''
            _amt = '' if total_wan in (None, 0) else ('%.4f' % trunc4(total_wan))
            _typ = ('%s/%s' % (da, xiao)) if da else ''
            r['项目类型_行列表'] = json.dumps([_typ] if _typ else [], ensure_ascii=False)
            r['金额_行列表'] = json.dumps([_amt or None], ensure_ascii=False)
            r['项目类型_行数'] = '1'
            r['多行标志'] = '否'
            r['金额分摊_待核定'] = ''
            r['分摊说明'] = 'L5兜底单行(无合同PDF)'
            r['项目类型_填报'] = _typ
            layer_stat['L5兜底'] += 1
        else:
            layer = rec['layer']
            mapped = rec['mapped']
            r['判据层'] = layer
            r['子项判定'] = layer
            r['子项原文'] = '; '.join(rec['items'])
            # 去重保序
            uniq = []
            for m in mapped:
                key = (m['大'], m['小'])
                if key not in uniq:
                    uniq.append(key)
            if layer == 'L5兜底' or not uniq:
                cat = (r.get('类别') or r.get('OCR类别') or '').strip()
                for kws, mp in CAT_FALLBACK:
                    if any(k in cat for k in kws):
                        uniq = [mp]; break
                r['子项判定'] = 'L5兜底' + ('(类别)' if uniq else '(类别空)')
            r['平台大类'] = '; '.join(u[0] for u in uniq)
            r['平台子项'] = '; '.join(u[1] for u in uniq)

            l4 = rec.get('l4rows') or []
            r['L4分项金额'] = json.dumps(l4, ensure_ascii=False) if l4 else ''
            r['L4合计'] = rec.get('l4total') or ''
            layer_stat[layer] += 1

            # ---- 多行 + 金额 ----
            if len(uniq) <= 1:
                r['项目类型_行数'] = '1'
                r['多行标志'] = '否'
                r['多行来源'] = '单行'
                amt = '' if total_wan in (None, 0) else ('%.4f' % trunc4(total_wan))
                _t0 = ('%s/%s' % uniq[0]) if uniq else ''
                r['项目类型_行列表'] = json.dumps([_t0] if _t0 else [], ensure_ascii=False)
                r['金额_行列表'] = json.dumps([amt or None], ensure_ascii=False)
                r['金额分摊_待核定'] = ''
                r['分摊说明'] = '单行全额'
            else:
                multi += 1
                # 把 L4 行对回 uniq：按映射项"原文"匹配，同子项金额累加
                keyamt = {}
                for m in mapped:
                    for n, a in l4:
                        if m['原文'] == n and a:
                            try:
                                k = (m['大'], m['小'])
                                keyamt[k] = keyamt.get(k, 0.0) + float(a)
                            except Exception:
                                pass
                # 主子项：非测绘排最后，其余按金额大→小（无金额则保序）
                uniq_sorted = sorted(
                    uniq,
                    key=lambda u: (u[0] == '非测绘', -keyamt.get(u, 0.0)))
                if keyamt:
                    src = 'L4真实分项' if len(keyamt) == len(uniq) else 'L4真实分项(部分)'
                    # 缺金额的项按已有项均值补
                    if len(keyamt) < len(uniq):
                        avg = sum(keyamt.values()) / len(keyamt)
                        for u in uniq:
                            keyamt.setdefault(u, avg)
                else:
                    src = '估值60/40'
                r['多行来源'] = src
                items_out = []
                if src.startswith('L4真实分项') and total_wan:
                    s = sum(keyamt.values()) or 1.0
                    running = 0.0
                    for i, u in enumerate(uniq_sorted):
                        if i == len(uniq_sorted) - 1:
                            w = trunc4(total_wan - running)
                        else:
                            w = trunc4(keyamt[u] / s * total_wan)
                            running = trunc4(running + w)
                        items_out.append({'类型': '%s/%s' % u, '金额': '%.4f' % w})
                elif total_wan:
                    # 主子项 60%，其余均摊 40%
                    main = uniq_sorted[0]
                    m_amt = trunc4(total_wan * 0.6)
                    rest = trunc4(total_wan - m_amt)
                    each = trunc4(rest / (len(uniq_sorted) - 1))
                    running = m_amt
                    for i, u in enumerate(uniq_sorted):
                        if i == 0:
                            w = m_amt
                        elif i == len(uniq_sorted) - 1:
                            w = trunc4(total_wan - running)
                        else:
                            w = each
                            running = trunc4(running + w)
                        items_out.append({'类型': '%s/%s' % u, '金额': '%.4f' % w})
                else:
                    for u in uniq_sorted:
                        items_out.append({'类型': '%s/%s' % u, '金额': ''})
                r['项目类型_行数'] = str(len(uniq_sorted))
                r['多行标志'] = '是' if len(uniq_sorted) > 1 else '否'
                # ⚠️ 格式对齐 beian_form_mapper._generate_gc_form_data：
                #    项目类型_行列表 = 类型字符串列表；金额_行列表 = 同长度金额（空金额用 None）
                r['项目类型_行列表'] = json.dumps([x['类型'] for x in items_out], ensure_ascii=False)
                r['金额_行列表'] = json.dumps([(x['金额'] or None) for x in items_out], ensure_ascii=False)
                r['金额分摊_待核定'] = '是' if src == '估值60/40' else ''
                r['分摊说明'] = '%d项；%s；主子项=%s' % (len(uniq_sorted), src, uniq_sorted[0][1])

            # 主字段 = 首行
            try:
                rl = json.loads(r['项目类型_行列表'] or '[]')
                r['项目类型_填报'] = rl[0] if rl else ''
            except Exception:
                r['项目类型_填报'] = ''

    with open(REFINE, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, '') for k in cols})

    print('写回行数:', len(rows), '| 列数:', len(cols))
    print('判据层分布:', dict(layer_stat))
    mc = collections.Counter(r['多行标志'] for r in rows)
    print('多行标志:', dict(mc))
    print('多行行数分布:', dict(collections.Counter(r['项目类型_行数'] for r in rows)))
    print('多行来源:', dict(collections.Counter(r['多行来源'] for r in rows)))
    print('金额分摊待核定:', dict(collections.Counter(r['金额分摊_待核定'] for r in rows)))


if __name__ == '__main__':
    main()
