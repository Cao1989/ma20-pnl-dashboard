#!/usr/bin/env python3
"""
MA20净值表 - 每日数据后移脚本
每天18:00执行：D21→D20→D19→...→D3→D2，D1保持空值

数据流向（后移方向）：
  新D20 ← 旧D21
  新D19 ← 旧D20
  ...
  新D2  ← 旧D3
  D1  ← 永远为空（不写入）
"""
import subprocess
import json
import sys
import os
import tempfile
import time
from datetime import date
import chinese_calendar

BASE_TOKEN = "JWJ1bTzQ0aBETsseSJqcWn7EnJe"
TABLE_ID = "tblMcst8z8IYH72v"
USER_OPEN_ID = "ou_1d2af5f7db994ab6e0151176109f5057"

# 字段ID → 字段名（用于调试和校验）
ID_TO_NAME = {
    "fldWFYu1sW": "D21",
    "fldcVkLAoo": "D20",
    "fldtonHuMM": "D19",
    "fldwT8faxz": "D18",
    "fldyMA6D95": "D17",
    "fld6aSTbD8": "D16",
    "fldOb2igoY": "D15",
    "fldZilzQxW": "D14",
    "fldx9UbdOu": "D13",
    "fldkfyasH2": "D12",
    "fldx3IhWZ8": "D11",
    "fldS0V7dD8": "D10",
    "fldI4NHL0J": "D9",
    "fldZKpK6eO": "D8",
    "fldqHCNT5H": "D7",
    "fldtWeWkwR": "D6",
    "fldvPlyNIa": "D5",
    "fldzmwOxdr": "D4",
    "fldy32wH19": "D3",
    "fldUIOrA9s": "D2",
    "fldUVbGZZF": "D1",
}

# 后移映射：目标字段ID ← 源字段ID
# 新D20 = 旧D21, 新D19 = 旧D20, ...
SHIFT_MAP = {
    "fldcVkLAoo": "fldWFYu1sW",   # D20 ← D21
    "fldtonHuMM": "fldcVkLAoo",   # D19 ← D20
    "fldwT8faxz": "fldtonHuMM",   # D18 ← D19
    "fldyMA6D95": "fldwT8faxz",   # D17 ← D18
    "fld6aSTbD8": "fldyMA6D95",   # D16 ← D17
    "fldOb2igoY": "fld6aSTbD8",   # D15 ← D16
    "fldZilzQxW": "fldOb2igoY",   # D14 ← D15
    "fldx9UbdOu": "fldZilzQxW",   # D13 ← D14
    "fldkfyasH2": "fldx9UbdOu",   # D12 ← D13
    "fldx3IhWZ8": "fldkfyasH2",   # D11 ← D12
    "fldS0V7dD8": "fldx3IhWZ8",   # D10 ← D11
    "fldI4NHL0J": "fldS0V7dD8",   # D9  ← D10
    "fldZKpK6eO": "fldI4NHL0J",   # D8  ← D9
    "fldqHCNT5H": "fldZKpK6eO",   # D7  ← D8
    "fldtWeWkwR": "fldqHCNT5H",   # D6  ← D7
    "fldvPlyNIa": "fldtWeWkwR",   # D5  ← D6
    "fldzmwOxdr": "fldvPlyNIa",   # D4  ← D5
    "fldy32wH19": "fldzmwOxdr",   # D3  ← D4
    "fldUIOrA9s": "fldy32wH19",   # D2  ← D3
    # D1 (fldUVbGZZF) 不参与后移，保持空
}


def get_lark_cli():
    """找到 lark-cli 可执行文件路径"""
    # 先试 which
    r = subprocess.run(["which", "lark-cli"], capture_output=True, text=True)
    if r.returncode == 0 and r.stdout.strip():
        return "lark-cli"
    # 尝试常见安装路径
    candidates = [
        "/opt/homebrew/bin/lark-cli",
        "/usr/local/bin/lark-cli",
        os.path.expanduser("~/.npm/bin/lark-cli"),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    raise RuntimeError("找不到 lark-cli，请确保已安装并在 PATH 中")


def run_lark(args, label=""):
    """调用 lark-cli，返回 (ok, stdout, stderr)"""
    cli = get_lark_cli()
    cmd = [cli] + args
    print(f"  执行: {' '.join(cmd[:6])}...")
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"  [ERROR] {label or '命令失败'}")
        print(f"  stderr: {r.stderr[:300]}")
        return False, r.stdout, r.stderr
    return True, r.stdout, r.stderr


def send_feishu_msg(markdown_text):
    """发送飞书消息给用户（--as bot，更稳定）"""
    cli = get_lark_cli()
    r = subprocess.run([
        cli, "im", "+messages-send",
        "--user-id", USER_OPEN_ID,
        "--as", "bot",
        "--markdown", markdown_text,
    ], capture_output=True, text=True)
    if r.returncode != 0:
        print(f"  [WARN] 飞书消息发送失败: {r.stderr[:200]}")


def main():
    # ─── 交易日检查 ─────────────────────────────────────────
    today = date.today()
    weekday_cn = ["周一","周二","周三","周四","周五","周六","周日"][today.weekday()]
    if not chinese_calendar.is_workday(today):
        print(f"=== MA20净值表 每日数据后移 ===")
        print(f"  今天 {today.strftime('%Y-%m-%d')} {weekday_cn} 为非交易日，跳过执行。")
        return

    print("=== MA20净值表 每日数据后移 ===")

    cli = get_lark_cli()
    print(f"使用 lark-cli: {cli}")

    # 1. 读取所有记录（JSON格式）
    print("\n[1/3] 读取MA20净值表记录...")
    ok, stdout, _ = run_lark([
        "base", "+record-list",
        "--base-token", BASE_TOKEN,
        "--table-id", TABLE_ID,
        "--as", "user",
        "--format", "json",
    ], "读取记录")
    if not ok:
        sys.exit(1)

    resp = json.loads(stdout)
    data = resp["data"]
    records = data["data"]            # list of lists
    field_id_list = data["field_id_list"]   # 每个数组位置对应的字段ID
    record_id_list = data["record_id_list"] # 每条记录对应的record_id

    print(f"  共 {len(records)} 条记录，{len(field_id_list)} 个字段")

    # 2. 定位每个 D 字段在 field_id_list 中的位置
    print("\n[2/3] 定位字段位置...")
    field_pos = {}  # field_id -> array_index
    for idx, fid in enumerate(field_id_list):
        field_pos[fid] = idx

    # 校验所有需要的字段都在
    for target_fid in SHIFT_MAP:
        if target_fid not in field_pos:
            print(f"  [WARN] 目标字段 {ID_TO_NAME.get(target_fid, target_fid)} 未在表格中找到")
        source_fid = SHIFT_MAP[target_fid]
        if source_fid not in field_pos:
            print(f"  [WARN] 源字段 {ID_TO_NAME.get(source_fid, source_fid)} 未在表格中找到")

    # 3. 构造批量更新数据
    print("\n[3/3] 构造后移更新数据...")
    updates = []
    for rec_idx, rec in enumerate(records):
        rid = record_id_list[rec_idx]
        update_fields = {}

        for target_fid, source_fid in SHIFT_MAP.items():
            src_pos = field_pos.get(source_fid)
            if src_pos is None or src_pos >= len(rec):
                continue
            val = rec[src_pos]
            # 空值（None、空字符串）不写入（让目标字段变为空）
            if val is None or val == "":
                # 写入 None 来清空字段
                update_fields[ID_TO_NAME[target_fid]] = None
            else:
                # 确保是 float，保留4位小数
                try:
                    update_fields[ID_TO_NAME[target_fid]] = round(float(val), 4)
                except (ValueError, TypeError):
                    update_fields[ID_TO_NAME[target_fid]] = None

        # 关键：后移完成后必须清空 D21，确保第二天净值获取能正常填入新值
        update_fields["D21"] = None
        updates.append({
            "record_id": rid,
            "fields": update_fields
        })

    print(f"  需要更新 {len(updates)} 条记录")

    if not updates:
        print("  没有需要更新的记录，退出。")
        return

    # 4. 逐条执行更新（使用 +record-upsert）
    print("\n[4/4] 执行逐条更新...")
    success_count = 0
    for i, item in enumerate(updates):
        rid = item["record_id"]
        fields = item["fields"]
        fields_json = json.dumps(fields, ensure_ascii=False)
        
        ok, stdout, _ = run_lark([
            "base", "+record-upsert",
            "--base-token", BASE_TOKEN,
            "--table-id", TABLE_ID,
            "--record-id", rid,
            "--as", "user",
            "--json", fields_json,
        ], f"更新记录 {i+1}/{len(updates)}")
        
        if ok:
            success_count += 1
        else:
            print(f"  ✗ 记录 {i+1} ({rid[:8]}) 更新失败")
        
        time.sleep(0.1)
    
    print(f"  更新成功 {success_count}/{len(updates)} 条")

    # 5. 清零底层数据表的「盈亏_日」字段（新的一天从 0 开始）
    print("\n[5/5] 清零底层表「盈亏_日」字段...")
    BOTTOM_TABLE_ID = "tbl6QMWWCrGLbgtS"
    PNL_DAY_FIELD = "盈亏_日"
    # 读取底层表所有 record_id
    ok_b, stdout_b, _ = run_lark([
        "base", "+record-list",
        "--base-token", BASE_TOKEN,
        "--table-id", BOTTOM_TABLE_ID,
        "--as", "user", "--format", "json",
    ], "读取底层数据表")
    if ok_b:
        resp_b = json.loads(stdout_b)
        bottom_record_ids = resp_b["data"]["record_id_list"]
        clear_ok = 0
        for rid_b in bottom_record_ids:
            ok_c, _, _ = run_lark([
                "base", "+record-upsert",
                "--base-token", BASE_TOKEN,
                "--table-id", BOTTOM_TABLE_ID,
                "--record-id", rid_b,
                "--as", "user",
                "--json", '{"' + PNL_DAY_FIELD + '": 0}',
            ], f"清零 {rid_b[:8]}")
            if ok_c:
                clear_ok += 1
            time.sleep(0.1)
        print(f"  盈亏_日 清零完成: {clear_ok}/{len(bottom_record_ids)} 条")
    else:
        print("  [WARN] 底层表读取失败，盈亏_日 清零跳过")

    # 发送飞书通知
    time_str = time.strftime("%H:%M", time.localtime())
    total = len(updates)
    if success_count == total:
        msg = (
            f"📋 **老曹投资助手 数据后移完成**\n\n"
            f"**时间：** {time_str}\n"
            f"**更新：** {success_count}/{total} 条记录\n\n"
            f"D21 已清空，17:00 起开始填入今日净值。"
        )
    else:
        fail_count = total - success_count
        msg = (
            f"📋 **老曹投资助手 数据后移完成（有异常）**\n\n"
            f"**时间：** {time_str}\n"
            f"**更新：** {success_count}/{total} 条\n"
            f"**失败：** {fail_count} 条，请检查日志\n\n"
            f"D21 已清空，17:00 起开始填入今日净值。"
        )
    send_feishu_msg(msg)

    print("\n=== 数据后移完成 ===")


if __name__ == "__main__":
    main()
