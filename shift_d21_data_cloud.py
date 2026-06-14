#!/usr/bin/env python3
"""
MA20净值表 - 每日数据后移（云端版）
每天 08:00 执行：D21→D20→D19→...→D3→D2，D1保持空值，D21 清空。
"""
import json
import sys
import os
import time
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from feishu_api import base_list_records, base_update_record, base_batch_update, send_feishu_msg

try:
    import chinese_calendar
    HAS_CC = True
except ImportError:
    HAS_CC = False

BASE_TOKEN = "JWJ1bTzQ0aBETsseSJqcWn7EnJe"
TABLE_MA20 = "tblMcst8z8IYH72v"
TABLE_BOTTOM = "tbl6QMWWCrGLbgtS"

ID_TO_NAME = {
    "fldWFYu1sW": "D21", "fldcVkLAoo": "D20", "fldtonHuMM": "D19",
    "fldwT8faxz": "D18", "fldyMA6D95": "D17", "fld6aSTbD8": "D16",
    "fldOb2igoY": "D15", "fldZilzQxW": "D14", "fldx9UbdOu": "D13",
    "fldkfyasH2": "D12", "fldx3IhWZ8": "D11", "fldS0V7dD8": "D10",
    "fldI4NHL0J": "D9",  "fldZKpK6eO": "D8",  "fldqHCNT5H": "D7",
    "fldtWeWkwR": "D6",  "fldvPlyNIa": "D5",  "fldzmwOxdr": "D4",
    "fldy32wH19": "D3",  "fldUIOrA9s": "D2",  "fldUVbGZZF": "D1",
}

SHIFT_MAP = {
    "fldcVkLAoo": "fldWFYu1sW", "fldtonHuMM": "fldcVkLAoo",
    "fldwT8faxz": "fldtonHuMM", "fldyMA6D95": "fldwT8faxz",
    "fld6aSTbD8": "fldyMA6D95", "fldOb2igoY": "fld6aSTbD8",
    "fldZilzQxW": "fldOb2igoY", "fldx9UbdOu": "fldZilzQxW",
    "fldkfyasH2": "fldx9UbdOu", "fldx3IhWZ8": "fldkfyasH2",
    "fldS0V7dD8": "fldx3IhWZ8", "fldI4NHL0J": "fldS0V7dD8",
    "fldZKpK6eO": "fldI4NHL0J", "fldqHCNT5H": "fldZKpK6eO",
    "fldtWeWkwR": "fldqHCNT5H", "fldvPlyNIa": "fldtWeWkwR",
    "fldzmwOxdr": "fldvPlyNIa", "fldy32wH19": "fldzmwOxdr",
    "fldUIOrA9s": "fldy32wH19",
}


def is_trading_day():
    today = date.today()
    if HAS_CC:
        return chinese_calendar.is_workday(today)
    return today.weekday() < 5


def main():
    if not is_trading_day():
        print("非交易日，跳过执行。")
        return

    print("=== MA20净值表 数据后移（云端） ===")

    # 1. 读取 MA20 表
    print("\n[1/4] 读取MA20净值表...")
    resp = base_list_records(BASE_TOKEN, TABLE_MA20)
    records = resp["data"]
    field_id_list = resp["field_id_list"]
    record_id_list = resp["record_id_list"]
    print(f"  共 {len(records)} 条记录")

    # 2. 定位字段
    print("\n[2/4] 定位字段位置...")
    field_pos = {fid: i for i, fid in enumerate(field_id_list)}

    # 3. 构造后移数据
    print("\n[3/4] 构造后移更新数据...")
    updates = []
    for rec_idx, rec in enumerate(records):
        rid = record_id_list[rec_idx]
        update_fields = {}

        for target_fid, source_fid in SHIFT_MAP.items():
            src_pos = field_pos.get(source_fid)
            if src_pos is None or src_pos >= len(rec):
                continue
            val = rec[src_pos]
            target_name = ID_TO_NAME.get(target_fid, target_fid)
            if val is None or val == "":
                update_fields[target_name] = None
            else:
                try:
                    update_fields[target_name] = round(float(val), 4)
                except (ValueError, TypeError):
                    update_fields[target_name] = None

        # 清空 D21
        update_fields["D21"] = None
        updates.append({"record_id": rid, "fields": update_fields})

    print(f"  需更新 {len(updates)} 条")

    # 4. 批量更新（用 base_batch_update）
    print("\n[4/4] 执行批量更新...")
    try:
        base_batch_update(BASE_TOKEN, TABLE_MA20, updates)
        print(f"  ✅ {len(updates)} 条全部更新成功")
    except Exception as e:
        print(f"  ❌ 批量更新失败: {e}")
        # 降级为逐条更新
        success = 0
        for i, item in enumerate(updates):
            try:
                base_update_record(BASE_TOKEN, TABLE_MA20, item["record_id"], item["fields"])
                success += 1
            except Exception as e2:
                print(f"  ✗ 记录 {i+1} 失败: {e2}")
            time.sleep(0.1)
        print(f"  降级完成: {success}/{len(updates)} 条")
        updates_count = success
    else:
        updates_count = len(updates)

    # 5. 清零底层表「盈亏_日」
    print("\n[5/5] 清零底层表「盈亏_日」...")
    try:
        bottom_resp = base_list_records(BASE_TOKEN, TABLE_BOTTOM)
        bottom_rids = bottom_resp["record_id_list"]
        clear_count = 0
        for rid in bottom_rids:
            try:
                base_update_record(BASE_TOKEN, TABLE_BOTTOM, rid, {"盈亏_日": 0})
                clear_count += 1
            except Exception:
                pass
            time.sleep(0.1)
        print(f"  盈亏_日 清零完成: {clear_count}/{len(bottom_rids)} 条")
    except Exception as e:
        print(f"  [WARN] 底层表清零失败: {e}")

    # 6. 发送通知
    time_str = time.strftime("%H:%M", time.localtime())
    msg = (
        f"📋 **老曹投资助手 数据后移完成**\n\n"
        f"**时间：** {time_str}\n"
        f"**更新：** {updates_count}/{len(updates)} 条记录\n\n"
        f"D21 已清空，17:00 起开始填入今日净值。"
    )
    try:
        send_feishu_msg(msg)
    except Exception as e:
        print(f"  飞书通知失败: {e}")

    print("\n=== 数据后移完成 ===")


if __name__ == "__main__":
    main()
