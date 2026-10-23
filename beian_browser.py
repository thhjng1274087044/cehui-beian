"""
备案网站可控浏览器控制器
- 通过 CDP 连接本机已启动的 Chrome(--remote-debugging-port=9222)
- 复用 Chrome 持久用户目录里的登录态，避免重复登录
- 用法:
    python beian_browser.py state            # 打印当前页面 url/title/是否登录
    python beian_browser.py screenshot PATH  # 截图保存

作为模块导入时:
    from beian_browser import BeianBrowser
    b = BeianBrowser()         # 连接 CDP, 自动打开/复用备案页
    b.page.goto(URL)           # 导航
    b.page.screenshot(...)     # 截图
"""
import sys, json, os
from playwright.sync_api import sync_playwright
import beian_config as _cfg

# 备案目标站 (浙江省测绘地理信息综合监管服务平台)
BEIAN_URL = _cfg.CFG.get("beian_url", "https://hyjg.zrzyt.zj.gov.cn/main.htm")
CDP_URL = _cfg.CFG.get("cdp_url", "http://localhost:9333")


def find_existing_page(browser, keywords):
    for ctx in browser.contexts:
        for page in ctx.pages:
            u = page.url or ""
            if any(k in u for k in keywords):
                return page
    return None


class BeianBrowser:
    """连接本机 CDP Chrome 的便捷封装。"""

    def __init__(self, target_url=BEIAN_URL, match_keywords=None):
        self.pw = sync_playwright().start()
        self.browser = self.pw.chromium.connect_over_cdp(CDP_URL)
        self.target_url = target_url
        kws = match_keywords or ["hyjg.zrzyt", "zrzyt.zj", "main.htm", "login"]
        self.page = find_existing_page(self.browser, kws)
        if self.page is None:
            ctx = self.browser.contexts[0] if self.browser.contexts else self.browser.new_context()
            self.page = ctx.new_page()
            self.page.goto(target_url, wait_until="domcontentloaded", timeout=20000)
        self.page.set_viewport_size({"width": 1400, "height": 900})

    def state(self):
        try:
            self.page.wait_for_load_state("domcontentloaded", timeout=8000)
        except Exception:
            pass
        has_pw = None
        try:
            has_pw = self.page.query_selector("input[type=password]") is not None
        except Exception:
            pass
        return {
            "url": self.page.url,
            "title": self.page.title(),
            "has_password_input": has_pw,
        }

    def screenshot(self, path):
        try:
            self.page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass
        self.page.screenshot(path=path, full_page=False)

    def close(self):
        try:
            self.browser.close()
        except Exception:
            pass
        try:
            self.pw.stop()
        except Exception:
            pass


def connect():
    """兼容旧调用: 返回 (pw, browser, page)"""
    b = BeianBrowser()
    return b.pw, b.browser, b.page


def cmd_state():
    b = BeianBrowser()
    print(json.dumps(b.state(), ensure_ascii=False, indent=2))
    b.close()


def cmd_screenshot(path):
    b = BeianBrowser()
    b.screenshot(path)
    print("screenshot saved:", path)
    b.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: state | screenshot PATH")
        sys.exit(1)
    act = sys.argv[1]
    if act == "state":
        cmd_state()
    elif act == "screenshot":
        cmd_screenshot(sys.argv[2] if len(sys.argv) > 2 else os.path.join(_cfg.DEPLOY_ROOT, "_beian_state.png"))
    else:
        print("unknown action:", act)
