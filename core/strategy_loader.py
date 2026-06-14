"""
策略加载器 — 加载和验证岗位配置、回复策略 JSON 文件
"""

import os
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple


class StrategyLoader:
    """岗位配置与回复策略的加载 / 验证 / 管理"""

    def __init__(self, base_path: str = None):
        if base_path is None:
            base_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "data"
            )
        self.data_dir = Path(base_path)
        self.positions_dir = self.data_dir / "positions"
        self.strategies_dir = self.data_dir / "strategies"

        # 确保目录存在
        self.positions_dir.mkdir(parents=True, exist_ok=True)
        self.strategies_dir.mkdir(parents=True, exist_ok=True)

    # ==================== 岗位配置 ====================

    def list_positions(self) -> List[dict]:
        """列出所有岗位配置的基本信息"""
        positions = []
        for fp in self.positions_dir.glob("*.json"):
            config = self._load_json(fp)
            positions.append({
                "file": fp.name,
                "position_id": config.get("position_id", fp.stem),
                "position_name": config.get("position_name", fp.stem),
                "company_name": config.get("company_name", ""),
                "strategy_id": config.get("strategy_id", "default"),
                "enabled": config.get("monitoring", {}).get("enabled", False),
                "auto_reply_enabled": config.get("auto_reply", {}).get("enabled", False),
            })
        return positions

    def load_position(self, position_id: str) -> Tuple[Optional[dict], str]:
        """
        加载指定岗位的完整配置

        返回: (配置字典或None, 错误信息)
        先尝试精确匹配文件名，再尝试匹配配置内的 position_id
        """
        # 精确文件名匹配
        exact_path = self.positions_dir / f"{position_id}.json"
        if exact_path.exists():
            config = self._load_json(exact_path)
            err = self._validate_position(config)
            return (config, "") if not err else (None, err)

        # 遍历搜索
        for fp in self.positions_dir.glob("*.json"):
            config = self._load_json(fp)
            if config.get("position_id") == position_id:
                err = self._validate_position(config)
                return (config, "") if not err else (None, err)

        return None, f"岗位 '{position_id}' 不存在"

    def save_position(self, config: dict) -> str:
        """
        保存岗位配置到文件

        返回: 错误信息（空字符串表示成功）
        """
        err = self._validate_position(config)
        if err:
            return err

        pos_id = config.get("position_id", "")
        if not pos_id:
            return "缺少 position_id"

        file_path = self.positions_dir / f"{pos_id}.json"
        self._save_json(config, file_path)
        return ""

    def delete_position(self, position_id: str) -> bool:
        file_path = self.positions_dir / f"{position_id}.json"
        if file_path.exists():
            file_path.unlink()
            return True
        return False

    def clone_position(self, source_id: str, new_id: str) -> Tuple[Optional[dict], str]:
        """克隆岗位配置"""
        config, err = self.load_position(source_id)
        if err:
            return None, err
        config["position_id"] = new_id
        config["position_name"] = config.get("position_name", "") + " (副本)"
        save_err = self.save_position(config)
        return (config, "") if not save_err else (None, save_err)

    # ==================== 策略配置 ====================

    def list_strategies(self) -> List[dict]:
        """列出所有回复策略"""
        strategies = []
        for fp in self.strategies_dir.glob("*.json"):
            config = self._load_json(fp)
            strategies.append({
                "file": fp.name,
                "strategy_id": config.get("strategy_id", fp.stem),
                "name": config.get("name", fp.stem),
                "temperature": config.get("temperature", 0.7),
                "follow_up_enabled": config.get("follow_up", {}).get("enabled", True),
            })
        return strategies

    def load_strategy(self, strategy_id: str) -> Tuple[Optional[dict], str]:
        """加载策略配置"""
        exact_path = self.strategies_dir / f"{strategy_id}.json"
        if exact_path.exists():
            config = self._load_json(exact_path)
            err = self._validate_strategy(config)
            return (config, "") if not err else (None, err)

        for fp in self.strategies_dir.glob("*.json"):
            config = self._load_json(fp)
            if config.get("strategy_id") == strategy_id:
                err = self._validate_strategy(config)
                return (config, "") if not err else (None, err)

        return None, f"策略 '{strategy_id}' 不存在"

    def save_strategy(self, config: dict) -> str:
        """保存策略配置"""
        err = self._validate_strategy(config)
        if err:
            return err
        sid = config.get("strategy_id", "")
        if not sid:
            return "缺少 strategy_id"
        self._save_json(config, self.strategies_dir / f"{sid}.json")
        return ""

    def delete_strategy(self, strategy_id: str) -> bool:
        file_path = self.strategies_dir / f"{strategy_id}.json"
        if file_path.exists():
            file_path.unlink()
            return True
        return False

    # ==================== 组合加载 ====================

    def load_position_with_strategy(
        self, position_id: str
    ) -> Tuple[Optional[dict], Optional[dict], str]:
        """
        一次性加载岗位配置 + 对应的策略配置

        返回: (岗位配置, 策略配置, 错误信息)
        """
        position, err = self.load_position(position_id)
        if err:
            return None, None, err

        strategy_id = position.get("strategy_id", "default")
        strategy, s_err = self.load_strategy(strategy_id)
        if s_err:
            # 策略不存在时使用默认回退
            strategy = self._default_strategy()

        return position, strategy, ""

    # ==================== 验证 ====================

    @staticmethod
    def _validate_position(config: dict) -> str:
        """验证岗位配置必填字段"""
        required = ["position_id", "position_name"]
        for key in required:
            if not config.get(key):
                return f"岗位配置缺少必填字段: {key}"

        # 验证自动回复配置
        auto_reply = config.get("auto_reply", {})
        if not isinstance(auto_reply, dict):
            return "auto_reply 必须是字典"

        # 验证监控配置
        monitoring = config.get("monitoring", {})
        if not isinstance(monitoring, dict):
            return "monitoring 必须是字典"

        return ""

    @staticmethod
    def _validate_strategy(config: dict) -> str:
        """验证策略配置必填字段"""
        required = ["strategy_id", "system_prompt_template"]
        for key in required:
            if not config.get(key):
                return f"策略配置缺少必填字段: {key}"

        fu = config.get("follow_up", {})
        if not isinstance(fu, dict):
            return "follow_up 必须是字典"

        return ""

    @staticmethod
    def _default_strategy() -> dict:
        """返回内置默认策略"""
        return {
            "strategy_id": "default",
            "name": "标准招聘回复",
            "system_prompt_template": (
                "你是{company_name}的招聘负责人，正在{platform}上与求职者沟通。\n\n"
                "招聘职位：{position_name}\n"
                "公司简介：{company_info}\n"
                "职位描述：{job_description}\n"
                "职位要求：{requirements}\n"
                "薪资范围：{salary_range}\n"
                "工作地点：{location}\n"
                "福利待遇：{benefits}\n\n"
                "回复规则：\n"
                "1. 称呼对方为\"您好\"，语气专业友好\n"
                "2. 如果对方打招呼，先问候并简短介绍公司和职位\n"
                "3. 对方问薪资时，给出薪资范围并说明根据能力可谈\n"
                "4. 对方问工作时间时，根据公司实际情况回答\n"
                "5. 每次回复控制在2-4句话，不要过长\n"
                "6. 基于已知信息回答，不确定的就说需要确认\n"
                "7. 对有明确意向的候选人，邀请发送简历或安排面试"
            ),
            "temperature": 0.7,
            "max_tokens": 400,
            "follow_up": {
                "enabled": True,
                "max_count": 2,
                "interval_hours": 24,
                "templates": [
                    "您好，看到您对我们{position_name}岗位感兴趣，如果有什么想了解的可以随时问我~",
                    "您好，关于{position_name}这个岗位您还有其他问题吗？我们可以详细聊聊~",
                ],
            },
            "require_human_approval": ["薪资谈判", "面试时间", "offer相关"],
            "auto_reject_keywords": ["不合适", "不考虑了", "已经找到工作"],
            "blocked_phrases": ["加微信", "私下联系", "转账", "支付宝", "银行卡"],
        }

    # ==================== 工具方法 ====================

    @staticmethod
    def _load_json(file_path: Path) -> dict:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def _save_json(data: dict, file_path: Path):
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
