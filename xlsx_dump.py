#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""纯标准库 xlsx 读取器（修正版）：递归查找 sheets，兼容 WPS 的 mc:AlternateContent 包裹。"""
import sys, zipfile, re
import xml.etree.ElementTree as ET

NS = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
RNS = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'

def col_to_num(col):
    n = 0
    for c in col:
        n = n * 26 + (ord(c) - ord('A') + 1)
    return n

def load(path):
    z = zipfile.ZipFile(path)
    shared = []
    if 'xl/sharedStrings.xml' in z.namelist():
        root = ET.fromstring(z.read('xl/sharedStrings.xml'))
        for si in root.findall(f'{NS}si'):
            shared.append(''.join(t.text or '' for t in si.iter(f'{NS}t')))
    wb = ET.fromstring(z.read('xl/workbook.xml'))
    sheets = list(wb.iter(f'{NS}sheet'))
    rels = ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))
    rid2target = {r.get('Id'): r.get('Target') for r in rels}
    result = []
    for s in sheets:
        name = s.get('name')
        rid = s.get(f'{RNS}id')
        tgt = rid2target.get(rid)
        if not tgt:
            continue
        if not tgt.startswith('xl/'):
            tgt = 'xl/' + tgt.lstrip('/')
        sroot = ET.fromstring(z.read(tgt))
        grid = []
        for row in sroot.iter(f'{NS}row'):
            cells = {}
            maxc = 0
            for c in row.findall(f'{NS}c'):
                ref = c.get('r')
                if not ref:
                    continue
                col = re.match(r'[A-Z]+', ref).group()
                cn = col_to_num(col)
                maxc = max(maxc, cn)
                t = c.get('t')
                v = c.find(f'{NS}v')
                isn = c.find(f'{NS}is')
                val = ''
                if t == 's' and v is not None:
                    val = shared[int(v.text)]
                elif t == 'inlineStr' and isn is not None:
                    val = ''.join(x.text or '' for x in isn.iter(f'{NS}t'))
                elif v is not None:
                    val = v.text or ''
                cells[cn] = val
            line = [cells.get(i, '') for i in range(1, maxc + 1)]
            grid.append(line)
        result.append((name, grid))
    return result

if __name__ == '__main__':
    path = sys.argv[1]
    maxr = int(sys.argv[2]) if len(sys.argv) > 2 else 12
    maxc = int(sys.argv[3]) if len(sys.argv) > 3 else 45
    data = load(path)
    print(f"# FILE: {path}  (子表数={len(data)})")
    for name, grid in data:
        print(f"\n===== 子表: {name}  行数={len(grid)} =====")
        for ri, line in enumerate(grid[:maxr], 1):
            print(f"R{ri}: " + " | ".join(line[:maxc]))
