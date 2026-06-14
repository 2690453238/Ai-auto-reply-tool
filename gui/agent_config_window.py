"""
智能体配置窗口 — 岗位配置 / 策略编辑 / 候选人记忆浏览 / 审批队列管理
"""

import os
import sys
import json
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
from typing import Optional

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from core.strategy_loader import StrategyLoader
from core.memory_store import MemoryStore
from core.agent_engine import AgentManager


class AgentConfigWindow:
    """智能体配置管理窗口"""

    def __init__(self, parent: tk.Tk, agent_manager: AgentManager = None):
        self.parent = parent
        self.window = tk.Toplevel(parent)
        self.window.title("智能体配置管理")
        self.window.geometry("1050x700")
        self.window.minsize(900, 600)

        # 数据
        self.strategy_loader = StrategyLoader()
        self.agent_manager = agent_manager or AgentManager()
        self.current_position_id: Optional[str] = None
        self.current_strategy_id: Optional[str] = None

        self._build_ui()
        self._refresh_positions()
        self._refresh_strategies()

    # ==================== UI 构建 ====================

    def _build_ui(self):
        """构建界面"""
        # 主容器
        main_frame = ttk.Frame(self.window)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        # 顶部工具栏
        toolbar = ttk.Frame(main_frame)
        toolbar.pack(fill=tk.X, pady=(0, 8))

        ttk.Button(toolbar, text="💾 保存配置", command=self._save_position).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(toolbar, text="📋 克隆岗位", command=self._clone_position).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(toolbar, text="🗑 删除岗位", command=self._delete_position).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(
            side=tk.LEFT, fill=tk.Y, padx=8, pady=2
        )
        ttk.Button(toolbar, text="➕ 新建岗位", command=self._new_position).pack(
            side=tk.LEFT, padx=2
        )
        ttk.Button(toolbar, text="🔄 刷新", command=self._refresh_all).pack(
            side=tk.LEFT, padx=2
        )

        # 笔记本（岗位配置 / 策略管理 / 候选人记忆）
        self.notebook = ttk.Notebook(main_frame)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        self._build_position_tab()
        self._build_strategy_tab()
        self._build_memory_tab()

    # ==================== Tab 1: 岗位配置 ====================

    def _build_position_tab(self):
        """岗位配置 Tab"""
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="📋 岗位配置")

        paned = ttk.PanedWindow(tab, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)

        # 左：岗位列表
        left = ttk.Frame(paned)
        paned.add(left, weight=1)

        ttk.Label(left, text="岗位列表", font=("", 9, "bold")).pack(
            anchor=tk.W, padx=4, pady=2
        )

        list_frame = ttk.Frame(left)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=2)

        scrollbar = ttk.Scrollbar(list_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.pos_listbox = tk.Listbox(
            list_frame, font=("微软雅黑", 9),
            yscrollcommand=scrollbar.set,
            exportselection=False,
        )
        self.pos_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.pos_listbox.bind("<<ListboxSelect>>", self._on_pos_select)
        scrollbar.config(command=self.pos_listbox.yview)

        # 右：编辑表单
        right = ttk.Frame(paned)
        paned.add(right, weight=3)

        # 滚动表单
        canvas = tk.Canvas(right, highlightthickness=0)
        scrollbar_y = ttk.Scrollbar(right, orient=tk.VERTICAL, command=canvas.yview)
        form_frame = ttk.Frame(canvas)

        form_frame.bind("<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

        canvas.create_window((0, 0), window=form_frame, anchor=tk.NW)
        canvas.configure(yscrollcommand=scrollbar_y.set)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar_y.pack(side=tk.RIGHT, fill=tk.Y)

        # 表单字段
        self.pos_fields = {}
        field_defs = [
            ("基本信息", [
                ("position_id", "岗位ID", 30),
                ("position_name", "岗位名称", 30),
                ("company_name", "公司名称", 30),
                ("company_info", "公司简介", 60),
            ]),
            ("招聘信息", [
                ("job_description", "职位描述", 80),
                ("requirements", "职位要求", 60),
                ("salary_range", "薪资范围", 20),
                ("location", "工作地点", 30),
                ("benefits", "福利待遇", 40),
                ("working_hours", "工作时间", 20),
            ]),
            ("AI配置", [
                ("strategy_id", "策略ID", 20),
                ("llm_model", "LLM模型", 20),
                ("boss_zhipin_job_id", "BOSS岗位ID", 20),
            ]),
        ]

        row = 0
        for section, fields in field_defs:
            ttk.Label(form_frame, text=section, font=("", 9, "bold")).grid(
                row=row, column=0, columnspan=2, sticky=tk.W, padx=4, pady=(10, 2)
            )
            row += 1

            for field_id, label, height in fields:
                ttk.Label(form_frame, text=label + ":", anchor=tk.E).grid(
                    row=row, column=0, sticky=tk.NE, padx=4, pady=1
                )
                if height <= 30:
                    widget = ttk.Entry(form_frame, width=50)
                else:
                    widget = tk.Text(form_frame, width=50, height=min(height // 15, 6),
                                     font=("微软雅黑", 9))
                widget.grid(row=row, column=1, sticky=tk.W, padx=4, pady=1)
                self.pos_fields[field_id] = widget
                row += 1

        # 自动回复复选框
        row += 1
        self.auto_reply_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(form_frame, text="启用自动回复",
                        variable=self.auto_reply_var).grid(
            row=row, column=1, sticky=tk.W, padx=4
        )

        row += 1
        self.night_mode_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(form_frame, text="仅夜间自动回复 (22:00-08:00)",
                        variable=self.night_mode_var).grid(
            row=row, column=1, sticky=tk.W, padx=4
        )

        row += 1
        self.monitoring_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(form_frame, text="启用后台监控",
                        variable=self.monitoring_var).grid(
            row=row, column=1, sticky=tk.W, padx=4
        )

    # ==================== Tab 2: 策略管理 ====================

    def _build_strategy_tab(self):
        """策略管理 Tab"""
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="📝 回复策略")

        paned = ttk.PanedWindow(tab, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)

        # 左：策略列表
        left = ttk.Frame(paned)
        paned.add(left, weight=1)

        ttk.Label(left, text="策略列表", font=("", 9, "bold")).pack(
            anchor=tk.W, padx=4, pady=2
        )

        strat_list_frame = ttk.Frame(left)
        strat_list_frame.pack(fill=tk.BOTH, expand=True, padx=2)

        sb = ttk.Scrollbar(strat_list_frame)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        self.strat_listbox = tk.Listbox(
            strat_list_frame, font=("微软雅黑", 9),
            yscrollcommand=sb.set,
            exportselection=False,
        )
        self.strat_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.strat_listbox.bind("<<ListboxSelect>>", self._on_strat_select)
        sb.config(command=self.strat_listbox.yview)

        # 右：策略编辑
        right = ttk.Frame(paned)
        paned.add(right, weight=3)

        # 策略名称
        row_frame = ttk.Frame(right)
        row_frame.pack(fill=tk.X, padx=4, pady=2)

        ttk.Label(row_frame, text="策略名称:").pack(side=tk.LEFT)
        self.strat_name_var = tk.StringVar()
        ttk.Entry(row_frame, textvariable=self.strat_name_var, width=30).pack(
            side=tk.LEFT, padx=4
        )

        ttk.Label(row_frame, text="Temperature:").pack(side=tk.LEFT, padx=(16, 0))
        self.strat_temp_var = tk.StringVar(value="0.7")
        ttk.Entry(row_frame, textvariable=self.strat_temp_var, width=5).pack(
            side=tk.LEFT, padx=2
        )

        ttk.Label(row_frame, text="Max Tokens:").pack(side=tk.LEFT, padx=(8, 0))
        self.strat_tokens_var = tk.StringVar(value="400")
        ttk.Entry(row_frame, textvariable=self.strat_tokens_var, width=5).pack(
            side=tk.LEFT, padx=2
        )

        # System Prompt
        ttk.Label(right, text="System Prompt 模板:", anchor=tk.W).pack(
            fill=tk.X, padx=4, pady=(8, 2)
        )
        self.strat_prompt_text = scrolledtext.ScrolledText(
            right, font=("Consolas", 9), height=12, wrap=tk.WORD
        )
        self.strat_prompt_text.pack(fill=tk.BOTH, expand=True, padx=4, pady=2)

        # 跟进设置
        ttk.Label(right, text="跟进设置:", anchor=tk.W, font=("", 9, "bold")).pack(
            fill=tk.X, padx=4, pady=(8, 2)
        )
        fu_frame = ttk.Frame(right)
        fu_frame.pack(fill=tk.X, padx=4)

        self.fu_enabled_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(fu_frame, text="启用跟进", variable=self.fu_enabled_var).pack(
            side=tk.LEFT
        )
        ttk.Label(fu_frame, text="最大次数:").pack(side=tk.LEFT, padx=(8, 0))
        self.fu_max_var = tk.StringVar(value="2")
        ttk.Entry(fu_frame, textvariable=self.fu_max_var, width=4).pack(side=tk.LEFT, padx=2)
        ttk.Label(fu_frame, text="间隔(小时):").pack(side=tk.LEFT, padx=(8, 0))
        self.fu_interval_var = tk.StringVar(value="24")
        ttk.Entry(fu_frame, textvariable=self.fu_interval_var, width=4).pack(side=tk.LEFT, padx=2)

        # 保存按钮
        ttk.Button(right, text="💾 保存策略", command=self._save_strategy).pack(
            pady=8
        )

    # ==================== Tab 3: 候选人记忆 ====================

    def _build_memory_tab(self):
        """候选人记忆浏览 Tab"""
        tab = ttk.Frame(self.notebook)
        self.notebook.add(tab, text="🧠 候选人记忆")

        # 岗位选择
        top = ttk.Frame(tab)
        top.pack(fill=tk.X, padx=4, pady=4)

        ttk.Label(top, text="岗位:").pack(side=tk.LEFT)
        self.memory_pos_var = tk.StringVar()
        self.memory_pos_combo = ttk.Combobox(
            top, textvariable=self.memory_pos_var, state="readonly", width=25
        )
        self.memory_pos_combo.pack(side=tk.LEFT, padx=4)
        self.memory_pos_combo.bind("<<ComboboxSelected>>", self._on_memory_pos_select)

        ttk.Button(top, text="刷新", command=self._refresh_memory_list).pack(
            side=tk.LEFT, padx=4
        )

        # 候选人列表 + 详情
        paned = ttk.PanedWindow(tab, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)

        # 左：候选人列表
        left = ttk.Frame(paned)
        paned.add(left, weight=1)

        cand_frame = ttk.Frame(left)
        cand_frame.pack(fill=tk.BOTH, expand=True)

        sb2 = ttk.Scrollbar(cand_frame)
        sb2.pack(side=tk.RIGHT, fill=tk.Y)

        self.memory_listbox = tk.Listbox(
            cand_frame, font=("微软雅黑", 9),
            yscrollcommand=sb2.set,
        )
        self.memory_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.memory_listbox.bind("<<ListboxSelect>>", self._on_memory_cand_select)
        sb2.config(command=self.memory_listbox.yview)

        # 右：详情
        right = ttk.Frame(paned)
        paned.add(right, weight=3)

        self.memory_detail = scrolledtext.ScrolledText(
            right, font=("Consolas", 9), wrap=tk.WORD,
            state=tk.DISABLED,
        )
        self.memory_detail.pack(fill=tk.BOTH, expand=True)

        # 操作按钮
        btn_frame = ttk.Frame(tab)
        btn_frame.pack(fill=tk.X, padx=4, pady=4)

        ttk.Button(btn_frame, text="归档候选人",
                   command=self._archive_candidate).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="删除记录",
                   command=self._delete_memory).pack(side=tk.LEFT, padx=2)

    # ==================== 岗位列表操作 ====================

    def _refresh_positions(self):
        """刷新岗位列表"""
        self.pos_listbox.delete(0, tk.END)
        positions = self.strategy_loader.list_positions()
        self._pos_list_data = positions
        for pos in positions:
            status_icon = "✅" if pos.get("auto_reply_enabled") else "⬜"
            self.pos_listbox.insert(tk.END,
                f"{status_icon} {pos['position_name']} ({pos['position_id']})"
            )

    def _on_pos_select(self, event=None):
        """选中岗位"""
        sel = self.pos_listbox.curselection()
        if not sel:
            return

        idx = sel[0]
        if idx >= len(self._pos_list_data):
            return

        pos = self._pos_list_data[idx]
        self.current_position_id = pos["position_id"]

        # 加载完整配置
        config, err = self.strategy_loader.load_position(pos["position_id"])
        if err:
            messagebox.showerror("错误", err)
            return

        self._populate_position_form(config)

    def _populate_position_form(self, config: dict):
        """将配置填充到表单"""
        # 清空
        for widget in self.pos_fields.values():
            if isinstance(widget, ttk.Entry):
                widget.delete(0, tk.END)
            elif isinstance(widget, tk.Text):
                widget.delete(1.0, tk.END)

        # 填充
        for field_id, widget in self.pos_fields.items():
            value = config.get(field_id, "")
            if isinstance(widget, ttk.Entry):
                widget.insert(0, str(value))
            elif isinstance(widget, tk.Text):
                widget.insert(1.0, str(value))

        # 复选框
        auto = config.get("auto_reply", {})
        self.auto_reply_var.set(auto.get("enabled", False))
        self.night_mode_var.set(auto.get("night_mode_only", True))

        mon = config.get("monitoring", {})
        self.monitoring_var.set(mon.get("enabled", False))

    def _get_form_config(self) -> dict:
        """从表单读取配置"""
        config = {}
        for field_id, widget in self.pos_fields.items():
            if isinstance(widget, ttk.Entry):
                config[field_id] = widget.get().strip()
            elif isinstance(widget, tk.Text):
                config[field_id] = widget.get(1.0, tk.END).strip()

        config["auto_reply"] = {
            "enabled": self.auto_reply_var.get(),
            "night_mode_only": self.night_mode_var.get(),
            "night_start_hour": 22,
            "night_end_hour": 8,
            "max_replies_per_candidate_per_day": 5,
            "cooldown_minutes": 5,
        }

        config["monitoring"] = {
            "enabled": self.monitoring_var.get(),
            "check_interval_seconds": 300,
        }

        return config

    def _save_position(self):
        """保存岗位配置"""
        if not self.current_position_id:
            messagebox.showinfo("提示", "请先选择一个岗位")
            return

        config = self._get_form_config()
        err = self.strategy_loader.save_position(config)
        if err:
            messagebox.showerror("保存失败", err)
        else:
            messagebox.showinfo("成功", f"岗位 '{config['position_name']}' 已保存")
            self._refresh_positions()

    def _new_position(self):
        """新建岗位"""
        pid = f"position_{len(self._pos_list_data) + 1}"
        config = {
            "position_id": pid,
            "position_name": "新岗位",
            "company_name": "",
            "company_info": "",
            "job_description": "",
            "requirements": "",
            "salary_range": "",
            "location": "",
            "benefits": "",
            "working_hours": "",
            "strategy_id": "default",
            "llm_model": "qwen2.5:7b",
            "boss_zhipin_job_id": "",
            "auto_reply": {"enabled": False, "night_mode_only": True,
                           "night_start_hour": 22, "night_end_hour": 8,
                           "max_replies_per_candidate_per_day": 5, "cooldown_minutes": 5},
            "monitoring": {"enabled": False, "check_interval_seconds": 300},
        }
        self.current_position_id = pid
        self._populate_position_form(config)
        self._refresh_positions()

    def _clone_position(self):
        """克隆岗位"""
        if not self.current_position_id:
            messagebox.showinfo("提示", "请先选择一个岗位")
            return
        new_id = self.current_position_id + "_copy"
        config, err = self.strategy_loader.clone_position(
            self.current_position_id, new_id
        )
        if err:
            messagebox.showerror("克隆失败", err)
        else:
            messagebox.showinfo("成功", f"已克隆为 '{new_id}'")
            self._refresh_positions()

    def _delete_position(self):
        """删除岗位"""
        if not self.current_position_id:
            return
        if messagebox.askyesno("确认删除",
            f"确定要删除岗位 '{self.current_position_id}' 吗？\n此操作不可恢复。"):
            self.strategy_loader.delete_position(self.current_position_id)
            self.current_position_id = None
            self._refresh_positions()

    # ==================== 策略列表操作 ====================

    def _refresh_strategies(self):
        """刷新策略列表"""
        self.strat_listbox.delete(0, tk.END)
        strategies = self.strategy_loader.list_strategies()
        self._strat_list_data = strategies
        for st in strategies:
            self.strat_listbox.insert(tk.END,
                f"{st['name']} ({st['strategy_id']})"
            )

    def _on_strat_select(self, event=None):
        """选中策略"""
        sel = self.strat_listbox.curselection()
        if not sel:
            return

        idx = sel[0]
        if idx >= len(self._strat_list_data):
            return

        st = self._strat_list_data[idx]
        self.current_strategy_id = st["strategy_id"]

        config, err = self.strategy_loader.load_strategy(st["strategy_id"])
        if err:
            messagebox.showerror("错误", err)
            return

        self.strat_name_var.set(config.get("name", ""))
        self.strat_temp_var.set(str(config.get("temperature", 0.7)))
        self.strat_tokens_var.set(str(config.get("max_tokens", 400)))
        self.strat_prompt_text.delete(1.0, tk.END)
        self.strat_prompt_text.insert(1.0, config.get("system_prompt_template", ""))

        fu = config.get("follow_up", {})
        self.fu_enabled_var.set(fu.get("enabled", True))
        self.fu_max_var.set(str(fu.get("max_count", 2)))
        self.fu_interval_var.set(str(fu.get("interval_hours", 24)))

    def _save_strategy(self):
        """保存策略"""
        if not self.current_strategy_id:
            return

        config = {
            "strategy_id": self.current_strategy_id,
            "name": self.strat_name_var.get(),
            "system_prompt_template": self.strat_prompt_text.get(1.0, tk.END).strip(),
            "temperature": float(self.strat_temp_var.get() or 0.7),
            "max_tokens": int(self.strat_tokens_var.get() or 400),
            "follow_up": {
                "enabled": self.fu_enabled_var.get(),
                "max_count": int(self.fu_max_var.get() or 2),
                "interval_hours": int(self.fu_interval_var.get() or 24),
                "templates": [],
            },
            "require_human_approval": ["薪资谈判", "面试时间", "offer相关"],
            "auto_reject_keywords": ["不合适", "不考虑了"],
            "blocked_phrases": ["加微信", "转账", "银行卡号"],
        }

        err = self.strategy_loader.save_strategy(config)
        if err:
            messagebox.showerror("保存失败", err)
        else:
            messagebox.showinfo("成功", f"策略 '{config['name']}' 已保存")
            self._refresh_strategies()

    # ==================== 记忆浏览 ====================

    def _refresh_memory_positions(self):
        """刷新记忆浏览的岗位列表"""
        positions = self.strategy_loader.list_positions()
        self.memory_pos_combo["values"] = [
            f"{p['position_name']} ({p['position_id']})"
            for p in positions
        ]

    def _on_memory_pos_select(self, event=None):
        """选择要浏览记忆的岗位"""
        self._refresh_memory_list()

    def _refresh_memory_list(self):
        """刷新候选人记忆列表"""
        self.memory_listbox.delete(0, tk.END)

        pos_text = self.memory_pos_var.get()
        if not pos_text:
            return

        # 从 "岗位名称 (position_id)" 提取 position_id
        import re
        m = re.search(r"\(([^)]+)\)$", pos_text)
        if not m:
            return

        pos_id = m.group(1)
        memory_store = MemoryStore(pos_id)
        candidates = memory_store.list_candidates()

        self._memory_data = candidates
        self._memory_pos_id = pos_id

        for c in candidates:
            status = c.get("status", "")
            icon = "🔵" if status == "active" else "⚫"
            self.memory_listbox.insert(tk.END,
                f"{icon} {c['candidate_name']} [{status}] {c.get('last_interaction', '')[:16]}"
            )

    def _on_memory_cand_select(self, event=None):
        """选中候选人，显示记忆详情"""
        sel = self.memory_listbox.curselection()
        if not sel:
            return

        idx = sel[0]
        if not hasattr(self, "_memory_data") or idx >= len(self._memory_data):
            return

        cand = self._memory_data[idx]
        pos_id = getattr(self, "_memory_pos_id", "")
        if not pos_id:
            return

        memory_store = MemoryStore(pos_id)
        memory = memory_store.get(cand["candidate_name"])

        self.memory_detail.configure(state=tk.NORMAL)
        self.memory_detail.delete(1.0, tk.END)

        if not memory:
            self.memory_detail.insert(1.0, "无记录")
        else:
            formatted = json.dumps(memory, ensure_ascii=False, indent=2)
            self.memory_detail.insert(1.0, formatted)

        self.memory_detail.configure(state=tk.DISABLED)
        self._selected_memory_cand = cand

    def _archive_candidate(self):
        """归档选中候选人"""
        if not hasattr(self, "_selected_memory_cand"):
            return
        cand = self._selected_memory_cand
        pos_id = getattr(self, "_memory_pos_id", "")
        if not pos_id:
            return

        if messagebox.askyesno("确认", f"归档 {cand['candidate_name']}?"):
            memory_store = MemoryStore(pos_id)
            memory_store.archive_candidate(cand["candidate_name"])
            self._refresh_memory_list()

    def _delete_memory(self):
        """删除候选人记忆"""
        if not hasattr(self, "_selected_memory_cand"):
            return
        cand = self._selected_memory_cand
        pos_id = getattr(self, "_memory_pos_id", "")
        if not pos_id:
            return

        if messagebox.askyesno("确认删除",
            f"永久删除 {cand['candidate_name']} 的聊天记忆？\n此操作不可恢复。"):
            memory_store = MemoryStore(pos_id)
            memory_store.delete_candidate(cand["candidate_name"])
            self._refresh_memory_list()
            self.memory_detail.configure(state=tk.NORMAL)
            self.memory_detail.delete(1.0, tk.END)
            self.memory_detail.configure(state=tk.DISABLED)

    # ==================== 通用操作 ====================

    def _refresh_all(self):
        """刷新所有数据"""
        self._refresh_positions()
        self._refresh_strategies()
        self._refresh_memory_positions()
        if hasattr(self, "_memory_pos_id"):
            self._refresh_memory_list()

    def show(self):
        """显示窗口并置顶"""
        self.window.deiconify()
        self.window.lift()
        self.window.focus_force()
