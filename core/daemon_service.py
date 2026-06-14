"""
后台监控守护进程 — 持续截图 → OCR → AI分析 → 自动回复
支持启停/暂停/恢复，以及活动日志记录
"""

import os
import sys
import time
import json
import threading
import traceback
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Callable
from collections import deque

# 确保项目路径
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from core.llm_client import LLMClient
from core.agent_engine import AgentEngine, AgentManager, PendingReply
from core.strategy_loader import StrategyLoader
from core.ocr_engine import OCREngine
from core.ui_analyzer import UIAnalyzer


class DaemonService:
    """
    后台监控守护进程

    运行模式：
    - 有浏览器：浏览器截图 → DOM抓取(优先) → OCR(回退)
    - 无浏览器：需要用户手动提供截图（回退到手动模式）

    状态机: stopped → starting → running → paused → stopping → stopped
    """

    def __init__(self, data_dir: str = None):
        if data_dir is None:
            data_dir = str(Path(_project_root) / "data")

        self.data_dir = Path(data_dir)
        self.state = "stopped"  # stopped | starting | running | paused | stopping

        # 组件
        self.agent_manager = AgentManager(data_dir=str(self.data_dir))
        self.llm_client = LLMClient()
        self.ocr_engine = OCREngine()
        self.browser = None  # 延迟初始化

        # 控制
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._pause_event.set()  # 初始不暂停
        self._thread: Optional[threading.Thread] = None

        # 活动日志（环形缓冲）
        self._activity_log = deque(maxlen=1000)
        self._error_count = 0
        self._error_log = deque(maxlen=100)

        # 回调（供 GUI 使用）
        self.on_status_change: Optional[Callable] = None
        self.on_activity: Optional[Callable] = None
        self.on_reply_pending: Optional[Callable] = None
        self.on_reply_sent: Optional[Callable] = None
        self.on_error: Optional[Callable] = None

        # 配置
        self.check_interval = 300  # 默认5分钟，从岗位配置也可覆盖
        self.use_browser = True    # 是否尝试使用浏览器自动化

    # ==================== 生命周期 ====================

    def start(self, use_browser: bool = True) -> bool:
        """
        启动守护进程（非阻塞）
        所有重操作（OCR/浏览器/LLM）在后台线程完成

        返回是否成功启动
        """
        if self.state in ("running", "starting"):
            return False

        self.state = "starting"
        self._stop_event.clear()
        self._pause_event.set()
        self.use_browser = use_browser

        self._log_activity("system", "守护进程启动中...")

        # 立即启动后台线程，所有初始化在后台完成
        self._thread = threading.Thread(target=self._init_and_run, daemon=True)
        self._thread.start()

        return True

    def _init_and_run(self):
        """在后台线程中完成初始化，然后进入主循环"""
        try:
            # === 初始化 OCR ===
            self._log_activity("system", "正在加载 OCR 引擎...")
            if OCREngine.is_ready():
                self._log_activity("system", "OCR 引擎已就绪")
            else:
                success = OCREngine.init_reader(
                    callback=lambda msg: self._log_activity("system", msg)
                )
                if not success:
                    self._log_activity("error", f"OCR 初始化失败: {OCREngine.get_error()}")
                    self._log_activity("warning", "OCR 不可用，后台监控将无法识别截图")
                    # 不终止，让用户知道OCR挂了但其他功能可用
                else:
                    self._log_activity("system", "OCR 引擎加载完成 ✓")

            # === 检查 LLM ===
            self._log_activity("system", "检查 LLM 服务...")
            if self.llm_client.is_available():
                self._log_activity("system", f"LLM 服务可用: {self.llm_client.list_models()}")
            else:
                self._log_activity("warning", "LLM 服务不可用，将跳过自动回复")

            # === 加载岗位 ===
            try:
                agents = self.agent_manager.load_all_enabled()
                if not agents:
                    self._log_activity("warning", "没有启用的岗位，请先在智能体配置中添加")
                else:
                    self._log_activity("system", f"已加载 {len(agents)} 个岗位智能体")
                    for agent in agents.values():
                        agent.on_reply_queued = self._on_agent_reply_queued
                        agent.on_reply_sent = self._on_agent_reply_sent
                        agent.on_error = lambda msg, a=agent: self._log_activity(
                            "error", f"[{a.position_id}] {msg}"
                        )
            except Exception as e:
                self._log_activity("error", f"加载岗位失败: {e}")

            # === 初始化浏览器 ===
            if self.use_browser:
                try:
                    from automation.browser_controller import BrowserController
                    self.browser = BrowserController(headless=True)
                    if self.browser.start():
                        self._log_activity("system", "浏览器已启动 (headless)")
                        if not self.browser.login_saved_session():
                            self._log_activity("warning",
                                "浏览器未登录 BOSS直聘，请先手动登录"
                            )
                    else:
                        self._log_activity("warning",
                            "浏览器启动失败，将使用手动截图模式"
                        )
                        self.browser = None
                except ImportError:
                    self._log_activity("warning",
                        "未安装 selenium，使用手动截图模式"
                    )
                    self.browser = None

            # === 初始化完成 ===
            self.state = "running"
            self._log_activity("system", "守护进程初始化完成 ✓")
            if self.on_status_change:
                self.on_status_change("running")

            # === 进入主循环 ===
            self._run_loop()

        except Exception as e:
            self._log_activity("error", f"初始化失败: {e}")
            self.state = "stopped"
            if self.on_status_change:
                self.on_status_change("stopped")

    def stop(self):
        """停止守护进程"""
        if self.state in ("stopped", "stopping"):
            return

        self._log_activity("system", "守护进程停止中...")
        self.state = "stopping"
        self._stop_event.set()
        self._pause_event.set()  # 解除暂停以便退出

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=10)

        # 保存所有审批队列
        for agent in self.agent_manager.agents.values():
            try:
                agent.save_approval_queue()
            except Exception:
                pass

        # 关闭浏览器
        if self.browser:
            try:
                self.browser.close()
            except Exception:
                pass
            self.browser = None

        self.state = "stopped"
        self._log_activity("system", "守护进程已停止")

        if self.on_status_change:
            self.on_status_change(self.state)

    def pause(self):
        """暂停处理（浏览器保持打开）"""
        if self.state != "running":
            return
        self._pause_event.clear()
        self.state = "paused"
        self._log_activity("system", "守护进程已暂停")
        if self.on_status_change:
            self.on_status_change(self.state)

    def resume(self):
        """恢复处理"""
        if self.state != "paused":
            return
        self._pause_event.set()
        self.state = "running"
        self._log_activity("system", "守护进程已恢复")
        if self.on_status_change:
            self.on_status_change(self.state)

    # ==================== 主循环 ====================

    def _run_loop(self):
        """后台主循环"""
        self._log_activity("system", "监控循环已启动")

        # 计算检查间隔（取所有岗位配置的最小值）
        check_interval = self._get_check_interval()

        while not self._stop_event.is_set():
            # 等待暂停解除
            self._pause_event.wait()

            if self._stop_event.is_set():
                break

            try:
                self._process_cycle()
            except Exception as e:
                self._error_count += 1
                err_msg = f"处理周期出错: {e}\n{traceback.format_exc()[-300:]}"
                self._error_log.append({
                    "time": datetime.now().isoformat(),
                    "error": err_msg,
                })
                self._log_activity("error", f"处理出错 (累计{self._error_count}次)")

                if self.on_error:
                    self.on_error(err_msg)

            # 等待下一个周期
            self._stop_event.wait(check_interval)

    def _process_cycle(self):
        """一个处理周期"""
        cycle_start = datetime.now()
        self._log_activity("cycle", f"--- 新周期 {cycle_start.strftime('%H:%M:%S')} ---")

        agents_to_process = list(self.agent_manager.agents.values())

        for agent in agents_to_process:
            if self._stop_event.is_set() or not self._pause_event.is_set():
                break

            pos_id = agent.position_id
            pos_name = agent.position.get("position_name", pos_id)

            try:
                self._log_activity("agent", f"处理岗位: {pos_name}")

                # === Step 1: 获取截图 ===
                screenshot = None
                if self.browser and self.browser.is_running():
                    # 浏览器模式
                    job_id = agent.position.get("boss_zhipin_job_id", "")
                    self.browser.navigate_to_job_chats(job_id)
                    screenshot = self.browser.take_screenshot()

                if screenshot is None:
                    self._log_activity("agent",
                        f"[{pos_name}] 无法获取截图，跳过此周期"
                    )
                    continue

                # === Step 2: OCR ===
                ocr_results = self.ocr_engine.recognize(screenshot)

                # === Step 3: UI 分析 ===
                ui_result = UIAnalyzer.comprehensive_analysis(ocr_results)
                platform = ui_result.get("平台", "通用")

                if platform == "通用":
                    self._log_activity("agent",
                        f"[{pos_name}] 未检测到BOSS直聘界面"
                    )
                    continue

                # === Step 4: 处理候选人 ===
                # 先尝试 DOM 抓取（如果浏览器可用）
                force_approval = not agent._should_auto_send()

                replies = agent.process_ui_result(
                    ui_result=ui_result,
                    platform=platform,
                    force_approval=force_approval,
                )

                # === Step 5: 自动发送（如果条件满足） ===
                auto_sent_count = 0
                pending_count = 0
                for reply in replies:
                    if reply.auto_send and reply.approved is None:
                        # 尚未处理 — 需要实际发送
                        if self.browser and self.browser.is_running():
                            # 点击候选人
                            self.browser.click_candidate(reply.candidate_name)
                            time.sleep(1)
                            # 发送消息
                            if self.browser.send_message(reply.reply_text):
                                agent.approve_reply(reply.reply_id)
                                auto_sent_count += 1
                                self._log_activity("reply_sent",
                                    f"[{pos_name}] 自动回复 → {reply.candidate_name}: "
                                    f"{reply.reply_text[:40]}..."
                                )
                            else:
                                self._log_activity("error",
                                    f"[{pos_name}] 发送失败 → {reply.candidate_name}"
                                )
                        else:
                            # 无浏览器 — 标记为已生成但需要人工发送
                            pending_count += 1
                    elif not reply.auto_send:
                        pending_count += 1

                if auto_sent_count > 0 or pending_count > 0:
                    self._log_activity("agent",
                        f"[{pos_name}] 自动发送 {auto_sent_count} 条, "
                        f"待审批 {pending_count} 条"
                    )

                # === Step 6: 跟进检查 ===
                follow_ups = agent.check_follow_ups(platform=platform)
                for fu in follow_ups:
                    if fu.auto_send and self.browser and self.browser.is_running():
                        self.browser.click_candidate(fu.candidate_name)
                        time.sleep(1)
                        if self.browser.send_message(fu.reply_text):
                            agent.approve_reply(fu.reply_id)
                            self._log_activity("follow_up",
                                f"[{pos_name}] 自动跟进 → {fu.candidate_name}"
                            )

            except Exception as e:
                self._log_activity("error",
                    f"[{pos_name}] 处理失败: {e}"
                )
                if self.on_error:
                    self.on_error(f"[{pos_name}] {e}")

        # 统计
        elapsed = (datetime.now() - cycle_start).total_seconds()
        if elapsed > 5:
            self._log_activity("cycle", f"周期完成，耗时 {elapsed:.1f}s")

    # ==================== 配置 ====================

    def _get_check_interval(self) -> int:
        """从启用的岗位中选择最小的检查间隔"""
        intervals = []
        for agent in self.agent_manager.agents.values():
            monitoring = agent.position.get("monitoring", {})
            if monitoring.get("enabled"):
                interval = monitoring.get("check_interval_seconds", 300)
                intervals.append(interval)

        return min(intervals) if intervals else self.check_interval

    # ==================== 活动日志 ====================

    def _log_activity(self, level: str, message: str):
        """记录活动日志"""
        entry = {
            "time": datetime.now().strftime("%H:%M:%S"),
            "level": level,  # system | cycle | agent | reply_sent | follow_up | error | warning
            "message": message,
        }
        self._activity_log.append(entry)

        if self.on_activity:
            self.on_activity(entry)

    def get_activity_log(self, n: int = 100) -> List[dict]:
        """获取最近的 N 条活动日志"""
        log = list(self._activity_log)
        return log[-n:]

    def get_errors(self) -> List[dict]:
        """获取最近的错误日志"""
        return list(self._error_log)

    # ==================== Agent 回调 ====================

    def _on_agent_reply_queued(self, reply: PendingReply):
        """Agent 有回复进入审批队列"""
        if self.on_reply_pending:
            self.on_reply_pending(reply)

    def _on_agent_reply_sent(self, reply: PendingReply):
        """Agent 已发送回复"""
        if self.on_reply_sent:
            self.on_reply_sent(reply)

    # ==================== 状态查询 ====================

    def get_status(self) -> dict:
        """获取守护进程完整状态"""
        return {
            "state": self.state,
            "llm_available": self.llm_client.is_available(),
            "ocr_ready": OCREngine.is_ready(),
            "browser_running": self.browser is not None and self.browser.is_running(),
            "browser_logged_in": (
                self.browser._logged_in if self.browser else False
            ),
            "agents_loaded": len(self.agent_manager.agents),
            "check_interval": self._get_check_interval(),
            "activity_count": len(self._activity_log),
            "error_count": self._error_count,
            "agents": [
                {
                    "position_id": a.position_id,
                    "position_name": a.position.get("position_name", ""),
                    "pending_approvals": len(a.approval_queue),
                    "auto_reply_enabled": a.position.get("auto_reply", {}).get("enabled", False),
                    "is_night": a._is_night_now(),
                    "candidates_tracked": len(a.memory_store.list_candidates()),
                }
                for a in self.agent_manager.agents.values()
            ],
        }
