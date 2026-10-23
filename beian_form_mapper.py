"""
表单字段映射与数据生成模块（已对齐真实 DOM 标签）
================================================
根据 2026-08-11 DOM 探测结果修正所有标签名。
"""
import re, math
from datetime import datetime, timedelta

# ================================================================
#  一、固定值（每次填报不变）
# ================================================================
FIXED_FIELDS = {
    # ---- 基础信息 ----
    "是否分包项目":                      "否",
    "是否多测合一项目":                  "否",        # 原误写为"多参合一"
    "项目范围是否跨地市":                "否",
    "项目范围是否跨区县":                "否",
    "质量验收约定":                      "其他",
    "是否有监理":                        "否",
    "是否涉及有限空间作业或地下管线探测": "否",

    # ---- 建设单位 ----
    "建设单位联系电话":                  "",          # ⚠️ 不填(留空)
    "测绘单位项目联系人":                "张阳凡",     # 原误写为"验绘单位"
    "测绘单位联系人电话":               "13858606777", # ⚠️ 正确号码（用户 2026-08-11 纠正）

    # ---- 合同信息 ----
    "合同编号":                          "",          # ⚠️ 不填(留空)
    "项目类型":                          "房产测绘/房产测绘",   # cascader 选项值(大类/小类)
    "是否属于基础测绘项目或重大建设工程的测绘项目": "不属于",

    # ---- 地址固定部分 ----
    "省":                               "浙江省",
    "市":                               "台州市",
    "区县":                             "温岭市",
}

# ================================================================
#  二、变动值生成规则
# ================================================================
def extract_town(房屋座落: str) -> str:
    """从房屋座落提取乡镇/街道。如"温岭市城西街道吴山村"→"城西街道"。"""
    if not 房屋座落:
        return ""
    m = re.search(r'(?:温岭市|台州市)[^\s]*?([\u4e00-\u9fa5]{2,4}(?:镇|街道))', 房屋座落)
    if m:
        return m.group(1)
    m = re.search(r'([\u4e00-\u9fa5]{2,4}(?:镇|街道))', 房屋座落)
    if m:
        return m.group(1)
    return ""

def generate_project_name(委托方: str) -> str:
    return f"{(委托方 or '').strip()}个人建房建筑面积测绘"

def calc_date_range(施测日期_str: str) -> tuple:
    d = None
    if not 施测日期_str:
        d = datetime.now()
    else:
        m = re.match(r'(\d{4})年(\d{1,2})月(\d{1,2})日', 施测日期_str)
        if m:
            d = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        else:
            try:
                d = datetime.strptime(施测日期_str.strip(), "%Y-%m-%d")
            except ValueError:
                d = datetime.now()
    start = d
    end = d + timedelta(days=10)
    return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")

def calc_contract_amount(总面积: float) -> str:
    """合同金额(万元) = 面积(m²) × 0.65(元/m²) ÷ 10000，截断4位小数。
    实测验证: 面积~343㎡ → 0.0222924万元"""
    try:
        val = float(总面积) * 0.65 / 10000.0
        truncated = math.floor(val * 10000) / 10000
        return f"{truncated:.4f}"
    except (ValueError, TypeError):
        return "0.0000"

def parse_施测日期_for_contract(施测日期_str: str) -> str:
    start, _ = calc_date_range(施测日期_str)
    return start

# ================================================================
#  三、主函数：从台账记录 → 完整表单数据
# ================================================================
def generate_form_data(record: dict) -> dict:
    # ===== 工程备案分支 =====
    # 判据：有 委托单位/平台大类/项目类型_填报，或带有工程备案专属列
    # （判据层/子项判定）—— 后者用于"无合同PDF且台账类别为空"的行，
    # 否则会误落到房产备案分支、丢掉项目类型多行结构。
    if (record.get("委托单位") or record.get("平台大类") or record.get("项目类型_填报")
            or record.get("判据层") or record.get("子项判定")):
        return _generate_gc_form_data(record)

    name = (record.get("委托方") or "").strip()
    area = record.get("总建筑面积") or "0"
    施测日期 = record.get("施测日期") or ""
    房屋座落 = record.get("房屋座落") or ""

    town = extract_town(房屋座落)
    proj_name = generate_project_name(name)
    start_date, end_date = calc_date_range(施测日期)
    contract_amt = calc_contract_amount(area)
    contract_date = parse_施测日期_for_contract(施测日期)

    form = {
        # ===== 变动值 =====
        "项目名称":              proj_name,
        "详细地址(乡镇)":         town,
        "预计开工时间":          start_date,
        "预计完工时间":          end_date,
        "建设单位":              name,
        "建设单位项目联系人":     name,
        "合同签订日期":           contract_date,
        "项目合同金额(万元)":     contract_amt,
        "金额(万元)":             contract_amt,

        # ===== 固定值 =====
        "是否分包项目":           FIXED_FIELDS["是否分包项目"],
        "是否多测合一项目":       FIXED_FIELDS["是否多测合一项目"],
        "项目范围是否跨地市":     FIXED_FIELDS["项目范围是否跨地市"],
        "项目范围是否跨区县":     FIXED_FIELDS["项目范围是否跨区县"],
        "质量验收约定":           FIXED_FIELDS["质量验收约定"],
        "是否有监理":             FIXED_FIELDS["是否有监理"],
        "是否涉及有限空间作业或地下管线探测": FIXED_FIELDS["是否涉及有限空间作业或地下管线探测"],
        "建设单位联系电话":       FIXED_FIELDS["建设单位联系电话"],      # 空字符串=不填
        "测绘单位项目联系人":     FIXED_FIELDS["测绘单位项目联系人"],
        "测绘单位联系人电话":     FIXED_FIELDS["测绘单位联系人电话"],
        "合同编号":              FIXED_FIELDS["合同编号"],             # 空字符串=不填
        "项目类型":              FIXED_FIELDS["项目类型"],
        "是否属于基础测绘项目或重大建设工程的测绘项目": FIXED_FIELDS["是否属于基础测绘项目或重大建设工程的测绘项目"],

        # ===== 地址 =====
        "省":                    FIXED_FIELDS["省"],
        "市":                    FIXED_FIELDS["市"],
        "区县":                  FIXED_FIELDS["区县"],

        # ===== 来源追踪 =====
        "_source_report_no":     record.get("报告编号", ""),
        "_source_pdf":           record.get("source_pdf", ""),
        "_source_合同":          record.get("合同", []),
    }
    return form


# ================================================================
#  四、工程备案分支（合同归档台账 → 单表单报送）
# ================================================================
def _norm_date(s: str) -> str:
    """从 '2025-01-14 0:00:00' / '20250114' / '2025-01-14' 等取 yyyy-mm-dd。"""
    import re as _re
    s = (s or "").strip()
    m = _re.search(r'(\d{4})[-/年.](\d{1,2})[-/月.](\d{1,2})', s)
    if m:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = _re.search(r'(\d{4})(\d{2})(\d{2})', s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return s


def _generate_gc_form_data(record: dict) -> dict:
    wei = (record.get("委托单位") or "").strip()
    合同名称 = (record.get("合同名称") or "").strip()
    经办人 = (record.get("经办人") or "").strip()
    联系人 = (record.get("建设单位项目联系人") or "").strip()  # 已含“X先生”
    项目地点 = (record.get("项目地点") or "").strip()
    签订日期 = (record.get("签订日期") or "").strip()
    金额 = (record.get("最终金额万元") or record.get("打折后万元") or "").strip()
    开工 = (record.get("预计开工") or "").strip()
    完工 = (record.get("预计完工") or "").strip()
    项目类型 = (record.get("项目类型_填报") or "").strip()

    # ===== 多行项目类型（表单可重复行：每行 = 一个项目类型 + 金额(万元)）=====
    import json as _json
    try:
        行列表 = _json.loads(record.get("项目类型_行列表") or "[]")
    except Exception:
        行列表 = []
    try:
        金额行 = _json.loads(record.get("金额_行列表") or "[]")
    except Exception:
        金额行 = []
    if not 行列表:
        行列表 = [项目类型] if 项目类型 else []
    if len(金额行) < len(行列表):
        金额行 = list(金额行) + [None] * (len(行列表) - len(金额行))
    行数据 = []
    for _i, _t in enumerate(行列表):
        _a = 金额行[_i] if _i < len(金额行) else None
        _astr = f"{float(_a):.4f}" if _a is not None else ""
        行数据.append({"类型": (_t or "").strip(), "金额": _astr})
    首行类型 = 行数据[0]["类型"] if 行数据 else 项目类型

    town = extract_town(项目地点) if 项目地点 else ""
    # 无金额（台账空或 0）→ 留空不填（用户 2026-10-14 拍板：86 条无金额留空；
    # 与 beian_gc_build_rows 金额_行列表=null 口径一致，beian_fill 对空值自动跳过）
    amt = ""
    if 金额:
        try:
            _v = float(金额)
            amt = f"{_v:.4f}" if _v else ""
        except (ValueError, TypeError):
            amt = ""
    首行金额 = 行数据[0]["金额"] if (行数据 and 行数据[0]["金额"]) else amt
    合同日期 = _norm_date(签订日期)

    # 联系人兜底：若未预生成，则按“经办人姓氏+先生”现场算
    if not 联系人 and 经办人:
        联系人 = (经办人[:2] if 经办人[:2] in ("欧阳", "司马", "上官", "诸葛", "东方", "独孤", "南宫", "令狐", "皇甫", "宇文", "慕容", "司徒", "夏侯") else 经办人[:1]) + "先生"

    form = {
        # ===== 变动值 =====
        "项目名称":              合同名称 or wei,
        "详细地址(乡镇)":         town,
        "预计开工时间":          _norm_date(开工) if 开工 else "",
        "预计完工时间":          _norm_date(完工) if 完工 else "",
        "建设单位":              wei,
        "建设单位项目联系人":     联系人,
        "合同签订日期":           合同日期,
        "项目合同金额(万元)":      amt,
        "金额(万元)":             首行金额,
        "项目类型_多行":          行数据,

        # ===== 固定值 =====
        "是否分包项目":           FIXED_FIELDS["是否分包项目"],
        "是否多测合一项目":       FIXED_FIELDS["是否多测合一项目"],
        "项目范围是否跨地市":     FIXED_FIELDS["项目范围是否跨地市"],
        "项目范围是否跨区县":     FIXED_FIELDS["项目范围是否跨区县"],
        "质量验收约定":           FIXED_FIELDS["质量验收约定"],
        "是否有监理":             FIXED_FIELDS["是否有监理"],
        "是否涉及有限空间作业或地下管线探测": FIXED_FIELDS["是否涉及有限空间作业或地下管线探测"],
        "建设单位联系电话":       FIXED_FIELDS["建设单位联系电话"],
        "测绘单位项目联系人":     FIXED_FIELDS["测绘单位项目联系人"],
        "测绘单位联系人电话":     FIXED_FIELDS["测绘单位联系人电话"],
        "合同编号":              FIXED_FIELDS["合同编号"],
        "项目类型":              首行类型 or 项目类型,
        "是否属于基础测绘项目或重大建设工程的测绘项目": FIXED_FIELDS["是否属于基础测绘项目或重大建设工程的测绘项目"],

        # ===== 地址 =====
        "省":                    FIXED_FIELDS["省"],
        "市":                    FIXED_FIELDS["市"],
        "区县":                  FIXED_FIELDS["区县"],

        # ===== 来源追踪 =====
        "_source_report_no":     record.get("合同号", ""),
        "_source_pdf":           record.get("匹配PDF", ""),
        "_source_合同":          record.get("合同", []) if isinstance(record.get("合同"), list) else [],
    }
    return form


if __name__ == "__main__":
    import json, sys
    import beian_config as _cfg
    ledger_path = _cfg.LEDGER_PATH
    try:
        ledger = json.load(open(ledger_path, encoding="utf-8"))
    except FileNotFoundError:
        print(f"错误: 找不到 {ledger_path}")
        sys.exit(1)

    samples = list(ledger.items())[:3]
    print(f"=== 表单数据生成测试（前{len(samples)}条）===\n")
    for i, (key, rec) in enumerate(samples):
        print(f"--- {i+1}: {key} ({rec.get('委托方')}) ---")
        form = generate_form_data(rec)
        for fk in ["项目名称","详细地址(乡镇)","预计开工时间","预计完工时间",
                   "建设单位","合同签订日期","项目合同金额(万元)","金额(万元)",
                   "建设单位联系电话","测绘单位联系人电话","合同编号"]:
            v = form.get(fk, "")
            print(f"  {fk}: {v if v else '(不填)'}")
        print()
