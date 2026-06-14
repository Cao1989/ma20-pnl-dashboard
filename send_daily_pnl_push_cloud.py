#!/usr/bin/env python3
"""
23:00 每日盈亏简报推送到飞书 IM（云端版）
"""
import json
import os
import sys
import subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from feishu_api import send_feishu_msg

CWD = os.path.dirname(os.path.abspath(__file__))


def clean_name(n):
    s = str(n)
    if s.startswith("['") and s.endswith("']"):
        return s[2:-2]
    return s


def fmt_pnl(v):
    sign = "+" if v >= 0 else ""
    return f"{sign}¥{abs(v):,.0f}"


def fmt_rate(r):
    sign = "+" if r >= 0 else ""
    return f"{sign}{r:.2f}%"


def main():
    # 1. 导出最新数据
    print("导出盈亏数据...")
    proc = subprocess.run(
        [sys.executable, os.path.join(CWD, "export_pnl_data_cloud.py")],
        capture_output=True, text=True, timeout=120
    )
    print(proc.stdout)
    if proc.returncode != 0:
        print(f"[ERROR] 数据导出失败: {proc.stderr}")
        sys.exit(1)

    json_path = os.path.join(CWD, ".workbuddy", "pnl_data.json")
    with open(json_path) as f:
        data = json.load(f)

    total_day = data["total_day_pnl"]
    total_all = data["total_all_pnl"]
    total_cost = data.get("total_cost", 0)

    total_day_rate = (total_day / total_cost * 100) if total_cost else 0
    total_all_rate = (total_all / total_cost * 100) if total_cost else 0

    day_up = [(clean_name(x["基金名称"]), x["盈亏_日"], x.get("日盈亏率", 0))
              for x in data["day_sorted"] if x["盈亏_日"] > 0]
    day_down = [(clean_name(x["基金名称"]), x["盈亏_日"], x.get("日盈亏率", 0))
                for x in data["day_sorted"] if x["盈亏_日"] < 0]

    top3_up = day_up[:3]
    top3_down = day_down[-3:]

    emoji = "🟢" if total_day < 0 else "🔴"
    lines = [
        f"{emoji} **每日净值简报**",
        "",
        f"**今日总盈亏：{fmt_pnl(total_day)}**  ({fmt_rate(total_day_rate)})",
        f"**投资以来：{fmt_pnl(total_all)}**  ({fmt_rate(total_all_rate)})",
        "",
    ]

    if top3_up:
        lines.append("📈 **涨幅前三**")
        for i, (name, val, rate) in enumerate(top3_up, 1):
            lines.append(f"  {i}. {name}  {fmt_pnl(val)}  ({fmt_rate(rate)})")
        lines.append("")

    if top3_down:
        lines.append("📉 **跌幅前三**")
        for i, (name, val, rate) in enumerate(top3_down, 1):
            lines.append(f"  {i}. {name}  {fmt_pnl(val)}  ({fmt_rate(rate)})")
        lines.append("")

    lines.append("[→ 查看完整盈亏看板](https://befbde6378d64f398052798c82318ad9.app.codebuddy.work/)")

    markdown = "\n".join(lines)

    # 2. 发送飞书消息
    try:
        send_feishu_msg(markdown)
        print("推送成功！")
    except Exception as e:
        print(f"[ERROR] 推送失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
