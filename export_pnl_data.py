#!/usr/bin/env python3
"""导出底层数据表盈亏数据为JSON，供HTML看板使用（含仓位汇总、盈亏率、最新净值）"""
import subprocess, json, os

BASE_TOKEN = "JWJ1bTzQ0aBETsseSJqcWn7EnJe"
TABLE_ID  = "tbl6QMWWCrGLbgtS"
MA20_TABLE_ID = "tblMcst8z8IYH72v"
D1_FIELD_ID = "fldUVbGZZF"   # MA20表 D1字段（最新净值）

# ── 1. 获取底层数据表 ─────────────────────────────────────
result = subprocess.run(
    ["lark-cli", "base", "+record-list",
     "--base-token", BASE_TOKEN,
     "--table-id", TABLE_ID,
     "--as", "user", "--format", "json"],
    capture_output=True, text=True, timeout=60
)
data = json.loads(result.stdout)["data"]

field_ids = data["field_id_list"]
names = data["fields"]
records = data["data"]
ids = data["record_id_list"]

name2idx = {n: i for i, n in enumerate(names)}

# ── 2. 获取 MA20 净值表，建立 基金名称→D1(最新净值) 映射 ──
nav_map = {}   # {基金名称: D1净值}
try:
    r2 = subprocess.run(
        ["lark-cli", "base", "+record-list",
         "--base-token", BASE_TOKEN,
         "--table-id", MA20_TABLE_ID,
         "--as", "user", "--format", "json"],
        capture_output=True, text=True, timeout=60
    )
    d2 = json.loads(r2.stdout)["data"]
    fnames2 = d2["fields"]
    # 找 D21 字段（最新净值，fetch_fund_nav.py 写入此处）
    d21_idx = None
    for i, fn in enumerate(fnames2):
        if fn == "D21" or fn == "d21":
            d21_idx = i
            break
    name_idx = fnames2.index("基金名称") if "基金名称" in fnames2 else -1
    if d21_idx is not None and name_idx >= 0:
        for row in d2["data"]:
            # 基金名称：MA20 表存的是数组 ['xxx']，取第一个元素
            raw_name = row[name_idx] if name_idx < len(row) else None
            if isinstance(raw_name, list) and len(raw_name) > 0:
                fname = str(raw_name[0]).strip()
            elif isinstance(raw_name, str):
                fname = raw_name.strip()
            else:
                fname = ""
            # D21 净值：跳过 None
            d21_val = row[d21_idx] if d21_idx < len(row) else None
            if fname and d21_val is not None:
                try:
                    nav_map[fname] = float(d21_val)
                except:
                    pass
        print(f"  ✅ 获取净值(D21): {len(nav_map)} 条")
    else:
        print(f"  ⚠️  未找到 D1 字段，fields={fnames2}")
except Exception as e:
    print(f"  ⚠️  获取净值失败: {e}")

# 仓位名称映射：修正底层表名称以匹配用户习惯
POSITION_ALIAS = {
    "战术仓": "战术",
    "债券/红利": "压舱石",
}

want = ["基金名称", "盈亏_日", "盈亏_总", "持仓金额", "持有金额", "仓位", "场内场外"]
results = []
for row, rid in zip(records, ids):
    item = {"record_id": rid}
    for fname in want:
        idx = name2idx.get(fname, -1)
        if idx >= 0 and idx < len(row):
            val = row[idx]

            # 单选字段（如「场内场外」）：API返回 [option_name]，取第一个元素
            if isinstance(val, list) and len(val) > 0:
                item[fname] = str(val[0])
                continue

            # 仓位字段强制转字符串
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

    # 标准化仓位名称
    raw_pos = item.get("仓位", "").strip()
    item["仓位"] = POSITION_ALIAS.get(raw_pos, raw_pos)

    # 场内场外：从数组中提取字符串，如 ['场外基金'] → '场外基金'
    io = item.get("场内场外", "")
    if isinstance(io, list) and len(io) > 0:
        item["场内场外"] = io[0]
    elif not io:
        item["场内场外"] = "场外基金"  # 兜底

    # 最新净值（从 MA20 表 D1 字段获取）
    fname_nav = item.get("基金名称", "")
    item["nav"] = nav_map.get(fname_nav, 0)

    # 计算盈亏率（持仓金额作为分母）
    cost = item.get("持仓金额", 0)
    item["日盈亏率"] = (item.get("盈亏_日", 0) / cost * 100) if cost else 0
    item["总盈亏率"] = (item.get("盈亏_总", 0) / cost * 100) if cost else 0
    # 持仓金额 ≤ 0 的基金跳过（已清仓/未建仓）
    if item.get("持仓金额", 0) <= 0:
        continue
    results.append(item)

# 按仓位分组汇总
position_order = ["战略仓", "媳妇", "乔治", "佩奇", "战术", "高增长", "压舱石"]
position_summary = []
for pos in position_order:
    funds = [x for x in results if x.get("仓位") == pos]
    if not funds:
        continue
    day_pnl   = sum(x.get("盈亏_日", 0) for x in funds)
    total_pnl = sum(x.get("盈亏_总", 0) for x in funds)
    cost      = sum(x.get("持仓金额", 0) for x in funds)
    day_rate  = (day_pnl / cost * 100) if cost else 0
    total_rate = (total_pnl / cost * 100) if cost else 0
    position_summary.append({
        "仓位": pos,
        "日盈亏": round(day_pnl, 2),
        "日盈亏率": round(day_rate, 4),
        "总盈亏": round(total_pnl, 2),
        "总盈亏率": round(total_rate, 4),
        "持仓金额": round(cost, 2),
        "基金列表": [x.get("基金名称","?") for x in funds],
    })

# Filter out zero-value items for charts
day_filtered   = [x for x in results if abs(x.get("盈亏_日", 0)) > 0.01]
day_sorted     = sorted(day_filtered, key=lambda x: x.get("盈亏_日", 0), reverse=True)

total_filtered  = [x for x in results if abs(x.get("盈亏_总", 0)) > 0.01]
total_sorted   = sorted(total_filtered, key=lambda x: x.get("盈亏_总", 0), reverse=True)

total_day   = sum(x.get("盈亏_日", 0) for x in results)
total_all   = sum(x.get("盈亏_总", 0) for x in results)
total_cost  = sum(x.get("持仓金额", 0) for x in results)

out = {
    "day_sorted": day_sorted,
    "total_sorted": total_sorted,
    "position_summary": position_summary,
    "total_day_pnl": round(total_day, 2),
    "total_all_pnl": round(total_all, 2),
    "total_cost":     round(total_cost, 2),
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

json_path = os.path.join(os.path.dirname(__file__), ".workbuddy", "pnl_data.json")
os.makedirs(os.path.dirname(json_path), exist_ok=True)
with open(json_path, "w") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)

total_day_rate  = (total_day / total_cost * 100) if total_cost else 0
total_all_rate  = (total_all / total_cost * 100) if total_cost else 0

print(f"✅ 导出完成: {len(results)} 条记录, {len(position_summary)} 个仓位")
for ps in position_summary:
    print(f"  {ps['仓位']:8s}  日:{ps['日盈亏']:>10,.2f}({ps['日盈亏率']:>+7.2f}%)  总:{ps['总盈亏']:>10,.2f}({ps['总盈亏率']:>+7.2f}%)")
print(f"合计  日:{total_day:>10,.2f}({total_day_rate:>+7.2f}%)  总:{total_all:>10,.2f}({total_all_rate:>+7.2f}%)")
