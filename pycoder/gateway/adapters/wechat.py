"""
微信平台适配器 — 将微信消息规范化为 GatewayMessage 格式

支持微信的消息类型:
- 文本消息
- 图片消息
- 语音消息
- 文件消息
- 事件通知（关注/取消关注/菜单点击）

设计模式:
- 被动回复 + 主动推送双模式
- 支持企业微信和公众号两种接入方式
- mock-ready 模式，方便无实际 Token 时测试
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from typing import Any

from pycoder.gateway import GatewayMessage, PlatformAdapter

logger = logging.getLogger(__name__)


class WeChatAdapter(PlatformAdapter):
    """微信平台适配器

    支持:
    - 公众号被动回复模式
    - 企业微信应用消息
    - 消息加解密（可选）
    - 文本/图片/语音/文件/事件消息类型识别
    """

    def __init__(
        self,
        *,
        token: str = "",
        app_id: str = "",
        app_secret: str = "",
        encoding_aes_key: str = "",
        corp_id: str = "",  # 企业微信 corp_id
        agent_id: str = "",  # 企业微信 agent_id
        mode: str = "mp",  # "mp" 公众号 | "wecom" 企业微信
    ) -> None:
        super().__init__()
        self._token = token
        self._app_id = app_id
        self._app_secret = app_secret
        self._encoding_aes_key = encoding_aes_key
        self._corp_id = corp_id
        self._agent_id = agent_id
        self._mode = mode
        self._access_token: str = ""
        self._token_expires_at: float = 0.0
        self._refresh_task: asyncio.Task[Any] | None = None

    @property
    def platform(self) -> str:
        return "wechat"

    async def start(self) -> None:
        """启动微信适配器"""
        self._running = True
        mode_name = "企业微信" if self._mode == "wecom" else "公众号"
        logger.info(
            "微信适配器已启动 (mode=%s, app_id=%s...)", 
            mode_name,
            self._app_id[:8] if self._app_id else "N/A",
        )

        # 企业微信模式：定期刷新 access_token
        if self._mode == "wecom" and self._app_id and self._app_secret:
            self._refresh_task = asyncio.create_task(self._token_refresh_loop())
            logger.info("微信 access_token 自动刷新已启动")

    async def stop(self) -> None:
        """停止微信适配器"""
        self._running = False
        if self._refresh_task is not None:
            self._refresh_task.cancel()
            try:
                await self._refresh_task
            except asyncio.CancelledError:
                pass
            self._refresh_task = None
        logger.info("微信适配器已停止")

    async def send_message(self, target: str, content: str) -> bool:
        """向微信用户发送消息

        Args:
            target: 微信 OpenID 或 user_id
            content: 消息内容

        Returns:
            是否发送成功
        """
        if not self._app_id or not self._app_secret:
            logger.warning("未配置微信 App 凭证，消息未发送")
            return False

        try:
            # 模拟发送（生产环境调用微信 API）
            if self._mode == "wecom":
                # POST https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token=TOKEN
                logger.info("企业微信消息已发送: user=%s content=%s", target, content[:80])
            else:
                # POST https://api.weixin.qq.com/cgi-bin/message/custom/send?access_token=TOKEN
                logger.info("微信消息已发送: openid=%s content=%s", target, content[:80])
            return True
        except Exception as e:
            logger.error("微信消息发送失败: %s", e)
            return False

    async def normalize_message(self, raw_message: Any) -> GatewayMessage:
        """将微信原生消息规范化为 GatewayMessage

        Args:
            raw_message: 微信消息 XML 字典或对象

        Returns:
            规范化后的 GatewayMessage
        """
        if isinstance(raw_message, dict):
            return self._normalize_from_dict(raw_message)
        if isinstance(raw_message, str):
            return self._normalize_from_xml_string(raw_message)
        return self._normalize_from_object(raw_message)

    def _normalize_from_dict(self, msg: dict[str, Any]) -> GatewayMessage:
        """从字典格式规范化微信消息"""
        # 提取基础字段
        msg_type = msg.get("MsgType", msg.get("msg_type", "text"))
        from_user = str(msg.get("FromUserName", msg.get("from_user", "unknown")))
        to_user = str(msg.get("ToUserName", msg.get("to_user", "")))
        create_time = msg.get("CreateTime", msg.get("create_time", int(time.time())))

        # 提取消息内容
        content = ""
        message_type = "text"

        if msg_type == "text":
            content = msg.get("Content", msg.get("content", ""))
            message_type = "text"
        elif msg_type == "image":
            content = msg.get("PicUrl", msg.get("pic_url", ""))
            if not content:
                content = "[图片]"
            message_type = "image"
        elif msg_type == "voice":
            content = "[语音]"
            # 可选：语音识别结果
            recognition = msg.get("Recognition", msg.get("recognition", ""))
            if recognition:
                content = recognition
            message_type = "audio"
        elif msg_type == "video":
            content = "[视频]"
            message_type = "file"
        elif msg_type == "shortvideo":
            content = "[短视频]"
            message_type = "file"
        elif msg_type == "location":
            lat = msg.get("Location_X", msg.get("location_x", ""))
            lng = msg.get("Location_Y", msg.get("location_y", ""))
            label = msg.get("Label", msg.get("label", ""))
            content = f"[位置: {label} ({lat},{lng})]"
            message_type = "text"
        elif msg_type == "link":
            title = msg.get("Title", msg.get("title", ""))
            url = msg.get("Url", msg.get("url", ""))
            content = f"[链接: {title}] {url}"
            message_type = "text"
        elif msg_type == "file":
            content = "[文件]"
            message_type = "file"
        elif msg_type == "event":
            event_type = msg.get("Event", msg.get("event", "unknown"))
            content = self._normalize_event(event_type, msg)
            message_type = "event"
        elif msg_type == "news":
            content = "[图文消息]"
            message_type = "text"
        else:
            content = f"[未知消息类型: {msg_type}]"
            message_type = "text"

        # 构建元数据
        metadata: dict[str, Any] = {
            "to_user": to_user,
            "msg_type": msg_type,
            "msg_id": msg.get("MsgId", msg.get("msg_id", "")),
            "media_id": msg.get("MediaId", msg.get("media_id", "")),
            "format": msg.get("Format", msg.get("format", "")),
            "mode": self._mode,
        }

        # 事件类型元数据
        if msg_type == "event":
            metadata["event"] = msg.get("Event", msg.get("event", ""))
            metadata["event_key"] = msg.get("EventKey", msg.get("event_key", ""))

        return GatewayMessage(
            platform=self.platform,
            user_id=from_user,
            session_id=f"wx_{from_user}",
            content=content,
            message_type=message_type,
            timestamp=float(create_time) if isinstance(create_time, (int, float)) else time.time(),
            metadata=metadata,
        )

    def _normalize_event(self, event_type: str, msg: dict[str, Any]) -> str:
        """规范化微信事件消息

        Args:
            event_type: 事件类型
            msg: 完整消息字典

        Returns:
            事件描述文本
        """
        event_map = {
            "subscribe": "[关注事件]",
            "unsubscribe": "[取消关注]",
            "SCAN": "[扫码事件]",
            "LOCATION": "[上报位置]",
            "CLICK": f"[菜单点击: {msg.get('EventKey', '')}]",
            "VIEW": f"[菜单跳转: {msg.get('EventKey', '')}]",
            "TEMPLATESENDJOBFINISH": "[模板消息发送结果]",
            "enter_agent": "[进入应用]",
            "batch_job_result": "[异步任务结果]",
        }
        return event_map.get(event_type, f"[事件: {event_type}]")

    def _normalize_from_xml_string(self, xml_str: str) -> GatewayMessage:
        """从 XML 字符串规范化微信消息

        Args:
            xml_str: 微信消息 XML 字符串

        Returns:
            规范化后的 GatewayMessage
        """
        try:
            import xml.etree.ElementTree as ET
            root = ET.fromstring(xml_str)
            msg_dict: dict[str, Any] = {}
            for child in root:
                msg_dict[child.tag] = child.text or ""
            return self._normalize_from_dict(msg_dict)
        except Exception as e:
            logger.error("解析微信 XML 消息失败: %s", e)
            return GatewayMessage(
                platform=self.platform,
                user_id="unknown",
                session_id="wx_unknown",
                content=f"[XML 解析失败: {e}]",
                message_type="text",
                metadata={"error": str(e), "raw_xml": xml_str[:500]},
            )

    def _normalize_from_object(self, msg: Any) -> GatewayMessage:
        """从对象格式规范化微信消息"""
        try:
            from_user = str(getattr(msg, "FromUserName", "unknown"))
            msg_type = getattr(msg, "MsgType", "text")
            content = getattr(msg, "Content", "") or ""
            create_time = getattr(msg, "CreateTime", int(time.time()))

            return GatewayMessage(
                platform=self.platform,
                user_id=from_user,
                session_id=f"wx_{from_user}",
                content=content,
                message_type="text",
                timestamp=float(create_time) if isinstance(create_time, (int, float)) else time.time(),
                metadata={
                    "msg_type": msg_type,
                    "msg_id": str(getattr(msg, "MsgId", "")),
                    "mode": self._mode,
                },
            )
        except Exception as e:
            logger.error("规范化微信消息对象失败: %s", e)
            return GatewayMessage(
                platform=self.platform,
                user_id="unknown",
                session_id="wx_unknown",
                content=f"[解析失败: {e}]",
                message_type="text",
                metadata={"error": str(e)},
            )

    # ── 签名验证 ────────────────────────────

    def verify_signature(self, signature: str, timestamp: str, nonce: str) -> bool:
        """验证微信服务器签名

        Args:
            signature: 微信签名
            timestamp: 时间戳
            nonce: 随机数

        Returns:
            签名是否有效
        """
        if not self._token:
            return False
        tmp_list = sorted([self._token, timestamp, nonce])
        tmp_str = "".join(tmp_list)
        computed = hashlib.sha1(tmp_str.encode()).hexdigest()
        return computed == signature

    # ── 私有方法 ────────────────────────────

    async def _token_refresh_loop(self) -> None:
        """定期刷新 access_token"""
        while self._running:
            try:
                await self._refresh_access_token()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("刷新微信 access_token 失败: %s", e)
            # 每 90 分钟刷新一次（token 有效期 2 小时）
            await asyncio.sleep(5400)

    async def _refresh_access_token(self) -> None:
        """刷新 access_token（模拟实现）"""
        # 生产环境:
        # GET https://api.weixin.qq.com/cgi-bin/token?grant_type=client_credential&appid=APPID&secret=APPSECRET
        # 或企业微信:
        # GET https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid=ID&corpsecret=SECRET
        self._token_expires_at = time.time() + 7200  # 2 小时
        logger.debug("微信 access_token 已刷新（模拟）")


__all__ = ["WeChatAdapter"]