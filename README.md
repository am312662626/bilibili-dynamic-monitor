# B站动态微信监控

监控指定 B站 UP 主的动态更新，有新动态时通过 **Server酱** 实时推送到你的微信。

> 🎯 当前监控: [UID 11473291](https://space.bilibili.com/11473291/dynamic)

## 工作原理

```
GitHub Actions (每5分钟)
    │
    ▼
bili_monitor.py
    │
    ├─ ① 访问 bilibili.com 获取 Cookie
    ├─ ② 获取 WBI 签名密钥
    ├─ ③ 调用动态 API (WBI签名) 获取最新动态
    ├─ ④ 对比 state.json 中的 last_dynamic_id
    ├─ ⑤ 新动态 → Server酱 → 微信通知
    └─ ⑥ 更新 state.json 提交回仓库
```

## 快速开始

### 1. 获取 Server酱 SendKey

1. 打开 [Server酱](https://sct.ftqq.com/)
2. 微信扫码登录
3. 复制你的 **SendKey**（类似 `SCT123456...`）

### 2. Fork 并配置仓库

1. Fork 本仓库到你的 GitHub 账号
2. 进入仓库 **Settings → Secrets and variables → Actions**
3. 点击 **New repository secret**
4. Name: `SERVER_CHAN_SENDKEY`
5. Value: 粘贴你的 SendKey
6. 点击 **Add secret**

### 3. 启用 Actions

1. 进入仓库 **Actions** 标签页
2. 点击 "I understand my workflows, go ahead and enable them"
3. 手动触发一次测试: **Actions → B站动态监控 → Run workflow**

### 4. (可选) 修改监控目标

编辑 `.github/workflows/monitor.yml`，修改 `BILI_UID` 环境变量:

```yaml
env:
  BILI_UID: "11473291"   # 改成你想监控的 UID
```

或者编辑 `bili_monitor.py` 顶部的 `BILI_UID` 默认值。

## 文件说明

| 文件 | 说明 |
|------|------|
| `bili_monitor.py` | 核心监控脚本 |
| `state.json` | 状态文件，记录上次最新动态ID（自动维护） |
| `requirements.txt` | Python 依赖 |
| `.github/workflows/monitor.yml` | GitHub Actions 定时任务配置 |

## 本地运行

```bash
# 安装依赖
pip install -r requirements.txt

# 设置环境变量并运行
set SERVER_CHAN_SENDKEY=你的SendKey
python bili_monitor.py
```

## 频率限制

- GitHub Actions 免费版最短间隔为 **5 分钟**
- Server酱 免费版每天最多 **5 条**通知（升级后可更多）

## License

MIT
