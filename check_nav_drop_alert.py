#!/usr/bin/env python3
"""
MA20净值回撤提醒脚本
检查每只基金的 D21（最新净值）相对 H（20日最高净值）的跌幅，
当跌幅 ≥ 10% 时通过飞书发送提醒。
"""
import subprocess
import json
import sys
import os
import time
from datetime import date
import chinese_calendar

BASE_TOKEN = "JWJ1bTzQ0aBETsseSJqcWn7EnJe"
TABLE_MA20 = "tblMcst8z8IYH72v"
FIELD_FUND_NAME = "fldS6Vtx56"
FIELD_D21 = "fldWFYu1sW"
FIELD_H = "fldHJVOt5t"

USER_OPEN_ID = "ou_1d2af5f7db994ab6e0151176109f5057"
DROP_THRESHOLD = 0.10  # 10% 回撤阈值


def get_lark_cli():
    r = subprocess.run(["which", "lark-cli"], capture_output=True, text=True)
    if r.returncode == 0 and r.stdout.strip():
        return "lark-cli"
    for c in ["/opt/homebrew/bin/lark-cli", "/usr/local/bin/lark-cli"]:
        if os.path.exists(c):
            return c
    raise RuntimeError("找不到 lark-cli")


def run_lark(args):
    cli = get_lark_cli()
    r = subprocess.run([cli] + args, capture_output=True, text=True)
    if r.returncode != 0:
        return None, r.stderr[:200]
    return r.stdout, None


def send_feishu_msg(markdown_text):
    """发送飞书消息（--as bot）"""
    _, err = run_lark([
        "im", "+messages-send",
        "--user-id", USER_OPEN_ID,
        "--as", "bot",
        "--markdown", markdown_text,
    ])
    if err:
        print(f"  ✗ 飞书消息发送失败: {err}")
    else:
        print("  ✓ 飞书消息已发送")


def read_ma20_table():
    """读取 MA20 净值表，解析每条记录的 (名称, D21, H)"""
    stdout, err = run_lark([
        "base", "+record-list",
        "--base-token", BASE_TOKEN,
        "--table-id", TABLE_MA20,
        "--as", "user", "--format", "json",
    ])
    if err:
        print(f"[ERROR] 读取MA20表失败: {err}")
        return []

    resp = json.loads(stdout)["data"]
    field_ids = resp["field_id_list"]
    records = resp["data"]

    # 定位字段位置
    name_pos = d21_pos = h_pos = None
    for i, fid in enumerate(field_ids):
        if fid == FIELD_FUND_NAME:
            name_pos = i
        elif fid == FIELD_D21:
            d21_pos = i
        elif fid == FIELD_H:
            h_pos = i

    if None in (name_pos, d21_pos, h_pos):
        print(f"[ERROR] 字段定位失败: name={name_pos}, d21={d21_pos}, h={h_pos}")
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


def _to_float(val):
    """安全转换为 float，失败返回 None"""
    if val is None or val == "":
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def main():
    # ─── 交易日检查 ─────────────────────────────────────────
    today = date.today()
    weekday_cn = ["周一","周二","周三","周四","周五","周六","周日"][today.weekday()]
    if not chinese_calendar.is_workday(today):
        print(f"=== 老曹投资助手 · 净值回撤检查 ===")
        print(f"  今天 {today.strftime('%Y-%m-%d')} {weekday_cn} 为非交易日，跳过执行。")
        return

    print("=== 老曹投资助手 · 净值回撤检查 ===")
    print(f"  阈值: 跌幅 ≥ {DROP_THRESHOLD*100:.0f}% 时提醒\n")

    # 1. 读取 MA20 表
    records = read_ma20_table()
    if not records:
        print("[ERROR] 无法读取MA20表")
        sys.exit(1)
    print(f"  读取 {len(records)} 条记录\n")

    # 2. 逐一检查
    alerts = []
    for r in records:
        name = r["name"]
        d21 = r["d21"]
        h_val = r["h"]

        # 跳过无效数据
        if not name or d21 is None or h_val is None:
            continue
        if d21 <= 0 or h_val <= 0:
            continue

        drop_rate = (h_val - d21) / h_val

        if drop_rate >= DROP_THRESHOLD:
            alerts.append({
                "name": name,
                "d21": d21,
                "h": h_val,
                "drop_rate": drop_rate,
            })
            print(f"  ⚠️  {name}: D21={d21:.4f}, H={h_val:.4f}, 回撤={drop_rate*100:.2f}%")

    # 3. 结果
    if not alerts:
        print("\n✅ 无触发提醒：所有基金回撤均低于 10%。")
        return

    # 4. 构造飞书消息
    print(f"\n  共 {len(alerts)} 只基金触发提醒，发送飞书通知...\n")

    lines = [
        "⚠️ **老曹投资助手 · 净值回撤提醒**",
        "",
        f"以下 **{len(alerts)}** 只基金/股票当日净值相对 20 日最高净值回撤超过 **{DROP_THRESHOLD*100:.0f}%**：",
        "",
    ]

    for a in alerts:
        lines.append(
            f"📉 **{a['name']}**"
        )
        lines.append(
            f"　　　当日净值：{a['d21']:.4f}"
        )
        lines.append(
            f"　　　20日最高：{a['h']:.4f}"
        )
        lines.append(
            f"　　　回撤幅度：**{a['drop_rate']*100:.2f}%**"
        )
        lines.append("")

    send_feishu_msg("\n".join(lines))
    print("\n=== 回撤检查完成 ===")


if __name__ == "__main__":
    main()
