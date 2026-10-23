# 备案专用 Chrome 启动器（常驻版）
# 用法：python launch_chrome_beian.py
# 设计：用普通 Popen 拉起 Chrome 并保持本进程存活（p.wait），
# 由调用方以「后台任务」方式运行，从而跨回合保活，不被回合结束回收。
import subprocess, sys, time, os

# Chrome 路径自动探测（本机 / 服务器通用）
_CANDIDATES = [
    os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
    os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
    os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
    r"C:\Users\admin\AppData\Local\Google\Chrome\Application\chrome.exe",
]
CHROME = next((p for p in _CANDIDATES if os.path.exists(p)), _CANDIDATES[0])
PROFILE = r"E:\网站备案\备案部署包\browser_profile_beian"
URL     = "https://hyjg.zrzyt.zj.gov.cn/main.htm"

LOG = r"E:\网站备案\备案部署包\chrome_beian.log"

def main():
    import os
    with open(LOG, "a", encoding="utf-8") as f:
        f.write("\n[%s] launching chrome...\n" % time.strftime("%Y-%m-%d %H:%M:%S"))
    cmd = [CHROME, "--remote-debugging-port=9333", f"--user-data-dir={PROFILE}",
           "--no-first-run", "--no-default-browser-check", URL]
    p = subprocess.Popen(cmd)
    sys.stdout.write("LAUNCHED pid=%d\n" % p.pid)
    sys.stdout.flush()
    with open(LOG, "a", encoding="utf-8") as f:
        f.write("pid=%d\n" % p.pid)
    # 保持本进程存活，直到 Chrome 退出（后台任务据此持续存在）
    rc = p.wait()
    sys.stdout.write("CHROME_EXITED rc=%s\n" % rc)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write("chrome exited rc=%s\n" % rc)

if __name__ == "__main__":
    main()
