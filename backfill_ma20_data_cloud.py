#!/usr/bin/env python3
"""
MA20净值表 - 历史数据回填（云端版）
回填 D2~D20 的历史净值数据，修复因云端迁移导致的数据丢失。

数据源：
- 场外基金：天天基金历史净值 API (eastmoney)
- 场内ETF/LOF/个股：新浪K线 API

D字段与交易日映射（按北京时间）：
  D2 = 上一个交易日，D3 = 上上个，...，D20 = 20天前的交易日
"""
import json
import os
import sys
import re
import time
import urllib.request
from datetime import date, datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from feishu_api import (
    base_list_records, base_update_record,
    base_batch_update, send_feishu_msg,
)

BEIJING_TZ = timezone(timedelta(hours=8))

BASE_TOKEN = "JWJ1bTzQ0aBETsseSJqcWn7EnJe"
TABLE_BOTTOM = "tbl6QMWWCrGLbgtS"
TABLE_MA20 = "tblMcst8z8IYH72v"

FIELD_FUND_NAME_BOTTOM = "fldaynV4MN"
FIELD_FUND_NAME_MA20 = "fldS6Vtx56"
FIELD_CODE = "fldfLmbLHe"

# D字段映射: 字段名 → field_id
D_FIELDS = {
    "D2":  "fldUIOrA9s", "D3":  "fldy32wH19", "D4":  "fldzmwOxdr",
    "D5":  "fldvPlyNIa", "D6":  "fldtWeWkwR", "D7":  "fldqHCNT5H",
    "D8":  "fldZKpK6eO", "D9":  "fldI4NHL0J", "D10": "fldS0V7dD8",
    "D11": "fldx3IhWZ8", "D12": "fldkfyasH2", "D13": "fldx9UbdOu",
    "D14": "fldZilzQxW", "D15": "fldOb2igoY", "D16": "fld6aSTbD8",
    "D17": "fldyMA6D95", "D18": "fldwT8faxz", "D19": "fldtonHuMM",
    "D20": "fldcVkLAoo", "D21": "fldWFYu1sW",
}

# D字段序号 → 字段名
D_ORDER = [f"D{i}" for i in range(2, 22)]

KLINE_CODES = {
    "600900", "600036", "002463",
    "588290", "515880", "159326", "513300",
    "513650", "159611", "161130", "513090",
    "518850", "159516", "513100", "510050",
    "561780",
}

try:
    import chinese_calendar
    HAS_CC = True
except ImportError:
    HAS_CC = False


def get_beijing_now():
    return datetime.now(BEIJING_TZ)


def is_trading_day(d):
    """判断是否为交易日"""
    if HAS_CC:
        return chinese_calendar.is_workday(d)
    return d.weekday() < 5


def get_last_n_trading_days(n, before_date=None):
    """获取最近N个交易日（不含当天）"""
    if before_date is None:
        before_date = get_beijing_now().date()
    result = []
    d = before_date - timedelta(days=1)
    while len(result) < n:
        if is_trading_day(d):
            result.append(d)
        d -= timedelta(days=1)
    return result


def fetch_fund_nav_history(code, start_date, end_date):
    """
    获取基金历史净值（天天基金/eastmoney API）
    返回: {date_str: nav, ...}
    """
    # 使用 eastmoney 基金历史净值 API
    url = f"https://api.fund.eastmoney.com/f10/lsjz?fundCode={code}&pageIndex=1&pageSize=60"
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://fundf10.eastmoney.com/",
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8")
        data = json.loads(raw)
        items = data.get("Data", {}).get("LSJZList", [])
        result = {}
        for item in items:
            nav_date = item.get("FSRQ", "")  # 净值日期
            nav_val = item.get("DWJZ", "")    # 单位净值
            if nav_date and nav_val:
                try:
                    result[nav_date] = float(nav_val)
                except ValueError:
                    pass
        return result
    except Exception as e:
        print(f"    ⚠ 基金历史净值API异常 ({code}): {e}")
        return {}


def fetch_stock_kline_history(code, start_date, end_date):
    """
    获取股票/ETF历史收盘价（新浪K线API）
    返回: {date_str: close_price, ...}
    """
    prefix = "sh" if code.startswith(("6", "5")) else "sz"
    url = (
        f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
        f"CN_MarketData.getKLineData?symbol={prefix}{code}&scale=240&ma=no&datalen=100"
    )
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://finance.sina.com.cn",
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("gbk")
        data = json.loads(raw)
        result = {}
        for item in data:
            day = item.get("day", "")
            close = item.get("close", "")
            if day and close:
                try:
                    result[day] = float(close)
                except ValueError:
                    pass
        return result
    except Exception as e:
        print(f"    ⚠ K线历史API异常 ({code}): {e}")
        return {}


def fetch_history(code):
    """获取历史净值/收盘价"""
    code_str = str(code).strip()
    # 获取足够多的历史数据（最近30个交易日的）
    end = get_beijing_now().date()
    start = end - timedelta(days=60)
    end_str = end.strftime("%Y-%m-%d")
    start_str = start.strftime("%Y-%m-%d")

    if code_str in KLINE_CODES:
        return fetch_stock_kline_history(code_str, start_str, end_str)
    else:
        return fetch_fund_nav_history(code_str, start_str, end_str)


def read_bottom_table():
    """读取底层数据表 → {基金名称: 代码}"""
    resp = base_list_records(BASE_TOKEN, TABLE_BOTTOM)
    field_ids = resp["field_id_list"]
    field_names = resp["fields"]
    records = resp["data"]

    # 用 field name 找位置（因为 API 可能返回重复的 fid/fname 条目）
    name_pos = code_pos = None
    for i, (fid, fname) in enumerate(zip(field_ids, field_names)):
        if name_pos is None and fname == "基金名称":
            name_pos = i
        if code_pos is None and fname == "代码":
            code_pos = i

    if name_pos is None or code_pos is None:
        print(f"[ERROR] 底层表字段定位失败: name_pos={name_pos}, code_pos={code_pos}")
        print(f"  fields: {list(zip(field_ids, field_names))}")
        sys.exit(1)

    result = {}
    for rec in records:
        name = rec[name_pos] if name_pos < len(rec) else None
        code = rec[code_pos] if code_pos < len(rec) else None
        if isinstance(name, list):
            name = name[0] if name else None
        if isinstance(code, list):
            code = code[0] if code else None
        if name and code:
            result[str(name)] = str(code).strip()
    return result


def read_ma20_table():
    """读取MA20表 → [{rid, name}, ...]"""
    resp = base_list_records(BASE_TOKEN, TABLE_MA20)
    field_ids = resp["field_id_list"]
    field_names = resp["fields"]
    records = resp["data"]
    record_ids = resp["record_id_list"]

    # 用 field name 找位置
    name_pos = None
    for i, fname in enumerate(field_names):
        if name_pos is None and fname == "基金名称":
            name_pos = i
            break

    if name_pos is None:
        print("[ERROR] MA20表基金名称字段定位失败")
        sys.exit(1)

    result = []
    for i, rec in enumerate(records):
        name = rec[name_pos] if name_pos < len(rec) else None
        if isinstance(name, list):
            name = name[0] if name else None
        result.append({
            "rid": record_ids[i],
            "name": str(name) if name else "",
        })
    return result


def main():
    print("=== MA20净值表 历史数据回填 ===\n")

    # 1. 获取最近20个交易日
    trading_days = get_last_n_trading_days(20)
    print(f"[1] 最近20个交易日:")
    for i, d in enumerate(trading_days):
        label = f"D{i+2}"
        print(f"    {label} = {d.strftime('%Y-%m-%d')} ({d.strftime('%A')})")

    # 建立日期 → D字段映射
    date_to_field = {}
    for i, d in enumerate(trading_days):
        field_name = f"D{i+2}"
        date_to_field[d.strftime("%Y-%m-%d")] = field_name

    # 2. 读取底层表
    print(f"\n[2] 读取底层数据表...")
    fund_code_map = read_bottom_table()
    print(f"    {len(fund_code_map)} 只基金")

    # 3. 读取MA20表
    print(f"\n[3] 读取MA20表...")
    ma20_records = read_ma20_table()
    print(f"    {len(ma20_records)} 条记录")

    # 建立名称→rid映射
    name_to_rid = {}
    for rec in ma20_records:
        name_to_rid[rec["name"]] = rec["rid"]

    # 4. 逐只基金获取历史净值并构建更新
    print(f"\n[4] 获取历史净值...")
    all_updates = {}  # rid → {field_name: value}

    for idx, (fund_name, code) in enumerate(fund_code_map.items()):
        rid = name_to_rid.get(fund_name)
        if not rid:
            print(f"  ⊘ [{idx+1}/{len(fund_code_map)}] {fund_name}: 未在MA20表中找到")
            continue

        print(f"  [{idx+1}/{len(fund_code_map)}] {fund_name} ({code})...", end=" ")
        nav_history = fetch_history(code)

        if not nav_history:
            print("无历史数据")
            continue

        # 匹配交易日
        updates = {}
        matched = 0
        for date_str, field_name in date_to_field.items():
            nav = nav_history.get(date_str)
            if nav is not None and nav > 0:
                updates[field_name] = round(nav, 4)
                matched += 1

        print(f"匹配 {matched}/{len(trading_days)} 天")

        if updates:
            all_updates[rid] = updates

        time.sleep(0.3)  # 避免API频率限制

    # 5. 批量写入
    print(f"\n[5] 批量写入MA20表...")
    if not all_updates:
        print("    无数据可写!")
        return

    batch_records = []
    for rid, fields in all_updates.items():
        batch_records.append({"record_id": rid, "fields": fields})

    print(f"    共 {len(batch_records)} 条记录待更新")
    base_batch_update(BASE_TOKEN, TABLE_MA20, batch_records)
    print(f"    ✅ 回填完成!")

    # 6. 汇总
    total_fields = sum(len(f) for f in all_updates.values())
    print(f"\n[6] 汇总: 回填了 {len(all_updates)} 只基金的 {total_fields} 个字段")
    for dname in D_ORDER:
        count = sum(1 for f in all_updates.values() if dname in f)
        print(f"    {dname}: {count} 只基金")


if __name__ == "__main__":
    main()
