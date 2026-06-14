# MA20 云端迁移 — 配置指南

完成以下 3 步后，所有自动化将在 GitHub 云端运行，**电脑关机也不影响**。

---

## 第 1 步：创建飞书应用

### 1.1 进入飞书开发者后台
打开 https://open.feishu.cn/app → 点击「创建企业自建应用」

### 1.2 填写基本信息
- **应用名称**：`老曹投资助手`
- **应用描述**：`MA20 净值表自动化`

### 1.3 添加权限（「权限管理」→「API 权限」→ 搜索并开通）
| 权限 | 用途 |
|------|------|
| `bitable:app` | 读写多维表格 |
| `im:message:send_as_bot` | 发送飞书消息 |

### 1.4 创建应用版本并发布
- 「版本管理」→「创建版本」→ 填写版本号 `1.0.0` → 提交发布
- 等待管理员（你自己）审核通过

### 1.5 授权多维表格
- 打开飞书多维表格（你的 MA20 净值表）
- 右上角「…」→「更多」→「添加文档应用」
- 搜索「老曹投资助手」→ 添加

### 1.6 获取凭据
- 「凭证与基础信息」页面，复制：
  - **App ID** → 稍后填入 GitHub Secrets
  - **App Secret** → 稍后填入 GitHub Secrets

---

## 第 2 步：创建 GitHub 仓库

### 2.1 创建新仓库
打开 https://github.com/new

- **仓库名**：`ma20-pnl-dashboard`（或任何你喜欢的名字）
- **可见性**：**Public**（GitHub Pages 免费要求公开仓库）
- ⚠️ 不要勾选「Initialize with README」

### 2.2 推送代码
在你的电脑终端执行（我已经帮你准备好了所有文件）：

```bash
cd /Users/vking/WorkBuddy/MA20-Cloud-Migration

# 初始化 Git
git init
git add -A
git commit -m "MA20 云端自动化 v1"

# 连接远程仓库（替换为你的仓库地址）
git remote add origin https://github.com/你的用户名/ma20-pnl-dashboard.git
git branch -M main
git push -u origin main
```

### 2.3 设置 Secrets
- 仓库页面 → `Settings` → `Secrets and variables` → `Actions`
- 点击 `New repository secret`，添加：

| 名称 | 值 |
|------|-----|
| `FEISHU_APP_ID` | 飞书应用的 App ID |
| `FEISHU_APP_SECRET` | 飞书应用的 App Secret |

### 2.4 启用 GitHub Pages
- 仓库页面 → `Settings` → `Pages`
- Source: `Deploy from a branch`
- Branch: `gh-pages` `/ (root)`
- 点击 Save

等待 1-2 分钟后，看板地址：
```
https://你的用户名.github.io/ma20-pnl-dashboard/
```

---

## 第 3 步：验证

### 3.1 手动触发测试
- 仓库页面 → `Actions` 标签
- 选择任一 workflow → `Run workflow` → 手动运行
- 观察运行日志，确认无报错

### 3.2 检查飞书消息
确认收到飞书通知消息。

### 3.3 首次看板部署
手动运行 `看板刷新+部署` workflow，等待完成后访问 GitHub Pages 地址。

---

## 自动化排程总览

| 北京时间 | 任务 | Workflow |
|----------|------|----------|
| 08:00 | 数据后移 | `shift.yml` |
| 17:00~22:30 | 净值获取（每30分钟） | `fetch-nav.yml` |
| 22:30 | 回撤≥10%提醒 | `check-drop.yml` |
| 22:35 | 盈亏看板刷新+部署 | `dashboard.yml` |
| 23:00 | 飞书推送每日简报 | `push.yml` |

**全部在工作日（周一至周五）自动执行，无需电脑开机。**

---

## 备选方案

### 如果不想公开仓库
GitHub Pages 免费版需要公开仓库。如果必须私有：
- **方案 A**：升级到 GitHub Pro（约 $4/月）
- **方案 B**：用 CloudStudio 托管看板（保持现有固定 URL），GitHub Actions 只跑数据同步和飞书推送

### 如果 GitHub Actions 延迟较大
GitHub Actions 免费版可能有排队延迟（通常 < 5 分钟）。如果对实时性要求高，可升级到 GitHub Team 或改用其他 CI 服务。
