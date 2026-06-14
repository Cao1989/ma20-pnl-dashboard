#!/usr/bin/env python3
"""
同步底层数据表的公式字段值到普通数字字段（云端版）
"""
import json
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from feishu_api import base_list_records, base_update_record

BASE_TOKEN = "JWJ1bTzQ0aBETsseSJqcWn7EnJe"
TABLE_ID = "tbl6QMWWCrGLbgtS"


def main():
    print("=== 同步盈亏字段（云端） ===")
    resp = base_list_records(BASE_TOKEN, TABLE_ID)

    field_ids = resp["field_id_list"]
    field_names = resp["fields"]
    records = resp["data"]
    record_ids = resp["record_id_list"]

    # 构建名称索引
    name_idx = {n: i for i, n in enumerate(field_names)}
    idx_day_src = name_idx["当日盈亏"]
    idx_total_src = name_idx["持有收益"]
    idx_name = name_idx["基金名称"]

    print(f"共 {len(records)} 条记录\n")

    success = 0
    for i, (row, rid) in enumerate(zip(records, record_ids)):
        name_val = row[idx_name]
        if isinstance(name_val, list):
            name_val = name_val[0] if name_val else "?"

        pnl_day = row[idx_day_src]
        pnl_total = row[idx_total_src]

        try:
            if isinstance(pnl_day, str) and pnl_day:
                pnl_day = float(pnl_day)
            if isinstance(pnl_total, str) and pnl_total:
                pnl_total = float(pnl_total)
        except ValueError:
            continue

        if pnl_day is None and pnl_total is None:
            continue

        fields = {}
        if pnl_day is not None:
            fields["盈亏_日"] = pnl_day
        if pnl_total is not None:
            fields["盈亏_总"] = pnl_total

        try:
            base_update_record(BASE_TOKEN, TABLE_ID, rid, fields)
            print(f"  ✅ {str(name_val):15s}  盈亏_日={pnl_day}  盈亏_总={pnl_total}")
            success += 1
        except Exception as e:
            print(f"  ❌ {name_val} 更新失败: {e}")
        time.sleep(0.15)

    print(f"\n完成: {success} 成功")


if __name__ == "__main__":
    main()
