#!/usr/bin/env python3
"""
MA20净值表 - 每日净值获取（云端版）
用 feishu_api.py 替代 lark-cli，可直接在 GitHub Actions 运行。

每半小时运行一次（17:00~22:30），只填充 D21 为空的基金。
"""
import json
import sys
import os
import re
import time
import urllib.request
from datetime import date

# 添加项目根目录到 path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from feishu_api import base_list_records, base_update_record, send_feishu_msg

# 日期判断：用 chinese_calendar；若未安装则降级为周一到周五
try:
    import chinese_calendar
    HAS_CHINESE_CALENDAR = True
except ImportError:
    HAS_CHINESE_CALENDAR = False

BASE_TOKEN = "JWJ1bTzQ0aBETsseSJqcWn7EnJe"
TABLE_BOTTOM = "tbl6QMWWCrGLbgtS"
TABLE_MA20 = "tblMcst8z8IYH72v"

FIELD_FUND_NAME_BOTTOM = "fldaynV4MN"
FIELD_FUND_NAME_MA20 = "fldS6Vtx56"
FIELD_D21 = "fldWFYu1sW"
FIELD_CODE = "fldfLmbLHe"

KLINE_CODES = {
    "600900", "600036", "002463",
    "588290", "515880", "159326", "513300",
    "513650", "159611", "161130", "513090",
    "518850", "159516", "513100", "510050",
    "561780",
}

# ─── 工具函数 ─────────────────────────────────────────────

def is_trading_day():
    today = date.today()
    if HAS_CHINESE_CALENDAR:
        return chinese_calendar.is_workday(today)
    return today.weekday() < 5  # Mon-Fri


def _is_valid_nav(val):
    if not val or not str(val).strip():
        return False
    try:
        return float(val) > 0.0001
    except (ValueError, TypeError):
        return False


def fetch_fund_nav(code):
    """天天基金 API 获取净值"""
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
        jzrq = data.get("jzrq", "")
        if _is_valid_nav(dwjz):
            tag = f"(净值日:{jzrq})" if jzrq else ""
            return True, float(dwjz), f"{name} 单位净值={dwjz} {tag}".strip()
        return False, None, f"无净值数据（dwjz={dwjz}）"
    except Exception as e:
        return False, None, f"API异常: {e}"


def fetch_stock_kline_close(code):
    """新浪 K 线 API 获取收盘价"""
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
        latest = data[-1]
        close = latest.get("close", "")
        day = latest.get("day", "")
        if close and float(close) > 0:
            return True, float(close), f"{code} 收盘价={close} ({day})"
        return False, None, "收盘价为空"
    except Exception as e:
        return False, None, f"K线API异常: {e}"


def fetch_nav(code):
    code_str = str(code).strip()
    if code_str in KLINE_CODES:
        return fetch_stock_kline_close(code_str)
    return fetch_fund_nav(code_str)


# ─── 读取表格 ─────────────────────────────────────────────

def read_ma20_table():
    """读取MA20净值表，返回 records 列表"""
    resp = base_list_records(BASE_TOKEN, TABLE_MA20)
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
            "d21": d21,
        })
    return result


def read_bottom_table():
    """读取底层数据表，返回 {基金名称: 代码}"""
    resp = base_list_records(BASE_TOKEN, TABLE_BOTTOM)
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


# ─── 主流程 ───────────────────────────────────────────────

def main():
    if not is_trading_day():
        print(f"非交易日，跳过执行。")
        return

    print("=== MA20净值表 每日净值获取（云端） ===")

    # 1. 读取 MA20 表
    print("\n[1] 读取MA20净值表，检查D21状态...")
    ma20_records = read_ma20_table()
    total = len(ma20_records)
    empty_d21 = [r for r in ma20_records if not r["d21"] or r["d21"] == ""]
    filled_d21 = [r for r in ma20_records if r["d21"] and r["d21"] != ""]
    print(f"  总计 {total} 条 | 已填 {len(filled_d21)} | 待填 {len(empty_d21)}")

    if not empty_d21:
        print("\n✅ D21 已全部填满，无需操作。")
        return

    # 2. 读取底层数据表
    print("\n[2] 读取底层数据表...")
    fund_code_map = read_bottom_table()
    print(f"  {len(fund_code_map)} 只基金有代码")

    # 3. 获取净值
    print(f"\n[3] 获取 {len(empty_d21)} 只待填基金的净值...")
    new_fills = []
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
            nav = round(nav, 4)
            print(f"  ✓ {name} ({code}): {msg}")
            try:
                base_update_record(BASE_TOKEN, TABLE_MA20, rec["rid"], {
                    "D21": nav,
                })
                new_fills.append((name, nav, msg))
            except Exception as e:
                print(f"  ✗ 写入失败: {e}")
                still_missing.append(name)
        else:
            print(f"  ✗ {name} ({code}): {msg}")
            still_missing.append(name)
        time.sleep(0.3)

    # 4. 汇总
    newly_filled = len(new_fills)
    total_filled = len(filled_d21) + newly_filled
    missing = len(still_missing)
    print(f"\n[4] 汇总: 本轮新填 {newly_filled} 只, 累计 {total_filled}/{total}, 仍缺 {missing} 只")

    if newly_filled == 0 and missing > 0:
        return

    # 5. 发送飞书消息
    time_str = time.strftime("%H:%M", time.localtime())
    fill_details = "\n".join([f"  - {n}：{v}" for n, v, _ in new_fills])

    if total_filled == total:
        msg = (
            f"✅ **老曹投资助手**\n\n"
            f"MA20净值全部获取完毕！\n\n"
            f"**时间：** {time_str}\n"
            f"**完成：** {total}/{total} 只基金\n\n"
            f"今日净值已全部填入 D21 字段。"
        )
    else:
        missing_names = "、".join(still_missing[:8])
        msg = (
            f"📊 **老曹投资助手** {time_str}\n\n"
            f"**本轮新增：** {newly_filled} 只\n"
            f"{fill_details}\n\n"
            f"**累计完成：** {total_filled}/{total}\n"
            f"**仍缺失：** {missing} 只\n"
            f"  - {missing_names}\n\n"
            f"下一轮 30 分钟后继续刷新。"
        )

    print("\n[5] 发送飞书通知...")
    try:
        send_feishu_msg(msg)
    except Exception as e:
        print(f"  飞书消息发送失败: {e}")

    print("\n=== 净值获取完成 ===")


if __name__ == "__main__":
    main()
