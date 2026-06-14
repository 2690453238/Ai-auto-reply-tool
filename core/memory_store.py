"""
会话记忆存储 — 每个候选人独立的 JSON 对话记录
支持：创建/加载/追加/摘要/跟进检测
"""

import os
import json
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Tuple


class MemoryStore:
    """每候选人独立的 JSON 文件会话记忆"""

    def __init__(self, position_id: str, base_path: str = None):
        if base_path is None:
            base_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "data", "memories"
            )
        self.position_id = position_id
        self.storage_dir = Path(base_path) / position_id
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    # ==================== 密钥生成 ====================

    @staticmethod
    def candidate_key(candidate_name: str) -> str:
        """从候选人姓名生成唯一短密钥"""
        return hashlib.md5(candidate_name.encode("utf-8")).hexdigest()[:8]

    def _file_path(self, candidate_key: str) -> Path:
        return self.storage_dir / f"{candidate_key}.json"

    # ==================== 记忆 CRUD ====================

    def get_or_create(
        self,
        candidate_name: str,
        job_title: str = "",
        source: str = "boss_zhipin",
    ) -> dict:
        """
        加载已有记忆或创建新文件

        返回: 完整的记忆字典
        """
        key = self.candidate_key(candidate_name)
        file_path = self._file_path(key)

        if file_path.exists():
            memory = self._load(file_path)
            memory["candidate_name"] = candidate_name  # 更新（防止改名）
            if job_title:
                memory["job_title"] = job_title
            self._save(memory, file_path)
            return memory

        # 新建
        memory = {
            "candidate_key": key,
            "candidate_name": candidate_name,
            "job_title": job_title,
            "first_seen": datetime.now().isoformat(),
            "last_interaction": datetime.now().isoformat(),
            "status": "active",  # active | followed_up | archived
            "source": source,
            "metadata": {
                "extracted_phone": "",
                "extracted_email": "",
                "extracted_age_range": "",
                "extracted_education": "",
                "interview_scheduled": False,
                "offer_sent": False,
                "follow_up_count": 0,
                "tags": [],
            },
            "threads": [],
        }
        self._save(memory, file_path)
        return memory

    def get(self, candidate_name: str) -> Optional[dict]:
        """仅读取，不创建"""
        key = self.candidate_key(candidate_name)
        file_path = self._file_path(key)
        if file_path.exists():
            return self._load(file_path)
        return None

    def exists(self, candidate_name: str) -> bool:
        key = self.candidate_key(candidate_name)
        return self._file_path(key).exists()

    # ==================== 消息操作 ====================

    def add_message(
        self,
        candidate_name: str,
        role: str,         # "candidate" | "assistant" | "system"
        content: str,
        source: str = "screenshot_ocr",  # screenshot_ocr | ai_generated | web_scraped | manual
        auto_sent: bool = False,
        thread_id: str = None,
    ) -> Optional[dict]:
        """
        向当前会话添加一条消息

        如果未指定 thread_id，追加到最后一个活跃线程；
        如果没有活跃线程，自动创建一个新线程。
        """
        key = self.candidate_key(candidate_name)
        file_path = self._file_path(key)
        if not file_path.exists():
            return None

        memory = self._load(file_path)

        # 找到或创建线程
        if thread_id:
            thread = next(
                (t for t in memory["threads"] if t["thread_id"] == thread_id),
                None
            )
            if thread is None:
                thread = self._new_thread(f"从对话框 {thread_id}")
                memory["threads"].append(thread)
        else:
            # 取最后一个非归档线程
            active_threads = [
                t for t in memory["threads"]
                if not t.get("archived", False)
            ]
            if active_threads:
                thread = active_threads[-1]
            else:
                thread = self._new_thread()
                memory["threads"].append(thread)

        turn = {
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
            "source": source,
            "auto_sent": auto_sent,
        }
        thread["turns"].append(turn)
        thread["last_updated"] = datetime.now().isoformat()

        # 更新元数据
        memory["last_interaction"] = datetime.now().isoformat()
        if role == "assistant" and auto_sent:
            memory["metadata"]["follow_up_count"] = memory["metadata"].get(
                "follow_up_count", 0
            ) + 1

        self._save(memory, file_path)
        return memory

    def add_batch_messages(
        self,
        candidate_name: str,
        messages: List[Dict[str, str]],
        source: str = "screenshot_ocr",
    ) -> Optional[dict]:
        """
        批量添加消息（从 OCR 结果导入）
        messages: [{"role": "candidate", "content": "xxx"}, ...]
        只有新消息才会被加入（基于内容去重）
        """
        memory = self.get(candidate_name)
        if memory is None:
            return None

        existing_texts = set()
        for thread in memory.get("threads", []):
            for turn in thread.get("turns", []):
                existing_texts.add(turn.get("content", "").strip())

        added = 0
        for msg in messages:
            content = msg.get("content", "").strip()
            if content and content not in existing_texts:
                self.add_message(
                    candidate_name=candidate_name,
                    role=msg.get("role", "candidate"),
                    content=content,
                    source=source,
                )
                existing_texts.add(content)
                added += 1

        if added > 0:
            return self.get(candidate_name)
        return memory

    # ==================== 查询 ====================

    def get_conversation_context(
        self,
        candidate_name: str,
        max_turns: int = 20,
    ) -> str:
        """
        获取格式化的对话历史，用于 LLM prompt 上下文

        返回格式:
        求职者: 您好，这个岗位还招人吗？
        你: 您好！前台岗位还在招聘中...
        求职者: 工作时间是怎样的？
        """
        memory = self.get(candidate_name)
        if not memory or not memory.get("threads"):
            return ""

        lines = []
        turn_count = 0
        # 从最近的线程开始，反向取消息
        for thread in reversed(memory["threads"]):
            if thread.get("archived"):
                # 归档线程只展示摘要
                summary = thread.get("summary", "")
                if summary:
                    lines.insert(0, f"[历史对话摘要]: {summary}")
                continue

            thread_lines = []
            for turn in reversed(thread.get("turns", [])):
                role_label = "求职者" if turn["role"] == "candidate" else "你"
                thread_lines.insert(0, f"{role_label}: {turn['content']}")
                turn_count += 1
                if turn_count >= max_turns:
                    break
            lines = thread_lines + lines

            if turn_count >= max_turns:
                break

        return "\n".join(lines)

    def get_last_n_turns(
        self, candidate_name: str, n: int = 10
    ) -> List[dict]:
        """获取最近 N 轮对话"""
        memory = self.get(candidate_name)
        if not memory:
            return []

        all_turns = []
        for thread in memory.get("threads", []):
            all_turns.extend(thread.get("turns", []))

        return all_turns[-n:]

    def get_new_messages_since(
        self, candidate_name: str, since: str
    ) -> List[dict]:
        """获取指定时间之后的新消息"""
        memory = self.get(candidate_name)
        if not memory:
            return []

        since_dt = datetime.fromisoformat(since)
        new_msgs = []
        for thread in memory.get("threads", []):
            for turn in thread.get("turns", []):
                try:
                    turn_dt = datetime.fromisoformat(turn["timestamp"])
                    if turn_dt > since_dt:
                        new_msgs.append(turn)
                except (ValueError, KeyError):
                    pass
        return new_msgs

    # ==================== 跟进检测 ====================

    def needs_follow_up(
        self,
        candidate_name: str,
        interval_hours: int = 24,
        max_follow_ups: int = 3,
    ) -> Tuple[bool, str]:
        """
        检查候选人是否需要跟进

        返回: (是否需要跟进, 原因)
        """
        memory = self.get(candidate_name)
        if not memory:
            return False, "无记录"

        if memory.get("status") == "archived":
            return False, "已归档"

        follow_up_count = memory["metadata"].get("follow_up_count", 0)
        if follow_up_count >= max_follow_ups:
            return False, f"已达最大跟进次数({max_follow_ups})"

        # 找到最后一条消息的时间
        last_time = None
        last_role = None
        for thread in reversed(memory.get("threads", [])):
            if thread.get("archived"):
                continue
            turns = thread.get("turns", [])
            if turns:
                last_turn = turns[-1]
                last_time = last_turn.get("timestamp", "")
                last_role = last_turn.get("role", "")
                break

        if not last_time:
            return False, "无消息记录"

        try:
            last_dt = datetime.fromisoformat(last_time)
            elapsed = datetime.now() - last_dt
            if elapsed >= timedelta(hours=interval_hours):
                if last_role == "candidate":
                    return True, f"候选人{elapsed.total_seconds()/3600:.1f}小时前最后发言，需要跟进"
                elif last_role == "assistant":
                    return True, f"已回复{elapsed.total_seconds()/3600:.1f}小时，候选人未回应，需要跟进"
        except ValueError:
            pass

        return False, "无需跟进"

    # ==================== 线程管理 ====================

    def summarize_thread(
        self,
        candidate_name: str,
        thread_id: str,
        llm_client=None,
    ) -> Optional[str]:
        """
        用 LLM 压缩旧线程为摘要，避免上下文溢出
        返回摘要文本
        """
        memory = self.get(candidate_name)
        if not memory:
            return None

        thread = next(
            (t for t in memory["threads"]
             if t["thread_id"] == thread_id),
            None
        )
        if not thread or thread.get("archived"):
            return thread.get("summary", "") if thread else ""

        # 拼接对话文本
        turns = thread.get("turns", [])
        if len(turns) < 15:
            return None  # 不需要压缩

        dialog = "\n".join(
            f"{'求职者' if t['role'] == 'candidate' else '招聘方'}: {t['content']}"
            for t in turns[:-5]  # 保留最后5轮
        )

        if llm_client:
            summary, ok = llm_client.summarize(dialog)
            if ok:
                thread["summary"] = summary
                thread["turns"] = turns[-5:]  # 只保留最近5轮
                thread["archived"] = False
                self._save(memory, self._file_path(memory["candidate_key"]))
                return summary

        # 无法用 LLM 时，简单截断
        thread["turns"] = turns[-10:]
        thread["summary"] = f"（已截断，保留了最近10轮对话，共{len(turns)}轮）"
        self._save(memory, self._file_path(memory["candidate_key"]))
        return thread["summary"]

    def archive_thread(self, candidate_name: str, thread_id: str):
        """归档一个线程（如面试已完成）"""
        memory = self.get(candidate_name)
        if not memory:
            return
        for thread in memory["threads"]:
            if thread["thread_id"] == thread_id:
                thread["archived"] = True
                self._save(memory, self._file_path(memory["candidate_key"]))
                return

    # ==================== 候选人管理 ====================

    def list_candidates(self, status: str = None) -> List[dict]:
        """列出所有候选人（可筛选状态）"""
        candidates = []
        for file_path in self.storage_dir.glob("*.json"):
            memory = self._load(file_path)
            if status is None or memory.get("status") == status:
                candidates.append({
                    "candidate_key": memory["candidate_key"],
                    "candidate_name": memory.get("candidate_name", "?"),
                    "job_title": memory.get("job_title", ""),
                    "status": memory.get("status", ""),
                    "last_interaction": memory.get("last_interaction", ""),
                    "follow_up_count": memory["metadata"].get("follow_up_count", 0),
                })
        candidates.sort(key=lambda c: c["last_interaction"], reverse=True)
        return candidates

    def update_metadata(
        self, candidate_name: str, meta_updates: dict
    ):
        """更新候选人元数据"""
        memory = self.get(candidate_name)
        if memory:
            memory["metadata"].update(meta_updates)
            self._save(memory, self._file_path(memory["candidate_key"]))

    def archive_candidate(self, candidate_name: str):
        """归档候选人（不再跟进）"""
        memory = self.get(candidate_name)
        if memory:
            memory["status"] = "archived"
            memory["metadata"]["archived_at"] = datetime.now().isoformat()
            self._save(memory, self._file_path(memory["candidate_key"]))

    def delete_candidate(self, candidate_name: str):
        """删除候选人记忆文件"""
        key = self.candidate_key(candidate_name)
        file_path = self._file_path(key)
        if file_path.exists():
            file_path.unlink()

    # ==================== 内部方法 ====================

    @staticmethod
    def _new_thread(thread_id: str = None) -> dict:
        import uuid
        return {
            "thread_id": thread_id or datetime.now().strftime("%Y%m%d_%H%M%S"),
            "created": datetime.now().isoformat(),
            "last_updated": datetime.now().isoformat(),
            "summary": "",
            "archived": False,
            "turns": [],
        }

    @staticmethod
    def _load(file_path: Path) -> dict:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def _save(memory: dict, file_path: Path):
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(memory, f, ensure_ascii=False, indent=2)

    def get_memory_path(self, candidate_name: str) -> str:
        """返回记忆文件的完整路径"""
        key = self.candidate_key(candidate_name)
        return str(self._file_path(key))
