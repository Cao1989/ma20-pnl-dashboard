#!/usr/bin/env python3
"""
MA20净值表 - 实时行情获取（云端版）
白天 9:30-15:00 每5分钟运行一次。

数据源:
  - 场内ETF/LOF/个股 → 新浪实时行情API (当前成交价)
  - 场外基金 → 天天基金估算API (gsz估算值, 回退到 dwjz 官方净值)

写入 MA20 净值表的 D21 字段。
"""
import json
import sys
import os
import re
import time
import urllib.request
from datetime import date, datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from feishu_api import base_list_records, base_update_record

# ─── 配置 ──────────────────────────────────────────────────

BASE_TOKEN = "JWJ1bTzQ0aBETsseSJqcWn7EnJe"
TABLE_BOTTOM = "tbl6QMWWCrGLbgtS"
TABLE_MA20 = "tblMcst8z8IYH72v"

FIELD_FUND_NAME_BOTTOM = "fldaynV4MN"
FIELD_FUND_NAME_MA20 = "fldS6Vtx56"
FIELD_D21 = "fldWFYu1sW"
FIELD_CODE = "fldfLmbLHe"

# 走新浪实时行情的代码（场内ETF/LOF/个股）
KLINE_CODES = {
    "600900", "600036", "002463",
    "588290", "515880", "159326", "513300",
    "513650", "159611", "161130", "513090",
    "518850", "159516", "513100", "510050",
    "561780",
}

SINA_PREFIX_MAP = {}
for c in KLINE_CODES:
    SINA_PREFIX_MAP[c] = "sh" if c.startswith(("6", "5")) else "sz"

# ─── 交易日判断 ────────────────────────────────────────────

BEIJING_TZ = timezone(timedelta(hours=8))


def get_beijing_now():
    """获取北京时间"""
    return datetime.now(BEIJING_TZ)


def is_trading_day():
    today = get_beijing_now().date()
    try:
        import chinese_calendar
        return chinese_calendar.is_workday(today)
    except ImportError:
        return today.weekday() < 5


def is_trading_hours():
    """判断当前是否在北京时间A股交易时段 (9:30-11:30, 13:00-15:00)"""
    now = get_beijing_now()
    t = now.hour * 60 + now.minute
    return (570 <= t <= 690) or (780 <= t <= 900)  # 9:30-11:30, 13:00-15:00


# ─── 新浪实时行情 ──────────────────────────────────────────

def fetch_sina_realtime(codes_batch):
    """
    批量获取新浪实时行情。
    codes_batch: [(code, prefix), ...]
    返回: {code: float_price, ...}
    """
    symbols = [f"{p}{c}" for c, p in codes_batch]
    url = f"https://hq.sinajs.cn/list={','.join(symbols)}"

    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://finance.sina.com.cn",
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("gbk", errors="replace")
    except Exception as e:
        print(f"  [ERROR] 新浪实时API请求失败: {e}")
        return {}

    results = {}
    for line in raw.strip().split("\n"):
        if not line.strip():
            continue
        m = re.search(r'hq_str_(\w+)="(.+)"', line)
        if not m:
            continue
        symbol = m.group(1)  # e.g. sh600900
        data = m.group(2).split(",")
        if len(data) < 4:
            continue
        # data[3] = 当前价
        try:
            price = float(data[3])
            if price > 0:
                code = symbol[2:]  # 去掉 sh/sz 前缀
                results[code] = round(price, 4)
        except (ValueError, IndexError):
            continue
    return results


# ─── 天天基金估算 ──────────────────────────────────────────

def fetch_fund_estimated_nav(code):
    """获取场外基金的估算净值(gsz)，回退到官方净值(dwjz)"""
    url = f"https://fundgz.1234567.com.cn/js/{code}.js"
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://fund.eastmoney.com",
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8")
    except Exception as e:
        return None, f"API异常: {e}"

    m = re.search(r'\{.*\}', raw)
    if not m:
        return None, f"无法解析"

    try:
        data = json.loads(m.group())
    except json.JSONDecodeError:
        return None, "JSON解析失败"

    gsz = data.get("gsz", "")
    dwjz = data.get("dwjz", "")
    gztime = data.get("gztime", "")
    jzrq = data.get("jzrq", "")

    if gsz and _is_valid_price(gsz):
        return round(float(gsz), 4), f"估算净值={gsz}({gztime})"
    if dwjz and _is_valid_price(dwjz):
        return round(float(dwjz), 4), f"官方净值={dwjz}(净值日:{jzrq})"
    return None, f"无有效净值"


def _is_valid_price(val):
    if not val or not str(val).strip():
        return False
    try:
        return float(val) > 0.0001
    except (ValueError, TypeError):
        return False


# ─── 表格读写 ──────────────────────────────────────────────

def read_ma20_table():
    """读取MA20净值表，返回 {基金名: {rid, d21}}"""
    resp = base_list_records(BASE_TOKEN, TABLE_MA20)
    field_ids = resp["field_id_list"]
    records = resp["data"]
    record_ids = resp["record_id_list"]

    name_pos = d21_pos = None
    for i, fid in enumerate(field_ids):
        if fid == FIELD_FUND_NAME_MA20:
            name_pos = i
        if fid == FIELD_D21:
            d21_pos = i

    if name_pos is None or d21_pos is None:
        print("[ERROR] MA20表字段定位失败")
        sys.exit(1)

    result = {}
    for i, rec in enumerate(records):
        name = rec[name_pos] if name_pos < len(rec) else None
        d21 = rec[d21_pos] if d21_pos < len(rec) else None
        if isinstance(name, list):
            name = name[0] if name else None
        if name:
            result[str(name)] = {
                "rid": record_ids[i],
                "d21": d21,
            }
    return result


def read_bottom_table():
    """读取底层数据表，返回 {基金名称: 代码}"""
    resp = base_list_records(BASE_TOKEN, TABLE_BOTTOM)
    field_ids = resp["field_id_list"]
    records = resp["data"]

    name_pos = code_pos = None
    for i, fid in enumerate(field_ids):
        if fid == FIELD_FUND_NAME_BOTTOM:
            name_pos = i
        if fid == FIELD_CODE:
            code_pos = i

    if name_pos is None or code_pos is None:
        print("[ERROR] 底层数据表字段定位失败")
        sys.exit(1)

    result = {}
    for rec in records:
        name = rec[name_pos] if name_pos < len(rec) else None
        code = rec[code_pos] if code_pos < len(rec) else None
        if isinstance(name, list):
            name = name[0] if name else None
        if name and code:
            result[str(name)] = str(code).strip()
    return result


# ─── 主流程 ────────────────────────────────────────────────

def main():
    if not is_trading_day():
        print("非交易日，跳过执行。")
        return

    if not is_trading_hours():
        now = datetime.now().strftime("%H:%M")
        print(f"当前 {now} 不在交易时段 (9:30-11:30, 13:00-15:00)，跳过。")
        return

    print(f"=== MA20 实时行情获取 [{datetime.now().strftime('%H:%M:%S')}] ===")

    # 1. 读取表格
    fund_code_map = read_bottom_table()
    ma20_map = read_ma20_table()
    print(f"  底层表: {len(fund_code_map)} 只基金")
    print(f"  MA20表: {len(ma20_map)} 条记录")

    # 2. 分组：场内 vs 场外
    kline_funds = []  # [(name, {rid, d21}, code), ...]
    oth_funds = []    # [(name, {rid, d21}, code), ...]

    for name, info in ma20_map.items():
        code = fund_code_map.get(name)
        if not code:
            continue
        if code in KLINE_CODES:
            kline_funds.append((name, info, code))
        else:
            oth_funds.append((name, info, code))

    print(f"  场内(K线): {len(kline_funds)} 只 | 场外(基金): {len(oth_funds)} 只")

    updated = 0
    errors = 0

    # 3. 场内实时行情（批量新浪API）
    if kline_funds:
        print(f"\n  [场内实时行情] 新浪批量获取...")
        # 新浪一次最多约80个，我们只有16个，一次搞定
        batch = [(c, SINA_PREFIX_MAP.get(c, "sh")) for _, _, c in kline_funds]
        prices = fetch_sina_realtime(batch)

        for name, info, code in kline_funds:
            price = prices.get(code)
            if price and price > 0:
                try:
                    base_update_record(BASE_TOKEN, TABLE_MA20, info["rid"], {
                        "D21": price,
                    })
                    print(f"    ✓ {name} ({code}): ¥{price}")
                    updated += 1
                except Exception as e:
                    print(f"    ✗ {name} ({code}): 写入失败 {e}")
                    errors += 1
            else:
                print(f"    ⊘ {name} ({code}): 未获取到实时价")
                errors += 1

    # 4. 场外基金估算净值
    if oth_funds:
        print(f"\n  [场外基金估算] 天天基金批量获取...")
        for name, info, code in oth_funds:
            nav, msg = fetch_fund_estimated_nav(code)
            if nav:
                try:
                    base_update_record(BASE_TOKEN, TABLE_MA20, info["rid"], {
                        "D21": nav,
                    })
                    print(f"    ✓ {name} ({code}): ¥{nav} ({msg})")
                    updated += 1
                except Exception as e:
                    print(f"    ✗ {name} ({code}): 写入失败 {e}")
                    errors += 1
            else:
                print(f"    ⊘ {name} ({code}): {msg}")
                errors += 1
            time.sleep(0.2)

    print(f"\n  结果: 更新 {updated} 只, 失败/跳过 {errors} 只")
    print("=== 实时行情获取完成 ===")


if __name__ == "__main__":
    main()
