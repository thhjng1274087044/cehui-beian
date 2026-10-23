#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""遍历所有缓存合同，OCR全部页，更新 _gc_ocr_cache.json 的 text，并用多种格式抽取签订日期。
"""
import re, json, os, fitz, numpy as np
from rapidocr_onnxruntime import RapidOCR
from datetime import date
import beian_gc_refine as R

CACHE="_gc_ocr_cache.json"; STAGE="_gc_stage"
ocr=RapidOCR()
cache=json.load(open(CACHE,encoding='utf-8')) if os.path.exists(CACHE) else {}

DATE_PATS=[
 r'签订日期[：: ]*(\d{4})[年./\-](\d{1,2})[月./\-](\d{1,2})',
 r'签订[：: ]*(\d{4})[年./\-](\d{1,2})[月./\-](\d{1,2})',
 r'(\d{4})[年./\-](\d{1,2})[月./\-](\d{1,2})日?',  # 兜底第一个看起来像日期的
]
def find_date(text):
    cand=[]
    for p in DATE_PATS:
        for m in re.finditer(p, text or ''):
            try:
                d=date(int(m.group(1)),int(m.group(2)),int(m.group(3)))
                if 2000<=d.year<=2035: cand.append(d)
            except: pass
    # 排除"归档日期"那种明显晚于"签订"的？先取文本中最早的合理日期作为签订日候选
    return min(cand) if cand else None

n=0; found=0
for k in sorted(cache.keys()):
    p=os.path.join(STAGE,k)  # 缓存键已含 .pdf 扩展名
    if not os.path.exists(p): continue
    d=fitz.open(p); full=''
    for pg in range(d.page_count):
        pix=d[pg].get_pixmap(dpi=180)
        img=np.frombuffer(pix.samples,dtype=np.uint8).reshape(pix.height,pix.width,pix.n)
        res,_=ocr(img)
        if res: full+="\n".join(t for _,t,_ in res)+"\n"
    old=cache[k]; old['text']=full
    if not old.get('date'):
        dt=find_date(full)
        if dt: old['date']=dt.isoformat(); found+=1
    cache[k]=old; n+=1
json.dump(cache,open(CACHE,'w',encoding='utf-8'),ensure_ascii=False)
print(f"重OCR合同数={n} 新找回签订日期={found}")
with open("_datefix_log.txt","w",encoding='utf-8') as f:
    f.write(f"重OCR合同数={n} 找回日期={found}\n")
