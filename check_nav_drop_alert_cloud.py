#!/usr/bin/env python3
"""
MA20净值回撤提醒（云端版）
检查 D21 相对 H 的跌幅，≥10% 时通过飞书发送提醒。
"""
import json
import sys
import os
import time
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from feishu_api import base_list_records, send_feishu_msg

try:
    import chinese_calendar
    HAS_CC = True
except ImportError:
    HAS_CC = False

BASE_TOKEN = "JWJ1bTzQ0aBETsseSJqcWn7EnJe"
TABLE_MA20 = "tblMcst8z8IYH72v"
FIELD_FUND_NAME = "fldS6Vtx56"
FIELD_D21 = "fldWFYu1sW"
FIELD_H = "fldHJVOt5t"

DROP_THRESHOLD = 0.10


def is_trading_day():
    today = date.today()
    if HAS_CC:
        return chinese_calendar.is_workday(today)
    return today.weekday() < 5


def _to_float(val):
    if val is None or val == "":
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def read_ma20_table():
    resp = base_list_records(BASE_TOKEN, TABLE_MA20)
    field_ids = resp["field_id_list"]
    records = resp["data"]

    name_pos = d21_pos = h_pos = None
    for i, fid in enumerate(field_ids):
        if fid == FIELD_FUND_NAME:
            name_pos = i
        elif fid == FIELD_D21:
            d21_pos = i
        elif fid == FIELD_H:
            h_pos = i

    if None in (name_pos, d21_pos, h_pos):
        print(f"[ERROR] 字段定位失败")
        return []

    result = []
    for rec in records:
        name = rec[name_pos] if name_pos < len(rec) else None
        d21 = rec[d21_pos] if d21_pos < len(rec) else None
        h_val = rec[h_pos] if h_pos < len(rec) else None
        if isinstance(name, list):
            name = name[0] if name else ""
        result.append({
            "name": str(name) if name else "",
            "d21": _to_float(d21),
            "h": _to_float(h_val),
        })
    return result


def main():
    if not is_trading_day():
        print("非交易日，跳过执行。")
        return

    print("=== 回撤检查（云端） ===")
    records = read_ma20_table()
    print(f"  读取 {len(records)} 条记录\n")

    alerts = []
    for r in records:
        name = r["name"]
        d21 = r["d21"]
        h_val = r["h"]
        if not name or d21 is None or h_val is None:
            continue
        if d21 <= 0 or h_val <= 0:
            continue

        drop_rate = (h_val - d21) / h_val
        if drop_rate >= DROP_THRESHOLD:
            alerts.append({"name": name, "d21": d21, "h": h_val, "drop_rate": drop_rate})
            print(f"  ⚠️  {name}: D21={d21:.4f}, H={h_val:.4f}, 回撤={drop_rate*100:.2f}%")

    if not alerts:
        print("\n✅ 无触发提醒。")
        return

    print(f"\n  共 {len(alerts)} 只基金触发提醒\n")

    lines = [
        "⚠️ **老曹投资助手 · 净值回撤提醒**",
        "",
        f"以下 **{len(alerts)}** 只基金/股票回撤超过 **{DROP_THRESHOLD*100:.0f}%**：",
        "",
    ]
    for a in alerts:
        lines.append(f"📉 **{a['name']}**")
        lines.append(f"　　　当日净值：{a['d21']:.4f}")
        lines.append(f"　　　20日最高：{a['h']:.4f}")
        lines.append(f"　　　回撤幅度：**{a['drop_rate']*100:.2f}%**")
        lines.append("")

    try:
        send_feishu_msg("\n".join(lines))
    except Exception as e:
        print(f"  飞书发送失败: {e}")

    print("\n=== 回撤检查完成 ===")


if __name__ == "__main__":
    main()
