#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""连 CDP 抓取备案表单「项目类型」两级级联器的真实可选项（只读，不提交）。增量保存，按索引点击鲁棒版。"""
import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from beian_browser import BeianBrowser

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_projtype_live.json")

def read_menus(page):
    return page.evaluate("""() => {
        const ps = [...document.querySelectorAll('.el-cascader-panel')].filter(p=>p.offsetParent!==null);
        if(!ps.length) return 'NO_PANEL';
        const p = ps[0];
        return [...p.querySelectorAll('.el-cascader-menu')].map(menu=>{
            return [...menu.querySelectorAll('.el-cascader-node')].map(n=>{
                const label = n.querySelector('.el-cascader-node__label')?.innerText?.trim();
                const isLeaf = n.getAttribute('class').includes('is-leaf');
                return {label, isLeaf};
            });
        });
    }""")

def open_cascader(page):
    item = page.locator('.el-form-item:has(.el-form-item__label:text-is("项目类型"))')
    cas = item.locator(".el-cascader")
    cas.locator("input").first.click(force=True, timeout=5000)
    page.wait_for_timeout(1000)

def main():
    b = BeianBrowser()
    page = b.page
    print("当前URL:", page.url)
    has_form = page.locator('.el-form-item:has(.el-form-item__label:text-is("项目类型"))').count()
    if has_form == 0:
        print("点击『添加』...")
        page.locator('button:has-text("添加")').first.click(timeout=8000)
        page.wait_for_selector(".el-form", timeout=10000)
        page.wait_for_timeout(1200)

    open_cascader(page)
    menus = read_menus(page)
    if not isinstance(menus, list):
        print("面板读取失败:", menus); b.close(); return
    l1 = [n["label"] for n in menus[0]]
    print("L1(大类)数量:", len(l1), l1)

    result = []
    for i, label in enumerate(l1):
        # 确保面板开着
        m = read_menus(page)
        if m == 'NO_PANEL':
            open_cascader(page); m = read_menus(page)
        # 按索引点击 L1
        try:
            page.locator(".el-cascader-panel").filter(visible=True).first \
                .locator(".el-cascader-menu").nth(0) \
                .locator(".el-cascader-node").nth(i).click(timeout=4000)
        except Exception as e:
            print(f"  [!] 点击 L1[{i}]={label} 失败: {e}")
            result.append({"大类": label, "小类": []})
            json.dump(result, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            continue
        page.wait_for_timeout(1400)
        m2 = read_menus(page)
        l2 = [x["label"] for x in m2[1]] if isinstance(m2, list) and len(m2) >= 2 else []
        result.append({"大类": label, "小类": l2})
        print(f"[{i}] {label} -> {len(l2)} 小类: {l2}")
        json.dump(result, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    print("\n已保存:", OUT)
    page.keyboard.press("Escape"); page.wait_for_timeout(300)
    b.close()
    print("DONE")

if __name__ == "__main__":
    main()
