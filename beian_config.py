# -*- coding: utf-8 -*-
"""
备案项目部署配置
================================================================
把所有「机器相关」的路径 / 端口 / URL 集中到本模块 + 同目录 config.json。
部署到公司服务器时，只改 config.json 一处即可，无需改任何 .py 源码。

配置优先级：config.json 中的键值覆盖下方 _DEFAULTS 的同名项。
相对路径（如 ".pdf_cache"）会自动相对于「部署根目录」(本文件所在目录) 解析成绝对路径。
"""
import os
import json

# 部署根目录 = 本文件所在目录（即整个部署包的根）
DEPLOY_ROOT = os.path.dirname(os.path.abspath(__file__))


# ---- 默认值（= 原开发机上的取值；服务器上通过 config.json 覆盖）----
_DEFAULTS = {
    # 数据源根（网络盘，可选；离线包用缓存即可，无需此盘）
    "root": r"<HOUSE_SRC_ROOT>",

    # 台账 / Excel 输出（相对部署根）
    "ledger": "beian_records.json",
    "xlsx": "beian_records.xlsx",

    # 本地 PDF / 合同缓存（相对部署根；离线包核心数据）
    "cache": ".pdf_cache",

    # Chrome 持久登录态目录（相对部署根）
    "browser_profile": "browser_profile_beian",

    # 政府备案目标站
    "beian_url": "https://hyjg.zrzyt.zj.gov.cn/main.htm",
    # Chrome CDP 调试端口（start_chrome.bat 里要一致）
    "cdp_url": "http://localhost:9333",
    # 本机 Chrome 可执行文件（服务器上改为实际安装路径）
    "chrome_path": r"C:/Program Files/Google/Chrome/Application/chrome.exe",

    # 各年数据源根（仅当服务器能挂 W: 重新提取时才用；离线包可忽略）
    "year_roots": [
        r"<HOUSE_SRC_ROOT>/2024年备案",
        r"<HOUSE_SRC_ROOT>/2025年备案",
        r"<HOUSE_SRC_ROOT>/2026年备案",
    ],

    # 台账 JSON 里写死的「旧缓存绝对路径」前缀；部署后会自动翻译成上面的 cache。
    # 若你曾把缓存放在别的盘，改这一项即可。
    "legacy_cache_root": r"E:/网站备案/.pdf_cache",

    # 政府网登录账号（注意：登录有图形验证码，脚本不会自动填，仍需人工登录一次）。
    # 这里仅作记录，目前不用于自动登录。
    "login_user": "",
    "login_pass": "",
}


def _resolve(p):
    """相对路径 -> 部署根下的绝对路径；绝对路径原样返回。"""
    if not p:
        return p
    if os.path.isabs(p):
        return p
    return os.path.normpath(os.path.join(DEPLOY_ROOT, p))


# ---- 合并 config.json ----
_CFG = dict(_DEFAULTS)
_cfg_path = os.path.join(DEPLOY_ROOT, "config.json")
if os.path.exists(_cfg_path):
    try:
        with open(_cfg_path, encoding="utf-8") as _f:
            _over = json.load(_f)
        if isinstance(_over, dict):
            _CFG.update(_over)
    except Exception as _e:  # 配置读不出就用默认，不致命
        import sys
        print(f"[beian_config] 读取 config.json 失败，使用默认配置: {_e}", file=sys.stderr)

CFG = _CFG

# ---- 解析后的关键绝对路径 ----
LEDGER_PATH = _resolve(CFG["ledger"])
XLSX_PATH = _resolve(CFG["xlsx"])
CACHE_PATH = _resolve(CFG["cache"])
PROFILE_PATH = _resolve(CFG["browser_profile"])


def norm_cache_path(p):
    """把台账里写死的旧缓存绝对路径翻译成当前配置的缓存根。

    例：E:/网站备案/.pdf_cache\\2023...\\合同.jpg
      -> <部署根>/.pdf_cache\\2023...\\合同.jpg
    已经是新缓存根的，原样返回；其它路径原样返回。
    """
    if not p:
        return p
    p2 = p.replace("/", "\\")
    legacy = CFG["legacy_cache_root"].replace("/", "\\").rstrip("\\")
    new = CACHE_PATH.replace("/", "\\").rstrip("\\")
    if new and p2.lower().startswith(new.lower()):
        return p2
    if legacy and p2.lower().startswith(legacy.lower()):
        return new + p2[len(legacy):]
    return p
