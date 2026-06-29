#!/usr/bin/env python3
"""
B站动态监控脚本
监控指定UP主的动态更新，通过Server酱推送到微信。

使用方式:
    python bili_monitor.py

环境变量:
    SERVER_CHAN_SENDKEY   Server酱 SendKey (必需)
    BILI_UID              B站用户UID (可选，默认 11473291)

状态文件:
    state.json            记录上次最新动态ID，自动维护
"""

import hashlib
import json
import os
import sys
import time
import urllib.parse

import requests

# ============================================================
# 配置
# ============================================================
BILI_UID = os.environ.get("BILI_UID", "11473291")
SENDKEY = os.environ.get("SERVER_CHAN_SENDKEY", "")
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")

# 动态类型中文映射
TYPE_NAME = {
    "DYNAMIC_TYPE_DRAW": "图文",
    "DYNAMIC_TYPE_AV": "视频",
    "DYNAMIC_TYPE_ARTICLE": "专栏",
    "DYNAMIC_TYPE_LIVE_RCMD": "直播",
    "DYNAMIC_TYPE_FORWARD": "转发",
    "DYNAMIC_TYPE_WORD": "纯文字",
}

# WBI 混音密钥映射表
MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
    37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
    22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52,
]


# ============================================================
# 工具函数
# ============================================================

def get_mixin_key(raw: str) -> str:
    """从原始密钥拼接串中提取32位混音密钥"""
    return "".join(raw[n] for n in MIXIN_KEY_ENC_TAB)[:32]


def sign_params(params: dict, img_key: str, sub_key: str) -> dict:
    """对请求参数进行 WBI 签名，添加 wts 和 w_rid"""
    mixin_key = get_mixin_key(img_key + sub_key)
    params["wts"] = int(time.time())
    params = dict(sorted(params.items()))
    query = urllib.parse.urlencode(params)
    w_rid = hashlib.md5((query + mixin_key).encode()).hexdigest()
    params["w_rid"] = w_rid
    return params


def load_state() -> dict:
    """读取状态文件"""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {"last_dynamic_id": "0", "up_name": ""}


def save_state(state: dict):
    """写入状态文件"""
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


# ============================================================
# B站 API
# ============================================================

def create_session() -> requests.Session:
    """创建带浏览器伪装头的 Session，并预取 Cookie（带重试）"""
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;"
            "q=0.9,image/avif,image/webp,*/*;q=0.8"
        ),
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Cache-Control": "no-cache",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
    })
    # 依次访问主站和 UP 空间页获取完整 Cookie
    for url in [
        "https://www.bilibili.com/",
        f"https://space.bilibili.com/{BILI_UID}/dynamic",
    ]:
        for attempt in range(3):
            try:
                resp = session.get(url, timeout=15, allow_redirects=True)
                if resp.status_code == 200:
                    break
            except requests.RequestException:
                if attempt < 2:
                    time.sleep(2 ** attempt)
    return session


def get_wbi_keys(session: requests.Session) -> tuple:
    """从 nav 接口获取 WBI 签名所需的 img_key 和 sub_key（带重试）"""
    for attempt in range(3):
        try:
            resp = session.get(
                "https://api.bilibili.com/x/web-interface/nav",
                timeout=10,
                headers={
                    "User-Agent": session.headers.get("User-Agent", ""),
                    "Accept": "application/json, text/plain, */*",
                    "Referer": f"https://space.bilibili.com/{BILI_UID}/dynamic",
                    "Origin": "https://space.bilibili.com",
                },
            )
            print(f"  [调试] nav API status={resp.status_code}, "
                  f"content-type={resp.headers.get('Content-Type','?')[:50]}, "
                  f"body_len={len(resp.text)}, body[:200]={resp.text[:200]}")
            # 检查是否被风控（返回 HTML 而非 JSON）
            ct = resp.headers.get("Content-Type", "")
            if "text/html" in ct:
                if attempt < 2:
                    wait = 3 * (attempt + 1)
                    print(f"  [风控] nav 接口返回 HTML，{wait}秒后重试 ({attempt + 1}/3)...")
                    time.sleep(wait)
                    continue
                raise RuntimeError("nav API 被风控拦截，返回 HTML 页面")
            if not resp.text.strip():
                if attempt < 2:
                    wait = 3 * (attempt + 1)
                    print(f"  [风控] nav 接口返回空内容，{wait}秒后重试 ({attempt + 1}/3)...")
                    time.sleep(wait)
                    continue
                raise RuntimeError("nav API 返回空内容")
            data = resp.json()
            wbi_img = data["data"]["wbi_img"]
            img_key = wbi_img["img_url"].rsplit("/", 1)[-1].split(".")[0]
            sub_key = wbi_img["sub_url"].rsplit("/", 1)[-1].split(".")[0]
            return img_key, sub_key
        except (requests.RequestException, KeyError, json.JSONDecodeError) as e:
            if attempt < 2:
                print(f"  [重试] get_wbi_keys 失败 (尝试 {attempt + 1}/3): {e}")
                time.sleep(2 ** attempt)
    raise RuntimeError("获取 WBI 密钥失败，已重试 3 次")


def fetch_dynamics(session: requests.Session, uid: str, img_key: str, sub_key: str) -> list:
    """获取指定用户的动态列表（带重试）"""
    for attempt in range(3):
        try:
            params = sign_params(
                {"host_mid": uid, "timezone_offset": "-480"},
                img_key,
                sub_key,
            )
            resp = session.get(
                "https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/space",
                params=params,
                timeout=15,
                headers={
                    "Accept": "application/json, text/plain, */*",
                    "Referer": f"https://space.bilibili.com/{uid}/dynamic",
                    "Origin": "https://space.bilibili.com",
                },
            )
            data = resp.json()
            if data.get("code") == -412:
                # 风控拦截，等一会儿重试
                if attempt < 2:
                    wait = 3 * (attempt + 1)
                    print(f"  [风控] 412 被拦截，{wait}秒后重试 ({attempt + 1}/3)...")
                    time.sleep(wait)
                    continue
                raise RuntimeError("B站风控拦截 (412)，已重试 3 次")
            if data.get("code") != 0:
                raise RuntimeError(f"API错误: code={data.get('code')}, msg={data.get('message')}")
            return data["data"].get("items", [])
        except (requests.RequestException, KeyError) as e:
            if attempt < 2:
                print(f"  [重试] fetch_dynamics 失败 (尝试 {attempt + 1}/3): {e}")
                time.sleep(2 ** attempt)
    raise RuntimeError("获取动态列表失败，已重试 3 次")


# ============================================================
# 内容提取
# ============================================================

def extract_dynamic_info(item: dict) -> dict:
    """从单条动态中提取标题和摘要信息"""
    try:
        modules = item.get("modules") or {}
        md = modules.get("module_dynamic") or {}
        author = modules.get("module_author") or {}

        dtype = item.get("type", "DYNAMIC_TYPE_WORD")
        type_cn = TYPE_NAME.get(dtype, "动态")

        # 文本描述
        desc = md.get("desc")
        desc_text = desc.get("text", "") if isinstance(desc, dict) else ""

        # 根据类型提取附加信息
        extra = ""
        major = md.get("major") or {}
        if major.get("archive"):
            a = major["archive"]
            if isinstance(a, dict):
                extra = f"[{a.get('title', '')}] {a.get('desc', '')}"
        elif major.get("draw"):
            d = major["draw"]
            if isinstance(d, dict):
                count = len(d.get("items") or [])
                extra = f"共{count}张图片"
        elif major.get("article"):
            ar = major["article"]
            if isinstance(ar, dict):
                extra = ar.get("title", "")
        elif major.get("live_rcmd"):
            lr = major["live_rcmd"]
            if isinstance(lr, dict):
                # content 可能是 JSON 字符串或 dict
                lr_content = lr.get("content")
                if isinstance(lr_content, str):
                    try:
                        lr_content = json.loads(lr_content)
                    except json.JSONDecodeError:
                        lr_content = {}
                if isinstance(lr_content, dict):
                    live_info = lr_content.get("live_play_info") or {}
                    if isinstance(live_info, dict):
                        room_id = live_info.get("room_id", "")
                        title = live_info.get("title", "")
                        extra = f"直播间 {room_id}"
                        if title:
                            extra += f" - {title}"
                        else:
                            extra = "正在直播"
                    else:
                        extra = "正在直播"
                else:
                    extra = "正在直播"

        # 合并内容
        content = desc_text
        if extra and extra not in content:
            content = f"{content}\n{extra}" if content else extra

        # 置顶判断
        tag = modules.get("module_tag")
        is_pinned = tag.get("text") == "置顶" if isinstance(tag, dict) else False

        return {
            "dynamic_id": item.get("id_str", ""),
            "type": dtype,
            "type_cn": type_cn,
            "content": content.strip(),
            "author": author.get("name", "") if isinstance(author, dict) else "",
            "pub_time": author.get("pub_time", "") if isinstance(author, dict) else "",
            "is_pinned": is_pinned,
        }
    except Exception as e:
        # 单条解析失败不中断整体流程
        print(f"  [警告] 解析动态失败: {e}, item_id={item.get('id_str', '?')[:20]}")
        return {
            "dynamic_id": item.get("id_str", "0"),
            "type": item.get("type", "DYNAMIC_TYPE_WORD"),
            "type_cn": "动态",
            "content": "(解析失败)",
            "author": "",
            "pub_time": "",
            "is_pinned": False,
        }


# ============================================================
# 通知
# ============================================================

def send_server_chan(title: str, content: str):
    """通过 Server酱 发送微信通知"""
    if not SENDKEY:
        print("[跳过] 未配置 SERVER_CHAN_SENDKEY，不发送通知")
        return

    url = f"https://sctapi.ftqq.com/{SENDKEY}.send"
    payload = {
        "title": title,
        "desp": content.replace("\n", "\n\n"),
    }
    try:
        resp = requests.post(url, data=payload, timeout=15)
        result = resp.json()
        if result.get("code") == 0:
            print(f"[通知] 已发送: {title}")
        else:
            print(f"[通知] 发送失败: {result}")
    except requests.RequestException as e:
        print(f"[通知] 请求异常: {e}")


def notify_dynamic(info: dict):
    """构造通知并发送到微信"""
    url = f"https://space.bilibili.com/{BILI_UID}/dynamic"

    title = f"【B站动态】{info['author']} 发了新{info['type_cn']}"

    content = (
        f"## {info['author']} 发布了新{info['type_cn']}\n\n"
        f"> {info['content'][:300]}"
    )
    if len(info["content"]) > 300:
        content += "..."
    content += (
        f"\n\n---\n"
        f"🕐 发布时间: {info['pub_time']}\n"
        f"🔗 [查看动态]({url})"
    )

    send_server_chan(title, content)


# ============================================================
# 主流程
# ============================================================

def main():
    print(f"[启动] B站动态监控 | UID={BILI_UID}")

    # 1. 读取上次状态
    state = load_state()
    last_id = state.get("last_dynamic_id", "0")
    print(f"[状态] 上次最新动态ID: {last_id}")

    # 2. 创建会话并获取动态
    session = create_session()
    print(f"[调试] Session cookies: {dict(session.cookies)}")
    try:
        img_key, sub_key = get_wbi_keys(session)
        items = fetch_dynamics(session, BILI_UID, img_key, sub_key)
    except Exception as e:
        print(f"[错误] 获取动态失败: {e}")
        sys.exit(1)
    finally:
        session.close()

    print(f"[获取] 共 {len(items)} 条动态")

    if not items:
        print("[结束] 无动态数据")
        return

    # 3. 提取所有动态信息
    all_infos = [extract_dynamic_info(item) for item in items]

    # 更新 UP 主名称
    if all_infos and all_infos[0]["author"]:
        state["up_name"] = all_infos[0]["author"]

    # 4. 找出新动态（id_str 比 last_id 大的，且非置顶）
    new_infos = []
    for info in all_infos:
        if info["dynamic_id"] > last_id and not info["is_pinned"]:
            new_infos.append(info)

    if not new_infos:
        print("[结束] 没有新动态")
        # 即使没有新动态，也更新 last_id 为当前最新（处理置顶等边界情况）
        newest = max(all_infos, key=lambda x: x["dynamic_id"])
        state["last_dynamic_id"] = newest["dynamic_id"]
        save_state(state)
        return

    print(f"[新动态] 发现 {len(new_infos)} 条新动态")

    # 5. 按时间正序发送通知（最早的新动态先发）
    new_infos.reverse()
    for info in new_infos:
        print(f"  -> [{info['type_cn']}] {info['content'][:60]}...")
        notify_dynamic(info)
        # 每条通知之间间隔 1 秒，避免 Server酱 限流
        time.sleep(1)

    # 6. 更新状态
    newest = max(all_infos, key=lambda x: x["dynamic_id"])
    state["last_dynamic_id"] = newest["dynamic_id"]
    save_state(state)
    print(f"[完成] 已更新状态，最新动态ID: {newest['dynamic_id']}")


if __name__ == "__main__":
    main()
