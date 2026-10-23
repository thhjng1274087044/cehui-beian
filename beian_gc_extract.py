#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工程备案提取原型：台账xls -> 金额拆分(取打折后) -> 匹配V:合同PDF -> 草稿CSV。
项目类型(平台) 留空占位，待用户提供 公司类别->平台映射 后接入。"""
import re, csv, xlrd, os

LEDGER = "_ledger.xls"
L2025 = "_v2025_list.txt"
L2026 = "_v2026_list.txt"
OUT = "工程备案_提取草稿.csv"

def find_col(header_cells, *kw):
    for i,c in enumerate(header_cells):
        s=str(c)
        if any(k in s for k in kw): return i
    return None

def split_amount(raw):
    """台账金额（元）形如 '5266元//按实//5477元' -> (总额, 打折后)。无数字返回(None,None)。"""
    s=str(raw).strip()
    if not s or s=='按实':
        return (None,None)
    parts=re.split(r'/+', s)
    nums=[]
    for p in parts:
        m=re.search(r'(\d+(?:\.\d+)?)\s*元?', p)
        if m: nums.append(float(m.group(1)))
    if not nums:
        return (None,None)
    total=nums[0]
    discounted=nums[-1]   # 取最后一个数字作为打折后(实际)
    return (total, discounted)

def xdl_nums(text):
    """提取文本里的 XDL 编号集合，用于匹配。"""
    if not text: return set()
    pats=[r'XDL[-–\s]?CHHT[-–\s]?\d{4}[-–]\d+', r'XDL[-–\s]?\d{4}[-–]\d+']
    out=set()
    for p in pats:
        for m in re.findall(p, str(text), re.IGNORECASE):
            out.add(re.sub(r'[\s]','',m).upper())
    return out

def load_pdf_lists():
    pdfs={}
    for yr,fname in [("2025",L2025),("2026",L2026)]:
        with open(fname,encoding='utf-8',errors='replace') as f:
            for line in f:
                fn=line.strip()
                if not fn or not fn.lower().endswith('.pdf'): continue
                nums=xdl_nums(fn)
                if nums:
                    for n in nums: pdfs.setdefault(n,[]).append((yr,fn))
    return pdfs

def main():
    wb=xlrd.open_workbook(LEDGER)
    pdfs=load_pdf_lists()
    rows=[]
    for sh in wb.sheets():
        if sh.name not in ("2025","2026"): continue
        # 找表头行
        hdr=None
        for r in range(min(6,sh.nrows)):
            if any('金额' in str(sh.cell_value(r,c)) for c in range(sh.ncols)):
                hdr=r; break
        if hdr is None: continue
        hcells=[sh.cell_value(hdr,c) for c in range(sh.ncols)]
        c_no=find_col(hcells,'合同号'); c_arch=find_col(hcells,'归档号')
        c_ent=find_col(hcells,'委托单位'); c_name=find_col(hcells,'合同名称','项目名称')
        c_amt=find_col(hcells,'金额'); c_cat=find_col(hcells,'类别')
        c_date=find_col(hcells,'签订日期','日期'); c_web=find_col(hcells,'网上备案')
        for r in range(hdr+1, sh.nrows):
            def g(ci):
                if ci is None or ci>=sh.ncols: return ''
                v=sh.cell_value(r,ci)
                return '' if v is None else (str(int(v)) if isinstance(v,float) and v.is_integer() else str(v))
            row_no=r+1
            contract_no=g(c_no); archive=g(c_arch); ent=g(c_ent); name=g(c_name)
            amt_raw=g(c_amt); cat=g(c_cat); date=g(c_date); web=g(c_web)
            total,disc=split_amount(amt_raw)
            disc_wan = f"{disc/10000:.4f}" if disc is not None else ''
            # 匹配PDF
            keys=set()
            for fld in (contract_no,archive,name,ent):
                keys|=xdl_nums(fld)
            matched=[]
            for k in keys:
                if k in pdfs: matched+=pdfs[k]
            match_str="; ".join(f"{y}:{fn}" for y,fn in matched) if matched else ''
            rows.append({
                '行号':row_no,'年份':sh.name,'合同号':contract_no,'归档号':archive,
                '委托单位':ent,'合同名称':name,'类别_台账':cat,
                '金额原始':amt_raw,'总额':total if total is not None else '','打折后':disc if disc is not None else '',
                '打折后万元':disc_wan,'签订日期':date,'网上备案':web,
                '匹配PDF':match_str,'项目类型_平台':'',  # 占位，待映射
            })
    # 写CSV
    cols=['行号','年份','合同号','归档号','委托单位','合同名称','类别_台账','金额原始','总额','打折后','打折后万元','签订日期','网上备案','匹配PDF','项目类型_平台']
    with open(OUT,'w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=cols); w.writeheader()
        for r in rows: w.writerow(r)
    # 统计
    n=len(rows); matched=sum(1 for r in rows if r['匹配PDF'])
    disc_ok=sum(1 for r in rows if r['打折后']!='')
    web_done=sum(1 for r in rows if '备案' in str(r['网上备案']))
    print(f"台账行数(2025+2026)={n}")
    print(f"  匹配到V:PDF = {matched} ({matched*100//n}%)")
    print(f"  有打折后金额 = {disc_ok} ({disc_ok*100//n}%)")
    print(f"  网上备案已标记 = {web_done}")
    print(f"  类别分布: " + ", ".join(f"{k}={v}" for k,v in sorted(__import__('collections').Counter(r['类别_台账'] for r in rows).items(),key=lambda x:-x[1])))
    print(f"草稿已写出 -> {OUT}")
    # 展示5个匹配示例
    print("\n示例(匹配到的前5条):")
    for r in [x for x in rows if x['匹配PDF']][:5]:
        print(f"  {r['合同号']} | {r['类别_台账']} | 打折后={r['打折后']}万={r['打折后万元']} | {r['匹配PDF'][:40]}")

if __name__=='__main__':
    main()
