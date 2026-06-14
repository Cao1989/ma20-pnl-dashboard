#!/usr/bin/env python3
"""生成盈亏看板 HTML v12（大指标卡：持仓总市值+目标+当日/总盈亏）"""
import subprocess, json, os, sys, time

CWD = os.path.dirname(os.path.abspath(__file__))

# ─── 1. 导出最新盈亏数据 ─────────────────────────────────
export_script = os.path.join(CWD, "export_pnl_data_cloud.py")
result = subprocess.run([sys.executable, export_script], capture_output=True, text=True, timeout=120)
print(result.stdout)

pnl_path = os.path.join(CWD, ".workbuddy", "pnl_data.json")
with open(pnl_path) as f:
    data = json.load(f)

# ─── 2. 加载历史盈亏数据 ─────────────────────────────────
history_path = os.path.join(CWD, ".workbuddy", "history_pnl.json")
history_data = {}
if os.path.exists(history_path):
    with open(history_path) as f:
        history_data = json.load(f)
    print(f"加载历史盈亏: {len(history_data)} 个交易日")

# ─── 3. P&L 账本：总盈亏永久保留（理财级数据完整性）─────
ledger_path = os.path.join(CWD, ".workbuddy", "pnl_ledger.json")
total_all_pnl_raw = data["total_all_pnl"]
total_cost = data.get("total_cost", 0)

# 构建当前基金快照（用于检测申赎）
current_fund_snapshot = {}
for r in data.get("all_records", []):
    rid = r.get("record_id", "")
    if rid:
        current_fund_snapshot[rid] = {
            "name": str(r.get("基金名称", "?")),
            "total_pnl": r.get("盈亏_总", 0),
            "pos_amount": r.get("持仓金额", 0),
            "position": r.get("仓位", ""),
        }

# 加载或初始化账本
if os.path.exists(ledger_path):
    with open(ledger_path) as f:
        ledger = json.load(f)
else:
    ledger = {"realized_pnl": 0, "fund_snapshots": {}, "last_updated": ""}

# 检测已清仓/卖出基金 → 锁定已实现盈亏
removed_pnl = 0
if ledger.get("fund_snapshots"):
    for rid, snap in ledger["fund_snapshots"].items():
        if rid not in current_fund_snapshot:
            removed_pnl += snap.get("total_pnl", 0)
            print(f"  📤 检测到已清仓: {snap.get('name','?')} (锁定盈亏 {snap.get('total_pnl',0):+,.2f})")

ledger["realized_pnl"] += removed_pnl
ledger["fund_snapshots"] = current_fund_snapshot
ledger["last_updated"] = time.strftime("%Y-%m-%d")

# 显示总盈亏 = 飞书当前浮盈 + 已实现盈亏
display_total_all_pnl = total_all_pnl_raw + ledger["realized_pnl"]
display_total_all_rate = round((display_total_all_pnl / total_cost * 100) if total_cost else 0, 2)

# 保存账本
with open(ledger_path, "w") as f:
    json.dump(ledger, f, ensure_ascii=False, indent=2)

print(f"  💰 总盈亏: 飞书浮盈 {total_all_pnl_raw:+,.2f} + 已实现 {ledger['realized_pnl']:+,.2f} = {display_total_all_pnl:+,.2f}")

# ─── 4. 增量更新历史：仅覆盖最新交易日 ──────────────────
total_day_rate = round((data["total_day_pnl"] / total_cost * 100) if total_cost else 0, 2)
today_feishu_rate = total_day_rate

if history_data:
    latest_date = max(history_data.keys())
    history_data[latest_date] = {
        "amount": round(data["total_day_pnl"], 2),
        "rate": today_feishu_rate,
    }
    print(f"增量同步: 最后交易日 {latest_date} 已用飞书数据覆盖")

# 追加新交易日
from datetime import datetime, timedelta
today_str = time.strftime("%Y-%m-%d")
if today_str not in history_data:
    wd = datetime.strptime(today_str, "%Y-%m-%d").weekday()
    if wd < 5:
        history_data[today_str] = {
            "amount": round(data["total_day_pnl"], 2),
            "rate": today_feishu_rate,
        }
        print(f"新交易日: {today_str} 已追加")

# ─── 5. 工具函数 ─────────────────────────────────────────
def clean_name(n):
    s = str(n)
    if s.startswith("['") and s.endswith("']"):
        return s[2:-2]
    return s

# ─── 6. 仓位 SVG 图标 ────────────────────────────────────
POSITION_SVGS = {
    "战略仓": '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>',
    "媳妇":   '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="8" r="4"/><path d="M4 22c0-4.4 3.6-8 8-8s8 3.6 8 8"/></svg>',
    "乔治":   '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="7" r="4"/><path d="M5.5 21c1.5-4 4-6 6.5-6s5 2 6.5 6"/><circle cx="10" cy="10" r="1" fill="currentColor" stroke="none"/><circle cx="14" cy="10" r="1" fill="currentColor" stroke="none"/></svg>',
    "佩奇":   '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="7" r="4"/><path d="M5.5 21c1.5-4 4-6 6.5-6s5 2 6.5 6"/><circle cx="10" cy="10" r="1" fill="currentColor" stroke="none"/><circle cx="14" cy="10" r="1" fill="currentColor" stroke="none"/><path d="M12 11v5"/><path d="M9 16l3 3 3-3"/></svg>',
    "战术":   '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.5" fill="currentColor" stroke="none"/></svg>',
    "高增长": '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 17 9 11 13 15 21 7"/><path d="M17 5v3h3"/></svg>',
    "压舱石": '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="5" r="3"/><line x1="12" y1="14" x2="12" y2="22"/><path d="M8 18h8"/></svg>',
}
DEFAULT_SVG = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="12" cy="12" r="10"/></svg>'

# 小眼睛 SVG 图标
EYE_OPEN_SVG = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>'
EYE_CLOSED_SVG = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/></svg>'

# ─── 7. 仓位折叠菜单 ─────────────────────────────────────
# 计划占比（仓位内各基金的目标配置%，用户后续提供）
PLAN_RATIO = {
    "佩奇": {
        "中证A500": 50.0,
        "标普500南方": 50.0,
    },
    "乔治": {
        "易方达纳指LOF": 49.0,
        "宝盈纳指100": 26.0,
        "华夏纳指100": 26.0,
    },
    "媳妇": {
        "中证红利低波": 50.0,
        "招商银行": 25.0,
        "长江电力": 25.0,
    },
    "战略仓": {
        "景颐丰利": 28.0,
        "沪深300": 22.0,
        "通信ETF": 15.0,
        "科创芯片": 10.0,
        "东方人工智能": 8.0,
        "广发全球精选": 8.0,
        "黄金ETF": 5.0,
    },
}
# 不显示计划占比/再平衡的仓位
NO_PLAN_POSITIONS = {"战术", "高增长", "压舱石"}


total_cost = data.get("total_cost", 1)

# 补全每只基金的盈亏率（如果 pnl_data.json 里没有）
for r in data.get("all_records", []):
    cost = r.get("持仓金额", 0) or 0
    if "日盈亏率" not in r or not r.get("日盈亏率"):
        r["日盈亏率"] = round((r.get("盈亏_日", 0) / cost * 100) if cost else 0, 2)
    if "总盈亏率" not in r or not r.get("总盈亏率"):
        r["总盈亏率"] = round((r.get("盈亏_总", 0) / cost * 100) if cost else 0, 2)

# 按仓位分组基金
pos_funds = {}
for item in data.get("all_records", []):
    pos = item.get("仓位", "未知")
    if pos not in pos_funds:
        pos_funds[pos] = []
    pos_funds[pos].append(item)

position_cards = ""
for ps in data.get("position_summary", []):
    pos = ps['仓位']
    svg = POSITION_SVGS.get(pos, DEFAULT_SVG)
    pos_pct = round(ps.get("持仓金额", 0) / total_cost * 100, 1) if total_cost else 0
    all_cls  = "up" if ps["总盈亏"] >= 0 else "down"
    all_sign = "" if ps["总盈亏"] >= 0 else ""
    all_rate_sign = "" if ps["总盈亏率"] >= 0 else ""

    # 该仓位下的基金列表（按持有占比从高到低排序）
    funds_in_pos = pos_funds.get(pos, [])
    pos_total_amt = ps.get("持仓金额", 1) or 1

    funds_sorted = []
    for item in funds_in_pos:
        famt = round(item.get("持仓金额", 0), 2)
        favt_pct = round(famt / pos_total_amt * 100, 1) if pos_total_amt else 0
        funds_sorted.append((item, favt_pct))
    funds_sorted.sort(key=lambda x: x[1], reverse=True)

    fund_rows = ""
    for item, favt_pct in funds_sorted:
        fname = clean_name(item["基金名称"])
        is_inner = item.get("场内场外", "") == "场内ETF/LOF/股票"
        famt = round(item.get("持仓金额", 0), 2)
        # 持仓金额为0则不显示
        if famt <= 0:
            continue
        fpnl = round(item.get("盈亏_总", 0), 2)
        frate = round(item.get("总盈亏率", 0), 2)
        # 计划占比（从PLAN_RATIO取，缺省为0）
        plan_pct = PLAN_RATIO.get(pos, {}).get(item["基金名称"], 0)
        rebal_pct = round(plan_pct - favt_pct, 1)
        rebal_cls = "up" if rebal_pct >= 0 else "down"
        rebal_sign = "+" if rebal_pct >= 0 else ""

        fpnl_cls = "up" if fpnl >= 0 else "down"
        fpnl_sign = "" if fpnl >= 0 else ""
        frate_sign = "+" if frate >= 0 else ""

        # 战术/高增长/压舱石不显示计划占比和再平衡
        if pos in NO_PLAN_POSITIONS:
            ratios_html = f'<span class="f-ratio-item">持有 {favt_pct:.1f}%</span>'
        else:
            ratios_html = f'''<span class="f-ratio-item">计划 {plan_pct:.1f}%</span>
              <span class="f-ratio-item">持有 {favt_pct:.1f}%</span>
              <span class="f-ratio-item f-rebal {rebal_cls}">再平衡 {rebal_sign}{rebal_pct:.1f}%</span>'''

        fund_rows += f"""
      <div class="f-card" data-rid="{item.get('record_id','')}" data-name="{fname}" data-inner="{str(is_inner).lower()}" data-nav="{item.get('nav', 0)}">
        <div class="f-row">
          <div class="f-info">
            <span class="f-name">{fname}</span>
            <span class="f-fund-type">{'场内ETF/LOF/股票' if is_inner else '场外基金'}</span>
            <span class="f-ratios">
              {ratios_html}
            </span>
          </div>
          <div class="f-nums">
            <span class="f-amount">¥{famt:,.0f}</span>
            <span class="f-pnl {fpnl_cls}">{fpnl_sign}¥{fpnl:,.0f}<span class="f-rate">({frate_sign}{frate:.2f}%)</span></span>
          </div>
          <button class="f-trade-btn" onclick="event.stopPropagation();openTrade('{fname}','{item.get('record_id','')}','{str(is_inner).lower()}')" title="交易">+</button>
        </div>
        <div class="f-bar-wrap"><div class="f-bar" style="width:{favt_pct:.1f}%"></div></div>
      </div>"""

    position_cards += f"""
  <div class="p-card" onclick="togglePos('{pos}')">
    <div class="p-header" id="ph-{pos}">
      <span class="p-icon">{svg}</span>
      <div class="p-info">
        <span class="p-name">{pos}</span>
        <span class="p-ratio">持仓 {pos_pct:.1f}%</span>
      </div>
      <div class="p-nums">
        <span class="p-amount">¥{ps['持仓金额']:,.0f}</span>
        <span class="p-pnl {all_cls}">{all_sign}¥{ps['总盈亏']:,.0f}<span class="p-rate">({all_rate_sign}{ps['总盈亏率']:.2f}%)</span></span>
      </div>
      <span class="p-arrow" id="pa-{pos}"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg></span>
    </div>
    <div class="p-bar-wrap" id="pbw-{pos}"><div class="p-bar" style="width:{pos_pct:.1f}%"></div></div>
    <div class="p-body" id="pb-{pos}" onclick="event.stopPropagation()">
{fund_rows}
    </div>
  </div>"""

# ─── 8. 大指标卡（持仓总市值 + 收益目标 + 当日/总盈亏）─────
day_sign = "" if data["total_day_pnl"] >= 0 else ""
all_sign = "" if display_total_all_pnl >= 0 else ""
total_market_value = total_cost + display_total_all_pnl
mv_sign = "" if total_market_value >= 0 else ""

progress_pct = min(abs(display_total_all_rate), 100)
progress_cls = "bar-up" if display_total_all_pnl >= 0 else "bar-down"
goal_label = "达成目标" if display_total_all_rate >= 100 else f"距目标还差 ¥{(total_cost - display_total_all_pnl):,.0f}"

hero_card = f"""
<div class="hero-card">
  <div class="hero-top">
    <div class="hero-label">持仓总市值 <span class="eye-toggle" id="eyeToggle" onclick="toggleEye()" title="点击隐藏金额">__EYE_OPEN__</span></div>
    <div class="hero-value">¥{total_market_value:,.0f}</div>
  </div>
  <div class="hero-mid">
    <div class="goal-header">
      <span class="goal-label">收益目标</span>
      <span class="goal-pct" style="color:var(--tab-yellow)">{all_sign}{display_total_all_rate:.2f}%</span>
    </div>
    <div class="goal-bar-wrap">
      <div class="goal-bar {progress_cls}" style="width:{progress_pct}%"></div>
    </div>
    <div class="goal-footer">{goal_label}</div>
  </div>
  <div class="hero-bot">
    <div class="hero-sub">
      <div class="hero-sub-label">当日盈亏</div>
      <div class="hero-sub-val {'up' if data['total_day_pnl'] >= 0 else 'down'}">{day_sign}¥{data['total_day_pnl']:,.0f}<span class="hero-sub-rate"> ({'+' if total_day_rate >= 0 else ''}{total_day_rate:.2f}%)</span></div>
    </div>
    <div class="hero-divider"></div>
    <div class="hero-sub">
      <div class="hero-sub-label">总盈亏</div>
      <div class="hero-sub-val {'up' if display_total_all_pnl >= 0 else 'down'}">{all_sign}¥{display_total_all_pnl:,.0f}<span class="hero-sub-rate"> ({'+' if display_total_all_rate >= 0 else ''}{display_total_all_rate:.2f}%)</span></div>
    </div>
  </div>
</div>"""

# ─── 10. 图表数据（统一结构，三个排序视图）─────────────
all_funds = []
for item in data.get("all_records", []):
    pos_amt = round(item.get("持仓金额", 0), 2)
    fname = clean_name(item["基金名称"])
    # 判断是否场内：使用底表「场内场外」字段
    is_inner = item.get("场内场外", "") == "场内ETF/LOF/股票"
    all_funds.append({
        "n": fname,
        "dv": round(item.get("盈亏_日", 0), 2),
        "dr": round(item.get("日盈亏率", 0), 2),
        "tv": round(item.get("盈亏_总", 0), 2),
        "tr": round(item.get("总盈亏率", 0), 2),
        "pa": pos_amt,
        "pp": round(pos_amt / total_cost * 100, 1) if total_cost else 0,
        "rid": item.get("record_id", ""),
        "inner": is_inner,
    })

day_items    = sorted(all_funds, key=lambda x: x["dv"], reverse=True)
total_items  = sorted(all_funds, key=lambda x: x["tv"], reverse=True)
amount_items = sorted(all_funds, key=lambda x: x["pa"], reverse=True)

# ─── 11. 嵌入数据 ────────────────────────────────────────
embedded_data = json.dumps({
    "day_sorted": day_items,
    "total_sorted": total_items,
    "amount_sorted": amount_items,
    "total_day_pnl": round(data["total_day_pnl"], 2),
    "total_all_pnl": round(display_total_all_pnl, 2),
    "total_day_rate": total_day_rate,
    "total_all_rate": display_total_all_rate,
    "total_cost": round(total_cost, 2),
    "realized_pnl": round(ledger.get("realized_pnl", 0), 2),
    "history": history_data,
}, ensure_ascii=False)

# ─── 12. HTML 模板 v9 ──────────────────────────────────
html_template = r'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>盈亏看板</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
  :root {
    --bg: #0d1117; --card: #161b22; --border: #30363d;
    --text: #e6edf3; --text2: #8b949e;
    --up: #f85149; --down: #3fb950;
    --tab-yellow: #f0c000;
    --bar-up: linear-gradient(90deg, #f85149, #ff6b6b);
    --bar-down: linear-gradient(90deg, #3fb950, #5cdb6e);
  }
  * { margin:0; padding:0; box-sizing:border-box; -webkit-tap-highlight-color:transparent; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', sans-serif;
    background: var(--bg); color: var(--text);
    padding: 20px 16px 32px; min-height: 100vh;
    max-width: 480px; margin: 0 auto;
  }
  h1 { font-size: 17px; font-weight: 700; margin-bottom: 16px; }

  /* 刷新条 */
  .refresh-bar {
    display:flex; justify-content:space-between; align-items:center;
    background:var(--card); border:1px solid var(--border); border-radius:10px;
    padding:10px 14px; margin-bottom:14px; font-size:12px; color:var(--text2);
  }
  .refresh-btn {
    background:var(--tab-yellow); color:#111; border:none; border-radius:8px;
    padding:5px 14px; font-size:12px; cursor:pointer; font-weight:600;
  }

  /* === 1. 大指标卡 === */
  .hero-card {
    background:var(--card); border:1px solid var(--border); border-radius:12px;
    padding:20px 16px; margin-bottom:14px;
  }
  .hero-top { text-align:left; margin-bottom:16px; }
  .hero-label { font-size:13px; color:var(--text2); margin-bottom:6px; display:flex; align-items:center; gap:6px; }
  .eye-toggle {
    display:inline-flex; align-items:center; justify-content:center;
    cursor:pointer; color:var(--text2); padding:2px; border-radius:4px;
    transition:color .2s, background .2s; flex-shrink:0;
  }
  .eye-toggle:hover { color:var(--text); background:rgba(139,148,158,.1); }
  .eye-toggle.masked-eye { color:var(--tab-yellow); }
  .hero-value { font-size:32px; font-weight:800; letter-spacing:-1px; color:var(--text); }
  .hero-mid {
    padding:12px 0; border-top:1px solid rgba(48,54,61,0.35); border-bottom:1px solid rgba(48,54,61,0.35);
    margin-bottom:14px;
  }
  .goal-header { display:flex; justify-content:space-between; align-items:center; margin-bottom:8px; }
  .goal-label { font-size:12px; color:var(--text2); }
  .goal-pct { font-size:18px; font-weight:800; }
  .goal-bar-wrap { height:8px; background:#21262d; border-radius:4px; overflow:hidden; margin-bottom:6px; }
  .goal-bar { height:100%; border-radius:4px; transition:width .8s ease; }
  .goal-bar.bar-up { background:var(--tab-yellow); }
  .goal-bar.bar-down { background:var(--tab-yellow); }
  .goal-footer { font-size:11px; color:var(--text2); }
  .hero-bot { display:flex; align-items:stretch; gap:0; }
  .hero-sub { flex:1; text-align:center; }
  .hero-sub-label { font-size:12px; color:var(--text2); margin-bottom:4px; }
  .hero-sub-val { font-size:16px; font-weight:700; letter-spacing:-0.5px; }
  .hero-sub-rate { font-size:11px; opacity:0.75; }
  .hero-divider { width:1px; background:var(--border); align-self:stretch; margin:0 8px; }

  /* === 3. 收益日历 === */
  .cal-card {
    background:var(--card); border:1px solid var(--border); border-radius:12px;
    padding:10px 8px 8px;
  }
  .cal-topbar {
    display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;
  }
  .cal-nav { display:flex; align-items:center; gap:4px; }
  .cal-nav-btn {
    background:none; border:none; color:var(--text2); cursor:pointer;
    padding:2px 4px; border-radius:3px; font-size:13px; line-height:1;
  }
  .cal-nav-btn:hover { color:var(--text); }
  .cal-month { font-size:12px; font-weight:600; color:var(--text); min-width:80px; text-align:center; }
  .cal-toggle {
    display:flex; gap:1px; background:#21262d; border-radius:5px; padding:1px;
  }
  .cal-toggle button {
    border:none; background:none; color:var(--text2); font-size:10px;
    padding:3px 8px; border-radius:4px; cursor:pointer; font-weight:500; transition:all .2s;
  }
  .cal-toggle button.active { background:var(--tab-yellow); color:#111; }

  /* 期间切换 tabs */
  .cal-period-tabs {
    display:flex; gap:0; margin-bottom:6px;
    border-bottom:1.5px solid var(--border);
  }
  .cal-period-btn {
    flex:1; padding:6px 0 3px; text-align:center; font-size:11px; font-weight:600;
    background:none; border:none; color:var(--text2); cursor:pointer;
    position:relative; transition:color .2s;
  }
  .cal-period-btn::after {
    content:''; position:absolute; bottom:-1.5px; left:50%; transform:translateX(-50%) scaleX(0);
    width:1.6em; height:2.5px; background:var(--tab-yellow); border-radius:2px 2px 0 0;
    transition:transform .25s;
  }
  .cal-period-btn.active { color:var(--text); }
  .cal-period-btn.active::after { transform:translateX(-50%) scaleX(1); }

  /* 日视图 5列工作日 */
  .cal-grid { display:none; }
  .cal-grid.active { display:block; }
  .cal-weekdays {
    display:grid; grid-template-columns:repeat(5,1fr); text-align:center;
    font-size:8px; color:var(--text2); padding:1px 0 3px; font-weight:500; line-height:1.5;
  }
  .cal-days { display:grid; grid-template-columns:repeat(5,1fr); gap:1px; }
  .cal-cell {
    display:flex; flex-direction:column; align-items:center;
    justify-content:center; border-radius:4px; font-size:10px; line-height:1.4;
    cursor:default; transition:background .15s; padding:5px 2px; min-height:40px;
  }
  .cal-cell.today { background:rgba(240,192,0,.08); border:1px solid var(--tab-yellow); color:var(--tab-yellow); font-weight:700; }
  .cal-cell.has-data { background:#161b22; }
  .cal-cell.empty { visibility:hidden; }
  .cal-cell .cal-val { font-size:11px; font-weight:400; margin-top:2px; white-space:nowrap; }
  .cal-cell .cal-val.val-up { color:var(--up); }
  .cal-cell .cal-val.val-down { color:var(--down); }

  /* 周/月/年 指标卡 */
  .cal-summary { display:none; }
  #calSummaryWeek.active, #calSummaryYear.active { display:flex; flex-wrap:wrap; gap:4px; }
  #calSummaryMonth { display:none; }
  #calSummaryMonth.active { display:flex; flex-direction:column; gap:6px; }
  .cal-qrow { display:flex; align-items:center; gap:4px; }
  .cal-qrow > .sc-label { font-size:10px; color:var(--text2); font-weight:700; width:18px; text-align:center; flex-shrink:0; }
  .cal-qcells { display:grid; grid-template-columns:repeat(3,1fr); gap:3px; flex:1; }
  #calSummaryMonth .cal-sum-card { padding:5px 3px; min-width:0; }
  #calSummaryMonth .sc-val { font-size:9px; }
  .cal-sum-card {
    background:#1a2332; border:1px solid var(--border); border-radius:6px;
    padding:6px 8px; text-align:center; flex:1; min-width:50px;
  }
  .cal-sum-card.today { border-color:var(--tab-yellow); }
  .cal-sum-card .sc-label { font-size:8px; color:var(--text2); margin-bottom:3px; }
  .cal-sum-card .sc-val { font-size:10px; font-weight:700; }
  .cal-sum-card .sc-sub { font-size:7px; margin-top:3px; }

  /* === 响应式容器 === */
  .responsive-row { display:flex; flex-direction:column; gap:16px; margin-top:16px; }
  .responsive-col { flex:1; min-width:0; }

  /* === 4. 仓位卡 — 折叠菜单 === */
  .p-grid { display:flex; flex-direction:column; gap:8px; }
  .p-card {
    background:var(--card); border:1px solid var(--border); border-radius:8px;
    overflow:hidden; cursor:pointer; transition:border-color .2s;
  }
  .p-card:hover { border-color:#555; }
  .p-header {
    display:flex; align-items:center; gap:10px; padding:11px 15px;
  }
  .p-icon { flex-shrink:0; display:flex; align-items:center; color:var(--text2); }
  .p-info { display:flex; flex-direction:column; gap:2px; flex:1; }
  .p-name { color:var(--text); font-weight:600; font-size:11px; }
  .p-ratio { color:var(--text2); font-size:9px; }
  .p-nums { display:flex; flex-direction:column; gap:2px; text-align:right; flex-shrink:0; }
  .p-amount { font-weight:700; font-size:12px; color:var(--text); }
  .p-pnl { font-weight:600; font-size:10px; }
  .p-rate { font-size:10px; opacity:0.75; font-weight:400; }
  .p-arrow { display:flex; align-items:center; color:var(--text2); transition:transform .25s; margin-left:4px; flex-shrink:0; }
  .p-arrow.open { transform:rotate(180deg); }

  /* 折叠内容 */
  .p-body {
    border-top:1px solid rgba(48,54,61,0.35); padding:8px 15px 10px;
    max-height:0; overflow:hidden; transition:max-height .7s ease, padding .7s ease;
    padding-top:0; padding-bottom:0; border-top-color:transparent;
  }
  .p-body.open {
    max-height:1200px; padding-top:8px; padding-bottom:10px;
    border-top-color:rgba(48,54,61,0.35);
  }
  /* 基金独立卡片 */
  .f-card {
    background:#0d1117; border:1px solid rgba(48,54,61,0.5); border-radius:6px;
    overflow:hidden; margin-bottom:6px;
    transition:background .2s, border-color .2s;
    animation:fSlideIn .3s ease both;
  }
  .f-card:hover { background:#141920; border-color:rgba(72,78,90,0.6); }
  .f-row {
    display:flex; align-items:center; gap:8px; padding:9px 12px 9px 12px;
  }
  .f-info { display:flex; flex-direction:column; gap:1px; flex:1; }
  .f-name { color:var(--text); font-size:10px; font-weight:500; }
  .f-ratios { display:flex; gap:10px; flex-wrap:wrap; margin-top:1px; }
  .f-ratio-item { font-size:8px; color:var(--text2); }
  .f-fund-type { font-size:8px; color:var(--text2); margin-top:1px; }
  .f-rebal.up { color:var(--up); }
  .f-rebal.down { color:var(--down); }
  .f-nums { display:flex; flex-direction:column; gap:1px; text-align:right; flex-shrink:0; align-items:flex-end; }
  .f-pnl { font-weight:600; font-size:9px; margin-top:4px; }
  .f-amount { font-weight:700; font-size:11px; color:#9ea7b3; }
  .f-rate { font-size:8px; opacity:0.7; font-weight:400; }
  .f-bar-wrap { height:2px; background:#1a1f27; width:100%; }
  .f-bar { height:100%; background:var(--tab-yellow); transition:width .6s ease; }

  /* 仓位占比色条（默认显示，展开时隐藏） */
  .p-bar-wrap { height:3px; background:#21262d; width:100%; transition:opacity .25s; }
  .p-bar-wrap.hidden { opacity:0; height:0; }
  .p-bar { height:100%; background:var(--tab-yellow); border-radius:0 2px 0 0; transition:width .6s ease; }

  /* === 交易按钮：hover时圆圈黄色+号 === */
  .f-trade-btn {
    position:absolute; top:4px; right:4px;
    width:20px; height:20px; border-radius:50%;
    background:var(--tab-yellow); color:#111; border:none;
    font-size:13px; font-weight:700; cursor:pointer;
    display:flex; align-items:center; justify-content:center;
    opacity:0; transition:opacity .2s,transform .15s; flex-shrink:0; z-index:2;
    line-height:1;
  }
  .f-card { position:relative; }
  .f-card:hover .f-trade-btn { opacity:1; }
  .f-trade-btn:hover { transform:scale(1.15); }

  /* === 交易弹窗 === */
  .trade-overlay {
    position:fixed; top:0; left:0; width:100%; height:100%;
    background:rgba(0,0,0,.65); z-index:9998; display:none;
    align-items:flex-end; justify-content:center;
  }
  .trade-overlay.show { display:flex; animation:tFadeIn .25s ease; }
  @keyframes tFadeIn { from{opacity:0} to{opacity:1} }
  .trade-modal {
    background:var(--card); border:1px solid var(--border);
    border-radius:16px 16px 0 0; width:100%; max-width:480px;
    max-height:85vh; overflow-y:auto;
    padding:20px 18px 28px; margin-bottom:0;
    animation:tSlideUp .35s cubic-bezier(.16,1,.3,1);
  }
  @keyframes tSlideUp { from{transform:translateY(100%)} to{transform:translateY(0)} }

  .trade-header {
    display:flex; justify-content:space-between; align-items:center; margin-bottom:16px;
  }
  .trade-header-info { display:flex; flex-direction:column; gap:2px; }
  .trade-fund-name { font-size:15px; font-weight:700; color:var(--text); }
  .trade-fund-type { font-size:11px; color:var(--text2); }
  .trade-close {
    background:none; border:none; color:var(--text2); font-size:18px;
    cursor:pointer; display:flex; align-items:center; justify-content:center;
    width:28px; height:28px; border-radius:6px; transition:all .15s;
    line-height:1;
  }
  .trade-close:hover { background:rgba(139,148,158,.12); color:var(--text); }

  /* Tab 切换 */
  .trade-tabs {
    display:flex; gap:0; margin-bottom:18px;
    background:#21262d; border-radius:8px; padding:3px;
  }
  .trade-tab {
    flex:1; padding:8px 0; text-align:center; font-size:12px; font-weight:600;
    background:none; border:none; color:var(--text2); cursor:pointer;
    border-radius:6px; transition:all .2s;
  }
  .trade-tab.active { background:var(--tab-yellow); color:#111; }
  .trade-tab.sell-active { background:var(--down); color:#111; }
  .trade-tab.div-active { background:var(--up); color:#fff; }

  /* 表单 */
  .trade-form { display:flex; flex-direction:column; gap:14px; }
  .trade-field { display:flex; flex-direction:column; gap:4px; }
  .trade-label { font-size:11px; font-weight:600; color:var(--text2); display:flex; justify-content:space-between; align-items:center; }
  .trade-label-hint { font-weight:400; font-size:10px; color:var(--text2); opacity:.7; }
  .trade-input-wrap { display:flex; align-items:center; background:#0d1117; border:1px solid var(--border); border-radius:8px; overflow:hidden; min-height:42px; }
  .trade-input-icon { padding:0 10px; color:var(--text2); font-size:13px; flex-shrink:0; width:36px; text-align:center; }
  .trade-input {
    flex:1; background:none; border:none; color:var(--text);
    font-size:15px; font-weight:600; padding:11px 10px; outline:none; min-width:0;
  }
  .trade-input::placeholder { color:rgba(139,148,158,.5); font-weight:400; }
  .trade-input-unit { padding:0 12px; color:var(--text2); font-size:12px; font-weight:500; flex-shrink:0; }
  /* 日期选择器黄色主题 */
  input[type="date"] { color:var(--text); accent-color:var(--tab-yellow); }
  input[type="date"]::-webkit-calendar-picker-indicator { opacity:.5; cursor:pointer; }
  input[type="date"]::-webkit-calendar-picker-indicator:hover { opacity:.8; }
  .trade-toggle-group {
    display:flex; background:#21262d; border-radius:6px; padding:2px; gap:2px;
  }
  .trade-toggle-btn {
    flex:1; padding:7px 0; text-align:center; font-size:12px; font-weight:600;
    background:none; border:none; color:var(--text2); cursor:pointer;
    border-radius:4px; transition:all .2s;
  }
  .trade-toggle-btn.active { background:#161b22; color:var(--tab-yellow); box-shadow:0 1px 4px rgba(0,0,0,.4); border:1px solid rgba(240,192,0,.35); }
  /* 卖出模式：切换按钮绿色高亮 */
  .trade-modal[data-mode="sell"] .trade-toggle-btn.active { color:var(--down); border-color:rgba(63,185,80,.4); }
  /* 股息模式：切换按钮红色高亮 */
  .trade-modal[data-mode="div"] .trade-toggle-btn.active { color:var(--up); border-color:rgba(248,81,73,.4); }

  .trade-fee-row {
    display:flex; justify-content:space-between; align-items:center;
    padding:10px 12px; background:#0d1117; border-radius:8px; border:1px solid rgba(48,54,61,.4);
  }
  .trade-fee-label { font-size:11px; color:var(--text2); }
  .trade-fee-val { font-size:12px; font-weight:700; }

  .trade-nav-preview {
    min-height:20px; padding:4px 8px;
    background:rgba(240,192,0,.06); border-radius:6px;
    border:1px solid rgba(240,192,0,.15);
  }
  .trade-nav-preview.up { color:var(--up); }
  .trade-nav-preview.down { color:var(--down); }

  .trade-submit-row { display:flex; gap:10px; margin-top:20px; }
  .trade-btn-cancel {
    flex:1; padding:12px; background:none; border:1px solid var(--border);
    border-radius:10px; color:var(--text2); font-size:14px; font-weight:600; cursor:pointer;
    transition:all .15s;
  }
  .trade-btn-cancel:active { background:rgba(139,148,158,.1); }
  .trade-btn-submit {
    flex:2; padding:12px; background:var(--tab-yellow); border:none;
    border-radius:10px; color:#111; font-size:14px; font-weight:700; cursor:pointer;
  }
  .trade-btn-submit:active { transform:scale(.98); }
  .trade-btn-submit.sell-mode { background:var(--down); color:#111; }
  .trade-btn-submit.div-mode { background:var(--up); color:#fff; }

  .trade-toast {
    position:fixed; bottom:60px; left:50%; transform:translateX(-50%);
    background:rgba(240,192,0,.92); border:1px solid rgba(240,192,0,.5);
    border-radius:10px; padding:10px 20px; color:#111;
    font-size:12px; font-weight:700; z-index:10000; display:none;
    backdrop-filter:blur(8px); box-shadow:0 4px 20px rgba(240,192,0,.25);
  }
  .trade-toast.show { display:block; animation:tToastIn .3s ease; }
  @keyframes tToastIn { from{opacity:0;transform:translateX(-50%) translateY(10px)} to{opacity:1;transform:translateX(-50%) translateY(0)} }

  .up { color:var(--up); }
  .down { color:var(--down); }

  /* === 5. 图表区域 === */
  .chart-section { margin-top:16px; }
  .chart-topbar {
    display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;
  }
  .chart-title { font-size:13px; font-weight:600; color:var(--text); }
  .chart-toggle {
    display:flex; gap:1px; background:#21262d; border-radius:5px; padding:1px;
  }
  .chart-toggle button {
    border:none; background:none; color:var(--text2); font-size:10px;
    padding:3px 8px; border-radius:4px; cursor:pointer; font-weight:500; transition:all .2s;
  }
  .chart-toggle button.active { background:var(--tab-yellow); color:#111; }
  .chart-box {
    background:var(--card); border:1px solid var(--border); border-radius:12px;
    padding:14px 12px 18px;
  }
  .chart-wrap { position:relative; width:100%; }

  /* === 隐私模式遮罩 === */
  body.privacy-mode .masked {
    color: var(--text2) !important;
    letter-spacing: 1px;
  }
  body.privacy-mode .chart-wrap::after {
    content: "***";
    position: absolute; inset: 0; z-index: 10;
    display: flex; align-items: center; justify-content: center;
    font-size: 28px; font-weight: 800; color: var(--text2);
    background: rgba(13,17,23,.75); border-radius: 8px;
    letter-spacing: 2px;
  }

  /* 底部信息 */
  .bottom-info { text-align:center; color:var(--text2); font-size:11px; margin-top:24px; padding-bottom:8px; }

  /* === 密码遮罩 === */
  .pw-overlay {
    position:fixed; top:0; left:0; width:100%; height:100%;
    background:var(--bg); z-index:9999; display:flex;
    align-items:center; justify-content:center;
  }
  .pw-box {
    background:var(--card); border:1px solid var(--border); border-radius:12px;
    padding:32px 24px; text-align:center; max-width:300px; width:90%;
  }
  .pw-title { font-size:18px; font-weight:700; margin-bottom:8px; color:var(--text); }
  .pw-sub { font-size:12px; color:var(--text2); margin-bottom:20px; }
  .pw-input {
    width:100%; padding:10px 14px; border:1px solid var(--border); border-radius:8px;
    background:#0d1117; color:var(--text); font-size:16px; text-align:center;
    margin-bottom:12px; outline:none; letter-spacing:4px;
  }
  .pw-input:focus { border-color:var(--tab-yellow); }
  .pw-btn {
    width:100%; padding:10px; background:var(--tab-yellow); color:#111;
    border:none; border-radius:8px; font-size:14px; font-weight:600; cursor:pointer;
  }
  .pw-error { font-size:11px; color:var(--up); margin-top:8px; display:none; }

  /* === 响应式：横屏/桌面端 === */
  @media (min-width:640px) and (orientation:landscape), (min-width:768px) {
    body { max-width:960px; padding:24px 28px 50px; }
    .hero-value { font-size:40px; }
    .hero-sub-val { font-size:19px; }
    .responsive-row { flex-direction:row; gap:12px; align-items:stretch; }
    .responsive-col { flex:1; display:flex; flex-direction:column; }
    .responsive-col .cal-card { flex:1; }
    .responsive-col .p-grid { flex:1; }
    .p-name { font-size:12px; }
    .cal-cell .cal-val { font-size:7px; }
  }
  /* 竖屏：日历行高加大 */
  @media (max-width:639px), (orientation:portrait) {
    .hero-value { font-size:28px; }
    .hero-sub-val { font-size:15px; }
    .cal-cell { min-height:44px; padding:5px 1px; }
    .cal-cell .cal-val { font-size:10px; }
    .cal-days { gap:2px; }
  }
</style>
</head>
<body>
<!-- 密码验证遮罩 -->
<div class="pw-overlay" id="pwOverlay">
  <div class="pw-box">
    <div class="pw-title">私密看板</div>
    <div class="pw-sub">请输入访问密码</div>
    <input type="password" class="pw-input" id="pwInput" placeholder="输入密码" maxlength="20" inputmode="numeric">
    <button class="pw-btn" onclick="checkPassword()">确认</button>
    <div class="pw-error" id="pwError">密码错误，请重试</div>
  </div>
</div>

<!-- 交易弹窗 -->
<div class="trade-overlay" id="tradeOverlay" onclick="closeTrade()">
  <div class="trade-modal" id="tradeModal" data-mode="buy" onclick="event.stopPropagation()">
    <div class="trade-header">
      <div class="trade-header-info">
        <span class="trade-fund-name" id="tFundName">--</span>
        <span class="trade-fund-type" id="tFundType">场外基金</span>
        <span class="trade-nav-display" id="tNavDisplay" style="font-size:11px; color:var(--tab-yellow);"></span>
      </div>
      <button class="trade-close" onclick="closeTrade()">&times;</button>
    </div>
    <div class="trade-tabs" id="tradeTabs">
      <button class="trade-tab active" data-mode="buy" onclick="setTradeMode('buy')">买入</button>
      <button class="trade-tab" data-mode="sell" onclick="setTradeMode('sell')">卖出</button>
      <button class="trade-tab" data-mode="div" onclick="setTradeMode('div')">股息/分红</button>
    </div>
    <div class="trade-form" id="tradeForm">
      <!-- 交易时间 -->
      <div class="trade-field">
        <label class="trade-label">交易时间</label>
        <div class="trade-input-wrap">
          <span class="trade-input-icon" style="opacity:.65; display:flex; align-items:center; justify-content:center;">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>
          </span>
          <input type="date" class="trade-input" id="tDate">
          <span class="trade-input-unit"></span>
        </div>
      </div>
      <!-- 数量模式切换 + 数量输入 -->
      <div class="trade-field">
        <label class="trade-label"><span id="tQtyLabel">成交金额</span> <span class="trade-label-hint" id="tQtyHint">含手续费</span></label>
        <div class="trade-toggle-group" id="tUnitToggle">
          <button class="trade-toggle-btn active" data-u="amount" onclick="setTUnit('amount')">金额</button>
          <button class="trade-toggle-btn" data-u="share" onclick="setTUnit('share')">份额</button>
        </div>
        <div class="trade-input-wrap" style="margin-top:6px;">
          <span class="trade-input-icon" id="tQtyIcon" style="font-size:13px; opacity:.7;">&yen;</span>
          <input type="number" class="trade-input" id="tQty" placeholder="输入数量" inputmode="decimal" oninput="calcFee();updateNavPreview()">
          <span class="trade-input-unit" id="tQtyUnit">CNY</span>
        </div>
        <!-- 净值预览（场外基金） -->
        <div class="trade-nav-preview" id="tNavPreview" style="display:none; font-size:11px; color:var(--text2); margin-top:4px;"></div>
      </div>
      <!-- 价格(份) - 场内显示 -->
      <div class="trade-field" id="tPriceField">
        <label class="trade-label" id="tPriceLabel">买入价格（份）</label>
        <div class="trade-input-wrap">
          <span class="trade-input-icon">$</span>
          <input type="number" class="trade-input" id="tPrice" placeholder="0.0000" step="0.0001" inputmode="decimal" oninput="calcFee()">
          <span class="trade-input-unit" id="tPriceUnit">CNY</span>
        </div>
      </div>
      <!-- 手续费（自动计算，只读显示）-->
      <div class="trade-fee-row">
        <span class="trade-fee-label">手续费 (自动计算)</span>
        <span class="trade-fee-val" id="tFeeDisplay">¥0.00</span>
      </div>
    </div>
    <div class="trade-submit-row">
      <button class="trade-btn-cancel" onclick="closeTrade()">取消</button>
      <button class="trade-btn-submit" id="tSubmitBtn" onclick="submitTrade()">确认交易</button>
    </div>
  </div>
</div>

<div class="trade-toast" id="tradeToast">交易指令已复制，发送给老曹执行</div>

<h1>曹燕清全球成长精选（QDII）A</h1>

<div class="refresh-bar">
  <span id="updateTime">--</span>
  <button class="refresh-btn" onclick="location.reload()">Refresh</button>
</div>

<!-- 1. 大指标卡 -->
__HERO_CARD__

<!-- 2. 收益日历 + 仓位明细 (响应式左右排列) -->
<div class="responsive-row">
  <div class="responsive-col">
    <div class="chart-topbar">
      <span class="chart-title">收益日历</span>
    </div>
    <div class="cal-card">
      <div class="cal-topbar">
        <div class="cal-nav">
          <button class="cal-nav-btn" onclick="calPrevMonth()">◀</button>
          <span class="cal-month" id="calMonthLabel">--</span>
          <button class="cal-nav-btn" onclick="calNextMonth()">▶</button>
        </div>
        <div class="cal-toggle" id="calUnitToggle">
          <button class="active" data-unit="amount" onclick="setCalUnit('amount')">金额</button>
          <button data-unit="rate" onclick="setCalUnit('rate')">收益率</button>
        </div>
      </div>
      <div class="cal-period-tabs">
        <button class="cal-period-btn active" data-period="day" onclick="setCalPeriod('day')">日</button>
        <button class="cal-period-btn" data-period="week" onclick="setCalPeriod('week')">周</button>
        <button class="cal-period-btn" data-period="month" onclick="setCalPeriod('month')">月</button>
        <button class="cal-period-btn" data-period="year" onclick="setCalPeriod('year')">年</button>
      </div>
      <div class="cal-grid active" id="calGridDay">
        <div class="cal-weekdays"><span>一</span><span>二</span><span>三</span><span>四</span><span>五</span></div>
        <div class="cal-days" id="calDays"></div>
      </div>
      <div class="cal-summary" id="calSummaryWeek"></div>
      <div class="cal-summary" id="calSummaryMonth"></div>
      <div class="cal-summary" id="calSummaryYear"></div>
    </div>
  </div>
  <div class="responsive-col">
    <div class="chart-topbar">
      <span class="chart-title">仓位明细</span>
    </div>
    <div class="p-grid">__POSITION_CARDS__</div>
  </div>
</div>

<!-- 3. 持仓明细图表 -->
<div class="chart-section">
  <div class="chart-topbar">
    <span class="chart-title">持仓明细</span>
    <div class="chart-toggle" id="chartMetricToggle">
      <button class="active" data-metric="day" onclick="setChartMetric('day')">当日盈亏</button>
      <button data-metric="total" onclick="setChartMetric('total')">持有收益</button>
      <button data-metric="amount" onclick="setChartMetric('amount')">持有金额</button>
    </div>
  </div>
  <div class="chart-box">
    <div class="chart-wrap"><canvas id="mainChart"></canvas></div>
  </div>
</div>

<div class="bottom-info">Auto-refresh daily · 数据来自飞书多维表格</div>

<script>
var D = __DATA__;

// ==================== 密码验证 ====================
(function(){
  var pwOverlay = document.getElementById('pwOverlay');
  var pwInput = document.getElementById('pwInput');
  var pwError = document.getElementById('pwError');
  if (sessionStorage.getItem('pnl_auth') === 'ok') { pwOverlay.style.display = 'none'; return; }
  window.checkPassword = function() {
    if (pwInput.value === '0915') {
      sessionStorage.setItem('pnl_auth', 'ok');
      pwOverlay.style.display = 'none';
    } else {
      pwError.style.display = 'block';
      pwInput.value = '';
      pwInput.focus();
    }
  };
  pwInput.addEventListener('keydown', function(e) { if (e.key === 'Enter') checkPassword(); });
  pwInput.focus();
})();

// ==================== 仓位折叠菜单 ====================
function togglePos(pos) {
  var body = document.getElementById('pb-' + pos);
  var arrow = document.getElementById('pa-' + pos);
  var bar = document.getElementById('pbw-' + pos);
  var isOpen = body.classList.contains('open');
  if (isOpen) {
    body.classList.remove('open');
    arrow.classList.remove('open');
    if (bar) bar.classList.remove('hidden');
  } else {
    // 关闭其他已打开的
    document.querySelectorAll('.p-body.open').forEach(function(b) { b.classList.remove('open'); });
    document.querySelectorAll('.p-arrow.open').forEach(function(a) { a.classList.remove('open'); });
    document.querySelectorAll('.p-bar-wrap').forEach(function(w) { w.classList.remove('hidden'); });
    body.classList.add('open');
    arrow.classList.add('open');
    if (bar) bar.classList.add('hidden');
    applyPrivacyMask();
  }
}

function fmt(n) { return '¥' + Math.abs(n).toLocaleString('zh-CN',{minimumFractionDigits:0,maximumFractionDigits:0}); }
function fmtPct(n) { return n.toFixed(2) + '%'; }
function fmtFull(n) {
  return '¥' + Math.abs(n).toLocaleString('zh-CN',{minimumFractionDigits:0,maximumFractionDigits:0});
}
// 万为单位（月/年视图使用）
function fmtWan(n) {
  var abs = Math.abs(n);
  if (abs >= 10000) {
    return '¥' + (n / 10000).toFixed(2) + '万';
  }
  return '¥' + abs.toLocaleString('zh-CN',{minimumFractionDigits:0,maximumFractionDigits:0});
}

// ==================== Chart.js 柱状图 ====================
Chart.defaults.color = '#8b949e';
Chart.defaults.borderColor = '#21262d';
Chart.defaults.font.family = "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";

function barColors(values) {
  return values.map(function(v) { return v >= 0 ? '#f85149' : '#3fb950'; });
}

function makeTooltip(data) {
  return {
    label: function(ctx) {
      var d = data[ctx.dataIndex];
      if (!d) return '';
      var m = currentMetric;
      if (m === 'day') {
        return ['当日盈亏: ¥' + Math.abs(d.dv||0).toLocaleString('zh-CN'),
                '日盈亏率: ' + ((d.dr||0)>=0?'+':'') + (d.dr||0).toFixed(2) + '%'];
      } else if (m === 'total') {
        return ['持有收益: ¥' + Math.abs(d.tv||0).toLocaleString('zh-CN'),
                '收益率: ' + ((d.tr||0)>=0?'+':'') + (d.tr||0).toFixed(2) + '%'];
      } else {
        return ['持仓金额: ¥' + (d.pa||0).toLocaleString('zh-CN'),
                '持仓比: ' + (d.pp||0).toFixed(1) + '%'];
      }
    }
  };
}

var mainChart = null;
var currentMetric = 'day';

function getChartData(metric) {
  if (metric === 'day') return D.day_sorted;
  if (metric === 'total') return D.total_sorted;
  if (metric === 'amount') return D.amount_sorted;
  return D.day_sorted;
}

function getValueField(metric) {
  if (metric === 'day') return 'dv';
  if (metric === 'total') return 'tv';
  if (metric === 'amount') return 'pa';
  return 'dv';
}

function makeChart(items, valueField) {
  var ctx = document.getElementById('mainChart').getContext('2d');
  return new Chart(ctx, {
    type: 'bar',
    data: {
      labels: items.map(function(d) { return d.n; }),
      datasets: [{
        data: items.map(function(d) { return d[valueField]; }),
        backgroundColor: barColors(items.map(function(d) { return d[valueField]; })),
        borderRadius: 4,
        borderSkipped: false,
      }]
    },
    options: {
      indexAxis: 'y',
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: '#161b22',
          borderColor: '#30363d',
          borderWidth: 1,
          titleColor: '#e6edf3',
          bodyColor: '#e6edf3',
          padding: 10,
          callbacks: makeTooltip(items)
        }
      },
      scales: {
        x: {
          grid: { color: '#21262d' },
          ticks: { color: '#8b949e', callback: function(v) { return fmt(v); } }
        },
        y: {
          grid: { display: false },
          ticks: { color: '#e6edf3', font: { size: 11 } }
        }
      }
    }
  });
}

function setChartMetric(metric) {
  currentMetric = metric;
  document.querySelectorAll('#chartMetricToggle button').forEach(function(b) { b.classList.remove('active'); });
  document.querySelector('#chartMetricToggle button[data-metric="'+metric+'"]').classList.add('active');
  var items = getChartData(metric);
  var valueField = getValueField(metric);
  if (mainChart) mainChart.destroy();
  mainChart = makeChart(items, valueField);
  var el = document.querySelector('.chart-wrap');
  el.style.height = Math.max(280, items.length * 24) + 'px';
  applyPrivacyMask();
}

// 初始化：默认当日盈亏
setChartMetric('day');

// ==================== 收益日历（真实历史数据） ====================
var calYear = 2026, calMonth = 5;      // 0-indexed (5=June)
var calPeriod = 'day';
var calUnit = 'amount';
var calToday = new Date();
var calTodayY = calToday.getFullYear(), calTodayM = calToday.getMonth(), calTodayD = calToday.getDate();
var historyData = D.history || {};

function isToday(y,m,d) { return y===calTodayY && m===calTodayM && d===calTodayD; }

function getDayData(dateStr) {
  return historyData[dateStr] || null;
}

function renderCalendar() {
  document.getElementById('calMonthLabel').textContent = calYear + '年' + (calMonth+1) + '月';
  renderDayGrid();
  renderWeekCards();
  renderMonthCards();
  renderYearCards();
  switchCalView();
}

// 日视图 — 5列工作日 + 历史数据
function renderDayGrid() {
  var el = document.getElementById('calDays');
  var daysInMonth = new Date(calYear, calMonth+1, 0).getDate();
  var weekdays = [];
  for (var d = 1; d <= daysInMonth; d++) {
    var date = new Date(calYear, calMonth, d);
    var dow = date.getDay();
    if (dow !== 0 && dow !== 6) weekdays.push({day:d, dow:dow});
  }
  var firstDow = weekdays.length > 0 ? weekdays[0].dow - 1 : 0;
  var html = '';
  for (var i = 0; i < firstDow; i++) html += '<div class="cal-cell empty"></div>';

  for (var j = 0; j < weekdays.length; j++) {
    var wd = weekdays[j];
    var dateStr = calYear + '-' + String(calMonth+1).padStart(2,'0') + '-' + String(wd.day).padStart(2,'0');
    var today = isToday(calYear, calMonth, wd.day);
    var dd = getDayData(dateStr);
    var cls = 'cal-cell' + (today ? ' today' : '') + (dd ? ' has-data' : '');
    var valHtml = '';
    if (dd) {
      var v = calUnit === 'amount' ? dd.amount : dd.rate;
      if (calUnit === 'amount') {
        var clsV = v >= 0 ? 'val-up' : 'val-down';
        valHtml = '<span class="cal-val '+clsV+'">'+fmtFull(v)+'</span>';
      } else {
        var clsV = v >= 0 ? 'val-up' : 'val-down';
        valHtml = '<span class="cal-val '+clsV+'">'+fmtPct(v)+'</span>';
      }
    }
    html += '<div class="'+cls+'">'+wd.day+valHtml+'</div>';
  }
  el.innerHTML = html;
}

// 周视图
function renderWeekCards() {
  var el = document.getElementById('calSummaryWeek');
  var today = new Date();
  var dow = today.getDay(); dow = dow===0 ? 6 : dow-1;
  var mon = new Date(today); mon.setDate(today.getDate() - dow);
  var dayLabels = ['一','二','三','四','五'];
  var html = '';
  for (var i = 0; i < 5; i++) {
    var d = new Date(mon); d.setDate(mon.getDate() + i);
    var dateStr = d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0')+'-'+String(d.getDate()).padStart(2,'0');
    var isTd = (d.toDateString() === today.toDateString());
    var dd = getDayData(dateStr);
    var cls = 'cal-sum-card' + (isTd ? ' today' : '');
    var label = dayLabels[i] + '<br>' + d.getDate();
    if (dd && calUnit === 'amount') {
      var v = dd.amount, vcls = v>=0?'up':'down';
      html += '<div class="'+cls+'"><div class="sc-label">'+label+'</div><div class="sc-val '+vcls+'">'+fmt(v)+'</div></div>';
    } else if (dd && calUnit === 'rate') {
      var v = dd.rate, vcls = v>=0?'up':'down';
      html += '<div class="'+cls+'"><div class="sc-label">'+label+'</div><div class="sc-val '+vcls+'">'+fmtPct(v)+'</div></div>';
    } else {
      html += '<div class="'+cls+'"><div class="sc-label">'+label+'</div><div class="sc-val" style="color:var(--text2)">--</div></div>';
    }
  }
  el.innerHTML = html;
}

// 月视图 — 12个月，金额用万
function renderMonthCards() {
  var el = document.getElementById('calSummaryMonth');
  var quarters = [['Q1',0,1,2],['Q2',3,4,5],['Q3',6,7,8],['Q4',9,10,11]];
  var html = '';
  for (var q = 0; q < quarters.length; q++) {
    var qLabel = quarters[q][0];
    html += '<div class="cal-qrow"><div class="sc-label">'+qLabel+'</div><div class="cal-qcells">';
    for (var i = 1; i <= 3; i++) {
      var m = quarters[q][i];
      var monthSum = 0, monthCount = 0;
      var monthKey = calYear + '-' + String(m+1).padStart(2,'0');
      for (var dateStr in historyData) {
        if (dateStr.startsWith(monthKey)) {
          monthSum += calUnit==='amount' ? historyData[dateStr].amount : historyData[dateStr].rate;
          monthCount++;
        }
      }
      var monthName = (m+1)+'月';
      var isCur = (m === calTodayM && calYear === calTodayY);
      var cls = 'cal-sum-card' + (isCur ? ' today' : '');
      if (monthCount > 0) {
        if (calUnit === 'amount') {
          var vcls = monthSum>=0 ? 'up' : 'down';
          html += '<div class="'+cls+'"><div class="sc-label">'+monthName+'</div><div class="sc-val '+vcls+'">'+fmtWan(monthSum)+'</div></div>';
        } else {
          var vcls = monthSum>=0 ? 'up' : 'down';
          html += '<div class="'+cls+'"><div class="sc-label">'+monthName+'</div><div class="sc-val '+vcls+'">'+fmtPct(monthSum)+'</div></div>';
        }
      } else {
        html += '<div class="'+cls+'"><div class="sc-label">'+monthName+'</div><div class="sc-val" style="color:var(--text2)">--</div></div>';
      }
    }
    html += '</div></div>';
  }
  el.innerHTML = html;
}

// 年视图 — 显示所有年度（2025、2026...）
function renderYearCards() {
  var el = document.getElementById('calSummaryYear');
  var years = {};
  for (var dateStr in historyData) {
    var y = dateStr.substring(0, 4);
    if (!years[y]) years[y] = {sum: 0, count: 0};
    var d = historyData[dateStr];
    years[y].sum += calUnit === 'amount' ? d.amount : d.rate;
    years[y].count++;
  }
  var sortedYears = Object.keys(years).sort();
  var html = '';
  for (var i = 0; i < sortedYears.length; i++) {
    var y = sortedYears[i];
    var yd = years[y];
    var isCur = (parseInt(y) === calTodayY);
    var cls = 'cal-sum-card' + (isCur ? ' today' : '');
    if (calUnit === 'amount') {
      var vcls = yd.sum>=0 ? 'up' : 'down';
      html += '<div class="'+cls+'"><div class="sc-label">'+y+'年</div><div class="sc-val '+vcls+'">'+fmtWan(yd.sum)+'</div><div class="sc-sub" style="color:var(--text2)">'+yd.count+'个交易日</div></div>';
    } else {
      var vcls = yd.sum>=0 ? 'up' : 'down';
      html += '<div class="'+cls+'"><div class="sc-label">'+y+'年</div><div class="sc-val '+vcls+'">'+fmtPct(yd.sum)+'</div><div class="sc-sub" style="color:var(--text2)">'+yd.count+'个交易日</div></div>';
    }
  }
  el.innerHTML = html;
}

function switchCalView() {
  document.querySelectorAll('.cal-grid').forEach(function(el){el.classList.remove('active');});
  document.querySelectorAll('.cal-summary').forEach(function(el){el.classList.remove('active');});
  if (calPeriod === 'day') document.getElementById('calGridDay').classList.add('active');
  else if (calPeriod === 'week') document.getElementById('calSummaryWeek').classList.add('active');
  else if (calPeriod === 'month') document.getElementById('calSummaryMonth').classList.add('active');
  else if (calPeriod === 'year') document.getElementById('calSummaryYear').classList.add('active');
}

function setCalPeriod(period) {
  calPeriod = period;
  document.querySelectorAll('.cal-period-btn').forEach(function(b){b.classList.remove('active');});
  document.querySelector('[data-period="'+period+'"]').classList.add('active');
  switchCalView();
  applyPrivacyMask();
}

function setCalUnit(unit) {
  calUnit = unit;
  document.querySelectorAll('#calUnitToggle button').forEach(function(b){b.classList.remove('active');});
  document.querySelector('#calUnitToggle button[data-unit="'+unit+'"]').classList.add('active');
  renderDayGrid();
  renderWeekCards();
  renderMonthCards();
  renderYearCards();
  applyPrivacyMask();
}

function calPrevMonth() {
  if (calMonth === 0) { calYear--; calMonth = 11; } else calMonth--;
  renderCalendar();
  applyPrivacyMask();
}
function calNextMonth() {
  if (calMonth === 11) { calYear++; calMonth = 0; } else calMonth++;
  renderCalendar();
  applyPrivacyMask();
}

renderCalendar();

// ==================== 隐私模式（小眼睛） ====================
var privacyOn = false;
var EYE_OPEN = '__EYE_OPEN__';
var EYE_CLOSED = '__EYE_CLOSED__';

function maskOne(el) {
  if (el.classList.contains('masked')) return;
  el.setAttribute('data-orig', el.innerHTML);
  el.classList.add('masked');
  el.innerHTML = '***';
}

function unmaskAll() {
  var masked = document.querySelectorAll('.masked');
  masked.forEach(function(el) {
    if (el.hasAttribute('data-orig')) {
      el.innerHTML = el.getAttribute('data-orig');
      el.removeAttribute('data-orig');
    }
    el.classList.remove('masked');
  });
}

function applyPrivacyMask() {
  if (!privacyOn) return;
  // 先恢复（避免重复masked）
  unmaskAll();
  var selectors = '.hero-value, .hero-sub-val, .goal-pct, .p-amount, .p-pnl, .f-amount, .f-pnl, .cal-val, .sc-val, .hero-sub-rate, .f-rate, .p-rate';
  var els = document.querySelectorAll(selectors);
  els.forEach(maskOne);
  // 也遮罩导航里的占比和持仓金额
  document.querySelectorAll('.p-ratio, .f-ratio-item, .goal-footer').forEach(function(el) {
    maskOne(el);
  });
}

function toggleEye() {
  privacyOn = !privacyOn;
  var eyeEl = document.getElementById('eyeToggle');
  if (privacyOn) {
    eyeEl.innerHTML = EYE_CLOSED;
    eyeEl.classList.add('masked-eye');
    eyeEl.setAttribute('title', '点击显示金额');
    document.body.classList.add('privacy-mode');
    applyPrivacyMask();
  } else {
    eyeEl.innerHTML = EYE_OPEN;
    eyeEl.classList.remove('masked-eye');
    eyeEl.setAttribute('title', '点击隐藏金额');
    document.body.classList.remove('privacy-mode');
    unmaskAll();
  }
}

// ==================== 交易弹窗 ====================
// T+1 全球基金（净值确认滞后一天，买入按T+1净值计算份额）
var TPLUS1_NAMES = ['广发全球精选', '易方达全球', '宝盈纳指100'];
function _isTPlus1(name) {
  for (var i = 0; i < TPLUS1_NAMES.length; i++) {
    if (name.indexOf(TPLUS1_NAMES[i]) >= 0) return true;
  }
  return false;
}
var tState = { mode: 'buy', unit: 'amount', name: '', rid: '', is_inner: false, nav: 0, is_tplus1: false };
var _vpHandler = null;
var _scrollY = 0;

function openTrade(name, rid, isEtf) {
  tState.name = name; tState.rid = rid; tState.is_inner = (isEtf === 'true');
  tState.is_tplus1 = _isTPlus1(name);
  // 读净值（从卡片 data-nav 属性）
  var card = document.querySelector('[data-rid="'+rid+'"]');
  tState.nav = card ? parseFloat(card.dataset.nav) || 0 : 0;

  document.getElementById('tFundName').textContent = name;
  document.getElementById('tFundType').textContent = tState.is_inner ? '场内 ETF/LOF/股票' : '场外基金';
  // 显示净值
  var navEl = document.getElementById('tNavDisplay');
  if (navEl) navEl.textContent = tState.nav > 0 ? '最新净值: ' + tState.nav.toFixed(4) + (tState.is_tplus1 ? '（T+1确认）' : '') : '';

  var td = new Date().toISOString().split('T')[0];
  document.getElementById('tDate').value = td;
  document.getElementById('tQty').value = '';
  document.getElementById('tPrice').value = '';
  setTradeMode('buy');
  // 滚动锁定：记录位置，固定body
  _scrollY = window.scrollY || window.pageYOffset;
  document.body.style.position = 'fixed';
  document.body.style.width = '100%';
  document.body.style.top = '-' + _scrollY + 'px';
  document.body.style.overflow = 'hidden';
  document.getElementById('tradeOverlay').classList.add('show');
  // 键盘弹起时推高弹窗
  if (window.visualViewport) {
    _vpHandler = function() {
      var vkH = window.innerHeight - window.visualViewport.height - window.visualViewport.offsetTop;
      var modal = document.getElementById('tradeModal');
      if (modal) { modal.style.marginBottom = vkH > 0 ? vkH + 'px' : '0'; }
    };
    window.visualViewport.addEventListener('resize', _vpHandler);
    window.visualViewport.addEventListener('scroll', _vpHandler);
  }
}

function closeTrade() {
  document.getElementById('tradeOverlay').classList.remove('show');
  // 恢复滚动
  document.body.style.position = '';
  document.body.style.width = '';
  document.body.style.top = '';
  document.body.style.overflow = '';
  window.scrollTo(0, _scrollY);
  var modal = document.getElementById('tradeModal');
  if (modal) { modal.style.marginBottom = '0'; }
  if (window.visualViewport && _vpHandler) {
    window.visualViewport.removeEventListener('resize', _vpHandler);
    window.visualViewport.removeEventListener('scroll', _vpHandler);
    _vpHandler = null;
  }
}

// 统一更新价格框显示/标签
function updatePriceFieldVisibility() {
  var show = tState.is_inner && tState.mode !== 'div';
  document.getElementById('tPriceField').style.display = show ? '' : 'none';
  var label = (tState.mode === 'sell') ? '卖出价格（份）' : '买入价格（份）';
  var labelEl = document.getElementById('tPriceLabel');
  if (labelEl) labelEl.textContent = label;
}

function setTradeMode(m) {
  // 切换标签时清空所有输入
  document.getElementById('tQty').value = '';
  document.getElementById('tPrice').value = '';
  var preview = document.getElementById('tNavPreview');
  if (preview) { preview.style.display = 'none'; preview.innerHTML = ''; }
  calcFee();

  tState.mode = m;
  document.querySelectorAll('#tradeTabs .trade-tab').forEach(function(b){
    b.classList.remove('active','sell-active','div-active');
    if(b.dataset.mode === m) {
      b.classList.add(m === 'sell' ? 'sell-active' : (m === 'div' ? 'div-active' : 'active'));
    }
  });
  // 设置modal主题属性
  var modal = document.getElementById('tradeModal');
  if (modal) { modal.setAttribute('data-mode', m); }
  // 场外/场内 单位切换逻辑
  var qtyLabel, submitText, btnCls;
  if (tState.is_inner) {
    // 场内ETF：可切换金额/份额
    qtyLabel = {buy:'成交金额', sell:'卖出数量', div:'分红金额'}[m];
    submitText = {buy:'确认买入', sell:'确认卖出', div:'确认记录'}[m];
    btnCls = m === 'sell' ? ' trade-btn-submit sell-mode' : (m === 'div' ? ' trade-btn-submit div-mode' : '');
    document.getElementById('tUnitToggle').style.display = (m !== 'div') ? '' : 'none';
    if (m === 'div') { setTUnit('amount'); } else { if (!tState.unit) setTUnit('amount'); updatePriceFieldVisibility(); }
  } else {
    // 场外基金
    if (m === 'buy') {
      // 场外买入：固定金额模式
      qtyLabel = '成交金额';
      submitText = '确认买入';
      btnCls = '';
      setTUnit('amount');
      document.getElementById('tUnitToggle').style.display = 'none';
    } else if (m === 'sell') {
      // 场外卖出：固定份额模式
      qtyLabel = '卖出份额';
      submitText = '确认卖出';
      btnCls = ' trade-btn-submit sell-mode';
      setTUnit('share');
      document.getElementById('tUnitToggle').style.display = 'none';
    } else {
      // 分红
      qtyLabel = '分红金额';
      submitText = '确认记录';
      btnCls = ' trade-btn-submit div-mode';
      setTUnit('amount');
      document.getElementById('tUnitToggle').style.display = 'none';
    }
  }
  document.getElementById('tQtyLabel').textContent = qtyLabel;
  document.getElementById('tSubmitBtn').className = 'trade-btn-submit' + btnCls;
  document.getElementById('tSubmitBtn').textContent = submitText;
  // 净值预览（场外买入时显示预估份额）
  updateNavPreview();
  calcFee();
}

function setTUnit(u) {
  tState.unit = u;
  document.querySelectorAll('#tUnitToggle .trade-toggle-btn').forEach(function(b){
    b.classList.toggle('active', b.dataset.u === u);
  });
  var qtyUnit = u === 'amount' ? 'CNY' : '份';
  var qtyPlaceholder = u === 'amount' ? '输入金额' : '输入份额';
  document.getElementById('tQtyUnit').textContent = qtyUnit;
  document.getElementById('tQty').placeholder = qtyPlaceholder;
  document.getElementById('tQtyIcon').innerHTML = u === 'amount' ? '&yen;' : '<span style="font-size:11px;opacity:.8;">#</span>';
  updatePriceFieldVisibility();
  calcFee();
}

function calcFee() {
  var qty = parseFloat(document.getElementById('tQty').value) || 0;
  var price = parseFloat(document.getElementById('tPrice').value) || 0;
  var fee = 0;

  // 未输入数量时不计算手续费（避免默认显示最低5元）
  if (!qty || qty <= 0) {
    var feeEl = document.getElementById('tFeeDisplay');
    feeEl.textContent = '\u514D\u8D39';
    feeEl.style.color = 'var(--down)';
    return;
  }

  var amount = (tState.unit === 'share') ? qty * price : qty;

  if (tState.mode === 'buy') {
    fee = tState.is_inner ? Math.max(amount * 0.00025, 5) : Math.round(amount * 0.0015 * 100) / 100;
  } else if (tState.mode === 'sell') {
    fee = tState.is_inner ? (Math.max(amount * 0.00025, 5) + amount * 0.001) : Math.round(amount * 0.005 * 100) / 100;
  }

  var feeEl = document.getElementById('tFeeDisplay');
  feeEl.textContent = fee > 0 ? '\u00A5' + fee.toFixed(2) : '\u514D\u8D39';
  feeEl.style.color = fee > 0 ? 'var(--up)' : 'var(--down)';
}

function updateNavPreview() {
  var preview = document.getElementById('tNavPreview');
  if (!preview) return;
  // 仅场外基金显示预估份额/金额
  if (tState.is_inner || !tState.nav || tState.nav <= 0) {
    preview.style.display = 'none';
    return;
  }
  var qty = parseFloat(document.getElementById('tQty').value) || 0;
  if (qty <= 0) {
    preview.style.display = 'none';
    return;
  }
  preview.style.display = '';
  var tplusNote = tState.is_tplus1 ? ' <span style="color:var(--tab-yellow);">（全球基金T+1确认净值，实际以确认净值为准）</span>' : '';
  if (tState.mode === 'buy') {
    // 金额 → 预估份额
    var shares = qty / tState.nav;
    preview.innerHTML = '预估份额: <b>' + shares.toFixed(2) + '</b> 份&nbsp;|&nbsp;净值 ' + tState.nav.toFixed(4) + tplusNote;
  } else if (tState.mode === 'sell') {
    // 份额 → 预估金额
    var amount = qty * tState.nav;
    preview.innerHTML = '预估金额: <b>¥' + amount.toFixed(2) + '</b>&nbsp;|&nbsp;净值 ' + tState.nav.toFixed(4) + tplusNote;
  } else {
    preview.style.display = 'none';
  }
}

function submitTrade() {
  var qty = parseFloat(document.getElementById('tQty').value);
  var price = parseFloat(document.getElementById('tPrice').value) || 0;
  var date = document.getElementById('tDate').value;
  if (!qty || qty <= 0) { alert('\u8BF7\u8F93\u5165\u6709\u6548\u6570\u91CF'); return; }
  if (!date) { alert('\u8BF7\u9009\u62E9\u4EA4\u6613\u65F6\u95F4'); return; }

  var amount = (tState.unit === 'share') ? Math.round(qty * price * 100) / 100 : qty;
  var shares = (tState.unit === 'share') ? qty : 0;
  var feeVal = parseFloat(document.getElementById('tFeeDisplay').textContent.replace(/[\u00A5,]/g,'')) || 0;

  var trade = {
    action: tState.mode, fund_name: tState.name, record_id: tState.rid,
    is_etf: tState.is_inner, is_tplus1: tState.is_tplus1,
    date: date, unit: tState.unit,
    quantity: qty, price_per_share: price,
    total_amount: Math.round(amount*100)/100, shares: shares, fee: Math.round(feeVal*100)/100,
    nav: tState.nav
  };

  // 下载 trade_pending.json 到本地
  var jsonStr = JSON.stringify(trade, null, 2);
  var blob = new Blob([jsonStr], {type: 'application/json'});
  var url = URL.createObjectURL(blob);
  var a = document.createElement('a');
  a.href = url;
  a.download = 'trade_pending.json';
  a.style.display = 'none';
  document.body.appendChild(a);
  a.click();
  setTimeout(function(){ document.body.removeChild(a); URL.revokeObjectURL(url); }, 200);

  var tip = '✅ ' + trade.fund_name + ' ' + ({buy:'买入',sell:'卖出',div:'分红'}[trade.action] || trade.action) + ' ¥' + trade.total_amount + ' 已记录！\n运行：python3 trade_manager.py';
  navigator.clipboard.writeText(jsonStr).then(function(){
    showToast(tip);
  }).catch(function(){
    showToast(tip);
  });
  closeTrade();
}

function showToast(msg) {
  var el = document.getElementById('tradeToast');
  if (msg) { el.textContent = msg; }
  el.classList.add('show');
  setTimeout(function(){
    el.classList.remove('show');
    el.textContent = '交易指令已复制，发送给老曹执行';
  }, 2800);
}

// ==================== 时间 ====================
var now = new Date();
document.getElementById('updateTime').textContent = 'Updated: ' + now.toLocaleString('zh-CN');
</script>
</body>
</html>'''

# ─── 13. 替换并输出 ──────────────────────────────────────
html = (html_template
    .replace("__HERO_CARD__", hero_card)
    .replace("__POSITION_CARDS__", position_cards)
    .replace("__DATA__", embedded_data)
    .replace("__EYE_OPEN__", EYE_OPEN_SVG)
    .replace("__EYE_CLOSED__", EYE_CLOSED_SVG))

output_path = os.path.join(CWD, "pnl_dashboard.html")
with open(output_path, "w") as f:
    f.write(html)

print(f"\n✅ 看板 v12 已生成: {output_path}")
print(f"   市值: ¥{total_cost + display_total_all_pnl:,.0f} | 总盈亏: {display_total_all_rate:+.2f}% | 今日: {total_day_rate:+.2f}%")
if ledger.get("realized_pnl"):
    print(f"   已实现盈亏: {ledger['realized_pnl']:+,.2f} (已锁定)")
