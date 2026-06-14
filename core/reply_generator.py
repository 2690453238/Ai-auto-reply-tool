"""
回复生成器 — 构建 prompt 并通过 LLM 生成候选人回复
支持：首次回复 / 跟进回复 / 安全检查 / 内容清洗
"""

import re
from typing import Tuple, Optional, List
from core.llm_client import LLMClient
from core.memory_store import MemoryStore


class ReplyGenerator:
    """基于 LLM 的招聘回复生成器"""

    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

    # ==================== 核心生成 ====================

    def generate_reply(
        self,
        candidate_name: str,
        new_messages: List[str],
        memory_store: MemoryStore,
        position_config: dict,
        strategy_config: dict,
        platform: str = "BOSS直聘",
    ) -> Tuple[str, bool, str]:
        """
        根据对话上下文生成回复

        参数:
            candidate_name: 候选人姓名
            new_messages: 新的候选人消息列表
            memory_store: 记忆存储实例
            position_config: 岗位配置
            strategy_config: 策略配置
            platform: 平台名称

        返回: (回复文本, 是否成功, 错误/警告信息)
        """
        # 1. 检查LLM可用性
        if not self.llm.is_available():
            return "", False, "LLM 服务不可用"

        # 2. 构建 system prompt
        system_prompt = self._build_system_prompt(
            position_config, strategy_config, platform
        )

        # 3. 获取对话历史
        conversation_history = memory_store.get_conversation_context(
            candidate_name, max_turns=15
        )

        # 4. 构建用户消息
        user_message = "\n".join(
            f"求职者新消息: {msg}" for msg in new_messages
        )
        if not user_message.strip():
            return "", False, "没有新的消息内容"

        # 5. 调用 LLM
        model = position_config.get("llm_model", self.llm.default_model)
        temperature = strategy_config.get("temperature", 0.7)
        max_tokens = strategy_config.get("max_tokens", 500)

        result, ok = self.llm.generate_with_context(
            user_message=user_message,
            conversation_history=conversation_history,
            system_prompt=system_prompt,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        if not ok:
            return "", False, f"LLM 生成失败: {result}"

        # 6. 清洗回复
        cleaned = self._clean_response(result)

        # 7. 安全检查
        is_safe, safety_reason = self._check_safety(cleaned, strategy_config)
        if not is_safe:
            return cleaned, True, f"安全警告: {safety_reason}"

        # 8. 检查是否需要人工审批
        needs_approval = self._needs_human_approval(
            cleaned, new_messages, strategy_config
        )
        if needs_approval:
            return cleaned, True, "需要人工审批"

        return cleaned, True, ""

    def generate_follow_up(
        self,
        candidate_name: str,
        memory_store: MemoryStore,
        position_config: dict,
        strategy_config: dict,
        platform: str = "BOSS直聘",
    ) -> Tuple[str, bool, str]:
        """
        生成跟进回复（候选人长时间未回复时）

        返回: (跟进文本, 是否成功, 错误/警告信息)
        """
        follow_up_config = strategy_config.get("follow_up", {})
        if not follow_up_config.get("enabled", True):
            return "", False, "跟进功能已禁用"

        # 检查跟进次数
        memory = memory_store.get(candidate_name)
        if not memory:
            return "", False, "无候选人记录"

        current_count = memory["metadata"].get("follow_up_count", 0)
        max_count = follow_up_config.get("max_count", 2)
        if current_count >= max_count:
            return "", False, f"已达最大跟进次数({max_count})"

        # 获取对话历史
        conversation_history = memory_store.get_conversation_context(
            candidate_name, max_turns=10
        )

        # 构建 system prompt
        system_prompt = self._build_system_prompt(
            position_config, strategy_config, platform
        )
        system_prompt += (
            f"\n\n注意：这是第{current_count + 1}次跟进。"
            "对方之前没有回复你的消息，请简短礼貌地提醒对方，并询问是否还有意向。"
            "跟进消息控制在1-2句话，语气轻松自然，不要施加压力。"
        )

        # 获取跟进模板作为参考
        templates = follow_up_config.get("templates", [])
        template_hint = ""
        if templates:
            import random
            picked = random.choice(templates)
            # 填充模板变量
            for key, value in position_config.items():
                picked = picked.replace(f"{{{key}}}", str(value))
            template_hint = f"\n参考语气（不要直接复制）：{picked}"

        user_msg = (
            f"你需要对候选人 {candidate_name} 进行第{current_count + 1}次跟进。"
            f"{template_hint}\n"
            f"之前的对话：\n{conversation_history}\n\n"
            f"请生成一条自然的跟进消息："
        )

        model = position_config.get("llm_model", self.llm.default_model)
        result, ok = self.llm.generate(
            prompt=user_msg,
            system_prompt=system_prompt,
            model=model,
            temperature=0.8,  # 跟进可以稍微灵活一些
            max_tokens=strategy_config.get("max_tokens", 300),
        )

        if not ok:
            return "", False, f"LLM 生成跟进失败: {result}"

        cleaned = self._clean_response(result)
        return cleaned, True, ""

    def generate_new_greet_reply(
        self,
        candidate_name: str,
        memory_store: MemoryStore,
        position_config: dict,
        strategy_config: dict,
        platform: str = "BOSS直聘",
    ) -> Tuple[str, bool, str]:
        """
        处理新招呼（候选人有未读消息，内容未知）
        生成主动打招呼的简短消息
        """
        system_prompt = self._build_system_prompt(
            position_config, strategy_config, platform
        )
        system_prompt += "\n\n对方刚刚和你打过招呼或者是新的求职者，还没有具体的对话内容。请主动简短介绍公司和职位，邀请对方沟通。"

        user_msg = f"求职者 {candidate_name} 给你发来了新消息（暂未看到具体内容）。请生成一条友好的欢迎消息，主动介绍职位。"

        model = position_config.get("llm_model", self.llm.default_model)
        result, ok = self.llm.generate(
            prompt=user_msg,
            system_prompt=system_prompt,
            model=model,
            temperature=0.7,
            max_tokens=strategy_config.get("max_tokens", 400),
        )

        if not ok:
            return "", False, f"LLM 生成失败: {result}"

        cleaned = self._clean_response(result)
        return cleaned, True, ""

    # ==================== Prompt 构建 ====================

    def _build_system_prompt(
        self,
        position_config: dict,
        strategy_config: dict,
        platform: str = "BOSS直聘",
    ) -> str:
        """用岗位信息填充策略模板"""
        template = strategy_config.get("system_prompt_template", "")

        # 准备模板变量
        variables = {
            "platform": platform,
            "position_name": position_config.get("position_name", ""),
            "company_name": position_config.get("company_name", "本公司"),
            "company_info": position_config.get("company_info", "暂无信息"),
            "job_description": position_config.get("job_description", "暂无描述"),
            "requirements": position_config.get("requirements", "暂无"),
            "salary_range": position_config.get("salary_range", "面议"),
            "location": position_config.get("location", "未指定"),
            "benefits": position_config.get("benefits", "五险一金"),
        }

        # 填充模板
        prompt = template
        for key, value in variables.items():
            prompt = prompt.replace(f"{{{key}}}", str(value))

        return prompt

    # ==================== 内容清洗 ====================

    @staticmethod
    def _clean_response(raw_text: str) -> str:
        """清洗 LLM 原始输出"""
        text = raw_text.strip()

        # 去掉常见的 LLM 前缀
        prefixes = [
            "回复：", "回复内容：", "生成回复：",
            "答复：", "回答：", "说：",
            "建议回复：", "合适的回复：",
        ]
        for prefix in prefixes:
            if text.startswith(prefix):
                text = text[len(prefix):].strip()

        # 去掉开头和结尾的引号
        if text.startswith('"') and text.endswith('"'):
            text = text[1:-1]
        if text.startswith("「") and text.endswith("」"):
            text = text[1:-1]
        if text.startswith('"') and text.endswith('"'):
            text = text[1:-1]

        # 去掉"您好，"如果在太前面有重复
        text = re.sub(r"^(您好，\s*)(您好，\s*)+", "您好，", text)

        # 控制长度
        if len(text) > 500:
            # 在最后一个句号/感叹号处截断
            truncated = text[:500]
            last_punct = max(
                truncated.rfind("。"),
                truncated.rfind("！"),
                truncated.rfind("？"),
                truncated.rfind("\n"),
            )
            if last_punct > 300:
                text = truncated[:last_punct + 1]
            else:
                text = truncated + "..."

        return text.strip()

    # ==================== 安全检查 ====================

    @staticmethod
    def _check_safety(text: str, strategy_config: dict) -> Tuple[bool, str]:
        """
        检查生成的回复是否安全

        返回: (是否安全, 原因)
        """
        blocked = strategy_config.get("blocked_phrases", [])
        for phrase in blocked:
            if phrase in text:
                return False, f"包含敏感词: {phrase}"

        # 额外安全规则
        dangerous_patterns = [
            (r"1[3-9]\d{9}", "包含手机号"),
            (r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", "包含邮箱"),
        ]
        for pattern, warning in dangerous_patterns:
            if re.search(pattern, text):
                return False, f"回复包含敏感信息: {warning}"

        return True, ""

    @staticmethod
    def _needs_human_approval(
        text: str,
        new_messages: List[str],
        strategy_config: dict,
    ) -> bool:
        """判断回复是否需要人工审批"""
        approval_triggers = strategy_config.get("require_human_approval", [])

        # 检查回复内容是否涉及敏感话题
        for trigger in approval_triggers:
            if trigger in text:
                return True

        # 检查候选人消息是否包含特殊请求
        sensitive_incoming = ["薪资", "工资", "多少钱", "月薪", "年薪", "面试", "offer"]
        for msg in new_messages:
            for kw in sensitive_incoming:
                if kw in msg:
                    # 涉及薪资/面试的话题需要人工审批
                    if any(t in approval_triggers for t in ["薪资谈判", "面试时间"]):
                        return True

        return False
