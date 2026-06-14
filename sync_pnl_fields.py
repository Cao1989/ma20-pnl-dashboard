#!/usr/bin/env python3
"""同步底层数据表的公式字段值到普通数字字段，供仪表盘排序使用。"""
import subprocess
import json
import sys
import time

BASE_TOKEN = "JWJ1bTzQ0aBETsseSJqcWn7EnJe"
TABLE_ID = "tbl6QMWWCrGLbgtS"

def run_cmd(cmd_args):
    result = subprocess.run(cmd_args, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"ERROR: {result.stderr[:200]}")
        return None
    return json.loads(result.stdout)

def main():
    print("获取所有记录...")
    data = run_cmd([
        "lark-cli", "base", "+record-list",
        "--base-token", BASE_TOKEN,
        "--table-id", TABLE_ID,
        "--as", "user", "--format", "json"
    ])
    if not data:
        sys.exit(1)
    
    d = data["data"]
    names = d["fields"]
    records = d["data"]
    record_ids = d["record_id_list"]
    
    # Build name -> index
    name_idx = {n: i for i, n in enumerate(names)}
    idx_day_src = name_idx["当日盈亏"]     # formula field
    idx_total_src = name_idx["持有收益"]   # formula field
    idx_name = name_idx["基金名称"]
    
    print(f"共 {len(records)} 条记录\n")
    
    success = 0
    for i, (row, rid) in enumerate(zip(records, record_ids)):
        name_val = row[idx_name]
        if isinstance(name_val, list):
            name_val = name_val[0] if name_val else "?"
        
        pnl_day = row[idx_day_src]
        pnl_total = row[idx_total_src]
        
        # Convert to number if it's a string
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
        
        json_str = json.dumps(fields)
        result = run_cmd([
            "lark-cli", "base", "+record-upsert",
            "--base-token", BASE_TOKEN,
            "--table-id", TABLE_ID,
            "--record-id", rid,
            "--json", json_str,
            "--as", "user"
        ])
        if result and result.get("ok"):
            day_s = f"{pnl_day:>12,.2f}" if pnl_day is not None else "N/A"
            total_s = f"{pnl_total:>12,.2f}" if pnl_total is not None else "N/A"
            print(f"  ✅ {name_val:15s}  盈亏_日={day_s}  盈亏_总={total_s}")
            success += 1
        else:
            print(f"  ❌ {name_val} 更新失败")
        time.sleep(0.15)
    
    print(f"\n完成: {success} 成功")

if __name__ == "__main__":
    main()
