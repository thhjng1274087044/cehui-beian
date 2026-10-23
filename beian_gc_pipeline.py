#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工程备案固化管线 v2：
台账xls(2025/2026) -> 金额拆分(取打折后) -> 匹配V:合同PDF(暂存ASCII) ->
OCR抽项目类别(公司)+实际金额+全文(缓存) -> 抽工期/工作量/地点 ->
计算 预计开工(签订日期) / 预计完工(工作量估 or 百度存疑) -> 草稿CSV。
OCR 全文缓存到 _gc_ocr_cache.json，重跑秒回。只读不改源数据。
"""
import re, csv, json, os, xlrd
from datetime import date, timedelta
import fitz, numpy as np
from rapidocr_onnxruntime import RapidOCR
from beian_gc_category_map import map_category

LEDGER = "_ledger.xls"
STAGE  = "_gc_stage"
CACHE  = "_gc_ocr_cache.json"
OUT    = "工程备案_全量草稿.csv"

_ocr = None
def ocr_engine():
    global _ocr
    if _ocr is None: _ocr = RapidOCR()
    return _ocr

# ---------- 公司类别(从合同标题) ----------
CATS=[
 ("综合测绘",["综合测绘","综合测绘技术"]),
 ("工程测绘",["工程测量","工程测绘","竣工测量","放样","沉降观测","变形观测","地形测量","控制测量","规划测量","管线测量"]),
 ("不动产测绘",["不动产","房产测绘","地籍","房产测量","建筑面积"]),
 ("用地报批",["用地报批","农转用","征收报批"]),
 ("技术服务",["技术服务","资料录入","数据录入","系统录入"]),
 ("资料整理",["资料整理","档案整理"]),
]
def extract_cat(text):
    titles=[l for l in text.split('\n') if '合同' in l]
    pool="\n".join(titles[:3]) if titles else text[:400]
    for cat,kws in CATS:
        if any(k in pool for k in kws): return cat
    for cat,kws in CATS:
        if any(k in text for k in kws): return cat
    return "未识别"

def extract_amount_from_ocr(text):
    cands=[]
    for m in re.finditer(r'(\d{2,}(?:\.\d+)?)\s*元', text):
        cands.append(float(m.group(1)))
    for kw in ['合计','总价','合同价','金额（元）','收费']:
        for m in re.finditer(kw+r'.{0,12}?(\d{2,}(?:\.\d+)?)\s*元', text):
            cands.insert(0, float(m.group(1)))
    return (max(cands) if cands else None), cands

# ---------- 工期 / 工作量 / 地点 ----------
def extract_duration_days(text):
    """返回显式工期天数(若合同写明)；否则 None。"""
    for pat in [r'工期[：: ]*(\d+)\s*天', r'总工期[：: ]*(\d+)\s*天',
                r'工期[：: ]*约?\s*(\d+)\s*个?月', r'(\d+)\s*个?工作日']:
        m=re.search(pat, text)
        if m:
            n=int(m.group(1))
            if '月' in pat: return n*30
            return n
    # 自 X年X月X日 至 X年X月X日
    m=re.search(r'自\s*(\d{4})年(\d{1,2})月(\d{1,2})日\s*至\s*(\d{4})年(\d{1,2})月(\d{1,2})日', text)
    if m:
        y1,mo1,d1,y2,mo2,d2=map(int,m.groups())
        try:
            return (date(y2,mo2,d2)-date(y1,mo1,d1)).days
        except: return None
    return None

def extract_workload(text):
    """面积(㎡)、户数、幢数、长度(m/km)。"""
    w={'area':None,'house':None,'bld':None,'len':None}
    m=re.search(r'(\d{2,}(?:\.\d+)?)\s*(?:平方米|平米|㎡|m2|M2)', text)
    if m: w['area']=float(m.group(1))
    m=re.search(r'(\d+)\s*户', text)
    if m: w['house']=int(m.group(1))
    m=re.search(r'(\d+)\s*[幢栋]', text)
    if m: w['bld']=int(m.group(1))
    m=re.search(r'(\d+(?:\.\d+)?)\s*(?:km|千米|公里)', text)
    if m: w['len']=float(m.group(1))*1000
    else:
        m=re.search(r'(\d+(?:\.\d+)?)\s*米', text)
        if m: w['len']=float(m.group(1))
    return w

LOC_PATTERNS=[
 r'温岭市([\u4e00-\u9fa5]{1,6}(?:镇|街道|乡))([\u4e00-\u9fa5]{1,10}(?:村|社区|居))?',
 r'([\u4e00-\u9fa5]{1,6}(?:镇|街道|乡))([\u4e00-\u9fa5]{1,10}(?:村|社区|居))?',
 r'项目位于([\u4e00-\u9fa5]{2,12})',
 r'位于([\u4e00-\u9fa5]{2,12})',
]
def extract_location(text):
    for pat in LOC_PATTERNS:
        m=re.search(pat, text)
        if m:
            g=[x for x in m.groups() if x]
            return "".join(g)
    return ""

CAT_DAYS={
 '放样':30,'建筑面积实测':30,'竣工测量':45,'综合测绘':90,'工程测绘':60,
 '不动产测绘':45,'用地报批':120,'技术服务':60,'资料整理':60,
}
def default_days(cat):
    for k,v in CAT_DAYS.items():
        if k in cat: return v
    return 60

def estimate_end(start, cat, dur, workload):
    """返回 (预计完工date, 依据str)。"""
    if start is None: return None,'无签订日期'
    if dur: return start+timedelta(days=dur), f'合同写明工期{dur}天'
    base=default_days(cat)
    scale=1.0; basis=''
    if workload['area']:
        scale=min(max(workload['area']/500.0,0.5),3.0); basis=f"面积{workload['area']:.0f}㎡"
    elif workload['house']:
        scale=min(max(workload['house']/50.0,0.5),3.0); basis=f"户数{workload['house']}"
    elif workload['bld']:
        scale=min(max(workload['bld']/10.0,0.5),3.0); basis=f"幢数{workload['bld']}"
    elif workload['len']:
        scale=min(max(workload['len']/1000.0,0.5),3.0); basis=f"长度{workload['len']:.0f}m"
    days=max(15,round(base*scale))
    return start+timedelta(days=days), f'按工作量估({basis or "无明确工作量"})×基准{base}天≈{days}天'

def serial_to_date(v, datemode):
    try:
        return xlrd.xldate.xldate_as_datetime(float(v), datemode).date()
    except: return None

def xdl_nums(text):
    if not text: return set()
    out=set()
    for m in re.findall(r'XDL[-–\s]?(?:CHHT[-–\s]?)?\d{4}[-–]\d+', str(text), re.IGNORECASE):
        out.add(re.sub(r'[-–\s]','-',m).upper().replace('CHHT-','CHHT'))
    return out

def split_amount(raw):
    s=str(raw).strip()
    if not s or s=='按实': return (None,None)
    parts=re.split(r'/+', s)
    nums=[]
    for p in parts:
        m=re.search(r'(\d+(?:\.\d+)?)\s*元?', p)
        if m: nums.append(float(m.group(1)))
    if not nums: return (None,None)
    return (nums[0], nums[-1])

def find_col(header_cells,*kw):
    for i,c in enumerate(header_cells):
        if any(k in str(c) for k in kw): return i
    return None

def load_ocr_cache():
    if os.path.exists(CACHE):
        try: return json.load(open(CACHE,encoding='utf-8'))
        except: return {}
    return {}

def stage_path(xdl):
    for ext in ('.pdf','.PDF'):
        p=os.path.join(STAGE, xdl+ext)
        if os.path.exists(p): return p
    return None

def main():
    cache=load_ocr_cache()
    wb=xlrd.open_workbook(LEDGER); dm=wb.datemode
    rows=[]; ocr_hits=0
    for sh in wb.sheets():
        if sh.name not in ("2025","2026"): continue
        hdr=None
        for r in range(min(6,sh.nrows)):
            if any('金额' in str(sh.cell_value(r,c)) for c in range(sh.ncols)): hdr=r; break
        if hdr is None: continue
        hc=[sh.cell_value(hdr,c) for c in range(sh.ncols)]
        c_no=find_col(hc,'合同号'); c_arch=find_col(hc,'归档号')
        c_ent=find_col(hc,'委托单位'); c_name=find_col(hc,'合同名称','项目名称')
        c_amt=find_col(hc,'金额'); c_cat=find_col(hc,'类别')
        c_date=find_col(hc,'签订日期','日期'); c_web=find_col(hc,'网上备案')
        for r in range(hdr+1, sh.nrows):
            def g(ci):
                if ci is None or ci>=sh.ncols: return ''
                v=sh.cell_value(r,ci)
                return '' if v is None else (str(int(v)) if isinstance(v,float) and v.is_integer() else str(v))
            contract_no=g(c_no); archive=g(c_arch); ent=g(c_ent); name=g(c_name)
            amt_raw=g(c_amt); cat_ledger=g(c_cat); date_raw=g(c_date); web=g(c_web)
            total,disc=split_amount(amt_raw)
            disc_wan = f"{disc/10000:.4f}" if disc is not None else ''
            keys=xdl_nums(contract_no)|xdl_nums(archive)|xdl_nums(name)
            sp=None
            for k in keys:
                sp=stage_path(k)
                if sp: break
            ocr_cat=''; ocr_amt=None; text=''; ocr_src=''
            if sp:
                key=os.path.basename(sp)
                if key in cache and 'text' in cache[key]:
                    d=cache[key]; ocr_cat=d.get('cat',''); ocr_amt=d.get('amt'); text=d.get('text',''); ocr_src='cache'
                else:
                    d=fitz.open(sp); text=''
                    for p in range(min(2,d.page_count)):
                        pix=d[p].get_pixmap(dpi=180)
                        img=np.frombuffer(pix.samples,dtype=np.uint8).reshape(pix.height,pix.width,pix.n)
                        res,_=ocr_engine()(img)
                        if res: text+="\n".join(t for _,t,_ in res)+"\n"
                    ocr_cat=extract_cat(text)
                    ocr_amt,_=extract_amount_from_ocr(text)
                    cache[key]={'cat':ocr_cat,'amt':ocr_amt,'text':text}
                    ocr_src='ocr'; ocr_hits+=1
            final_amt = disc if disc is not None else ocr_amt
            final_wan = f"{final_amt/10000:.4f}" if final_amt is not None else ''
            amt_src = '台账打折后' if disc is not None else ('OCR合同' if ocr_amt is not None else '无')
            big,small = map_category(ocr_cat if ocr_cat and ocr_cat!='未识别' else cat_ledger)
            # 日期
            start=serial_to_date(date_raw, dm)
            dur=extract_duration_days(text) if text else None
            workload=extract_workload(text) if text else {'area':None,'house':None,'bld':None,'len':None}
            end, basis = estimate_end(start, ocr_cat or cat_ledger, dur, workload)
            loc = extract_location(text) if text else ''
            # 存疑标记：无显式工期 且 无明确工作量 且 地点不清
            ambiguous = (dur is None) and (not any(workload.values())) and (not loc)
            rows.append({
                '行号':r+1,'年份':sh.name,'合同号':contract_no,'归档号':archive,
                '委托单位':ent,'合同名称':name,'类别_台账':cat_ledger,
                'OCR类别':ocr_cat,'金额原始':amt_raw,'总额':total if total is not None else '',
                '打折后_台账':disc if disc is not None else '','打折后万元_台账':disc_wan,
                'OCR金额':ocr_amt if ocr_amt is not None else '','最终金额万元':final_wan,
                '金额来源':amt_src,'签订日期':start.isoformat() if start else '',
                '预计开工':start.isoformat() if start else '',
                '工期天数_合同':dur if dur is not None else '',
                '工作量':('面积%.0f㎡'%(workload['area']) if workload['area'] else '')+
                          (' 户%d'%workload['house'] if workload['house'] else '')+
                          (' 幢%d'%workload['bld'] if workload['bld'] else '')+
                          (' %.0fm'%workload['len'] if workload['len'] else ''),
                '预计完工':end.isoformat() if end else '',
                '日期估算依据':basis,
                '项目地点':loc,
                '需百度核查':('是' if ambiguous else ''),
                '网上备案':web,
                '平台大类':big or '','平台小类':small or '','项目类型来源':'待映射' if not big else '映射',
                '匹配PDF':os.path.basename(sp) if sp else ''
            })
    json.dump(cache, open(CACHE,'w',encoding='utf-8'), ensure_ascii=False)
    cols=['行号','年份','合同号','归档号','委托单位','合同名称','类别_台账','OCR类别',
          '金额原始','总额','打折后_台账','打折后万元_台账','OCR金额','最终金额万元','金额来源',
          '签订日期','预计开工','工期天数_合同','工作量','预计完工','日期估算依据','项目地点','需百度核查',
          '网上备案','平台大类','平台小类','项目类型来源','匹配PDF']
    with open(OUT,'w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=cols); w.writeheader()
        for r in rows: w.writerow(r)
    n=len(rows)
    final_ok=sum(1 for r in rows if r['最终金额万元'])
    start_ok=sum(1 for r in rows if r['预计开工'])
    end_ok=sum(1 for r in rows if r['预计完工'])
    amb=sum(1 for r in rows if r['需百度核查']=='是')
    print(f"台账行数={n}")
    print(f"  OCR新识别={ocr_hits} (其余走缓存)")
    print(f"  预计开工有值={start_ok}  预计完工有值={end_ok}  需百度核查={amb}")
    print(f"  最终有金额={final_ok} ({final_ok*100//n}%)")
    print(f"  匹配PDF={sum(1 for r in rows if r['匹配PDF'])}")
    print(f"全量草稿 -> {OUT}")

if __name__=='__main__':
    main()
