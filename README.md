# 测绘备案自动化（jianfang2）

从公司内网共享盘批量提取测绘报告 / 合同信息，自动填入 **浙江省测绘地理信息综合监管服务平台**
（`https://hyjg.zrzyt.zj.gov.cn/main.htm`）并上传附件的半自动工具。覆盖**房产备案**与**工程备案**两条业务线。

> ⚠️ **合规前提**：本工具严格遵守「合法脚本」底线——不绕验证码、不伪造请求、不规避风控、不秒级狂刷；
> 按真人节奏操作（随机 5–15s + 模拟鼠标），登录态过期后由人工重新登录。详见 `SOP_测绘备案自动化.md` 第 1 章。

---

## ⚠️ 本仓库已脱敏（重要）

本仓库**只包含源码 + 文档 + 业务规则**，已剔除一切敏感内容：

| 类别 | 处理方式 |
|---|---|
| 客户台账 / 合同 PDF / OCR 缓存 | **不入库**（`.gitignore` 已排除），本地保管 |
| 明文账号密码 | 含明文密码的调试脚本（`_fill_login.py` 等）**已排除**；主力代码不硬编码密码 |
| 真实客户 / 委托人姓名 | 已从源码示例路径、测试键注释中去除；`beian_skip_names.json` 仅保留**示例占位** |
| 内网共享路径（`W:/`、`V:\`） | 仅作为配置 `default` / 注释示例出现，部署时通过 `config.json` 覆盖 |

部署到公司环境时，请按 `备案部署包/config.json` 的说明填入真实路径与端口；**切勿把客户数据、密码、真实姓名提交回本仓库**。

---

## 目录结构

```
测绘备案自动化/
├── beian_fill.py            # 房产备案主流程（提取→填表→上传→断点续跑）
├── beian_form_mapper.py     # 房产字段映射与生成填报数据
├── beian_ledger.py          # 台账读写 / 进度标记 / 断点续跑
├── beian_browser.py         # 通过 CDP 接管已登录的 Chrome
├── beian_config.py          # 路径 / 端口 / URL 集中配置（读 config.json 覆盖）
├── beian_extract_worker.py  # PDF 信息提取 worker
├── beian_gc_*.py            # 工程备案流水线（OCR / 解析 / 映射 / 填报 / runner）
├── gen_*.py / build_*.py / join_*.py / fix_*.py / tag_*.py / dump_*.py / xlsx_dump.py
├── analyze_skip.py / query_skip_people.py   # 不传规则分析
├── _projtype_live.json      # 平台「项目类型」词表（规则资产）
├── 工程备案_子项映射表_定稿.csv   # 子项→平台大类/子项 映射规则（190 条）
├── beian_skip_names.example.json  # 不传名单示例占位（真实名单本地保管）
├── SOP_测绘备案自动化.md    # 项目标准作业程序（业务规则 + 运行 SOP + 故障排查）
└── 备案部署包/              # 部署外壳：requirements / config.json / 启动 bat / 自检 / 手册
```

> 注：根目录的 `beian_*.py` 为最新源码；`备案部署包/` 内同名旧版已不再维护，仅保留其部署入口（bat / config / 手册 / 自检）。

---

## 环境要求

- **Python 3.11**（服务器硬约束：3.13 / 3.8 / 2.7 等均禁用）
- 依赖：`playwright` `fitz`(PyMuPDF) `openpyxl` `rapidocr-onnxruntime`（见 `备案部署包/requirements.txt`）
- 浏览器：独立 Chrome，以 `--remote-debugging-port=9333` + 持久 profile 启动，脚本经 CDP 接管
- 数据源：公司内网共享盘（房产 `W:/2020备案`、工程 `V:\2、合同类归档`），离线场景用本地 `.pdf_cache`

---

## 标准运行（简述）

1. 用户双击 `备案部署包/start_chrome.bat` 启动常驻 Chrome（**不能由脚本后台拉起**）；
2. 在 Chrome 中打开备案站并人工登录（账号见本地密码记录，不在此仓库）；
3. 跑 `备案部署包/precheck.py` 自检（依赖 / CDP / 登录态 / 队列）；
4. 执行上传：`python beian_fill.py --all --month=YYYYMM`（房产）或工程 runner（开发中）；
5. 登录态约 4h 过期 → 人工重登，脚本靠 `beian_progress.json` + `beian_upload_log.json` 断点续跑。

完整规则、字段口径、故障排查见 `SOP_测绘备案自动化.md`。

---

## 合规红线（不可逾越）

1. 不绕验证码、不伪造请求、不规避风控、不秒级狂刷；
2. 登录态过期必须人工重登，脚本不得自动破解；
3. 数据最小化：不上传客户隐私、不回传密码、不提交真实姓名；
4. 仅按用户确认的规则执行（无合同不传、委托方已在正式库不报、综合测绘=多测合一先不上传）。

---

## 仓库地址

- GitHub（私有）：`<待推送后填入，例如 https://github.com/<用户名>/<仓库名>>`
