#!/usr/bin/env python3
"""
导出底层数据表盈亏数据为JSON（云端版）
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from feishu_api import base_list_records

BASE_TOKEN = "JWJ1bTzQ0aBETsseSJqcWn7EnJe"
TABLE_ID = "tbl6QMWWCrGLbgtS"
MA20_TABLE_ID = "tblMcst8z8IYH72v"

POSITION_ALIAS = {
    "战术仓": "战术",
    "债券/红利": "压舱石",
}


def main():
    # ── 1. 获取底层数据表 ──
    resp = base_list_records(BASE_TOKEN, TABLE_ID)
    field_ids = resp["field_id_list"]
    field_names = resp["fields"]
    records = resp["data"]
    ids = resp["record_id_list"]

    # 使用第一个出现的字段名（飞书API可能返回重复字段名，后出现的为null）
    name2idx = {}
    for i, n in enumerate(field_names):
        if n not in name2idx:
            name2idx[n] = i

    # ── 2. 获取 MA20 净值表 D21 ──
    nav_map = {}
    try:
        r2 = base_list_records(BASE_TOKEN, MA20_TABLE_ID)
        fnames2 = r2["fields"]
        d21_name = None
        for fn in fnames2:
            if fn in ("D21", "d21"):
                d21_name = fn
                break
        name_field_idx = fnames2.index("基金名称") if "基金名称" in fnames2 else -1
        d21_idx = fnames2.index(d21_name) if d21_name else -1

        if d21_idx >= 0 and name_field_idx >= 0:
            for row in r2["data"]:
                raw_name = row[name_field_idx] if name_field_idx < len(row) else None
                if isinstance(raw_name, list) and len(raw_name) > 0:
                    fname = str(raw_name[0]).strip()
                elif isinstance(raw_name, str):
                    fname = raw_name.strip()
                else:
                    fname = ""
                d21_val = row[d21_idx] if d21_idx < len(row) else None
                if fname and d21_val is not None:
                    try:
                        nav_map[fname] = float(d21_val)
                    except:
                        pass
            print(f"  ✅ 获取净值(D21): {len(nav_map)} 条")
    except Exception as e:
        print(f"  ⚠️  获取净值失败: {e}")

    # ── 3. 解析记录 ──
    want = ["基金名称", "盈亏_日", "盈亏_总", "持仓金额", "持有金额", "仓位", "场内场外"]
    results = []
    for row, rid in zip(records, ids):
        item = {"record_id": rid}
        for fname in want:
            idx = name2idx.get(fname, -1)
            if idx >= 0 and idx < len(row):
                val = row[idx]
                if isinstance(val, list) and len(val) > 0:
                    item[fname] = str(val[0])
                    continue
                if fname == "仓位":
                    item[fname] = str(val).strip() if val is not None else ""
                    continue
                if isinstance(val, (int, float)):
                    item[fname] = val
                elif val is None:
                    item[fname] = 0
                elif isinstance(val, str) and fname != "基金名称":
                    try:
                        item[fname] = float(val)
                    except:
                        item[fname] = 0
                else:
                    item[fname] = str(val) if fname == "基金名称" else 0
            else:
                item[fname] = "?" if fname == "基金名称" else 0

        raw_pos = item.get("仓位", "").strip()
        item["仓位"] = POSITION_ALIAS.get(raw_pos, raw_pos)

        io = item.get("场内场外", "")
        if isinstance(io, list) and len(io) > 0:
            item["场内场外"] = io[0]
        elif not io:
            item["场内场外"] = "场外基金"

        fname_nav = item.get("基金名称", "")
        item["nav"] = nav_map.get(fname_nav, 0)

        cost = item.get("持仓金额", 0)
        item["日盈亏率"] = (item.get("盈亏_日", 0) / cost * 100) if cost else 0
        item["总盈亏率"] = (item.get("盈亏_总", 0) / cost * 100) if cost else 0

        if item.get("持仓金额", 0) <= 0:
            continue
        results.append(item)

    # ── 4. 仓位汇总 ──
    position_order = ["战略仓", "媳妇", "乔治", "佩奇", "战术", "高增长", "压舱石"]
    position_summary = []
    for pos in position_order:
        funds = [x for x in results if x.get("仓位") == pos]
        if not funds:
            continue
        day_pnl = sum(x.get("盈亏_日", 0) for x in funds)
        total_pnl = sum(x.get("盈亏_总", 0) for x in funds)
        cost = sum(x.get("持仓金额", 0) for x in funds)
        day_rate = (day_pnl / cost * 100) if cost else 0
        total_rate = (total_pnl / cost * 100) if cost else 0
        position_summary.append({
            "仓位": pos, "日盈亏": round(day_pnl, 2), "日盈亏率": round(day_rate, 4),
            "总盈亏": round(total_pnl, 2), "总盈亏率": round(total_rate, 4),
            "持仓金额": round(cost, 2),
            "基金列表": [x.get("基金名称", "?") for x in funds],
        })

    day_sorted = sorted(
        [x for x in results if abs(x.get("盈亏_日", 0)) > 0.01],
        key=lambda x: x.get("盈亏_日", 0), reverse=True
    )
    total_sorted = sorted(
        [x for x in results if abs(x.get("盈亏_总", 0)) > 0.01],
        key=lambda x: x.get("盈亏_总", 0), reverse=True
    )

    total_day = sum(x.get("盈亏_日", 0) for x in results)
    total_all = sum(x.get("盈亏_总", 0) for x in results)
    total_cost = sum(x.get("持仓金额", 0) for x in results)

    out = {
        "day_sorted": day_sorted,
        "total_sorted": total_sorted,
        "position_summary": position_summary,
        "total_day_pnl": round(total_day, 2),
        "total_all_pnl": round(total_all, 2),
        "total_cost": round(total_cost, 2),
        "all_records": [
            {
                "record_id": r.get("record_id", ""),
                "基金名称": str(r.get("基金名称", "?")),
                "盈亏_日": r.get("盈亏_日", 0),
                "盈亏_总": r.get("盈亏_总", 0),
                "持仓金额": r.get("持仓金额", 0),
                "日盈亏率": round(r.get("日盈亏率", 0), 4),
                "总盈亏率": round(r.get("总盈亏率", 0), 4),
                "仓位": r.get("仓位", ""),
                "场内场外": r.get("场内场外", "场外基金"),
                "nav": r.get("nav", 0),
            }
            for r in results
        ],
    }

    os.makedirs(".workbuddy", exist_ok=True)
    with open(".workbuddy/pnl_data.json", "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    total_day_rate = (total_day / total_cost * 100) if total_cost else 0
    total_all_rate = (total_all / total_cost * 100) if total_cost else 0

    print(f"✅ 导出完成: {len(results)} 条记录, {len(position_summary)} 个仓位")
    print(f"合计  日:{total_day:>+10,.2f}({total_day_rate:>+7.2f}%)  总:{total_all:>+10,.2f}({total_all_rate:>+7.2f}%)")


if __name__ == "__main__":
    main()
