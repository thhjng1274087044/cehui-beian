#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工程备案精修：复用 _gc_ocr_cache.json 全文 + 台账，不重跑 OCR。
1) 地点：优先 OCR正文 -> 合同名称/委托单位 解析温岭镇街 -> 标注非温岭(待百度)
2) 签订日期：台账签订日期 -> OCR正文签订日期 -> 归档日期
3) 预计完工：沿用工作量估算；地点/日期仍缺 -> 需百度核查
输出：工程备案_精修.csv + 百度核查清单 _baidu_queue.txt
"""
import re, csv, json, os, xlrd
from datetime import date, timedelta

LEDGER="_ledger.xls"; CACHE="_gc_ocr_cache.json"
OUT="工程备案_精修.csv"; QUEUE="_baidu_queue.txt"
DATE_COLS={"签订":8,"归档":13,"合同号":3,"归档号":2,"委托":4,"名称":5,"金额":6,"类别":10,"网上":15}

# 温岭市镇街词典
WENLING_TOWNS=["太平街道","城东街道","城西街道","城北街道","城南街道","横峰街道",
 "泽国镇","大溪镇","松门镇","箬横镇","新河镇","石塘镇","滨海镇","温峤镇","石桥头镇","坞根镇",
 "东部新区","经济开发区","温岭经济开发区"]
# 已知非温岭(省内其他地市)，命中即待百度
NON_WL={"杭州":["杭州","西湖区","双桥单元","杭政工出","拱墅","余杭","萧山","滨江","上城","下城","江干","西湖"],
 "宁波":["宁波","鄞州","北仑","镇海","慈溪","余姚"],
 "金华":["金华","义乌","东阳","永康"],
 "其他":["温州","绍兴","嘉兴","湖州","衢州","丽水","舟山","台州(非温岭)"]}

def find_town(text):
    for t in WENLING_TOWNS:
        if t in text: return t  # 仅返回镇街名，温岭市前缀由调用处统一加
    return None

def detect_non_wl(text):
    for city,keys in NON_WL.items():
        for k in keys:
            if k in text: return city
    return None

# 杭州双桥(云谷)单元 -> 杭州市西湖区 (WebSearch已确认)
HANGZHOU_OVERRIDE={"双桥单元":"杭州市西湖区","杭政工出":"杭州市西湖区","云谷单元":"杭州市西湖区"}

def loc_from_name(name, ent, ocr_text):
    name=name or ''; ent=ent or ''; ocr_text=ocr_text or ''
    # 0) 名称/委托单位含 温岭/台州 -> 本地优先(避免OCR抽到外地名误判)
    if '温岭' in name or '温岭' in ent:
        t=find_town(name) or find_town(ent) or find_town(ocr_text)
        return ("温岭市"+t) if t else "温岭市"
    if '台州' in name or '台州' in ent:
        return "台州市"
    # 1) 杭州项目(双桥/云谷/杭政工出)
    for kw,city in HANGZHOU_OVERRIDE.items():
        if kw in name or kw in ent: return city
    # 2) OCR 正文(温岭市..镇街)
    m=re.search(r'温岭市([\u4e00-\u9fa5]{1,6}(?:镇|街道|乡))', ocr_text)
    if m: return "温岭市"+m.group(1)
    t=find_town(ocr_text)
    if t: return t
    # 3) 非温岭(杭州其他/宁波等)
    nw=detect_non_wl(name+" "+ent+" "+ocr_text)
    if nw: return f"【{nw}·待百度】"
    # 4) 兜底：新大陆测绘为温岭本地公司，绝大多数合同在温岭，未识别到镇街的默认温岭市
    return "温岭市"

DATE_PAT=[r'签订日期[：: ]*(\d{4})年(\d{1,2})月(\d{1,2})日',
          r'签订[：: ]*(\d{4})年(\d{1,2})月(\d{1,2})日',
          r'(\d{4})年(\d{1,2})月(\d{1,2})日']
def date_from_text(text):
    for p in DATE_PAT:
        m=re.search(p, text or '')
        if m:
            try: return date(int(m.group(1)),int(m.group(2)),int(m.group(3)))
            except: pass
    return None

def serial_to_date(v, dm):
    try: return xlrd.xldate.xldate_as_datetime(float(v), dm).date()
    except: return None

# 估算完工(沿用管线逻辑，精简)
CAT_DAYS={'放样':30,'建筑面积实测':30,'竣工测量':45,'综合测绘':90,'工程测绘':60,'不动产测绘':45,'用地报批':120,'技术服务':60,'资料整理':60}
def default_days(cat):
    for k,v in CAT_DAYS.items():
        if k in cat: return v
    return 60
def estimate_end(start,cat,dur,wl):
    if start is None: return None,'无签订日期'
    if dur: return start+timedelta(days=dur), f'合同写明工期{dur}天'
    base=default_days(cat); scale=1.0; basis=''
    if wl.get('area'): scale=min(max(wl['area']/500.0,.5),3); basis=f"面积{wl['area']:.0f}㎡"
    elif wl.get('house'): scale=min(max(wl['house']/50.0,.5),3); basis=f"户{wl['house']}"
    elif wl.get('bld'): scale=min(max(wl['bld']/10.0,.5),3); basis=f"幢{wl['bld']}"
    elif wl.get('len'): scale=min(max(wl['len']/1000.0,.5),3); basis=f"{wl['len']:.0f}m"
    days=max(15,round(base*scale))
    return start+timedelta(days=days), f'按工作量估({basis or "无明确工作量"})×基准{base}天≈{days}天'

def extract_workload(text):
    w={'area':None,'house':None,'bld':None,'len':None}
    m=re.search(r'(\d{2,}(?:\.\d+)?)\s*(?:平方米|平米|㎡|m2|M2)', text or '')
    if m: w['area']=float(m.group(1))
    m=re.search(r'(\d+)\s*户', text or ''); 
    if m: w['house']=int(m.group(1))
    m=re.search(r'(\d+)\s*[幢栋]', text or ''); 
    if m: w['bld']=int(m.group(1))
    m=re.search(r'(\d+(?:\.\d+)?)\s*(?:km|千米|公里)', text or '')
    if m: w['len']=float(m.group(1))*1000
    else:
        m=re.search(r'(\d+(?:\.\d+)?)\s*米', text or '')
        if m: w['len']=float(m.group(1))
    return w

def extract_duration(text):
    for pat in [r'工期[：: ]*(\d+)\s*天',r'总工期[：: ]*(\d+)\s*天',r'(\d+)\s*个?工作日']:
        m=re.search(pat, text or '')
        if m: return int(m.group(1))
    m=re.search(r'自\s*(\d{4})年(\d{1,2})月(\d{1,2})日\s*至\s*(\d{4})年(\d{1,2})月(\d{1,2})日', text or '')
    if m:
        try: return (date(*map(int,m.groups()[3:]))-date(*map(int,m.groups()[:3]))).days
        except: return None
    return None

def split_amount(raw):
    s=str(raw).strip()
    if not s or s=='按实': return (None,None)
    nums=[float(re.search(r'(\d+(?:\.\d+)?)\s*元?',p).group(1)) for p in re.split(r'/+',s) if re.search(r'\d',p)]
    return (nums[0],nums[-1]) if nums else (None,None)

def main():
    cache=json.load(open(CACHE,encoding='utf-8')) if os.path.exists(CACHE) else {}
    wb=xlrd.open_workbook(LEDGER); dm=wb.datemode
    rows=[]; q=[]
    for sh in wb.sheets():
        if sh.name not in ("2025","2026"): continue
        for r in range(2, sh.nrows):
            def g(ci):
                v=sh.cell_value(r,ci)
                return '' if v is None else (str(int(v)) if isinstance(v,float) and v.is_integer() else str(v))
            contract_no=g(3); archive=g(2); ent=g(4); name=g(5)
            amt_raw=g(6); cat_ledger=g(10); date_raw=g(8); arch_raw=g(13); web=g(15)
            total,disc=split_amount(amt_raw)
            disc_wan=f"{disc/10000:.4f}" if disc is not None else ''
            # 匹配 OCR 缓存
            keys=set(re.findall(r'XDL[-–\s]?(?:CHHT[-–\s]?)?\d{4}[-–]\d+', (contract_no+archive+name), re.IGNORECASE))
            keys={re.sub(r'[-–\s]','-',k).upper().replace('CHHT-','CHHT') for k in keys}
            text=''; ocr_cat=''; ocr_amt=None
            for k in keys:
                if k in cache:
                    d=cache[k]; text=d.get('text',''); ocr_cat=d.get('cat',''); ocr_amt=d.get('amt'); break
            # 地点
            loc=loc_from_name(name,ent,text)
            nonwl = loc.startswith('【')
            # 日期：台账签订 -> OCR正文 -> 归档 -> 缓存date
            start=serial_to_date(date_raw,dm)
            start_src='台账签订日期'
            if start is None:
                dt=date_from_text(text)
                if dt: start=dt; start_src='OCR合同日期'
            if start is None:
                start=serial_to_date(arch_raw,dm)
                if start: start_src='归档日期(回退)'
            if start is None and keys:
                cached_date = cache.get(list(keys)[0],{}).get('date')
                if cached_date:
                    start=date(*map(int,cached_date.split('-'))); start_src='OCR全页日期'
            dur=extract_duration(text)
            wl=extract_workload(text)
            end,basis=estimate_end(start, ocr_cat or cat_ledger, dur, wl)
            final_amt=disc if disc is not None else ocr_amt
            final_wan=f"{final_amt/10000:.4f}" if final_amt is not None else ''
            amt_src='台账打折后' if disc is not None else ('OCR合同' if ocr_amt is not None else '无')
            # 需百度：地点仍缺(非温岭未定位 或 完全空) 或 起止日期都缺
            need_baidu = (not loc) or (nonwl) or (start is None)
            if need_baidu:
                reason=[]
                if nonwl: reason.append('非温岭待定位')
                elif not loc: reason.append('地点缺失')
                if start is None: reason.append('无签订日期')
                q.append((sh.name, name, ent, loc, reason))
            rows.append({
                '年份':sh.name,'合同号':contract_no,'委托单位':ent,'合同名称':name,
                '类别':cat_ledger,'OCR类别':ocr_cat,
                '金额原始':amt_raw,'打折后万元':disc_wan,'最终金额万元':final_wan,'金额来源':amt_src,
                '签订日期':start.isoformat() if start else '','日期来源':start_src if start else '',
                '预计开工':start.isoformat() if start else '','预计完工':end.isoformat() if end else '',
                '日期依据':basis,'项目地点':loc,
                '需百度核查':('是' if need_baidu else ''),
                '网上备案':web,'匹配PDF':(list(keys)[0]+'.pdf' if keys else '')
            })
    cols=['年份','合同号','委托单位','合同名称','类别','OCR类别','金额原始','打折后万元','最终金额万元','金额来源',
          '签订日期','日期来源','预计开工','预计完工','日期依据','项目地点','需百度核查','网上备案','匹配PDF']
    with open(OUT,'w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=cols); w.writeheader()
        for r in rows: w.writerow(r)
    with open(QUEUE,'w',encoding='utf-8') as f:
        for y,nm,en,lc,rs in q:
            f.write(f"{y}\t{nm}\t{en}\t{lc}\t{';'.join(rs)}\n")
    n=len(rows); nb=len(q)
    print(f"总行数={n}")
    print(f"  有签订日期={sum(1 for r in rows if r['签订日期'])}")
    print(f"  有预计完工={sum(1 for r in rows if r['预计完工'])}")
    print(f"  有地点(温岭/台州)={sum(1 for r in rows if r['项目地点'] and not r['项目地点'].startswith('【'))}")
    print(f"  需百度核查={nb}")
    print(f"  -> {OUT}")
    print(f"  -> {QUEUE}")

if __name__=='__main__':
    main()
