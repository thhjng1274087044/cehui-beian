"""
自动填报脚本：填表 + 上传 + 保存 + 关闭
========================================
流程：
  1. 导航到「项目信息报送」页 → 点击「添加」打开表单
  2. 填写全部字段（固定值 + 变动值）
  3. 选择地址级联（省/市/县）+ 填详细地址(乡镇)
  4. 选择项目类型级联
  5. 保存后进修改页：只上传合同（测绘其他资料不传）+ 分配人员
  6. 点击「保 存」
  7. 保存后：先点 X 关闭可能弹出的提示框 → 点「返回上一级」回主页 → 回主页后再点一次 X 关闭覆盖层

用法：
  python beian_fill.py --all --month=202401              # 只跑一个月
  python beian_fill.py --all --month=202401,202402,202403  # 一次跑多个月（按时间顺序）
  python beian_fill.py --all --month=202401-202406         # 一次跑连续区间（含首尾）
  python beian_fill.py --all                             # 台账内全部按月顺序跑完
  python beian_fill.py --all --limit=3                   # 限量试跑
  python beian_fill.py --dry-run                         # 只打印不操作浏览器
  python beian_fill.py --fix-contracts                 # 已上传但缺合同：只补合同（搜索→上传→保存→退出）
  python beian_fill.py --fix-contracts --dry-run       # 只列出待补，不动浏览器
  python beian_fill.py --fix-contracts --limit=5       # 限量补录

去重：以报告编号写入 beian_upload_log.json，已上传绝不重跑；重名委托方按「列表行数 vs 已上传同名数」决定新建还是补全。
合同补录进度：beian_contract_fix_log.json
"""
import sys, os, json, time, random, logging, datetime, re
from pathlib import Path

# ================================================================
#  日志配置
# ================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("beian_fill")

# ================================================================
#  导入
# ================================================================
from beian_browser import BeianBrowser
from beian_form_mapper import generate_form_data, generate_project_name
import beian_ledger as L
import beian_config as _cfg

# ================================================================
#  常量
# ================================================================
BASE_URL = "https://hyjg.zrzyt.zj.gov.cn/mapping/project/baseInfo/baseInfoRecord"
TEST_RECORD_KEY = "CX202402007"   # 试点用测试报告编号

# 测试数据路径（部署时通过 config.json 的 test_pdf_dir 覆盖；此处为占位示例）
TEST_PDF_DIR = _cfg.CFG.get("test_pdf_dir", r"<示例: <HOUSE_SRC_ROOT>/YYYY年备案/M月份/F# 地点/人名/文件名>")

# 用户确认：已在「项目信息查询」正式库、无需再报的委托方名单
SKIP_NAMES_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "beian_skip_names.json")

def load_skip_names():
    if os.path.exists(SKIP_NAMES_FILE):
        try:
            data = json.load(open(SKIP_NAMES_FILE, encoding="utf-8"))
            return set(data.get("names") or [])
        except Exception:
            return set()
    return set()

def is_skip_record(rec: dict, skip_names: set) -> bool:
    """委托方/建设单位命中跳过名单则不再上报。"""
    if not skip_names:
        return False
    for field in ("委托方", "建设单位"):
        name = (rec.get(field) or "").strip()
        if name and name in skip_names:
            return True
    return False


class BeianFiller:
    """自动填报器——封装完整的填表+上传+保存+关闭流程。"""

    def __init__(self, dry_run=False):
        self.dry_run = dry_run
        self.browser = None
        self.page = None
        if not dry_run:
            self.browser = BeianBrowser()
            self.page = self.browser.page

    # ---- 工具方法 ----

    def human_delay(self, min_s=0.3, max_s=0.7):
        """模拟人类操作间隔（已压缩：默认 0.3~0.7s，仍拟人但更快）。"""
        t = random.uniform(min_s, max_s)
        log.info(f"  ⏱ 等待 {t:.1f}s ...")
        time.sleep(t)

    def human_mouse(self, x=None, y=None):
        """模拟鼠标移动（让行为监测认为是真人）。"""
        if self.dry_run:
            return
        try:
            if x is None or y is None:
                # 随机移动到页面某处
                vw = self.page.viewport_size["width"]
                vh = self.page.viewport_size["height"]
                x = random.randint(100, vw - 100)
                y = random.randint(100, vh - 100)
            self.page.mouse.move(x, y)
            time.sleep(random.uniform(0.2, 0.6))
        except Exception:
            pass

    def _find_input_by_placeholder(self, placeholder: str):
        """通过 placeholder 找 input 元素。"""
        return self.page.locator(f'input[placeholder="{placeholder}"]')

    def _find_form_item_by_label(self, label_text: str):
        """通过标签文本找 .el-form-item，返回其内部控件容器。"""
        # 精确匹配 label 文本
        return self.page.locator(f'.el-form-item:has(.el-form-item__label:text-is("{label_text}"))')

    def _fill_text_input(self, placeholder: str, value: str, label_hint=""):
        """填写文本输入框。value 为空字符串则跳过。"""
        if not value:
            log.info(f"  ⏭ [{label_hint or placeholder}] = (不填)")
            return True
        log.info(f"  ✏️ [{label_hint or placeholder}] = {value}")
        if self.dry_run:
            return True
        try:
            inp = self._find_input_by_placeholder(placeholder)
            inp.click()
            self.human_delay(0.2, 0.4)
            inp.fill(value)
            self.human_mouse()
            return True
        except Exception as e:
            log.error(f"  ❌ 填写失败 [{placeholder}]: {e}")
            return False

    def _fill_select_by_label(self, label: str, value: str):
        """填写下拉选择框：找到对应 label 的 el-select，点开选值。"""
        log.info(f"  🔽 [{label}] → {value}")
        if self.dry_run:
            return True
        try:
            # 关掉可能残留的其它下拉，避免点到不稳定面板
            try:
                self.page.keyboard.press("Escape")
            except Exception:
                pass
            self.human_delay(0.15, 0.3)
            item = self._find_form_item_by_label(label)
            sel = item.locator(".el-select").first
            sel.click(force=True, timeout=5000)
            self.human_delay(0.25, 0.5)
            option = self.page.locator(
                ".el-select-dropdown:visible .el-select-dropdown__item"
            ).filter(has_text=value)
            option.first.wait_for(state="visible", timeout=5000)
            option.first.click(force=True, timeout=5000)
            self.human_delay(0.3, 0.7)
            self.human_mouse()
            return True
        except Exception as e:
            # 再试一次：关闭面板后重开
            try:
                self.page.keyboard.press("Escape")
                self.human_delay(0.2, 0.4)
                item = self._find_form_item_by_label(label)
                item.locator(".el-select").first.click(force=True, timeout=5000)
                self.human_delay(0.3, 0.6)
                option = self.page.locator(
                    ".el-select-dropdown:visible .el-select-dropdown__item"
                ).filter(has_text=value)
                option.first.click(force=True, timeout=5000)
                self.human_delay(0.3, 0.6)
                log.info(f"  ✅ [{label}] 重试成功 → {value}")
                return True
            except Exception as e2:
                log.error(f"  ❌ 选择失败 [{label}]→{value}: {e2}")
                try:
                    self.page.keyboard.press("Escape")
                except Exception:
                    pass
                return False

    def _open_cascader(self, locator):
        """稳健打开级联面板：force 点击内部 input，等待可见面板。"""
        inp = locator.locator("input").first
        inp.click(force=True, timeout=4000)
        # 等待可见面板（DOM 里可能有多个隐藏面板）
        self.page.locator(".el-cascader-panel").filter(visible=True).first.wait_for(
            state="visible", timeout=5000
        )
        self.human_delay(0.6, 1.2)

    def _pick_cascader_node(self, level_val: str):
        """在可见面板中点击文本匹配的节点（点 .el-cascader-node 本体更可靠）。"""
        node = (
            self.page.locator(".el-cascader-panel").filter(visible=True).first
            .locator(".el-cascader-node").filter(has_text=level_val).first
        )
        node.click(timeout=3000)
        self.human_delay(0.4, 0.9)

    def _fill_cascader_address(self, province: str, city: str, county: str, detail: str):
        """填写地址级联选择器（省→市→县）+ 详细地址文本框。"""
        log.info(f"  🗺 地址级联: {province} → {city} → {county}, 详细={detail}")
        if self.dry_run:
            return True
        try:
            cas = self.page.locator(".el-cascader.division")
            self._open_cascader(cas)

            for level_val in [province, city, county]:
                self._pick_cascader_node(level_val)

            self.page.keyboard.press("Escape")
            self.human_delay(0.2, 0.4)

            # 填详细地址（乡镇街道）
            if detail:
                detail_inp = self._find_input_by_placeholder("请填写详细地址")
                detail_inp.click()
                self.human_delay(0.3, 0.7)
                detail_inp.fill(detail)
                self.human_mouse()

            return True
        except Exception as e:
            log.error(f"  ❌ 地址级联失败: {e}")
            return False

    def _fill_one_cascader(self, cas, value: str):
        """在给定 cascader locator 上填值。value 支持 '大类/小类' 或 叶子单值。
        '大类/小类'：先点大类展开再点小类；叶子单值：点 L1 即完成。"""
        if not value:
            return False
        if "/" in value:
            big, small = [x.strip() for x in value.split("/", 1)]
        else:
            big, small = value.strip(), ""
        self._open_cascader(cas)
        self._pick_cascader_node(big)
        self.human_delay(0.3, 0.5)
        if small:
            self.page.locator(".el-cascader-panel").filter(visible=True).first \
                .locator(".el-cascader-menu").nth(1).wait_for(state="visible", timeout=5000)
            self.human_delay(0.3, 0.5)
            l2 = (self.page.locator(".el-cascader-panel").filter(visible=True).first
                  .locator(".el-cascader-menu").nth(1)
                  .locator(".el-cascader-node").filter(has_text=small).first)
            l2.click(timeout=3000)
            self.human_delay(0.2, 0.5)
        self.page.keyboard.press("Escape")
        self.human_mouse()
        return True

    def _fill_cascader_project_type(self, value: str):
        """填写第一个「项目类型」级联器（单行回退用）。"""
        log.info(f"  📂 项目类型 → {value}")
        if self.dry_run:
            return True
        if not value:
            log.warning("  ⚠️ 项目类型为空，跳过")
            return False
        try:
            item = self.page.locator(
                '.el-form-item:has(.el-form-item__label:text-is("项目类型"))').first
            cas = item.locator(".el-cascader").first
            return self._fill_one_cascader(cas, value)
        except Exception as e:
            log.error(f"  ❌ 项目类型级联失败: {e}")
            return False

    def _row_count_projtype(self) -> int:
        return self.page.locator(
            '.el-form-item:has(.el-form-item__label:text-is("项目类型"))').count()

    def _fill_project_type_rows(self, rows: list):
        """按 [{类型,金额}] 逐行填写可重复的「项目类型 + 金额(万元)」区。
        默认表单 1 行；不足时点「新增」补行。"""
        if not rows:
            return False
        log.info(f"  📂 项目类型多行 × {len(rows)}: {[r.get('类型','') for r in rows]}")
        if self.dry_run:
            return True
        try:
            n = len(rows)
            guard = 0
            while self._row_count_projtype() < n and guard < 15:
                before = self._row_count_projtype()
                btn = self.page.locator('button').filter(has_text="新增").first
                btn.click(timeout=4000)
                self.human_delay(0.5, 1.0)
                if self._row_count_projtype() <= before:
                    log.warning("  ⚠️ 「新增」未增加行，停止补行")
                    break
                guard += 1

            for i, r in enumerate(rows):
                typ = (r.get("类型") or "").strip()
                amt = (r.get("金额") or "").strip()
                # 第 i 个项目类型 cascader
                item = self.page.locator(
                    '.el-form-item:has(.el-form-item__label:text-is("项目类型"))').nth(i)
                if typ:
                    self._fill_one_cascader(item.locator(".el-cascader").first, typ)
                    self.human_delay(0.3, 0.6)
                # 第 i 个金额(万元)输入
                if amt:
                    amt_item = self.page.locator(
                        '.el-form-item:has(.el-form-item__label:text-is("金额(万元)"))').nth(i)
                    inp = amt_item.locator("input").first
                    inp.click()
                    self.human_delay(0.2, 0.4)
                    inp.fill(amt)
                    self.human_mouse()
                    self.human_delay(0.3, 0.6)
                log.info(f"     ✅ 行{i+1}: {typ} | {amt or '(金额空)'}")
            return True
        except Exception as e:
            log.error(f"  ❌ 项目类型多行填写失败: {e}")
            return False

    def _fill_date_range(self, start_date: str, end_date: str):
        """填写日期范围选择器（开工-完工时间）。"""
        log.info(f"  📅 日期范围: {start_date} ~ {end_date}")
        if self.dry_run:
            return True
        try:
            dp = self.page.locator(".el-date-editor--daterange")
            dp.click()
            self.human_delay(0.2, 0.5)

            # 清空并分别填入开始和结束日期
            inputs = dp.locator("input")
            inputs.nth(0).click()
            inputs.nth(0).fill(start_date)
            self.human_delay(0.2, 0.4)
            inputs.nth(1).click()
            inputs.nth(1).fill(end_date)
            self.human_delay(0.2, 0.4)

            # 按 Enter 或点击外部确认
            self.page.keyboard.press("Enter")
            self.human_mouse()
            return True
        except Exception as e:
            log.error(f"  ❌ 日期范围失败: {e}")
            return False

    def _fill_single_date(self, date_str: str, label="合同签订日期"):
        """填写单个日期选择器。"""
        log.info(f"  📅 {label} = {date_str}")
        if self.dry_run:
            return True
        try:
            item = self._find_form_item_by_label(label)
            dp = item.locator(".el-date-editor")
            dp.click()
            self.human_delay(0.2, 0.5)
            inp = dp.locator("input")
            inp.fill(date_str)
            self.human_delay(0.2, 0.4)
            self.page.keyboard.press("Enter")
            self.human_mouse()
            return True
        except Exception as e:
            log.error(f"  ❌ 日期填写失败[{label}]: {e}")
            return False

    def _wait_upload_done(self, timeout: float = 25, filename: str = ""):
        """等待最近一次上传完成。

        改用条件等待，检测到「文件名已出现在编辑弹窗附件表格(tbody)且无可进度条」即判定完成，
        不再傻等满 timeout（之前用 .el-upload-list__item 检测，但该站点上传列表是自定义表格，
        导致永远检测不到、白等约 30s 才点确定 —— 即“点确定很慢”的根因）。

        同时兼容传统 el-upload 列表(.el-upload-list__item 带 is-success)以兜底。
        """
        if self.dry_run:
            return True
        try:
            deadline = time.time() + timeout
            base = os.path.basename(filename) if filename else ""
            while time.time() < deadline:
                state = self.page.evaluate('''() => {
                    const out = {total:0, uploading:0, done:0, names:[], progress:0};
                    // 1) 传统 el-upload 列表（兜底）
                    const items = [...document.querySelectorAll('.el-upload-list__item')];
                    out.total += items.length;
                    out.uploading += items.filter(i =>
                        i.className.includes('is-uploading') || i.querySelector('.el-progress')).length;
                    out.done += items.filter(i => i.className.includes('is-success')).length;
                    // 2) 编辑弹窗附件表格（自定义 tbody）
                    const dlg = [...document.querySelectorAll('.el-dialog')].find(d => {
                        const w = d.closest('.el-dialog__wrapper') || d;
                        return w.style.display !== 'none' && getComputedStyle(w).visibility !== 'hidden';
                    });
                    if (dlg) {
                        dlg.querySelectorAll('.el-progress').forEach(pr => {
                            if (!/display:\\s*none/.test(pr.getAttribute('style') || '')) out.progress += 1;
                        });
                        dlg.querySelectorAll('tbody tr').forEach(tr => {
                            out.names.push((tr.innerText || '').replace(/\\s+/g, ' '));
                        });
                    }
                    return out;
                }''')
                if isinstance(state, dict):
                    # 文件名已入弹窗附件表格且无进度条 => 上传完成
                    if base and any(base in (n or '') for n in state.get("names", [])) \
                            and state.get("progress", 0) == 0:
                        return True
                    # 传统列表：无上传中且已有完成项
                    if state.get("total", 0) > 0 and state.get("uploading", 0) == 0:
                        return True
                    # 无文件名场景：弹窗表格已有行且无进度 => 视为完成
                    if not base and state.get("names", []) and state.get("progress", 0) == 0:
                        return True
                time.sleep(0.4)
            return False
        except Exception:
            return True

    def _upload_file(self, file_path: str, description=""):
        """上传文件到文件选择区域（提速版：set 后等完成，不再固定长延迟）。"""
        if not file_path or not os.path.exists(file_path):
            log.warning(f"  ⚠️ 文件不存在, 跳过上传: {file_path}")
            return False
        log.info(f"  📎 上传{description}: {os.path.basename(file_path)}")
        if self.dry_run:
            return True
        try:
            file_inputs = self.page.query_selector_all('input[type="file"]')
            if not file_inputs:
                log.error("  ❌ 未找到文件上传 input")
                return False
            fi = file_inputs[0]
            fi.set_input_files(file_path)
            ok = self._wait_upload_done()
            if not ok:
                log.warning("  ⚠️ 上传完成状态未确认，继续（可能已成功）")
            self.human_delay(0.2, 0.4)
            self.human_mouse()
            return True
        except Exception as e:
            log.error(f"  ❌ 上传失败: {e}")
            return False

    # ---- 主流程 ----

    def _click_btn_normalized(self, *texts):
        """按「去除空格后包含某文本」点击按钮，兼容「添 加」「保 存」等带空格文案。

        Playwright 的 has-text 不归一化空格，站点按钮常写成「添 加」「保 存」，
        用精确字符串匹配会漏。这里用 DOM 查询按 innerText 去空格后包含匹配并点击。
        """
        page = self.page
        for t in texts:
            norm = t.replace(" ", "")
            try:
                ok = page.evaluate('''([txt]) => {
                    const btns = [...document.querySelectorAll('button')];
                    const b = btns.find(el => {
                        const tx = (el.innerText || '').replace(/\\s+/g, '');
                        return tx.includes(txt) && getComputedStyle(el).display !== 'none'
                               && getComputedStyle(el).visibility !== 'hidden';
                    });
                    if (b) { b.click(); return true; }
                    return false;
                }''', norm)
                if ok:
                    return True
            except Exception:
                pass
        return False

    def ensure_form_open(self):
        """确保在「添加」表单页面。始终回到报送列表页再点击「添加」，避免列表页
        残留遮罩/可见筛选表单导致误判「表单已打开」而漏点「添加」。"""
        if self.dry_run:
            log.info("🔍 [DRY-RUN] 假设表单已打开")
            return True
        page = self.page
        # 始终回到报送列表页，得到干净、确定的页面状态
        page.goto(BASE_URL, wait_until="domcontentloaded", timeout=20000)
        self.human_delay(1, 2)
        self._clear_overlays("打开表单前")
        self.human_delay(0.3, 0.6)
        # 点击「新增 / 添加」打开新表单（按钮文本可能带空格，如「添 加」）
        log.info("🖱 点击「添加」...")
        if not self._click_btn_normalized("添加", "新增"):
            log.error("❌ 未找到「新增/添加」按钮")
            return False
        self.human_delay(0.8, 1.4)
        # 等待添加表单出现（优先 visible，退化 attached）
        try:
            page.wait_for_selector(".el-form", state="visible", timeout=10000)
        except Exception:
            try:
                page.wait_for_selector(".el-form", timeout=5000)
            except Exception as e:
                log.error(f"❌ 打开表单失败: {e}")
                return False
        log.info("✅ 表单已打开")
        return True

    def fill_one_record(self, record: dict, pdf_path: str = "", contract_paths: list = None,
                        close_after_save: bool = True):
        """填报一条完整记录。

        参数:
            record: 台账记录 dict
            pdf_path: 房测报告 PDF 绝对路径
            contract_paths: 合同文件绝对路径列表
        """
        contract_paths = contract_paths or []
        fd = generate_form_data(record)
        name = fd.get("建设单位", "?")
        report_no = fd.get("_source_report_no", "?")
        log.info(f"\n{'='*50}")
        log.info(f"📋 开始填报: {name} (编号:{report_no})")
        log.info(f"{'='*50}")

        # 1. 确保表单已打开
        if not self.ensure_form_open():
            return False
        self.human_delay()

        # 2. ===== 基本信息 =====
        log.info("\n--- 基本信息 ---")

        # 下拉固定值
        self._fill_select_by_label("是否分包项目", fd.get("是否分包项目"))
        self.human_delay()

        self._fill_select_by_label("是否多测合一项目", fd.get("是否多测合一项目"))
        self.human_delay()

        # 项目名称
        self._fill_text_input("请填写项目名称", fd.get("项目名称"), "项目名称")
        self.human_delay()

        # 跨地市/跨区县
        self._fill_select_by_label("项目范围是否跨地市", fd.get("项目范围是否跨地市"))
        self.human_delay()

        self._fill_select_by_label("项目范围是否跨区县", fd.get("项目范围是否跨区县"))
        self.human_delay()

        # 地址级联 + 详细地址
        self._fill_cascader_address(
            fd.get("省"), fd.get("市"), fd.get("区县"),
            fd.get("详细地址(乡镇)", "")
        )
        self.human_delay()

        # 日期范围（开工-完工）
        self._fill_date_range(fd.get("预计开工时间"), fd.get("预计完工时间"))
        self.human_delay()

        # 质量验收约定
        self._fill_select_by_label("质量验收约定", fd.get("质量验收约定"))
        self.human_delay()

        self._fill_select_by_label("是否有监理", fd.get("是否有监理"))
        self.human_delay()

        self._fill_select_by_label(
            "是否涉及有限空间作业或地下管线探测",
            fd.get("是否涉及有限空间作业或地下管线探测")
        )
        self.human_delay()

        # 3. ===== 建设单位 =====
        log.info("\n--- 建设单位 ---")

        self._fill_text_input("请填写业主单位名称", fd.get("建设单位"), "建设单位")
        self.human_delay()

        self._fill_text_input(
            "请填写建设单位项目联系人",
            fd.get("建设单位项目联系人"),
            "建设单位项目联系人"
        )
        self.human_delay()

        # 建设单位联系电话 = 不填
        phone_val = fd.get("建设单位联系电话", "")
        if phone_val:
            self._fill_text_input(
                "请填写建设单位联系电话",
                phone_val,
                "建设单位联系电话"
            )
        else:
            log.info(f"  ⏭ [建设单位联系电话] = (不填/留空)")
        self.human_delay()

        self._fill_text_input(
            "请填写测绘单位项目联系人",
            fd.get("测绘单位项目联系人"),
            "测绘单位项目联系人"
        )
        self.human_delay()

        survey_phone = fd.get("测绘单位联系人电话", "")
        if survey_phone:
            self._fill_text_input(
                "请填写测绘单位联系电话",
                survey_phone,
                "测绘单位联系人电话"
            )
        self.human_delay()

        # 4. ===== 合同信息 =====
        log.info("\n--- 合同信息 ---")

        # 合同编号 = 不填
        contract_no = fd.get("合同编号", "")
        if contract_no:
            self._fill_text_input("请填写合同编号", contract_no, "合同编号")
        else:
            log.info(f"  ⏭ [合同编号] = (不填/留空)")
        self.human_delay()

        # 合同签订日期
        self._fill_single_date(fd.get("合同签订日期", ""))
        self.human_delay()

        # 项目合同金额
        self._fill_text_input(
            "请填写项目合同金额",
            fd.get("项目合同金额(万元)"),
            "项目合同金额(万元)"
        )
        self.human_delay()

        # 项目类型 + 金额(万元)（可重复行：每行=一个项目类型+金额）
        rows_multi = fd.get("项目类型_多行") or []
        if rows_multi:
            self._fill_project_type_rows(rows_multi)
        else:
            # 回退：单行
            self._fill_text_input("请填写金额", fd.get("金额(万元)", ""), "金额(万元)")
            self.human_delay()
            self._fill_cascader_project_type(fd.get("项目类型", ""))
        self.human_delay()

        # 是否属于基础测绘...
        self._fill_select_by_label(
            "是否属于基础测绘项目或重大建设工程的测绘项目",
            fd.get("是否属于基础测绘项目或重大建设工程的测绘项目")
        )
        self.human_delay()

        # 5. ===== 上传附件 =====
        # 注意：创建表单无附件控件，附件（合同/PDF）在保存后的【修改页】上传，
        # 见 complete_via_modify()。此处不传，避免误命中隐藏 input。
        log.info("\n--- 上传附件 --- (创建表单无附件控件，留待修改页上传)")

        # 6. ===== 保存 =====
        log.info("\n--- 保存 ---")
        log.info("💾 点击「保 存」...")
        if not self.dry_run:
            try:
                save_btn = self.page.locator('button:has-text("保 存")').filter(visible=True)
                save_btn.first.click(timeout=5000)
                self.human_delay(1, 2)

                # 检查是否有成功提示或错误提示
                success = self._check_save_result()
                if success:
                    log.info("✅ 保存成功!")
                else:
                    log.warning("⚠️ 保存结果不确定，请人工检查")
            except Exception as e:
                log.error(f"❌ 点击保存失败: {e}")
                return False

        # 6.5 保存后：立即清掉可能出现的「保存成功」确认框（无 X、只有确定按钮）
        self._clear_overlays("保存后弹窗")

        # 7. ===== 关闭弹窗 / 返回主页面 / 修改页补全 =====
        if close_after_save:
            if not self.dry_run:
                self._return_to_main()
                # 进入修改页：上传合同、分配参与人员、保存、返回主页
                log.info("\n--- 进入修改页补全（上传合同+分配人员）---")
                ok_mod = self.complete_via_modify(record, pdf_path, contract_paths)
                if not ok_mod:
                    log.error(f"❌ 修改页补全失败: {name} — 不标记为已上传，下次可续跑补全")
                    return False
        else:
            log.info("\n--- 保存完成，表单保持打开（供人工核对）---")

        log.info(f"\n{'='*50}")
        log.info(f"🏁 填报完成: {name} ({report_no})")
        log.info(f"{'='*50}\n")
        return True

    def _check_save_result(self):
        """检查保存后的结果（成功提示/错误信息）。"""
        try:
            # 等待可能的弹窗/消息
            self.page.wait_for_timeout(1500)
            # 检查是否有成功消息 (Element Plus message)
            msg = self.page.query_selector(".el-message--success")
            if msg:
                text = msg.inner_text()
                log.info(f"  📢 系统提示: {text}")
                return True
            # 检查是否有错误消息
            err = self.page.query_selector(".el-message--error")
            if err:
                text = err.inner_text()
                log.error(f"  ❌ 系统错误: {text}")
                return False
            # 如果没有明确消息但也没报错，假设成功
            return True
        except Exception:
            return True  # 不确定时默认继续

    def _click_close_x(self, where: str = ""):
        """关闭任何可见的弹窗/覆盖层（点击右上角 X）。

        站点多处关闭动作靠右上角 X 完成（如保存后的提示框、返回主页后的
        覆盖层）。此方法尝试点常见的关闭按钮，找到并点击则返回 True。
        找不到说明当前无弹窗，属正常情况。
        """
        if self.dry_run:
            return False
        try:
            candidates = [
                ".el-dialog__headerbtn",   # 对话框右上角 X
                ".el-dialog__close",
                ".el-message-box__close",  # 确认框 X
                ".el-message__closeBtn",   # 成功/提示 toast 的关闭按钮（showClose 时）
                ".el-drawer__close",       # 抽屉 X
            ]
            for sel in candidates:
                btns = self.page.locator(sel).filter(visible=True)
                n = btns.count()
                if n > 0:
                    log.info(f"  ✖ 点击关闭X (找到 {n} 个, {where})")
                    btns.first.click(timeout=3000)
                    self.human_delay(0.2, 0.5)
                    self.human_mouse()
                    return True
            # 没有 X 按钮也正常（有些关闭仅靠「返回上一级」按钮）
            return False
        except Exception as e:
            log.warning(f"  ⚠️ 点击关闭X异常({where}): {e}")
            return False

    def _clear_overlays(self, where: str = ""):
        """反复清掉所有可见覆盖层（对话框/提示框/通知/抽屉/确认框），避免拦截后续点击。

        覆盖三类关闭方式：
          1) 右上角 X（含 toast / 抽屉 / 对话框 / 确认框关闭按钮）
          2) 无 X 的对话框/确认框：点其主操作按钮（确定/是）。遇到删除/作废等危险文案则跳过，
             避免误确认破坏性操作。
          3) 抽屉兜底：点关闭按钮 + 最终 Escape。
        """
        if self.dry_run:
            return
        page = self.page
        DANGER = ("删除", "注销", "作废", "清空", "移除", "关闭账号", "撤销")
        for _ in range(10):
            closed = False
            # 1) 任何可见的 header / 关闭按钮
            for sel in [".el-dialog__headerbtn", ".el-dialog__close",
                        ".el-message-box__close", ".el-drawer__close",
                        ".el-notification__closeBtn", ".el-message__closeBtn"]:
                try:
                    btns = page.locator(sel).filter(visible=True)
                    if btns.count() > 0:
                        btns.first.click(timeout=2000)
                        self.human_delay(0.2, 0.4)
                        closed = True
                except Exception:
                    pass
            # 2) 无 X 的对话框/确认框：点主操作按钮（确定/是）
            try:
                dlg = page.locator(".el-dialog:visible, .el-message-box:visible").first
                if dlg.count() > 0:
                    txt = dlg.inner_text() or ""
                    if not any(d in txt for d in DANGER):
                        ok = dlg.locator("button").filter(has_text=re.compile(r"^(确定|是)$"))
                        if ok.count() > 0:
                            ok.first.click(timeout=2000)
                            self.human_delay(0.2, 0.4)
                            closed = True
            except Exception:
                pass
            # 3) 抽屉兜底：点关闭按钮
            try:
                drawer = page.locator(".el-drawer:visible").first
                if drawer.count() > 0:
                    cb = drawer.locator(".el-drawer__close")
                    if cb.count() > 0:
                        cb.first.click(timeout=2000)
                        self.human_delay(0.2, 0.4)
                        closed = True
            except Exception:
                pass
            if not closed:
                break
        # 4) 兜底：Escape 关闭任何残留气泡/抽屉/模态
        try:
            page.keyboard.press("Escape")
            self.human_delay(0.2, 0.4)
        except Exception:
            pass

    def find_and_open_modify(self, project_name: str, name_key: str = ""):
        """在报送列表【搜索项目】并打开其『修改』页。

        流程：
          1) 强制回到列表主页(BASE_URL)并等待搜索框出现（避免停在别的页导致搜索失败）
          2) 用完整项目名称在 placeholder="请填写项目名称" 搜索框过滤
          3) 用 Playwright filter(has_text=) 稳匹配行，优先完整名、退化建设单位名
          4) 若仍未命中，清空搜索遍历全部行匹配
        命中后点击该行的『修改』按钮，等待修改页(含上传区)出现。
        返回是否成功进入修改页。
        """
        if self.dry_run:
            return False
        page = self.page
        log.info(f"\n--- 查找并打开修改: {project_name} (候选名:{name_key}) ---")

        # 1) 强制回到列表主页并等搜索框
        page.goto(BASE_URL, wait_until="domcontentloaded", timeout=20000)
        try:
            page.wait_for_selector('input[placeholder="请填写项目名称"]', timeout=10000)
        except Exception as e:
            log.warning(f"  ⚠️ 列表页搜索框未出现(可能未登录/掉线): {e}")
        self.human_delay(0.8, 1.5)
        # 列表页可能自动弹出提示框（如创建成功后的后续确认），先清掉再交互
        self._clear_overlays("列表页遮罩清理")

        # 2) 搜索：完整项目名称（遮罩残留时强制清两次 + force 点击）
        try:
            sb = page.locator('input[placeholder="请填写项目名称"]').first
            if sb.count() > 0:
                for attempt in range(3):
                    self._clear_overlays(f"搜索框交互前清理#{attempt+1}")
                    try:
                        sb.click(force=True, timeout=8000)
                        sb.fill(project_name)
                        self.human_delay(0.3, 0.6)
                        search_btn = page.locator('button:has-text("搜索")').first
                        if search_btn.count() > 0:
                            search_btn.click(force=True, timeout=5000)
                            self.human_delay(0.5, 1.0)
                            log.info("  🔎 已用完整项目名称搜索")
                        break
                    except Exception as e_try:
                        if attempt >= 2:
                            raise e_try
                        log.warning(f"  ⚠️ 搜索被遮罩拦截，重试({attempt+1}): {e_try}")
                        self.human_delay(0.5, 1.0)
        except Exception as e:
            log.warning(f"  ⚠️ 搜索框操作失败(忽略): {e}")

        def locate_and_click(match_text: str):
            rows = page.locator(".el-table__body-wrapper tbody tr")
            n = rows.count()
            log.info(f"  搜索结果 {n} 行，匹配关键字: {match_text}")
            hit = rows.filter(has_text=match_text)
            if hit.count() > 0:
                mod = hit.first.locator('button:has-text("修改")')
                if mod.count() > 0:
                    log.info(f"  ✏️ 找到匹配行，点击「修改」")
                    self._clear_overlays("点修改前清遮罩")
                    mod.first.click()
                    self.human_delay(0.6, 1.2)
                    try:
                        page.wait_for_selector(".el-form, .el-upload", timeout=8000)
                    except Exception:
                        pass
                    log.info("✅ 已进入修改页")
                    return True
            return False

        if locate_and_click(project_name):
            return True
        if name_key and locate_and_click(name_key):
            return True

        # 4) 退化：清空搜索后遍历全部行
        log.warning("  ⚠️ 按名称未命中，清空搜索遍历全部行")
        try:
            sb = page.locator('input[placeholder="请填写项目名称"]').first
            if sb.count() > 0:
                sb.fill("")
                page.locator('button:has-text("搜索")').first.click()
                self.human_delay(0.5, 1.0)
        except Exception:
            pass
        if name_key and locate_and_click(name_key):
            return True

        log.warning(f"  ❌ 未找到 {project_name} / {name_key} 的修改按钮")
        return False

    def _return_to_main(self):
        """从修改/详情页【返回主页面】，并确保所有弹窗/覆盖层都被 X 掉。

        用户规则：每次返回主页面都要点 X 关掉残留弹窗。本方法分三段：
          1) 返回前：循环清掉所有可见弹窗/抽屉/通知/确认框（多层堆叠也能清干净），
             避免残留弹窗遮罩拦截「返回上一级」点击。
          2) 点「返回上一级」/「返回」；找不到则直接导航到列表页（兜底整页刷新）。
          3) 返回主页后：再循环清一次覆盖层，确保主页干净。
        """
        if self.dry_run:
            return
        page = self.page
        log.info("\n--- 返回主页面 ---")

        # 1) 返回前：循环清掉所有可见覆盖层（多层也能清干净，避免挡住返回点击）
        self._clear_overlays("返回前覆盖层")

        # 2) 点返回按钮（优先「返回上一级」，退化「返回」），force 跳过偶发拦截
        for label in ["返回上一级", "返回"]:
            btn = page.locator(f'button:has-text("{label}")')
            if btn.count() > 0:
                try:
                    btn.first.click(timeout=5000, force=True)
                    self.human_delay(0.5, 1.0)
                    log.info(f"✅ 已点「{label}」")
                    break
                except Exception as e:
                    log.warning(f"⚠️ 点「{label}」异常: {e}")
        # 兜底：直接导航到列表页（整页刷新可清掉任何残留弹窗/遮罩）
        if "baseInfoRecord" not in page.url:
            page.goto(BASE_URL, wait_until="domcontentloaded", timeout=20000)
            self.human_delay(1, 2)

        # 3) 回主页面后再循环清一次（用户规则：主页也要点 X）
        self._clear_overlays("主页面覆盖层")
        log.info("✅ 已返回主页面（覆盖层已清理）")

    def _upload_via_dialog(self, row_label: str, file_path: str):
        """通过「编辑对话框」上传一个文件（修改页专用）。

        真实流程（已验证）：
          1) 点击附件材料表格中目标行（row_label）的「上传」→ 弹出「编辑」对话框
          2) 在对话框中点击「+ 文件上传」→ 延迟触发原生文件选择器（~3-5s）
          3) 通过 filechooser 设置文件路径
          4) 等待上传完成
          5) 点对话框内「确定」确认
        """
        if not os.path.exists(file_path):
            log.warning(f"  ⚠️ 文件不存在跳过: {file_path}")
            return False
        if self.dry_run:
            log.info(f"  📎 [DRY-RUN] 上传: {os.path.basename(file_path)} ({row_label})")
            return True

        page = self.page
        log.info(f"  📎 上传到 [{row_label}]: {os.path.basename(file_path)}")

        try:
            # ---- 步骤1：点行级「上传」打开编辑弹窗 ----
            row = page.locator("tr", has_text=row_label).first
            row_btn = row.locator('button:has-text("上传")').first
            row_btn.click(timeout=5000)
            self.human_delay(0.4, 0.9)

            # 等待编辑弹窗 + 内部「文件上传」按钮出现
            page.wait_for_selector(".el-dialog:visible button:has-text('文件上传')", timeout=8000)
            log.info("    编辑弹窗已打开")

            # ---- 步骤2：点弹窗内「+ 文件上传」→ 触发文件选择器 ----
            # 必须用 :visible 过滤，否则会命中 DOM 中残留的隐藏旧弹窗
            file_up_btn = page.locator(".el-dialog:visible button:has-text('文件上传')").first
            fc = None
            try:
                # 官方上下文管理器：专为此类延迟触发设计，最长等 30s
                with page.expect_file_chooser(timeout=30000) as fc_info:
                    file_up_btn.click(force=True, timeout=5000)
                fc = fc_info.value
                log.info("    ✅ 文件选择器已触发")
            except Exception as e:
                log.warning(f"    ⚠️ 文件选择器未触发({e})，退化：直接设置隐藏 input")
                fis = page.locator(".el-dialog:visible input[type='file']")
                if fis.count() > 0:
                    fis.first.set_input_files(file_path)
                    fc = True  # 标记已通过退化路径处理
                    log.info("    📎 经隐藏 input 直接上传")

            if fc is None:
                log.error("    ❌ 文件选择器未触发且无可设置 input（30秒超时）")
                self._click_close_x("上传失败·关弹窗")
                return False

            # ---- 步骤3：设置文件（仅在捕获到 filechooser 对象时） ----
            if fc is not True:
                fc.set_files(file_path)
                log.info(f"    文件已设置: {os.path.basename(file_path)}")

            # 等待上传完成（传入文件名，精确检测“文件名已落表”即完成，不再白等）
            ok = self._wait_upload_done(timeout=30, filename=os.path.basename(file_path))
            if not ok:
                log.warning("    ⚠️ 上传完成状态未确认，继续")

            self.human_delay(0.4, 0.9)
            self.human_mouse()

            # ---- 步骤4：点「确定」关闭编辑弹窗 ----
            confirm_btn = page.locator(".el-dialog:visible button:has-text('确定')").first
            confirm_btn.click(timeout=5000)
            self.human_delay(0.5, 1.0)
            log.info("    ✅ 已点确定")

            return True

        except Exception as e:
            log.error(f"  ❌ 上传失败 [{row_label}]: {e}")
            return False

    def _try_upload_in_modify(self, pdf_path: str, contract_paths: list):
        """在修改页『附件材料』区按行上传附件。

        映射（用户确认）：
          合同(jpg) → 第①行 *测绘项目合同或委托书
          测绘其他资料（房测报告 PDF）→ 不上传
        全部上传完成后点击「保存」。
        """
        if self.dry_run:
            return True
        page = self.page
        log.info("\n--- 修改页上传：附件材料区（仅合同）---")

        # 滚动到底部确保附件区可见
        page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
        self.human_delay(0.3, 0.6)

        # ① 合同 → *测绘项目合同或委托书
        for c in (contract_paths or []):
            self._upload_via_dialog("测绘项目合同或委托书", c)

        # 测绘其他资料：用户确认不上传
        if pdf_path:
            log.info(f"  ⏭ 跳过「测绘其他资料」: {os.path.basename(pdf_path)}")

        # 上传完成后再次点保存
        try:
            save = page.locator('button:has-text("保 存")').filter(visible=True)
            if save.count() > 0:
                save.first.click()
                self.human_delay(0.8, 1.4)
                log.info("  💾 修改页已再次点保存")
        except Exception as e:
            log.warning(f"  ⚠️ 修改页保存点击异常: {e}")
        return True

    # ---------- 参与人员分配（已验证逻辑，源自 beian_test_jan.py）----------
    def _get_eligible_people(self):
        """从「参与人员信息-添加」弹窗取可选人员名（排除禁用名单）。"""
        page = self.page
        # 等表格行出来（偶发弹窗先出来、数据后到）
        try:
            page.wait_for_selector(".el-dialog:visible tbody tr", timeout=8000)
        except Exception:
            pass
        self.human_delay(0.3, 0.6)
        rows_data = page.evaluate(r'''() => {
            const vis = (el) => {
                if (!el) return false;
                const st = getComputedStyle(el);
                if (st.display === 'none' || st.visibility === 'hidden') return false;
                const r = el.getBoundingClientRect();
                return r.width > 0 && r.height > 0;
            };
            const dialogs = [...document.querySelectorAll('.el-dialog')].filter(d => {
                const wrap = d.closest('.el-overlay') || d.closest('.el-dialog__wrapper') || d;
                return vis(wrap) || vis(d);
            });
            // 优先带「承担工作 / 作业证 / 新增」的人员选择弹窗
            const score = (d) => {
                const t = d.innerText || '';
                let s = 0;
                if (t.includes('承担工作')) s += 5;
                if (t.includes('作业证')) s += 3;
                if (t.includes('新增')) s += 2;
                if (t.includes('姓名')) s += 2;
                return s;
            };
            dialogs.sort((a, b) => score(b) - score(a));
            const d = dialogs[0];
            if (!d) return [];
            const names = [];
            d.querySelectorAll('tbody tr').forEach(tr => {
                const tds = [...tr.querySelectorAll('td')];
                // 姓名列通常在复选框后第 2/3 列；取第一个像人名的单元格
                for (const td of tds) {
                    const name = (td.innerText || '').trim().split(/\s+/)[0];
                    if (!name || /^\d+$/.test(name)) continue;
                    if (name.length < 2 || name.length > 8) continue;
                    if (/承担|负责|一般|操作|选择|上传|删除/.test(name)) continue;
                    names.push(name);
                    break;
                }
            });
            return names;
        }''')
        return [n for n in (rows_data or []) if n not in FORBIDDEN_PEOPLE]

    def _assign_one_role(self, name, role_name):
        """在弹窗某行勾选复选框并设角色下拉（用 aria-owns 精准定位自己面板）。"""
        page = self.page
        row = page.locator(".el-dialog:visible tbody tr").filter(has_text=name).first
        cb = row.locator(".el-checkbox").first
        cb.click(force=True, timeout=5000)
        self.human_delay(0.4, 0.8)
        sel = row.locator(".el-select").first
        sel.click(force=True, timeout=5000)
        self.human_delay(0.5, 0.9)
        # 通过 select 的 aria-owns 关联到【它自己】的下拉面板 id，
        # 避免命中其它行共享的几十个同名 .el-select-dropdown 面板（否则 .first 取错面板）。
        owns = ""
        try:
            owns = (sel.locator("input").first.get_attribute("aria-owns") or "").strip()
        except Exception:
            owns = ""
        if owns:
            opt = page.locator(f"#{owns} .el-select-dropdown__item").filter(has_text=role_name).first
        else:
            opt = page.locator('.el-select-dropdown .el-select-dropdown__item') \
                      .filter(visible=True, has_text=role_name).first
        try:
            opt.wait_for(state="visible", timeout=4000)
        except Exception:
            pass
        if opt.count() > 0 and opt.first.is_visible():
            opt.first.click(force=True, timeout=3000)
            self.human_delay(0.3, 0.6)
            log.info(f"    ✅ {name} → [{role_name}]")
        else:
            log.warning(f"    ⚠️ 未找到选项 [{role_name}]")
            page.keyboard.press("Escape")
            self.human_delay(0.2, 0.4)

    def assign_participants(self):
        """切到参与人员信息 tab → 添加 → 选3人分配角色 → 弹窗保存。返回是否成功。"""
        page = self.page
        log.info("\n=== 选定参与人员 ===")
        page.locator('.el-tabs__item:has-text("参与人员信息")').first \
         .click(force=True, timeout=5000)
        self.human_delay(1.2, 2.0)
        if not self._click_btn_normalized("添加"):
            log.error("  ❌ 未找到参与人员「添加」按钮")
            self._clear_overlays("人员弹窗异常关闭")
            return False
        self.human_delay(1.2, 2.0)
        page.wait_for_selector(".el-dialog:visible", timeout=8000)
        log.info("  ✅ 新增弹窗已打开")

        eligible = self._get_eligible_people()
        if len(eligible) < 3:
            # 偶发表格未渲染完：再等一次
            self.human_delay(1.0, 1.5)
            eligible = self._get_eligible_people()
        if len(eligible) < 3:
            log.error(f"  ❌ 可选人数不足({len(eligible)})，无法分配")
            self._clear_overlays("人员弹窗异常关闭")
            return False
        chosen = random.sample(eligible, 3)
        log.info(f"  随机选中: {chosen}")
        for name, role in zip(chosen, PARTY_ROLES):
            self._assign_one_role(name, role)
            self.human_delay(0.4, 0.8)
        dlg_save = page.locator(".el-dialog:visible button:has-text('保 存')").first
        dlg_save.click(force=True, timeout=5000)
        self.human_delay(1.5, 2.5)
        log.info("  ✅ 弹窗已保 存（人员已确定）")
        return True

    def upload_contract_only(self, record, contract_paths=None):
        """只补合同：搜索 → 打开修改 → 上传合同 → 保存 → 返回。不改人员、不传 PDF。"""
        if self.dry_run:
            return True
        contract_paths = contract_paths or []
        if not contract_paths:
            log.warning("  ⚠️ 无合同文件，跳过")
            return False
        fd = generate_form_data(record)
        proj_name = fd.get("项目名称", "")
        name_key = fd.get("建设单位", "") or ""
        if not proj_name:
            log.warning("  ⚠️ 无项目名称，跳过")
            return False

        log.info(f"\n=== 只补合同: {name_key} / {proj_name} ===")
        if not self.find_and_open_modify(proj_name, name_key):
            log.error("  ❌ 未找到修改页")
            return False

        self._clear_overlays("修改页进入后清理")
        ok_up = False
        for c in contract_paths:
            if self._upload_via_dialog("测绘项目合同或委托书", c):
                ok_up = True
            self.human_delay(0.5, 1.0)
        self._clear_overlays("上传确认框")
        if not ok_up:
            log.error("  ❌ 合同上传失败")
            self._return_to_main()
            return False

        try:
            save = self.page.locator('button:has-text("保 存")').filter(visible=True)
            if save.count() > 0:
                save.first.click(timeout=5000)
                self.human_delay(1.2, 2.0)
                log.info("  💾 已保存")
        except Exception as e:
            log.warning(f"  ⚠️ 保存异常: {e}")
            self._return_to_main()
            return False

        self._clear_overlays("保存后弹窗")
        self._return_to_main()
        return True

    def complete_via_modify(self, record, pdf_path="", contract_paths=None):
        """创建基础记录并保存返回后，进入修改页补全：上传合同、分配人员、保存、返回主页。

        仅在浏览器真实模式下执行（dry_run 直接返回 True）。
        用户确认：只上传合同；「测绘其他资料」不上传。
        人员分配失败时返回 False（调用方不得 mark_uploaded）。
        """
        if self.dry_run:
            return True
        contract_paths = contract_paths or []
        fd = generate_form_data(record)
        proj_name = fd.get("项目名称", "")
        name_key = fd.get("建设单位", "") or ""
        if not proj_name:
            log.warning("  ⚠️ 无法获取项目名称，跳过重传补全")
            return False

        # 1) 打开修改页
        if not self.find_and_open_modify(proj_name, name_key):
            log.error("  ❌ 无法打开修改页，补全失败")
            return False

        # 2) 仅上传合同（修改页附件区）；测绘其他资料不传
        self._clear_overlays("修改页进入后清理")
        if contract_paths:
            for c in contract_paths:
                self._upload_via_dialog("测绘项目合同或委托书", c)
                self.human_delay(0.5, 1.0)
        else:
            log.warning("  ⚠️ 无合同文件可上传")
        if pdf_path:
            log.info(f"  ⏭ 跳过「测绘其他资料」: {os.path.basename(pdf_path)}")
        self._clear_overlays("上传确认框")

        # 3) 分配参与人员（失败则整条不算完成）
        ok_party = self.assign_participants()
        self._clear_overlays("人员分配确认框")
        if not ok_party:
            log.error("  ❌ 参与人员分配失败，本条不标记完成")
            self._return_to_main()
            return False

        # 4) 修改页最终保存
        try:
            save = self.page.locator('button:has-text("保 存")').filter(visible=True)
            if save.count() > 0:
                save.first.click(timeout=5000)
                self.human_delay(1.5, 2.5)
                log.info("  💾 修改页已保 存")
        except Exception as e:
            log.warning(f"  ⚠️ 修改页保存异常: {e}")

        # 5) 返回主页（清理弹窗）
        self._return_to_main()
        return True

    def close(self):
        if self.browser:
            self.browser.close()

    # ---- 登录态检测 / 暂停等待 / 防重复 ----
    def is_logged_in(self):
        """检测是否仍处于登录态。

        判据（2026-10-14 在真实站点上逐条实测）：
          1. URL 含 /login                     → 未登录
          2. 页面存在 input[type=password]      → 未登录
          3. 门户 header 存在可见的「登录」按钮  → 未登录
             （`.header div.login`，未登录时可见；登录后该元素消失）
        第 3 条是补的：门户主页 /main.htm 未登录时既没有密码框、URL 也不含 login，
        旧逻辑会误判为「已登录」，导致第一条必然填报失败。已实证：
            未登录-门户   → 旧逻辑 True(错) / 新逻辑 False(对)
            未登录-登录页 → 旧逻辑 False / 新逻辑 False
        ⚠️ 第 3 条未在「已登录」状态下验证过（无账号无法验证）。若出现"明明已登录
        却一直提示未登录"，设环境变量 BEIAN_NO_HEADER_LOGIN_CHECK=1 关掉第 3 条重跑。
        """
        if self.dry_run:
            return True
        try:
            url = self.page.url
            if "login" in url.lower():
                return False
            if self.page.locator('input[type="password"]').count() > 0:
                return False
            if not os.environ.get("BEIAN_NO_HEADER_LOGIN_CHECK"):
                try:
                    if self.page.locator(".header div.login:visible").count() > 0:
                        return False
                except Exception:
                    pass
            return True
        except Exception:
            return True  # 不确定时假设仍登录，交由后续流程兜底报错

    def wait_for_login(self, check_sec: int = 30):
        """登录态失效时阻塞等待用户手动重新登录，登录恢复后自动续跑。

        用户规则：登录态约 4h 即掉，需人工解图形验证码。本方法让脚本在掉线处
        原地等待，每 check_sec 秒检测一次，登录成功后无需重启命令即可继续。
        （Ctrl+C 也会触发 KeyboardInterrupt，由 main 捕获并安全保存断点。）
        """
        log.warning("🔒 检测到未登录（跳到登录页 / 出现密码框 / 门户出现「登录」按钮）。")
        log.warning("   请在浏览器中手动登录：账号框点一下会弹出 Chrome 已保存的账号密码，选中即自动填，只需手输图形验证码。")
        log.warning(f"   ⏳ 脚本每 {check_sec}s 检测一次，登录成功后自动续跑，无需重启命令。")
        log.warning("   若你确实已登录却仍提示未登录，设环境变量 BEIAN_NO_HEADER_LOGIN_CHECK=1 再跑。")
        while True:
            time.sleep(check_sec)
            if self.is_logged_in():
                log.info("✅ 检测到已重新登录，继续执行剩余队列。")
                return
            log.info("   …仍未登录，继续等待…")

    def search_match_count(self, project_name: str, name_key: str = "") -> int:
        """搜索报送列表，返回与项目名（或建设单位）匹配的行数。

        用于断点续跑 / 重名判断：
          - 行数 > 本项目名下已上传条数 → 有未完成草稿，走修改页补全
          - 行数 == 已上传条数 → 已有记录都被本台账消化过，应再新建（重名第二条）
        """
        if self.dry_run:
            return 0
        page = self.page
        try:
            page.goto(BASE_URL, wait_until="domcontentloaded", timeout=20000)
            page.wait_for_selector('input[placeholder="请填写项目名称"]', timeout=10000)
        except Exception as e:
            log.warning(f"  ⚠️ 列表页/搜索框未出现(可能未登录): {e}")
            return 0
        self.human_delay(0.8, 1.5)
        self._clear_overlays("防重复搜索前清遮罩")
        try:
            sb = page.locator('input[placeholder="请填写项目名称"]').first
            self._clear_overlays("搜索框交互前清理")
            sb.click(timeout=8000)
            sb.fill(project_name)
            self.human_delay(0.3, 0.6)
            search_btn = page.locator('button:has-text("搜索")').filter(visible=True)
            if search_btn.count() > 0:
                search_btn.first.click(timeout=8000)
                self.human_delay(0.5, 1.0)
        except Exception as e:
            log.warning(f"  ⚠️ 搜索框操作失败: {e}")
            return 0
        rows = page.locator(".el-table__body-wrapper tbody tr")
        try:
            et = page.locator(".el-table__empty-text")
            if et.count() > 0 and et.first.is_visible():
                return 0
        except Exception:
            pass
        n = rows.filter(has_text=project_name).count()
        if n == 0 and name_key:
            n = rows.filter(has_text=name_key).count()
        return n

    def search_exists(self, project_name: str, name_key: str = ""):
        """兼容旧调用：是否至少有一行匹配。"""
        return self.search_match_count(project_name, name_key) > 0


# ================================================================
#  进度指针（断点续跑）：记录轮到哪个项目，下次启动从断点继续
# ================================================================
# 参与人员分配：排除名单与角色顺序（用户指定）
FORBIDDEN_PEOPLE = {"阮晓燕", "周琴晓", "黄帝仙"}
PARTY_ROLES = ["项目负责人", "技术负责人", "质检负责人"]

PROGRESS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "beian_progress.json")

def _now():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def load_progress():
    if os.path.exists(PROGRESS_FILE):
        try:
            return json.load(open(PROGRESS_FILE, encoding="utf-8"))
        except Exception:
            return {}
    return {}

def save_progress(p: dict):
    p = dict(p)
    p["updated_at"] = _now()
    tmp = PROGRESS_FILE + ".tmp"
    json.dump(p, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    os.replace(tmp, PROGRESS_FILE)


def record_month(key: str, rec: dict) -> str:
    """从报告编号/路径推断 YYYYMM，供按月排序。未知则 ZZ999999 排最后。"""
    for s in (key, rec.get("报告编号") or "", rec.get("source_pdf") or ""):
        m = re.search(r"(20\d{2})(0[1-9]|1[0-2])", str(s))
        if m:
            return m.group(1) + m.group(2)
    return "ZZ999999"


def _ym_iter(start: str, end: str):
    """生成 start..end（含）的 YYYYMM 列表。"""
    y, m = int(start[:4]), int(start[4:6])
    ye, me = int(end[:4]), int(end[4:6])
    out = []
    while (y, m) <= (ye, me):
        out.append(f"{y:04d}{m:02d}")
        m += 1
        if m > 12:
            m = 1
            y += 1
    return out


def parse_months(spec: str) -> list:
    """解析 --month= 参数：支持单月、逗号列表、区间。
    例：202401 | 202401,202403,202405 | 202401-202406
    """
    if not spec:
        return []
    months = []
    for part in re.split(r"[,，\s]+", spec.strip()):
        if not part:
            continue
        if "-" in part and re.fullmatch(r"20\d{4}\s*-\s*20\d{4}", part):
            a, b = [x.strip() for x in part.split("-", 1)]
            if not re.fullmatch(r"20\d{2}(0[1-9]|1[0-2])", a):
                raise ValueError(f"非法月份: {a}")
            if not re.fullmatch(r"20\d{2}(0[1-9]|1[0-2])", b):
                raise ValueError(f"非法月份: {b}")
            if a > b:
                a, b = b, a
            months.extend(_ym_iter(a, b))
        else:
            if not re.fullmatch(r"20\d{2}(0[1-9]|1[0-2])", part):
                raise ValueError(f"非法月份(需YYYYMM): {part}")
            months.append(part)
    # 去重且按时间排序
    return sorted(dict.fromkeys(months))


def match_month_filter(key: str, rec: dict, months: list) -> bool:
    """记录是否属于指定月份集合。"""
    rm = record_month(key, rec)
    if rm in months:
        return True
    # 兼容编号里直接含 YYYYMM
    blob = f"{key} {rec.get('报告编号') or ''}"
    return any(m in blob for m in months)


def count_uploaded_same_project(ledger: dict, uploaded: dict, project_name: str) -> int:
    """台账中同项目名且已写入 upload_log 的条数（重名场景用）。"""
    n = 0
    for k, v in ledger.items():
        if k not in uploaded:
            continue
        name = (v.get("委托方") or v.get("建设单位") or "").strip()
        if generate_project_name(name) == project_name:
            n += 1
    return n


# ================================================================
#  CLI 入口
# ================================================================
def load_test_record():
    """加载<SAMPLE_CLIENT_A>的测试记录。"""
    ledger = json.load(open(L.LEDGER, encoding="utf-8"))
    key = TEST_RECORD_KEY
    if key not in ledger:
        # 尝试找第一条 pending
        for k, v in ledger.items():
            if v.get("status") == "pending":
                key = k
                break
        else:
            key = list(ledger.keys())[0]
    rec = ledger[key]
    rec["_key"] = key
    return rec


CONTRACT_FIX_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "beian_contract_fix_log.json")
YEAR_ROOTS = tuple(_cfg.CFG.get("year_roots", [
    r"<HOUSE_SRC_ROOT>/2024年备案",
    r"<HOUSE_SRC_ROOT>/2025年备案",
    r"<HOUSE_SRC_ROOT>/2026年备案",
]))


def _prepare_contract_upload_path(src: str) -> str:
    """网站侧要求展示名为「合同」；非标准文件名时复制为临时 合同.ext 再传。"""
    if not src or not os.path.exists(src):
        return src
    stem, ext = os.path.splitext(os.path.basename(src))
    # 标准「合同.jpg」可直接传；其余（合同 (2)/人名合同/全同/委托书）规范成 合同.ext
    if stem == "合同":
        return src
    import tempfile, shutil
    td = tempfile.mkdtemp(prefix="beian_ht_")
    dest = os.path.join(td, f"合同{(ext.lower() or '.jpg')}")
    shutil.copy2(src, dest)
    log.info(f"  📎 合同已规范文件名: {os.path.basename(src)} → {os.path.basename(dest)}")
    return dest


def _locate_contracts_near_pdf(pdf_path: str) -> list:
    """在 PDF 同目录（缓存 / 各年网络盘）按规则找合同，返回绝对路径列表。"""
    if not pdf_path:
        return []
    found = []
    # 1) 直接相对 CACHE
    try:
        rel = os.path.relpath(pdf_path, L.CACHE)
        if not str(rel).startswith(".."):
            old = L.ROOT
            try:
                L.ROOT = L.CACHE
                for r in L.find_contracts(rel, use_cache_dir=True):
                    abs_c = os.path.join(L.CACHE, r)
                    if os.path.exists(abs_c):
                        found.append(abs_c)
            finally:
                L.ROOT = old
            if found:
                return found
    except ValueError:
        pass

    # 2) 缓存相对路径映射到各年 W: 根
    try:
        rel_cache = os.path.relpath(pdf_path, L.CACHE)
    except ValueError:
        rel_cache = None
    if rel_cache and not str(rel_cache).startswith(".."):
        for root_try in YEAR_ROOTS:
            w_pdf = os.path.join(root_try, rel_cache)
            if not os.path.exists(w_pdf) and not os.path.isdir(os.path.dirname(w_pdf)):
                continue
            old = L.ROOT
            try:
                L.ROOT = root_try
                # 用同相对路径定位（即使缓存里 PDF 路径，合同在 W:）
                for r in L.find_contracts(rel_cache, use_cache_dir=False):
                    abs_c = os.path.join(root_try, r)
                    if os.path.exists(abs_c):
                        found.append(abs_c)
                if found:
                    return found
            finally:
                L.ROOT = old

    # 3) PDF 已在某年根下
    for root_try in YEAR_ROOTS:
        try:
            rel = os.path.relpath(pdf_path, root_try)
        except ValueError:
            continue
        if str(rel).startswith(".."):
            continue
        old = L.ROOT
        try:
            L.ROOT = root_try
            for r in L.find_contracts(rel, use_cache_dir=False):
                abs_c = os.path.join(root_try, r)
                if os.path.exists(abs_c):
                    found.append(abs_c)
            if found:
                return found
        finally:
            L.ROOT = old
    return found


def find_pdf_and_contracts(record: dict):
    """根据台账记录中的 source 信息找到 PDF 和合同的实际路径。"""
    pdf_path = record.get("source_pdf", "")
    contracts = list(record.get("合同", []) or [])

    if not pdf_path or not os.path.exists(pdf_path):
        key = record.get("_key") or record.get("report_no") or ""
        if key:
            for root_try in YEAR_ROOTS:
                hits = list(Path(root_try).rglob(f"*{key}*房测报告*.pdf"))
                if hits:
                    pdf_path = str(hits[0])
                    break

    valid_contracts = []
    for c in contracts:
        if isinstance(c, str) and os.path.exists(c):
            valid_contracts.append(c)

    if not valid_contracts:
        valid_contracts = _locate_contracts_near_pdf(pdf_path)

    valid_contracts = [_prepare_contract_upload_path(c) for c in valid_contracts]
    return pdf_path, valid_contracts


def load_contract_fix_log():
    if not os.path.exists(CONTRACT_FIX_LOG):
        return {}
    try:
        with open(CONTRACT_FIX_LOG, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_contract_fix_log(d: dict):
    with open(CONTRACT_FIX_LOG, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)


def collect_contract_fix_targets(month_list=None, limit=None):
    """已上传、但提取时台账「合同」一直为空、现磁盘能定位到合同、且尚未补录成功的条目。

    判定要点：
    - 台账曾记过合同路径（哪怕缓存已删）→ 视为上传流程带过合同，跳过
    - 台账合同一直为空 + 现用宽匹配能找到文件 → 纳入补录
    - 台账空且磁盘仍找不到（如陈菊琴无「合同」字样文件）→ 记入 no_file，不上传
    """
    ledger = L.load_ledger()
    uploaded = L.load_upload_log()
    fixed = load_contract_fix_log()
    targets = []
    no_file = []
    for key in sorted(uploaded.keys()):
        if fixed.get(key, {}).get("status") in ("done", "skipped"):
            continue
        rec = ledger.get(key)
        if not rec:
            continue
        if month_list:
            m = record_month(key, rec)
            if m not in month_list:
                continue
        # 台账曾有过合同路径 → 认为当时已上传过合同，不重复补
        if any(isinstance(c, str) and c.strip() for c in (rec.get("合同") or [])):
            continue
        cons = _locate_contracts_near_pdf(rec.get("source_pdf") or "")
        if not cons:
            no_file.append((key, rec.get("委托方", "")))
            continue
        targets.append((key, rec, cons))
        if limit and len(targets) >= limit:
            break
    return targets, no_file


def run_fix_contracts(filler: "BeianFiller", month_list=None, limit=None, dry_run=False):
    targets, no_file = collect_contract_fix_targets(month_list, limit=None)
    # 先全量收集再截 limit，便于日志统计
    total_avail = len(targets)
    if limit:
        targets = targets[:limit]
    log.info(f"📋 合同补录：待补 {len(targets)}/{total_avail}（本地无合同文件 {len(no_file)}，已跳过）")
    if no_file:
        sample = ", ".join(f"{k}:{n}" for k, n in no_file[:15])
        log.info(f"  无合同文件样例: {sample}{' ...' if len(no_file)>15 else ''}")
    if dry_run:
        for i, (key, rec, cons) in enumerate(targets, 1):
            log.info(f"  [dry-run {i}] {key} {rec.get('委托方')} ← {[os.path.basename(c) for c in cons]}")
        return

    if not filler.is_logged_in():
        filler.wait_for_login()

    fix_log = load_contract_fix_log()
    ok_n = fail_n = 0
    for i, (key, rec, cons) in enumerate(targets, 1):
        rec = dict(rec)
        rec["_key"] = key
        # 规范上传名
        upload_cons = [_prepare_contract_upload_path(c) for c in cons]
        log.info(f"\n[{i}/{len(targets)}] 补合同 {key} | {rec.get('委托方')} | {os.path.basename(upload_cons[0])}")
        if not filler.is_logged_in():
            filler.wait_for_login()
        try:
            ok = filler.upload_contract_only(rec, upload_cons)
        except Exception as e:
            log.error(f"  ❌ 异常: {e}")
            ok = False
        if ok:
            ok_n += 1
            fix_log[key] = {
                "status": "done",
                "ts": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "file": os.path.basename(cons[0]),
                "name": rec.get("委托方", ""),
            }
            save_contract_fix_log(fix_log)
            # 同步写回台账合同路径（缓存绝对路径优先）
            try:
                ledger = L.load_ledger()
                if key in ledger:
                    ledger[key]["合同"] = cons
                    L.save_ledger(ledger)
            except Exception:
                pass
        else:
            fail_n += 1
            fix_log[key] = {
                "status": "failed",
                "ts": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "name": rec.get("委托方", ""),
            }
            save_contract_fix_log(fix_log)
    log.info(f"🎉 合同补录结束：成功 {ok_n} | 失败 {fail_n} | 本地无文件 {len(no_file)}")


def main():
    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    do_all = "--all" in args
    fix_contracts = "--fix-contracts" in args
    months = []
    limit = None
    for a in args:
        if a.startswith("--month="):
            # 允许多个 --month=；最终合并解析
            months.append(a.split("=", 1)[1])
        elif a.startswith("--limit="):
            try:
                limit = int(a.split("=", 1)[1])
            except ValueError:
                limit = None
    try:
        month_list = parse_months(",".join(months)) if months else []
    except ValueError as e:
        log.error(f"❌ {e}")
        return

    filler = BeianFiller(dry_run=dry_run)

    try:
        if fix_contracts:
            run_fix_contracts(filler, month_list=month_list or None, limit=limit, dry_run=dry_run)
            return
        if do_all:
            # 消费「已提取通过 且 尚未上传」的队列；跳过 verify/rule 失败与已上传
            ledger = L.load_ledger()
            uploaded = L.load_upload_log()
            skip_names = load_skip_names()
            pending, skipped, skipped_named, skipped_no_contract = {}, 0, 0, 0
            for k, v in ledger.items():
                ex = v.get("extract_status")
                if ex in ("verify_failed", "rule_failed"):
                    skipped += 1
                    continue
                if k in uploaded:
                    skipped += 1
                    continue
                if is_skip_record(v, skip_names):
                    skipped += 1
                    skipped_named += 1
                    continue
                # 无合同暂不上传（用户规则 2026-08-17）：合同字段为空或缓存缺失
                _cts = v.get("合同") or []
                if not (_cts and os.path.exists(_cts[0])):
                    skipped += 1
                    skipped_no_contract += 1
                    continue
                if v.get("status") == "pending" and (ex in (None, "ok")):
                    pending[k] = v
            if skipped_named:
                log.info(f"  已按名单跳过 {skipped_named} 条（{', '.join(sorted(skip_names))}）")

            # 按月份过滤（可多月）；未指定则整台账按月顺序跑
            if month_list:
                pending = {k: v for k, v in pending.items()
                           if match_month_filter(k, v, month_list)}
                log.info(f"  按月份过滤[{','.join(month_list)}]后剩余 {len(pending)} 条")

            # 按 YYYYMM → 报告编号 稳定排序，一个月一个月、不会乱序
            ordered_keys = sorted(pending.keys(),
                                  key=lambda k: (record_month(k, pending[k]), k))
            pending = {k: pending[k] for k in ordered_keys}
            months_in_queue = []
            for k in ordered_keys:
                m = record_month(k, pending[k])
                if m not in months_in_queue:
                    months_in_queue.append(m)
            if months_in_queue:
                log.info(f"  按月顺序: {' → '.join(months_in_queue)}")

            if limit is not None:
                pending = dict(list(pending.items())[:limit])
                log.info(f"  限制条数[{limit}]后剩余 {len(pending)} 条")
            total = len(pending)
            done_before = len(uploaded)          # 启动前已完成累计
            done_cnt = 0
            key, i = "", 0
            # —— 恢复断点提示 ——
            prog = load_progress()
            if prog:
                log.info(f"📍 恢复进度：上次已完成 {prog.get('done_count', 0)} 条，"
                         f"断点 key={prog.get('current_key', '?')}（index={prog.get('current_index', '?')}），将从这里继续")
            log.info(f"共 {total} 条可填报（跳过 提取未通过/已上传/无合同 共 {skipped} 条，其中无合同 {skipped_no_contract} 条）；已上传累计 {done_before} 条")

            try:
                current_month = None
                for i, (key, rec) in enumerate(pending.items()):
                    rec["_key"] = key
                    m = record_month(key, rec)
                    if m != current_month:
                        current_month = m
                        log.info(f"\n######## 开始月份 {m} ########")
                    # —— 写进度指针（断点）：轮到哪个项目 ——
                    save_progress({
                        "current_key": key, "current_index": i,
                        "total_pending": total,
                        "done_count": done_before + done_cnt,
                        "state": "running",
                        "current_month": m,
                    })
                    # —— 登录态检测：掉线则原地暂停等待用户重新登录 ——
                    if not filler.is_logged_in():
                        filler.wait_for_login()
                    # 准备路径与名称
                    fd = generate_form_data(rec)
                    pname = fd.get("项目名称", "")
                    name = fd.get("建设单位", "")
                    pdf, contracts = find_pdf_and_contracts(rec)
                    log.info(f"\n[{i+1}/{total}][{m}] 处理: {key} | {name} | "
                             f"PDF: {os.path.basename(pdf) if pdf else 'MISSING'} | 合同: {len(contracts)}")
                    # 重名安全：系统行数 > 本台账同名已上传数 → 补全草稿；否则新建
                    rows = filler.search_match_count(pname, name) if pname else 0
                    siblings_done = count_uploaded_same_project(
                        ledger, L.load_upload_log(), pname) if pname else 0
                    if pname and rows > siblings_done:
                        log.info(f"  ↪️ 列表已有 {rows} 条「{pname}」(台账已上传同名 {siblings_done})，"
                                 f"跳过创建，仅补全修改页")
                        ok = filler.complete_via_modify(rec, pdf, contracts)
                    else:
                        if rows and pname:
                            log.info(f"  ℹ️ 列表已有 {rows} 条同名，但台账已消化 {siblings_done} 条 → 新建一条（重名）")
                        ok = filler.fill_one_record(rec, pdf, contracts)
                    if ok and not dry_run:
                        L.mark_uploaded(key, rec)   # 写上传日志 + 清理缓存(防爆盘)
                        done_cnt += 1
                    elif ok and dry_run:
                        log.info("  (dry-run) 不标记")
                # —— 全部完成 ——
                save_progress({
                    "current_key": "", "current_index": total,
                    "total_pending": total,
                    "done_count": done_before + done_cnt,
                    "state": "finished",
                })
                log.info(f"🎉 本批完成：成功上传 {done_cnt}/{total}（累计已上传 {done_before + done_cnt} 条）")
            except KeyboardInterrupt:
                log.warning("🛑 已手动中断。进度已保存到 beian_progress.json，"
                            "下次启动 `--all` 将自动从断点（current_key）继续。")
                save_progress({
                    "current_key": key, "current_index": i,
                    "total_pending": total,
                    "done_count": done_before + done_cnt,
                    "state": "interrupted",
                })
            except Exception as e:
                log.error(f"💥 运行异常: {e}。进度已保存，下次启动将从断点继续。")
                save_progress({
                    "current_key": key, "current_index": i,
                    "total_pending": total,
                    "done_count": done_before + done_cnt,
                    "state": "interrupted",
                })
        else:
            # 单条测试（默认<SAMPLE_CLIENT_A>）
            rec = load_test_record()
            pdf, contracts = find_pdf_and_contracts(rec)
            log.info(f"测试记录: {rec['_key']} | PDF: {pdf} | 合同: {contracts}")
            filler.fill_one_record(rec, pdf, contracts)

    finally:
        filler.close()


if __name__ == "__main__":
    main()
