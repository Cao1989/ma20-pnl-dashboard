#!/usr/bin/env python3
"""
MA20净值表 - 每日净值获取脚本（支持增量刷新 + 飞书通知）
每半小时运行一次（17:00~22:30），只填充D21为空的基金，有进展时发飞书消息。

QDII 美股基金净值有 T+1 延迟，当当日净值未发布时，
自动使用最新已发布净值（前一交易日）填入 D21。
"""
import subprocess
import json
import sys
import os
import re
import time
import urllib.request
from datetime import date
import chinese_calendar

BASE_TOKEN = "JWJ1bTzQ0aBETsseSJqcWn7EnJe"
TABLE_BOTTOM = "tbl6QMWWCrGLbgtS"
TABLE_MA20 = "tblMcst8z8IYH72v"

FIELD_FUND_NAME_BOTTOM = "fldaynV4MN"
FIELD_FUND_NAME_MA20 = "fldS6Vtx56"
FIELD_D21 = "fldWFYu1sW"
FIELD_CODE = "fldfLmbLHe"

USER_OPEN_ID = "ou_1d2af5f7db994ab6e0151176109f5057"

# 走 K 线 API 的代码集（场内 ETF/LOF + 个股）
# 这些代码取市场收盘价，而非基金净值(IOPV)
KLINE_CODES = {
    # 个股
    "600900", "600036", "002463",
    # 场内 ETF/LOF
    "588290", "515880", "159326", "513300",
    "513650", "159611", "161130", "513090",
    "518850", "159516", "513100", "510050",
    "561780",
}

# ─── 工具函数 ─────────────────────────────────────────────

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


def send_feishu_msg(markdown_text):
    """发送飞书消息给用户（--as bot，更稳定）"""
    ok, _ = run_lark([
        "im", "+messages-send",
        "--user-id", USER_OPEN_ID,
        "--as", "bot",
        "--markdown", markdown_text,
    ], "发送飞书通知")
    if ok:
        print("  ✓ 飞书消息已发送")
    else:
        print("  ✗ 飞书消息发送失败")


# ─── 数据获取 ─────────────────────────────────────────────

def _is_valid_nav(val):
    """净值字符串是否有效（排除空值和 0 值，0 值意味着数据未发布）"""
    if not val or not str(val).strip():
        return False
    try:
        fv = float(val)
        return fv > 0.0001  # 排除 0 / 0.00 / 0.0000 等未发布标记
    except (ValueError, TypeError):
        return False


def fetch_fund_nav(code):
    """从天天基金获取净值。
    始终使用最新已发布单位净值(dwjz)，放弃估算值(gsz)。
    QDII 基金净值有 T+1 延迟，自动使用前一日已发布净值，并在消息中标注净值日期。
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
        dwjz = data.get("dwjz", "")
        name = data.get("name", "")
        jzrq = data.get("jzrq", "")  # 净值日期
        if _is_valid_nav(dwjz):
            tag = f"(净值日:{jzrq})" if jzrq else ""
            return True, float(dwjz), f"{name} 单位净值={dwjz} {tag}".strip()
        return False, None, f"无净值数据（dwjz={dwjz}）"
    except Exception as e:
        return False, None, f"API异常: {e}"


def fetch_stock_price(code):
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
            return False, None, "字段不足"
        name, price = parts[0], parts[3]
        if price and price != "0":
            return True, float(price), f"{name}({code_str}) 现价={price}"
        return False, None, "价格为空"
    except Exception as e:
        return False, None, f"API异常: {e}"


def fetch_stock_kline_close(code):
    """用 Sina K 线 API 获取最新收盘价（ETF/LOF/个股）"""
    prefix = "sh" if code.startswith(("6", "5")) else "sz"
    url = (
        f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
        f"CN_MarketData.getKLineData?symbol={prefix}{code}&scale=240&ma=no&datalen=3"
    )
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://finance.sina.com.cn",
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("gbk")
        data = json.loads(raw)
        if not data:
            return False, None, "K线返回空"
        # 取最新一条的收盘价
        latest = data[-1]
        close = latest.get("close", "")
        date = latest.get("day", "")
        if close and float(close) > 0:
            return True, float(close), f"{code} 收盘价={close} ({date})"
        return False, None, "收盘价为空"
    except Exception as e:
        return False, None, f"K线API异常: {e}"


def fetch_nav(code):
    """统一入口：场内 ETF/LOF 走 K 线取市场收盘价，场外基金走天天基金取单位净值"""
    code_str = str(code).strip()
    if not code_str:
        return False, None, "代码为空"
    # 场内 ETF/LOF 走 K 线 API
    if code_str in KLINE_CODES:
        return fetch_stock_kline_close(code_str)
    # 场外基金走天天基金 API
    return fetch_fund_nav(code_str)


# ─── 主流程 ───────────────────────────────────────────────

def read_ma20_table():
    """读取MA20净值表，返回 records 列表，每项包含 rid, name, d21_value"""
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
        result.append({"rid": record_ids[i], "name": str(name) if name else "", "d21": d21})
    return result


def read_bottom_table():
    """读取底层数据表，返回 {基金名称: 代码}"""
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


def main():
    # ─── 交易日检查 ─────────────────────────────────────────
    today = date.today()
    is_trading = chinese_calendar.is_workday(today)
    weekday_cn = ["周一","周二","周三","周四","周五","周六","周日"][today.weekday()]
    if not is_trading:
        print(f"=== MA20净值表 每日净值获取 ===")
        print(f"  今天 {today.strftime('%Y-%m-%d')} {weekday_cn} 为非交易日，跳过执行。")
        return

    print("=== MA20净值表 每日净值获取 (增量模式) ===")

    # 1. 读取 MA20 表，找出 D21 为空的记录
    print("\n[1] 读取MA20净值表，检查D21状态...")
    ma20_records = read_ma20_table()
    total = len(ma20_records)
    empty_d21 = [r for r in ma20_records if not r["d21"] or r["d21"] == ""]
    filled_d21 = [r for r in ma20_records if r["d21"] and r["d21"] != ""]
    print(f"  总计 {total} 条 | 已填 {len(filled_d21)} | 待填 {len(empty_d21)}")

    # 如果全部已填完，直接结束，不发消息
    if not empty_d21:
        print("\n✅ D21 已全部填满，无需操作。")
        return

    # 2. 读取底层数据表获取代码
    print("\n[2] 读取底层数据表...")
    fund_code_map = read_bottom_table()
    print(f"  {len(fund_code_map)} 只基金有代码")

    # 3. 对 D21 为空的基金逐个获取净值
    print(f"\n[3] 获取 {len(empty_d21)} 只待填基金的净值...")
    new_fills = []      # [(name, nav, msg)]
    still_missing = []

    for rec in empty_d21:
        name = rec["name"]
        code = fund_code_map.get(name)
        if not code:
            print(f"  ⊘ {name}: 未找到代码，跳过")
            still_missing.append(name)
            continue

        ok, nav, msg = fetch_nav(code)
        if ok:
            print(f"  ✓ {name} ({code}): {msg}")
            nav = round(nav, 4)
            # 写入飞书
            write_ok, _ = run_lark([
                "base", "+record-upsert",
                "--base-token", BASE_TOKEN,
                "--table-id", TABLE_MA20,
                "--record-id", rec["rid"],
                "--as", "user",
                "--json", json.dumps({"D21": nav}, ensure_ascii=False),
            ], f"写入 {name}")
            if write_ok:
                new_fills.append((name, nav, msg))
            else:
                still_missing.append(name)
        else:
            print(f"  ✗ {name} ({code}): {msg}")
            still_missing.append(name)
        time.sleep(0.3)

    # 4. 汇总并发送飞书消息
    newly_filled = len(new_fills)
    missing = len(still_missing) + (total - newly_filled - len(filled_d21))
    total_filled = len(filled_d21) + newly_filled

    print(f"\n[4] 汇总: 本轮新填 {newly_filled} 只, 累计 {total_filled}/{total}, 仍缺 {missing} 只")

    if newly_filled == 0 and missing > 0:
        print("  本轮无新净值获取，不发消息。")
        return

    # 构造飞书消息
    time_hour = time.localtime().tm_hour
    time_min = time.localtime().tm_min
    time_str = f"{time_hour:02d}:{time_min:02d}"

    # 详细填充信息 + QDII 备注
    fill_details_lines = []
    qdii_notes = []
    for n, v, msg in new_fills:
        line = f"  - {n}：{v}"
        fill_details_lines.append(line)
        # 若 msg 含"净值日"说明是 QDII 回退到前一交易日净值
        if "净值日" in msg:
            qdii_notes.append(f"{n}（使用前交易日净值）")

    fill_details = "\n".join(fill_details_lines)
    qdii_note_str = ""
    if qdii_notes:
        qdii_note_str = "\n\n📌 QDII 美股基金净值有 T+1 延迟，已使用前一交易日净值填充：\n  - " + "\n  - ".join(qdii_notes)

    if total_filled == total:
        # 全部完成
        msg = (
            f"✅ **老曹投资助手**\n\n"
            f"MA20净值全部获取完毕！\n\n"
            f"**时间：** {time_str}\n"
            f"**完成：** {total}/{total} 只基金\n\n"
            f"今日净值已全部填入 D21 字段。"
            f"{qdii_note_str}"
        )
    else:
        # 部分完成
        missing_names = "、".join(still_missing[:8])
        if len(still_missing) > 8:
            missing_names += f"... 等{len(still_missing)}只"

        msg = (
            f"📊 **老曹投资助手** {time_str}\n\n"
            f"**本轮新增：** {newly_filled} 只\n"
            f"{fill_details}\n\n"
            f"**累计完成：** {total_filled}/{total}\n"
            f"**仍缺失：** {missing} 只\n"
            f"  - {missing_names}\n\n"
            f"下一轮 30 分钟后继续刷新。"
            f"{qdii_note_str}"
        )

    print("\n[5] 发送飞书通知...")
    send_feishu_msg(msg)

    # 6. 同步「盈亏_日」数字字段（飞书公式→数字字段，供看板排序和显示）
    if newly_filled > 0:
        print("\n[6] 同步盈亏字段（当日盈亏公式 → 盈亏_日数字字段）...")
        sync_script = os.path.join(os.path.dirname(__file__), "sync_pnl_fields.py")
        proc_sync = subprocess.run(
            [sys.executable, sync_script],
            capture_output=True, text=True, timeout=120
        )
        if proc_sync.returncode == 0:
            print("  盈亏字段同步完成")
        else:
            print(f"  盈亏字段同步失败: {proc_sync.stderr[:200]}")

    # 7. 生成深色盈亏看板 HTML
    if newly_filled > 0:
        print("\n[7] 生成盈亏看板（深色版）...")
        dashboard_script = os.path.join(os.path.dirname(__file__), "generate_pnl_dashboard.py")
        proc = subprocess.run(
            [sys.executable, dashboard_script],
            capture_output=True, text=True, timeout=120
        )
        if proc.returncode == 0:
            print("  盈亏看板生成完成")
            for line in proc.stdout.strip().split("\n"):
                if line.startswith("✅") or line.startswith("  "):
                    print(f"  {line}")
        else:
            print(f"  盈亏看板生成失败: {proc.stderr[:200]}")

    print("\n=== 净值获取完成 ===")


if __name__ == "__main__":
    main()
