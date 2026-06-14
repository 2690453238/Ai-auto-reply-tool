"""
智能体引擎 — 每岗位一个Agent实例
核心职责：决策是否回复 → 生成回复 → 记忆存储 → 审批/自动发送
"""

import json
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Callable
from dataclasses import dataclass, field

from core.llm_client import LLMClient
from core.memory_store import MemoryStore
from core.reply_generator import ReplyGenerator
from core.strategy_loader import StrategyLoader


@dataclass
class PendingReply:
    """待审批回复"""
    reply_id: str
    candidate_name: str
    candidate_key: str
    position_id: str
    reply_text: str
    reply_type: str          # "greet" | "reply" | "follow_up"
    timestamp: str
    auto_send: bool = False  # 是否自动发送
    approved: Optional[bool] = None  # None=待审批, True=已批准, False=已拒绝
    edited_text: str = ""


@dataclass
class ReplyRecord:
    """已发送回复记录"""
    timestamp: str
    candidate_name: str
    candidate_key: str
    reply_text: str
    reply_type: str
    auto_sent: bool
    position_id: str


class AgentEngine:
    """
    每个岗位一个 AgentEngine 实例

    生命周期:
    1. 加载岗位配置 + 策略配置
    2. 初始化 MemoryStore（该岗位下的候选人记忆）
    3. 接收 UI 分析结果 → process_ui_result()
    4. 生成回复 → 审批队列或自动发送
    5. 存储记忆
    """

    def __init__(
        self,
        position_config: dict,
        strategy_config: dict,
        llm_client: LLMClient = None,
        data_dir: str = None,
    ):
        self.position = position_config
        self.strategy = strategy_config
        self.position_id = position_config.get("position_id", "unknown")

        # LLM 客户端
        self.llm = llm_client or LLMClient()

        # 记忆存储
        if data_dir is None:
            from pathlib import Path
            data_dir = str(
                Path(__file__).parent.parent / "data" / "memories"
            )
        self.memory_store = MemoryStore(self.position_id, base_path=data_dir)

        # 回复生成器
        self.reply_generator = ReplyGenerator(self.llm)

        # 审批队列 + 已发送记录
        self.approval_queue: List[PendingReply] = []
        self.reply_history: List[ReplyRecord] = []
        self._queue_lock = threading.Lock()

        # 冷却追踪: {candidate_key: last_reply_timestamp}
        self._cooldowns: Dict[str, str] = {}

        # 每日计数: {candidate_key: (date_str, count)}
        self._daily_counts: Dict[str, Tuple[str, int]] = {}

        # 事件回调（供 GUI 使用）
        self.on_reply_queued: Optional[Callable] = None
        self.on_reply_sent: Optional[Callable] = None
        self.on_error: Optional[Callable] = None

    # ==================== 主入口 ====================

    def process_ui_result(
        self,
        ui_result: dict,
        platform: str = "BOSS直聘",
        force_approval: bool = False,
    ) -> List[PendingReply]:
        """
        处理一次UI分析结果

        参数:
            ui_result: UIAnalyzer.comprehensive_analysis() 的结果
            platform: 平台名称
            force_approval: 强制所有回复进入审批队列（白天模式）

        返回:
            本次处理生成的 PendingReply 列表
        """
        new_replies = []

        candidates = ui_result.get("左侧_候选人列表", [])
        right_panel = ui_result.get("右侧_详情面板", {})

        # 获取右侧聊天消息
        right_messages = right_panel.get("messages", [])
        right_candidate_name = right_panel.get("candidate_name", "")

        for candidate in candidates:
            try:
                reply = self.process_candidate(
                    candidate=candidate,
                    chat_messages=right_messages
                    if candidate.get("name") == right_candidate_name
                    else [],
                    platform=platform,
                    force_approval=force_approval,
                )
                if reply:
                    new_replies.append(reply)
            except Exception as e:
                if self.on_error:
                    self.on_error(
                        f"处理候选人 {candidate.get('name', '?')} 时出错: {e}"
                    )

        return new_replies

    def process_candidate(
        self,
        candidate: dict,
        chat_messages: List[dict] = None,
        platform: str = "BOSS直聘",
        force_approval: bool = False,
    ) -> Optional[PendingReply]:
        """
        处理单个候选人

        决策流程:
        1. 是否有新消息？
        2. 是否应该自动回复？
        3. 生成回复
        4. 进入审批队列还是自动发送？
        """
        if chat_messages is None:
            chat_messages = []

        candidate_name = candidate.get("name", "")
        if not candidate_name:
            return None

        candidate_status = candidate.get("status", "")

        # 获取或创建候选人记忆
        memory = self.memory_store.get_or_create(
            candidate_name=candidate_name,
            job_title=candidate.get("job_title", ""),
        )

        # 检查是否有新消息
        has_new = candidate_status == "未读"
        has_messages = len(chat_messages) > 0

        if not has_new and not has_messages:
            return None

        # 确定回复类型
        if has_new and not has_messages:
            # 有未读但未展开聊天 — 发送主动招呼
            reply_type = "greet"
            new_msgs = ["[新招呼消息]"]
            reply_text, ok, info = self.reply_generator.generate_new_greet_reply(
                candidate_name=candidate_name,
                memory_store=self.memory_store,
                position_config=self.position,
                strategy_config=self.strategy,
                platform=platform,
            )
        else:
            # 有具体的聊天消息
            reply_type = "reply"
            candidate_msgs = [
                m.get("text", "")
                for m in chat_messages
                if m.get("sender") == "对方"
            ]
            if not candidate_msgs:
                return None

            # 导入新消息到记忆
            for msg in candidate_msgs:
                self.memory_store.add_message(
                    candidate_name=candidate_name,
                    role="candidate",
                    content=msg,
                    source="screenshot_ocr",
                )

            new_msgs = candidate_msgs
            reply_text, ok, info = self.reply_generator.generate_reply(
                candidate_name=candidate_name,
                new_messages=new_msgs,
                memory_store=self.memory_store,
                position_config=self.position,
                strategy_config=self.strategy,
                platform=platform,
            )

        if not ok or not reply_text.strip():
            if self.on_error:
                self.on_error(f"生成回复失败 ({candidate_name}): {info}")
            return None

        # 决定是否自动发送
        should_auto = (
            not force_approval
            and self._should_auto_send()
            and not self._is_in_cooldown(candidate_name)
            and not self._exceeded_daily_limit(candidate_name)
            and "需要人工审批" not in info
            and "安全警告" not in info
        )

        # 创建回复记录
        import uuid
        reply = PendingReply(
            reply_id=uuid.uuid4().hex[:12],
            candidate_name=candidate_name,
            candidate_key=self.memory_store.candidate_key(candidate_name),
            position_id=self.position_id,
            reply_text=reply_text,
            reply_type=reply_type,
            timestamp=datetime.now().isoformat(),
            auto_send=should_auto,
        )

        # 自动发送
        if should_auto:
            self._execute_send(reply)
        else:
            # 进入审批队列
            with self._queue_lock:
                self.approval_queue.append(reply)

            if self.on_reply_queued:
                self.on_reply_queued(reply)

        return reply

    def check_follow_ups(
        self,
        platform: str = "BOSS直聘",
    ) -> List[PendingReply]:
        """
        检查所有候选人是否需要跟进

        返回: 生成的跟进回复列表
        """
        follow_up_config = self.strategy.get("follow_up", {})
        if not follow_up_config.get("enabled", True):
            return []

        interval_hours = follow_up_config.get("interval_hours", 24)
        max_count = follow_up_config.get("max_count", 2)

        new_replies = []
        candidates = self.memory_store.list_candidates(status="active")

        for cand in candidates:
            candidate_name = cand["candidate_name"]

            needs, reason = self.memory_store.needs_follow_up(
                candidate_name=candidate_name,
                interval_hours=interval_hours,
                max_follow_ups=max_count,
            )

            if not needs:
                continue

            # 生成跟进
            reply_text, ok, info = self.reply_generator.generate_follow_up(
                candidate_name=candidate_name,
                memory_store=self.memory_store,
                position_config=self.position,
                strategy_config=self.strategy,
                platform=platform,
            )

            if not ok or not reply_text.strip():
                continue

            import uuid
            should_auto = (
                self._should_auto_send()
                and not self._is_in_cooldown(candidate_name)
                and not self._exceeded_daily_limit(candidate_name)
            )

            reply = PendingReply(
                reply_id=uuid.uuid4().hex[:12],
                candidate_name=candidate_name,
                candidate_key=cand["candidate_key"],
                position_id=self.position_id,
                reply_text=reply_text,
                reply_type="follow_up",
                timestamp=datetime.now().isoformat(),
                auto_send=should_auto,
            )

            if should_auto:
                self._execute_send(reply)
            else:
                with self._queue_lock:
                    self.approval_queue.append(reply)

            new_replies.append(reply)

        return new_replies

    # ==================== 审批操作 ====================

    def approve_reply(self, reply_id: str, edited_text: str = "") -> bool:
        """批准一条待审批回复"""
        with self._queue_lock:
            for reply in self.approval_queue:
                if reply.reply_id == reply_id:
                    if edited_text:
                        reply.reply_text = edited_text
                        reply.edited_text = edited_text
                    reply.approved = True
                    self._execute_send(reply)
                    self.approval_queue.remove(reply)
                    return True
        return False

    def reject_reply(self, reply_id: str) -> bool:
        """拒绝一条待审批回复"""
        with self._queue_lock:
            for reply in self.approval_queue:
                if reply.reply_id == reply_id:
                    reply.approved = False
                    self.approval_queue.remove(reply)
                    return True
        return False

    def get_pending_replies(self) -> List[PendingReply]:
        """获取所有待审批回复"""
        with self._queue_lock:
            return list(self.approval_queue)

    def get_recent_history(self, n: int = 50) -> List[ReplyRecord]:
        """获取最近发送的回复"""
        return self.reply_history[-n:]

    # ==================== 决策逻辑 ====================

    def _should_auto_send(self) -> bool:
        """检查是否满足自动发送条件"""
        auto_config = self.position.get("auto_reply", {})
        if not auto_config.get("enabled", False):
            return False

        # 检查夜间模式
        if auto_config.get("night_mode_only", True):
            now = datetime.now()
            night_start = auto_config.get("night_start_hour", 22)
            night_end = auto_config.get("night_end_hour", 8)

            if night_start > night_end:
                # 跨天夜间（如 22:00-08:00）
                is_night = now.hour >= night_start or now.hour < night_end
            else:
                is_night = night_start <= now.hour < night_end

            if not is_night:
                return False

        return True

    def _is_in_cooldown(self, candidate_name: str) -> bool:
        """检查是否在冷却期"""
        key = self.memory_store.candidate_key(candidate_name)
        cooldown_minutes = self.position.get("auto_reply", {}).get(
            "cooldown_minutes", 5
        )

        if key in self._cooldowns:
            last = datetime.fromisoformat(self._cooldowns[key])
            if datetime.now() - last < timedelta(minutes=cooldown_minutes):
                return True

        return False

    def _exceeded_daily_limit(self, candidate_name: str) -> bool:
        """检查是否超过每日回复上限"""
        key = self.memory_store.candidate_key(candidate_name)
        max_per_day = self.position.get("auto_reply", {}).get(
            "max_replies_per_candidate_per_day", 5
        )

        today = datetime.now().strftime("%Y-%m-%d")
        if key in self._daily_counts:
            date_str, count = self._daily_counts[key]
            if date_str == today and count >= max_per_day:
                return True

        return False

    # ==================== 发送执行 ====================

    def _execute_send(self, reply: PendingReply):
        """
        执行发送（更新记忆 + 记录历史 + 更新冷却）

        browser_controller 的实际发送由 daemon_service 负责；
        这里只记录回复到记忆系统中。
        """
        # 记录到记忆
        self.memory_store.add_message(
            candidate_name=reply.candidate_name,
            role="assistant",
            content=reply.reply_text,
            source="ai_generated",
            auto_sent=reply.auto_send,
        )

        # 更新冷却
        key = reply.candidate_key
        self._cooldowns[key] = datetime.now().isoformat()

        # 更新每日计数
        today = datetime.now().strftime("%Y-%m-%d")
        if key in self._daily_counts:
            date_str, count = self._daily_counts[key]
            if date_str == today:
                self._daily_counts[key] = (today, count + 1)
            else:
                self._daily_counts[key] = (today, 1)
        else:
            self._daily_counts[key] = (today, 1)

        # 记录历史
        record = ReplyRecord(
            timestamp=reply.timestamp,
            candidate_name=reply.candidate_name,
            candidate_key=reply.candidate_key,
            reply_text=reply.reply_text,
            reply_type=reply.reply_type,
            auto_sent=reply.auto_send,
            position_id=reply.position_id,
        )
        self.reply_history.append(record)

        # 触发回调
        if self.on_reply_sent:
            self.on_reply_sent(reply)

    # ==================== 工具 ====================

    def get_status(self) -> dict:
        """获取智能体状态摘要"""
        return {
            "position_id": self.position_id,
            "position_name": self.position.get("position_name", ""),
            "strategy_name": self.strategy.get("name", ""),
            "auto_reply_enabled": self.position.get("auto_reply", {}).get("enabled", False),
            "night_mode_only": self.position.get("auto_reply", {}).get("night_mode_only", True),
            "is_night_now": self._is_night_now(),
            "pending_approvals": len(self.approval_queue),
            "total_replies_today": sum(
                1 for r in self.reply_history
                if r.timestamp.startswith(datetime.now().strftime("%Y-%m-%d"))
            ),
            "candidates_tracked": len(self.memory_store.list_candidates()),
            "active_candidates": len(self.memory_store.list_candidates(status="active")),
        }

    def _is_night_now(self) -> bool:
        """当前是否为夜间"""
        now = datetime.now()
        night_start = self.position.get("auto_reply", {}).get("night_start_hour", 22)
        night_end = self.position.get("auto_reply", {}).get("night_end_hour", 8)
        if night_start > night_end:
            return now.hour >= night_start or now.hour < night_end
        else:
            return night_start <= now.hour < night_end

    # ==================== 持久化 ====================

    def save_approval_queue(self, file_path: str = None):
        """持久化审批队列（用于重启恢复）"""
        if file_path is None:
            file_path = str(
                Path(__file__).parent.parent / "data"
                / f"queue_{self.position_id}.json"
            )
        with self._queue_lock:
            data = [
                {
                    "reply_id": r.reply_id,
                    "candidate_name": r.candidate_name,
                    "candidate_key": r.candidate_key,
                    "position_id": r.position_id,
                    "reply_text": r.reply_text,
                    "reply_type": r.reply_type,
                    "timestamp": r.timestamp,
                    "auto_send": r.auto_send,
                    "approved": r.approved,
                    "edited_text": r.edited_text,
                }
                for r in self.approval_queue
            ]
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def load_approval_queue(self, file_path: str = None):
        """从文件恢复审批队列"""
        if file_path is None:
            file_path = str(
                Path(__file__).parent.parent / "data"
                / f"queue_{self.position_id}.json"
            )
        if not Path(file_path).exists():
            return

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            with self._queue_lock:
                self.approval_queue = [
                    PendingReply(**item) for item in data
                ]
        except Exception:
            pass


# ==================== Agent 管理器（多岗位协调） ====================

class AgentManager:
    """
    管理多个岗位的 AgentEngine 实例
    供 GUI 和 Daemon 使用
    """

    def __init__(self, data_dir: str = None):
        if data_dir is None:
            data_dir = str(
                Path(__file__).parent.parent / "data"
            )
        self.strategy_loader = StrategyLoader(base_path=data_dir)
        self.llm_client = LLMClient()
        self.agents: Dict[str, AgentEngine] = {}
        self.data_dir = data_dir

    def load_agent(self, position_id: str) -> Tuple[Optional[AgentEngine], str]:
        """加载一个岗位的智能体"""
        # 如果已加载，直接返回
        if position_id in self.agents:
            return self.agents[position_id], ""

        position, strategy, err = self.strategy_loader.load_position_with_strategy(
            position_id
        )
        if err:
            return None, err

        agent = AgentEngine(
            position_config=position,
            strategy_config=strategy,
            llm_client=self.llm_client,
            data_dir=str(Path(self.data_dir) / "memories"),
        )
        self.agents[position_id] = agent
        return agent, ""

    def load_all_enabled(self) -> Dict[str, AgentEngine]:
        """加载所有启用了监控的岗位智能体"""
        positions = self.strategy_loader.list_positions()
        for pos in positions:
            if pos.get("enabled") and pos["position_id"] not in self.agents:
                self.load_agent(pos["position_id"])
        return self.agents

    def get_agent(self, position_id: str) -> Optional[AgentEngine]:
        return self.agents.get(position_id)

    def list_agents(self) -> List[dict]:
        """列出所有已加载的智能体状态"""
        return [agent.get_status() for agent in self.agents.values()]

    def unload_agent(self, position_id: str):
        """卸载一个智能体（保存审批队列后移除）"""
        if position_id in self.agents:
            self.agents[position_id].save_approval_queue()
            del self.agents[position_id]
