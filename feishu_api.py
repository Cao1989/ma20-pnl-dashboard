#!/usr/bin/env python3
"""
飞书 OpenAPI 封装模块 —— 替代 lark-cli，供 GitHub Actions 云端运行。

用法:
    from feishu_api import base_list_records, base_update_record, send_feishu_msg

环境变量（需在 GitHub Secrets 中配置）:
    FEISHU_APP_ID      飞书应用 App ID
    FEISHU_APP_SECRET  飞书应用 App Secret
"""

import json
import os
import time
import urllib.request
import urllib.error

# ─── 配置 ────────────────────────────────────────────────

FEISHU_APP_ID = os.environ.get("FEISHU_APP_ID", "")
FEISHU_APP_SECRET = os.environ.get("FEISHU_APP_SECRET", "")
FEISHU_API_BASE = "https://open.feishu.cn/open-apis"
BOT_OPEN_ID = os.environ.get("FEISHU_BOT_OPEN_ID", "")

# token 缓存
_token_cache = {"token": "", "expires_at": 0}


# ─── 认证 ────────────────────────────────────────────────

def _get_tenant_token():
    """获取 tenant_access_token（带缓存）"""
    now = time.time()
    if _token_cache["token"] and now < _token_cache["expires_at"] - 60:
        return _token_cache["token"]

    if not FEISHU_APP_ID or not FEISHU_APP_SECRET:
        raise RuntimeError("请设置环境变量 FEISHU_APP_ID 和 FEISHU_APP_SECRET")

    url = f"{FEISHU_API_BASE}/auth/v3/tenant_access_token/internal"
    body = json.dumps({
        "app_id": FEISHU_APP_ID,
        "app_secret": FEISHU_APP_SECRET,
    }).encode("utf-8")

    req = urllib.request.Request(url, data=body, headers={
        "Content-Type": "application/json; charset=utf-8",
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        raise RuntimeError(f"获取 tenant token 失败: {e.code} {body}")

    if data.get("code") != 0:
        raise RuntimeError(f"获取 tenant token 失败: {data.get('msg')}")

    _token_cache["token"] = data["tenant_access_token"]
    _token_cache["expires_at"] = now + data.get("expire", 7200)
    return _token_cache["token"]


def _api(method, path, body=None):
    """通用飞书 API 请求"""
    token = _get_tenant_token()
    url = f"{FEISHU_API_BASE}{path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }

    body_bytes = json.dumps(body).encode("utf-8") if body else None
    req = urllib.request.Request(url, data=body_bytes, headers=headers, method=method)

    max_retries = 2
    for attempt in range(max_retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read().decode("utf-8"))
            code = result.get("code", -1)
            if code == 0:
                return result
            # 频率限制
            if code == 99991400 and attempt < max_retries:
                time.sleep(1.5)
                continue
            raise RuntimeError(f"API {method} {path} 错误: code={code} msg={result.get('msg','')}")
        except urllib.error.HTTPError as e:
            body_text = e.read().decode("utf-8")
            if attempt < max_retries:
                time.sleep(1.5)
                continue
            raise RuntimeError(f"HTTP {e.code}: {body_text}")


# ─── 多维表格 (Bitable) ─────────────────────────────────

def base_list_records(base_token, table_id, page_size=500):
    """
    读取表格全部记录。
    返回: {
        "field_id_list": ["fldxxx", ...],
        "fields": ["字段名1", ...],
        "data": [["值1", "值2", ...], ...],
        "record_id_list": ["recxxx", ...],
    }
    格式兼容原 lark-cli +record-list --format json 的输出。
    """
    all_items = []
    page_token = None

    while True:
        path = f"/bitable/v1/apps/{base_token}/tables/{table_id}/records?page_size={page_size}"
        if page_token:
            path += f"&page_token={page_token}"

        result = _api("GET", path)
        d = result.get("data", {})
        items = d.get("items", [])
        all_items.extend(items)

        if not d.get("has_more"):
            break
        page_token = d.get("page_token", "")

    if not all_items:
        return {"field_id_list": [], "fields": [], "data": [], "record_id_list": []}

    # 收集所有字段ID和名称
    field_id_set = {}
    for item in all_items:
        for fid in item.get("fields", {}):
            if fid not in field_id_set:
                field_id_set[fid] = fid  # 暂时用fid当名称，后面补

    # 获取字段元数据（名称映射）
    try:
        meta_result = _api("GET", f"/bitable/v1/apps/{base_token}/tables/{table_id}/fields")
        for f in meta_result.get("data", {}).get("items", []):
            fid = f.get("field_id", "")
            fname = f.get("field_name", "")
            if fid:
                field_id_set[fid] = fname
    except Exception:
        pass  # 降级：字段名用 field_id

    field_ids = list(field_id_set.keys())
    field_names = [field_id_set[fid] for fid in field_ids]

    # 转为数组格式
    data_rows = []
    record_ids = []
    for item in all_items:
        fields = item.get("fields", {})
        row = []
        for fid in field_ids:
            val = fields.get(fid)
            row.append(val)
        data_rows.append(row)
        record_ids.append(item.get("record_id", ""))

    return {
        "field_id_list": field_ids,
        "fields": field_names,
        "data": data_rows,
        "record_id_list": record_ids,
    }


def base_update_record(base_token, table_id, record_id, fields):
    """更新单条记录。fields 为 {字段名或field_id: 值} 字典。"""
    path = f"/bitable/v1/apps/{base_token}/tables/{table_id}/records/{record_id}"
    _api("PUT", path, {"fields": fields})


def base_batch_update(base_token, table_id, records):
    """
    批量更新记录。
    records = [{"record_id": "recxxx", "fields": {"字段名": 值, ...}}, ...]
    """
    # 飞书批量接口一次最多500条
    BATCH_SIZE = 500
    for i in range(0, len(records), BATCH_SIZE):
        batch = records[i:i + BATCH_SIZE]
        path = f"/bitable/v1/apps/{base_token}/tables/{table_id}/records/batch_update"
        _api("POST", path, {"records": batch})


def base_create_field(base_token, table_id, field_name, field_type=1):
    """
    创建字段。
    field_type: 1=文本, 2=数字, 3=单选, 4=多选,  ...
    返回: field_id
    """
    path = f"/bitable/v1/apps/{base_token}/tables/{table_id}/fields"
    body = {
        "field_name": field_name,
        "type": field_type,
    }
    result = _api("POST", path, body)
    return result.get("data", {}).get("field", {}).get("field_id", "")


def base_ensure_field(base_token, table_id, field_name, field_type=1):
    """
    确保字段存在，不存在则创建。
    返回: (field_id, 是否已存在)
    """
    # 先列出现有字段
    try:
        meta_result = _api("GET", f"/bitable/v1/apps/{base_token}/tables/{table_id}/fields")
        for f in meta_result.get("data", {}).get("items", []):
            if f.get("field_name") == field_name:
                return f.get("field_id", ""), True
    except Exception:
        pass
    # 不存在，创建
    field_id = base_create_field(base_token, table_id, field_name, field_type)
    return field_id, False


# ─── 消息 ───────────────────────────────────────────────

def send_feishu_msg(markdown_text):
    """
    发送飞书消息（使用 bot 身份）。
    使用 markdown 格式需要 msg_type=interactive 并包装。
    """
    # 飞书发送消息API，机器人发 markdown → 使用 post 消息
    # 这里用 text 格式简单发送，markdown 内容用 text 呈现
    content = json.dumps({"text": markdown_text}, ensure_ascii=False)

    body = {
        "receive_id": BOT_OPEN_ID or "ou_c864f9db22e3208dd09b3655107d0731",
        "msg_type": "text",
        "content": content,
    }
    _api("POST", "/im/v1/messages?receive_id_type=open_id", body)
