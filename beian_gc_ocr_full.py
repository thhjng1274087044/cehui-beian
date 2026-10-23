#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工程备案：合同 PDF **全页** OCR（带坐标），供分层判据解析。

⚠️ 背景：旧缓存 _gc_ocr_cache.json 只 OCR 了第 1 页，导致「第五条 测绘工程费 →
测绘费价格表」（真正的子项+分项金额）整页丢失，L4 判据被系统性漏掉。本脚本重做全页。

输出 _gc_ocr_pages.json：
  { "<V盘文件名>": { "pages": [ {"page":0,"w":W,"h":H,"items":[[x0,y0,x1,y1,text,score],...]} ],
                     "npage": N, "ok": true } }
多进程并行；增量缓存（已 ok 的跳过，--force 全重跑）。
用法：  python beian_gc_ocr_full.py [年 2025] [进程数 5] [--force]
只读源 PDF，不写回任何业务数据。
"""
import os, sys, glob, json, time

ROOT = r'<ENG_CONTRACT_SRC_ROOT>'
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, '_gc_ocr_pages.json')
DPI = int(os.environ.get('GC_OCR_DPI', '150'))
MAX_PAGES = int(os.environ.get('GC_OCR_MAXPAGES', '5'))
FORCE = '--force' in sys.argv

_args = [a for a in sys.argv[1:] if a != '--force']
if _args and _args[0].isdigit():
    PROCS = int(_args[0])
    YEARS = ['2025年', '2026年']
elif _args:
    YEARS = [y for part in _args[0].split(',') for y in [part.strip()] if y]
    PROCS = int(_args[1]) if len(_args) > 1 else 5
else:
    YEARS = ['2025年', '2026年']
    PROCS = 5
for _y in YEARS:
    if not _y.endswith('年'):
        YEARS[YEARS.index(_y)] = _y + '年'

_ocr = None
def _engine():
    global _ocr
    if _ocr is None:
        # ⚠️ 关键：rapidocr 的 OrtInferSession 建 SessionOptions 时没设 intra_op_num_threads，
        # 默认 = CPU 核数 → 每进程吃满全部核心，多进程互相抢占反而更慢。
        # 这里 monkey-patch 强制单线程，让 N 个进程真正并行。
        import onnxruntime as ort
        _orig_init = ort.InferenceSession.__init__
        def _patched(self, path_or_bytes, sess_options=None, providers=None, **kw):
            if sess_options is not None:
                sess_options.intra_op_num_threads = 1
                sess_options.inter_op_num_threads = 1
            return _orig_init(self, path_or_bytes, sess_options=sess_options,
                              providers=providers, **kw)
        ort.InferenceSession.__init__ = _patched
        os.environ['OMP_NUM_THREADS'] = '1'
        try:
            import cv2
            cv2.setNumThreads(1)
        except Exception:
            pass
        from rapidocr_onnxruntime import RapidOCR
        _ocr = RapidOCR()
    return _ocr


def collect_pdfs(years):
    out = []
    for y in years:
        d = os.path.join(ROOT, y)
        if not os.path.isdir(d):
            print('!! 缺年份目录', d); continue
        for ext in ('*.pdf', '*.PDF'):
            out += sorted(glob.glob(os.path.join(d, '**', ext), recursive=True))
    return sorted(set(out))


def ocr_pdf(path):
    import fitz, numpy as np
    ocr = _engine()
    doc = fitz.open(path)
    pages = []
    try:
        for i in range(min(doc.page_count, MAX_PAGES)):
            pix = doc[i].get_pixmap(dpi=DPI)
            img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
            if pix.n == 4:
                img = img[:, :, :3]
            res, _ = ocr(img)
            items = []
            for box, text, score in (res or []):
                xs = [pt[0] for pt in box]; ys = [pt[1] for pt in box]
                items.append([round(min(xs), 1), round(min(ys), 1),
                              round(max(xs), 1), round(max(ys), 1), text, round(float(score), 3)])
            pages.append({'page': i, 'w': pix.width, 'h': pix.height, 'items': items})
            del img
    finally:
        doc.close()
    return pages


def _work(path):
    b = os.path.basename(path)
    t = time.time()
    try:
        pages = ocr_pdf(path)
        return b, {'path': path, 'npage': len(pages), 'pages': pages, 'ok': True}, time.time() - t
    except Exception as e:
        return b, {'path': path, 'ok': False, 'err': str(e)[:200]}, time.time() - t


def main():
    pdfs = collect_pdfs(YEARS)
    print('年份:', YEARS, '| 发现 PDF:', len(pdfs), '| DPI:', DPI, '| 进程:', PROCS, flush=True)

    cache = {}
    if os.path.exists(OUT) and not FORCE:
        try:
            cache = json.load(open(OUT, encoding='utf-8'))
            print('已加载缓存:', len(cache), flush=True)
        except Exception as e:
            print('缓存损坏，重来:', e, flush=True); cache = {}

    todo = [p for p in pdfs
            if FORCE or not (os.path.basename(p) in cache and cache[os.path.basename(p)].get('ok'))]
    _lim = int(os.environ.get('GC_OCR_LIMIT', '0'))
    if _lim:
        todo = todo[: _lim]
    print('待处理:', len(todo), flush=True)
    if not todo:
        return

    if PROCS <= 1:
        t0 = time.time(); n = 0; bad = 0
        for p in todo:
            b, rec, dt = _work(p)
            n += 1
            cache[b] = rec
            if not rec.get('ok'):
                bad += 1
            print('[%d/%d] %s | %s页 | %.0fs/份 | 累计%.0fs' %
                  (n, len(todo), b[:52], rec.get('npage', '-'), dt, time.time() - t0), flush=True)
            if n % 5 == 0 or n == len(todo):
                json.dump(cache, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False)
        json.dump(cache, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False)
        print('完成。缓存 %d 条（失败 %d）| 总耗时 %.0fs' % (len(cache), bad, time.time() - t0), flush=True)
        return

    import multiprocessing as mp
    try:
        mp.set_start_method('spawn')
    except RuntimeError:
        pass

    t0 = time.time(); n = 0; bad = 0
    with mp.Pool(PROCS) as pool:
        for b, rec, dt in pool.imap_unordered(_work, todo, chunksize=1):
            n += 1
            cache[b] = rec
            if not rec.get('ok'):
                bad += 1
            el = time.time() - t0
            print('[%d/%d] %s | %s页 | %.0fs/份 | 累计%.0fs' %
                  (n, len(todo), b[:52], rec.get('npage', '-'), dt, el), flush=True)
            if n % 5 == 0 or n == len(todo):
                json.dump(cache, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False)

    json.dump(cache, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False)
    print('完成。缓存 %d 条（失败 %d）| 总耗时 %.0fs' % (len(cache), bad, time.time() - t0), flush=True)


if __name__ == '__main__':
    main()
