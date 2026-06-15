#!/usr/bin/env python3
"""
盘中实时净值获取脚本（交易时段每5分钟运行）

数据源：
- 场内品种(KLINE_CODES): 新浪 hq.sinajs.cn 实时行情
- 场外基金(OTC): 天天基金 fundgz.1234567.com.cn 预估净值(gsz)

写入 MA20 净值表 D21 字段，随后触发看板刷新 + CloudStudio 部署。
运行时段: 仅交易日 09:30-15:00（UTC+8）
"""
import subprocess
import json
import sys
import os
import re
import time
import urllib.request
from datetime import date, datetime, timezone, timedelta
import chinese_calendar

BEIJING_TZ = timezone(timedelta(hours=8))

BASE_TOKEN = "JWJ1bTzQ0aBETsseSJqcWn7EnJe"
TABLE_BOTTOM = "tbl6QMWWCrGLbgtS"
TABLE_MA20 = "tblMcst8z8IYH72v"

FIELD_FUND_NAME_BOTTOM = "fldaynV4MN"
FIELD_FUND_NAME_MA20 = "fldS6Vtx56"
FIELD_D21 = "fldWFYu1sW"
FIELD_CODE = "fldfLmbLHe"

# 走新浪实时行情 API 的品种（场内 ETF/LOF + 个股）
KLINE_CODES = {
    "600900", "600036", "002463",
    "588290", "515880", "159326", "513300",
    "513650", "159611", "161130", "513090",
    "518850", "159516", "513100", "510050",
    "561780",
}

# ─── lark-cli 封装 ─────────────────────────────────────────

def get_lark_cli():
    r = subprocess.run(["which", "lark-cli"], capture_output=True, text=True)
    if r.returncode == 0 and r.stdout.strip():
        return "lark-cli"
    for c in ["/opt/homebrew/bin/lark-cli", "/usr/local/bin/lark-cli"]:
        if os.path.exists(c):
            return c
    raise RuntimeError("找不到 lark-cli")


def run_lark(args, label=""):
    cli = get_lark_cli()
    cmd = [cli] + args
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"  [ERROR] {label}: {r.stderr[:200]}")
        return False, ""
    return True, r.stdout


# ─── 实时价格获取 ───────────────────────────────────────────

def fetch_stock_realtime(code):
    """
    新浪实时行情 API — 获取场内品种当前价
    返回: (success, price, detail_msg)
    """
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
            return False, None, f"新浪返回格式异常"
        data_part = raw.split("=", 1)[1].strip().strip('"').rstrip(";")
        parts = data_part.split(",")
        if len(parts) < 4:
            return False, None, f"字段不足({len(parts)})"
        name = parts[0]
        price = parts[3]  # 当前价
        if price and float(price) > 0:
            return True, float(price), f"{name} 现价={price}"
        return False, None, f"价格为空({price})"
    except Exception as e:
        return False, None, f"新浪API异常: {e}"


def fetch_otc_estimated_nav(code):
    """
    天天基金预估净值 API — 获取场外基金盘中预估净值(gsz)
    返回: (success, price, detail_msg)
    """
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
        gsz = data.get("gsz", "")      # 预估净值
        dwjz = data.get("dwjz", "")    # 已发布净值
        gszzl = data.get("gszzl", "")  # 预估涨幅%
        jzrq = data.get("jzrq", "")    # 净值日期

        # 优先用预估净值(gsz)，无效则回退到已发布净值(dwjz)
        if gsz and float(gsz) > 0.0001:
            tag = f"(预估)" if gszzl else ""
            return True, float(gsz), f"{name} 预估净值={gsz}{tag}"
        if dwjz and float(dwjz) > 0.0001:
            return True, float(dwjz), f"{name} 已发布净值={dwjz}({jzrq})"
        return False, None, f"无有效净值(gsz={gsz}, dwjz={dwjz})"
    except Exception as e:
        return False, None, f"天天基金API异常: {e}"


def fetch_realtime(code):
    """统一入口"""
    code_str = str(code).strip()
    if not code_str:
        return False, None, "代码为空"
    if code_str in KLINE_CODES:
        return fetch_stock_realtime(code_str)
    return fetch_otc_estimated_nav(code_str)


# ─── 飞书读写 ───────────────────────────────────────────────

def read_bottom_table():
    """读取底层数据表 → {基金名称: 代码}"""
    ok, stdout = run_lark([
        "base", "+record-list",
        "--base-token", BASE_TOKEN,
        "--table-id", TABLE_BOTTOM,
        "--as", "user", "--format", "json",
    ], "读取底层数据表")
    if not ok:
        sys.exit(1)
    resp = json.loads(stdout)["data"]
    field_ids = resp["field_id_list"]
    records = resp["data"]

    name_pos = code_pos = None
    for i, fid in enumerate(field_ids):
        if fid == FIELD_FUND_NAME_BOTTOM:
            name_pos = i
        if fid == FIELD_CODE:
            code_pos = i

    if name_pos is None or code_pos is None:
        print("[ERROR] 底层数据表字段定位失败")
        sys.exit(1)

    result = {}
    for rec in records:
        name = rec[name_pos] if name_pos < len(rec) else None
        code = rec[code_pos] if code_pos < len(rec) else None
        if isinstance(name, list):
            name = name[0] if name else None
        if name and code:
            result[str(name)] = str(code).strip()
    return result


def read_ma20_table():
    """读取MA20表 → [{rid, name, d21_old}, ...]"""
    ok, stdout = run_lark([
        "base", "+record-list",
        "--base-token", BASE_TOKEN,
        "--table-id", TABLE_MA20,
        "--as", "user", "--format", "json",
    ], "读取MA20净值表")
    if not ok:
        sys.exit(1)
    resp = json.loads(stdout)["data"]
    field_ids = resp["field_id_list"]
    records = resp["data"]
    record_ids = resp["record_id_list"]

    name_pos = d21_pos = None
    for i, fid in enumerate(field_ids):
        if fid == FIELD_FUND_NAME_MA20:
            name_pos = i
        if fid == FIELD_D21:
            d21_pos = i

    if name_pos is None or d21_pos is None:
        print("[ERROR] MA20表字段定位失败")
        sys.exit(1)

    result = []
    for i, rec in enumerate(records):
        name = rec[name_pos] if name_pos < len(rec) else None
        d21 = rec[d21_pos] if d21_pos < len(rec) else None
        if isinstance(name, list):
            name = name[0] if name else None
        result.append({
            "rid": record_ids[i],
            "name": str(name) if name else "",
            "d21_old": d21,
        })
    return result


def write_d21(rid, nav):
    """写入单个记录D21字段"""
    ok, _ = run_lark([
        "base", "+record-upsert",
        "--base-token", BASE_TOKEN,
        "--table-id", TABLE_MA20,
        "--record-id", rid,
        "--as", "user",
        "--json", json.dumps({"D21": nav}, ensure_ascii=False),
    ], f"写入 D21={nav}")
    return ok


def write_d21_batch(records):
    """逐条写入D21"""
    success = 0
    for rid, nav in records:
        ok, _ = run_lark([
            "base", "+record-upsert",
            "--base-token", BASE_TOKEN,
            "--table-id", TABLE_MA20,
            "--record-id", rid,
            "--as", "user",
            "--json", json.dumps({"D21": nav}, ensure_ascii=False),
        ], f"写入 D21={nav}")
        if ok:
            success += 1
        else:
            print(f"    ⚠ 写入失败 rid={rid}")
        time.sleep(0.15)  # 频率控制
    return success == len(records)


# ─── 主流程 ────────────────────────────────────────────────

def main():
    # ─── 运行时段检查 ──────────────────────────────────────
    now = datetime.now(BEIJING_TZ)
    today = now.date()
    current_hour = now.hour
    current_min = now.minute

    # 交易日检查
    is_trading = chinese_calendar.is_workday(today)
    if not is_trading:
        print(f"[跳过] {today} 非交易日")
        return

    # 时间窗口检查 (09:25-15:05, 留余量)
    current_minutes = current_hour * 60 + current_min
    if current_minutes < 565 or current_minutes > 905:  # 09:25-15:05
        print(f"[跳过] {now.strftime('%H:%M')} 不在交易时段 (09:30-15:00)")
        return

    print(f"=== 盘中实时净值获取 {now.strftime('%Y-%m-%d %H:%M:%S')} ===\n")

    # 1. 读取两张表
    print("[1] 读取飞书多维表格...")
    fund_code_map = read_bottom_table()
    ma20_records = read_ma20_table()
    print(f"    底层表: {len(fund_code_map)} 只基金")
    print(f"    MA20表: {len(ma20_records)} 条记录")

    # 2. 实时获取价格
    print(f"\n[2] 获取盘中实时价格...")
    new_values = []    # [(rid, nav)]
    updated = 0
    skipped = 0
    failed = 0

    for rec in ma20_records:
        name = rec["name"]
        code = fund_code_map.get(name)
        if not code:
            skipped += 1
            continue

        ok, price, msg = fetch_realtime(code)
        if ok:
            price = round(price, 4)
            old_val = rec["d21_old"]
            # 只写入有变化的（减少飞书API压力）
            try:
                old_num = float(old_val) if old_val and str(old_val).strip() else None
            except (ValueError, TypeError):
                old_num = None

            if old_num is not None and abs(old_num - price) < 0.001:
                # 价格未变，跳过
                skipped += 1
                continue

            new_values.append((rec["rid"], price))
            updated += 1
            old_str = f" (旧:{old_num})" if old_num else ""
            print(f"    ✓ {name:20s} {code:>8s} → {price:>10.4f}{old_str}")
        else:
            failed += 1
            print(f"    ✗ {name:20s} {code:>8s}: {msg}")

        time.sleep(0.1)  # 频率控制

    print(f"\n    汇总: 更新 {updated} | 未变 {skipped} | 失败 {failed}")

    # 3. 批量写入
    if new_values:
        print(f"\n[3] 写入 MA20 表 D21...")
        if write_d21_batch(new_values):
            print(f"    ✅ {len(new_values)} 条 D21 已更新")
        else:
            print(f"    ❌ 写入失败")
            return
    else:
        print(f"\n[3] 无数据变化，跳过写入")
        return

    # 4. 生成盈亏看板
    print(f"\n[4] 生成盈亏看板...")
    dashboard_script = os.path.join(os.path.dirname(__file__), "generate_pnl_dashboard.py")
    proc = subprocess.run(
        [sys.executable, dashboard_script],
        capture_output=True, text=True, timeout=120
    )
    if proc.returncode == 0:
        print("    ✅ 看板生成完成")
        for line in proc.stdout.strip().split("\n"):
            if line.strip():
                print(f"    {line}")
    else:
        print(f"    ❌ 看板生成失败: {proc.stderr[:200]}")
        return

    # 5. 复制到部署目录
    deploy_dir = os.path.join(os.path.dirname(__file__), ".deploy-dashboard")
    html_path = os.path.join(os.path.dirname(__file__), "pnl_dashboard.html")
    deploy_html = os.path.join(deploy_dir, "index.html")
    os.makedirs(deploy_dir, exist_ok=True)
    import shutil
    shutil.copy(html_path, deploy_html)
    print(f"\n[5] 已复制到 .deploy-dashboard/")
    print(f"=== 盘中刷新完成 {now.strftime('%H:%M:%S')} ===")


if __name__ == "__main__":
    main()
