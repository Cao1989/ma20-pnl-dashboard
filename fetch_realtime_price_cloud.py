#!/usr/bin/env python3
"""
盘中实时净值获取脚本（GitHub Actions 云端版）
- 场内品种: 新浪 hq.sinajs.cn 实时行情
- 场外基金: 天天基金 fundgz.1234567.com.cn 预估净值(gsz)
- 使用 feishu_api.py 读写飞书（无需 lark-cli）
- 写入 MA20 表 D21 字段 + 更新 _site/ 数据文件
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
    base_list_records, base_update_record, base_batch_update,
)

BEIJING_TZ = timezone(timedelta(hours=8))

BASE_TOKEN = "JWJ1bTzQ0aBETsseSJqcWn7EnJe"
TABLE_BOTTOM = "tbl6QMWWCrGLbgtS"
TABLE_MA20 = "tblMcst8z8IYH72v"
FIELD_D21 = "fldWFYu1sW"

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


def is_trading_day(d):
    if HAS_CC:
        return chinese_calendar.is_workday(d)
    return d.weekday() < 5


def fetch_stock_realtime(code):
    """新浪实时行情"""
    code_str = str(code).strip()
    prefix = "sh" if code_str.startswith("6") or code_str.startswith("5") else "sz"
    url = f"https://hq.sinajs.cn/list={prefix}{code_str}"
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://finance.sina.com.cn",
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("gbk")
        if "=" not in raw:
            return False, None, "返回格式异常"
        data_part = raw.split("=", 1)[1].strip().strip('"').rstrip(";")
        parts = data_part.split(",")
        if len(parts) < 4:
            return False, None, f"字段不足({len(parts)})"
        price = parts[3]
        if price and float(price) > 0:
            return True, float(price), f"{parts[0]} 现价={price}"
        return False, None, f"价格为空({price})"
    except Exception as e:
        return False, None, f"新浪API异常: {e}"


def fetch_otc_estimated_nav(code):
    """天天基金预估净值"""
    url = f"https://fundgz.1234567.com.cn/js/{code}.js"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8")
        m = re.search(r'\{.*\}', raw)
        if not m:
            return False, None, f"无法解析: {raw[:50]}"
        data = json.loads(m.group())
        name = data.get("name", "")
        gsz = data.get("gsz", "")
        dwjz = data.get("dwjz", "")
        gszzl = data.get("gszzl", "")
        jzrq = data.get("jzrq", "")

        if gsz and float(gsz) > 0.0001:
            tag = f"(预估{gszzl}%)" if gszzl else "(预估)"
            return True, float(gsz), f"{name} 预估净值={gsz}{tag}"
        if dwjz and float(dwjz) > 0.0001:
            return True, float(dwjz), f"{name} 已发布净值={dwjz}({jzrq})"
        return False, None, f"无有效净值"
    except Exception as e:
        return False, None, f"天天基金API异常: {e}"


def fetch_realtime(code):
    code_str = str(code).strip()
    if not code_str:
        return False, None, "代码为空"
    if code_str in KLINE_CODES:
        return fetch_stock_realtime(code_str)
    return fetch_otc_estimated_nav(code_str)


def read_tables():
    """读取底层表(代码映射) + MA20表(记录列表)"""
    # 底层表: {基金名称: 代码}
    resp = base_list_records(BASE_TOKEN, TABLE_BOTTOM)
    field_ids = resp["field_id_list"]
    field_names = resp["fields"]
    records = resp["data"]

    name_pos = code_pos = None
    for i, fname in enumerate(field_names):
        if name_pos is None and fname == "基金名称":
            name_pos = i
        if code_pos is None and fname == "代码":
            code_pos = i

    fund_code_map = {}
    for rec in records:
        name = rec[name_pos] if name_pos < len(rec) else None
        code = rec[code_pos] if code_pos < len(rec) else None
        if isinstance(name, list):
            name = name[0] if name else None
        if isinstance(code, list):
            code = code[0] if code else None
        if name and code:
            fund_code_map[str(name)] = str(code).strip()

    # MA20表: [{rid, name, d21_old}, ...]
    resp2 = base_list_records(BASE_TOKEN, TABLE_MA20)
    field_ids2 = resp2["field_id_list"]
    field_names2 = resp2["fields"]
    records2 = resp2["data"]
    record_ids2 = resp2["record_id_list"]

    name_pos2 = d21_pos = None
    for i, (fid, fname) in enumerate(zip(field_ids2, field_names2)):
        if name_pos2 is None and fname == "基金名称":
            name_pos2 = i
        if d21_pos is None and fid == FIELD_D21:
            d21_pos = i

    ma20_records = []
    for i, rec in enumerate(records2):
        name = rec[name_pos2] if name_pos2 < len(rec) else None
        d21 = rec[d21_pos] if d21_pos < len(rec) else None
        if isinstance(name, list):
            name = name[0] if name else None
        ma20_records.append({
            "rid": record_ids2[i],
            "name": str(name) if name else "",
            "d21_old": d21,
        })

    return fund_code_map, ma20_records


def main():
    now = datetime.now(BEIJING_TZ)
    today = now.date()
    current_minutes = now.hour * 60 + now.minute

    if not is_trading_day(today):
        print(f"[跳过] {today} 非交易日")
        return

    if current_minutes < 565 or current_minutes > 905:
        print(f"[跳过] {now.strftime('%H:%M')} 不在交易时段")
        return

    print(f"=== 盘中实时净值获取(云端) {now.strftime('%Y-%m-%d %H:%M:%S')} ===\n")

    # 1. 读取数据
    print("[1] 读取飞书多维表格...")
    fund_code_map, ma20_records = read_tables()
    print(f"    底层表: {len(fund_code_map)} 只基金, MA20表: {len(ma20_records)} 条")

    # 2. 获取实时价格
    print(f"\n[2] 获取盘中实时价格...")
    batch_records = []
    updated = 0
    failed = 0

    for rec in ma20_records:
        name = rec["name"]
        code = fund_code_map.get(name)
        if not code:
            continue

        ok, price, msg = fetch_realtime(code)
        if ok:
            price = round(price, 4)
            old_val = rec["d21_old"]
            try:
                old_num = float(old_val) if old_val and str(old_val).strip() else None
            except (ValueError, TypeError):
                old_num = None

            if old_num is not None and abs(old_num - price) < 0.001:
                continue

            batch_records.append({
                "record_id": rec["rid"],
                "fields": {"D21": price}
            })
            updated += 1
            print(f"    ✓ {name:20s} {code:>8s} → {price:>10.4f}" + (f" (旧:{old_num})" if old_num else ""))
        else:
            failed += 1
            print(f"    ✗ {name:20s} {code:>8s}: {msg}")

        time.sleep(0.1)

    print(f"\n    汇总: 更新 {updated} | 失败 {failed}")

    # 3. 批量写入
    if batch_records:
        print(f"\n[3] 写入 MA20 表 D21 (批量)...")
        base_batch_update(BASE_TOKEN, TABLE_MA20, batch_records)
        print(f"    ✅ {len(batch_records)} 条已更新")

        # 4. 保存数据文件供看板动态加载
        print(f"\n[4] 保存数据文件...")
        os.makedirs("_site", exist_ok=True)

        # 构建简化的 pnl_data
        pnl_data = {
            "updated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
            "realtime": True,
            "funds": {}
        }
        for rec in ma20_records:
            code = fund_code_map.get(rec["name"], "")
            pnl_data["funds"][rec["name"]] = {
                "code": code,
                "type": "KLINE" if code in KLINE_CODES else "OTC"
            }

        with open("_site/realtime_prices.json", "w") as f:
            json.dump(pnl_data, f, ensure_ascii=False)
        print(f"    ✅ _site/realtime_prices.json")

    else:
        print(f"\n[3] 无数据变化，跳过写入")

    print(f"=== 完成 {now.strftime('%H:%M:%S')} ===")


if __name__ == "__main__":
    main()
