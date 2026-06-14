#!/usr/bin/env python3
"""
计算历史每日盈亏，供收益日历使用。
1. 读取底层数据表 → 获取每只基金的代码、持仓日期、持仓金额
2. 对每只基金调用历史净值API (天天基金/新浪K线)
3. 计算每日收益金额和收益率
4. 汇总全部基金 → 输出 JSON
"""
import subprocess, json, os, sys, time, urllib.request, re

BASE_TOKEN = "JWJ1bTzQ0aBETsseSJqcWn7EnJe"
TABLE_BOTTOM = "tbl6QMWWCrGLbgtS"
KLINE_CODES = {
    "600900", "600036", "002463",
    "588290", "515880", "159326", "513300",
    "513650", "159611", "161130", "513090",
    "518850", "159516", "513100", "510050",
    "561780",
}

CWD = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE = os.path.join(CWD, ".workbuddy", "history_pnl.json")
NAV_CACHE_FILE = os.path.join(CWD, ".workbuddy", "nav_cache.json")

# ─── 工具 ─────────────────────────────────────────────
def run_lark(args, label=""):
    r = subprocess.run(["lark-cli"] + args, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"  [ERROR] {label}: {r.stderr[:200]}")
        return False, ""
    return True, r.stdout

# ─── 读取底层数据表 ────────────────────────────────────
def read_bottom_table():
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
    fields = resp["fields"]
    records = resp["data"]

    # 定位字段
    idx_map = {}
    for i, fid in enumerate(field_ids):
        idx_map[fid] = i

    funds = []
    for rec in records:
        code = rec[idx_map.get("fldfLmbLHe", -1)] if "fldfLmbLHe" in idx_map else None
        name = rec[idx_map.get("fldaynV4MN", -1)] if "fldaynV4MN" in idx_map else None
        pos_date = rec[idx_map.get("fldJUuuyBU", -1)] if "fldJUuuyBU" in idx_map else None
        pos_amount = rec[idx_map.get("fldMx19A5N", -1)] if "fldMx19A5N" in idx_map else 0

        if isinstance(name, list):
            name = name[0] if name else ""
        if isinstance(code, (int, float)):
            code = str(int(code))
        code = str(code).strip() if code else ""
        name = str(name).strip() if name else ""

        # 解析持仓日期
        pos_date_str = ""
        if pos_date:
            pos_date_str = str(pos_date).strip()[:10]  # "2025-12-15"

        # 解析持仓金额
        try:
            pos_amount = float(pos_amount) if pos_amount else 0
        except (ValueError, TypeError):
            pos_amount = 0

        if name and code and pos_date_str and pos_amount > 0:
            funds.append({
                "name": name,
                "code": code,
                "pos_date": pos_date_str,
                "pos_amount": pos_amount,
            })

    # 按持仓日期排序
    funds.sort(key=lambda x: x["pos_date"])
    print(f"读取 {len(funds)} 只有效基金（有代码+持仓日期+持仓金额）")
    return funds

# ─── 历史净值获取 ──────────────────────────────────────
def fetch_fund_nav_history(code, start_date, end_date):
    """天天基金历史净值。按年度拆分为多个窗口分别请求（API限制~6个月范围）。
    返回 [(date, nav), ...] 按日期升序"""
    all_items = []
    # 将范围按年度拆分（API只返回end_date往前约6个月数据）
    start_year = int(start_date[:4])
    end_year = int(end_date[:4])
    windows = []
    for yr in range(start_year, end_year + 1):
        w_start = f"{yr}-01-01" if yr > start_year else start_date
        w_end = f"{yr}-12-31" if yr < end_year else end_date
        windows.append((w_start, w_end))
    
    for w_start, w_end in windows:
        page = 1
        EFFECTIVE_PAGE_SIZE = 20
        while True:
            url = (f"https://api.fund.eastmoney.com/f10/lsjz?"
                   f"fundCode={code}&pageIndex={page}&pageSize={EFFECTIVE_PAGE_SIZE}"
                   f"&endDate={w_end.replace('-','')}")
            try:
                req = urllib.request.Request(url, headers={
                    "User-Agent": "Mozilla/5.0",
                    "Referer": "https://fundf10.eastmoney.com/",
                })
                with urllib.request.urlopen(req, timeout=15) as resp:
                    raw = resp.read().decode("utf-8")
                data = json.loads(raw)
                if data.get("ErrCode") != 0:
                    break
                items = data.get("Data", {}).get("LSJZList", [])
                if not items:
                    break
                added = 0
                for item in items:
                    d = item.get("FSRQ", "")
                    nav = item.get("DWJZ", "")
                    # 只保留在窗口范围内的数据
                    if d and nav and w_start <= d <= w_end:
                        try:
                            nav_val = float(nav)
                            if nav_val > 0:
                                all_items.append((d, nav_val))
                                added += 1
                        except ValueError:
                            pass
                # 已到达窗口起始日或没有新增项则停止
                if added == 0 or (items[-1].get("FSRQ", "9999") < w_start):
                    break
                page += 1
                time.sleep(0.15)
            except Exception as e:
                print(f"    fund {code} window {w_start}~{w_end} page {page} error: {e}")
                break
    
    # 去重并排序
    seen = set()
    unique = []
    for d, n in sorted(all_items, key=lambda x: x[0]):
        if d not in seen:
            seen.add(d)
            unique.append((d, n))
    return unique


def fetch_stock_history(code, start_date, end_date):
    """新浪个股/ETF K线（240分钟=日线）。返回 [(date, close_price), ...]"""
    prefix = "sh" if code.startswith(("6", "5")) else "sz"
    url = (f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
           f"CN_MarketData.getKLineData?symbol={prefix}{code}&scale=240&ma=no&datalen=500")
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://finance.sina.com.cn",
        })
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("gbk")
        data = json.loads(raw)
        items = []
        for bar in data:
            d = bar.get("day", "")
            close = bar.get("close", "")
            if d and close and d >= start_date and d <= end_date:
                try:
                    close_val = float(close)
                    if close_val > 0:
                        items.append((d, close_val))
                except ValueError:
                    pass
        items.sort(key=lambda x: x[0])
        return items
    except Exception as e:
        print(f"    stock {code} error: {e}")
        return []


def fetch_nav_history(code, start_date, end_date):
    """统一入口"""
    code_str = str(code).strip()
    if code_str in KLINE_CODES:
        return fetch_stock_history(code_str, start_date, end_date)
    return fetch_fund_nav_history(code_str, start_date, end_date)


# ─── 计算每日盈亏 ──────────────────────────────────────
def calc_daily_pnl(funds):
    """
    对每只基金：
      每日盈亏 = 持仓金额 × (当日净值/前日净值 - 1)
    汇总全部基金得到每日总盈亏。
    返回 { "2026-06-12": {"amount": 1247.5, "rate": 0.52}, ... }
    
    追加模式：如果 history_pnl.json 已存在，只计算新日期，保护历史数据。
    """
    # 检查现有历史数据，决定计算起始日期
    existing_history = {}
    calc_start_date = None  # None = 全量计算
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE) as f:
            existing_history = json.load(f)
        existing_dates = sorted(existing_history.keys())
        if existing_dates:
            # 从最后一个已知日期的前一天开始（需要前值计算delta）
            from datetime import datetime as dt, timedelta
            last_dt = dt.strptime(existing_dates[-1], "%Y-%m-%d")
            calc_start_date = (last_dt - timedelta(days=1)).strftime("%Y-%m-%d")
            print(f"追加模式: 保护 {len(existing_dates)} 天历史，从 {calc_start_date} 开始计算")

    # 加载净值缓存
    nav_cache = {}
    if os.path.exists(NAV_CACHE_FILE):
        with open(NAV_CACHE_FILE) as f:
            nav_cache = json.load(f)

    end_date = time.strftime("%Y-%m-%d")
    # 最早持仓日期
    earliest = min(f["pos_date"] for f in funds) if funds else end_date

    # 收集所有基金的每日净值
    fund_navs = {}  # code -> [(date, nav), ...]
    total_funds = len(funds)
    new_funds_count = 0

    for i, fund in enumerate(funds):
        code = fund["code"]
        cache_key = f"{code}_{fund['pos_date']}"
        
        if calc_start_date and cache_key in nav_cache:
            # 已有基金：只获取增量数据
            existing_navs = nav_cache[cache_key]
            print(f"[{i+1}/{total_funds}] {fund['name']}({code}) 增量更新...", end=" ")
            
            # 获取 calc_start_date 之后的新净值
            new_navs = fetch_nav_history(code, calc_start_date, end_date)
            
            # 合并：已有数据 + 新数据（去重）
            existing_dates_set = {d for d, _ in existing_navs}
            merged = list(existing_navs)
            for d, n in new_navs:
                if d not in existing_dates_set:
                    merged.append((d, n))
            merged.sort(key=lambda x: x[0])
            
            fund_navs[code] = merged
            nav_cache[cache_key] = merged
            print(f"({len(existing_navs)}→{len(merged)}条)")
            
        else:
            # 新基金或无缓存：全量获取
            print(f"[{i+1}/{total_funds}] {fund['name']}({code}) 全量获取...", end=" ")
            navs = fetch_nav_history(code, fund["pos_date"], end_date)
            fund_navs[code] = navs
            nav_cache[cache_key] = navs
            print(f"({len(navs)}条)")
            if calc_start_date:
                new_funds_count += 1
        
        time.sleep(0.2)

    # 保存缓存
    os.makedirs(os.path.dirname(NAV_CACHE_FILE), exist_ok=True)
    with open(NAV_CACHE_FILE, "w") as f:
        json.dump(nav_cache, f, ensure_ascii=False)

    # 构建 code -> daily_nav 映射
    code_nav_map = {}
    for code, nav_list in fund_navs.items():
        code_nav_map[code] = {d: n for d, n in nav_list}

    # 所有有净值的日期（并集）
    all_dates = set()
    for nav_map in code_nav_map.values():
        all_dates.update(nav_map.keys())
    all_dates = sorted(all_dates)

    # 持仓金额映射
    fund_map = {f["code"]: f for f in funds}

    # 计算每日总盈亏（只计算新日期）
    daily_pnl = {}
    if existing_history and calc_start_date:
        # 先继承已有历史
        daily_pnl = dict(existing_history)
        existing_date_set = set(existing_history.keys())

    for date in all_dates:
        # 跳过已有日期（已在 history 中）
        if date in daily_pnl and not new_funds_count:
            continue

        total_amount = 0.0
        total_cost = 0.0

        for code, f in fund_map.items():
            nav_map = code_nav_map.get(code, {})
            today_nav = nav_map.get(date)
            if today_nav is None:
                continue

            # 检查是否在持仓日期之后
            if date < f["pos_date"]:
                continue

            # 找前一个交易日净值
            prev_dates = [d for d in sorted(nav_map.keys()) if d < date]
            if prev_dates:
                prev_nav = nav_map[prev_dates[-1]]
            else:
                prev_nav = today_nav

            if prev_nav and prev_nav > 0:
                day_return_rate = (today_nav - prev_nav) / prev_nav
                day_pnl = f["pos_amount"] * day_return_rate
                total_amount += day_pnl
                total_cost += f["pos_amount"]

        if total_cost > 0:
            pnl_entry = {
                "amount": round(total_amount, 2),
                "rate": round(total_amount / total_cost * 100, 4),
            }
            # 如果是新基金导致的已有日期更新，叠加到现有值
            if date in daily_pnl:
                old_entry = daily_pnl[date]
                old_cost = total_cost  # 当日持仓金额已包含新旧基金
                daily_pnl[date] = pnl_entry  # 用全量计算结果覆盖（包含新基金）
            else:
                daily_pnl[date] = pnl_entry

    # 按日期排序
    daily_pnl = {k: daily_pnl[k] for k in sorted(daily_pnl.keys())}

    if existing_history and calc_start_date:
        new_dates = [d for d in daily_pnl if d not in existing_history]
        print(f"追加完成: 新增 {len(new_dates)} 个交易日")
        if new_funds_count:
            print(f"  {new_funds_count} 只新基金已纳入全部历史数据")

    return daily_pnl


# ─── 主流程 ────────────────────────────────────────────
def main():
    print("=== 历史盈亏计算 ===")
    funds = read_bottom_table()
    if not funds:
        print("没有有效基金数据")
        return

    daily_pnl = calc_daily_pnl(funds)
    print(f"\n计算完成，共 {len(daily_pnl)} 个交易日")

    # 输出统计
    dates = sorted(daily_pnl.keys())
    if dates:
        print(f"日期范围: {dates[0]} ~ {dates[-1]}")
        total_pnl = sum(v["amount"] for v in daily_pnl.values())
        print(f"累计盈亏: {total_pnl:+,.2f}")

    os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
    with open(CACHE_FILE, "w") as f:
        json.dump(daily_pnl, f, ensure_ascii=False, indent=2)
    print(f"\n结果已保存: {CACHE_FILE}")


if __name__ == "__main__":
    main()
