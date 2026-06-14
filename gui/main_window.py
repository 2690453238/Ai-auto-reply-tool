"""
GUI 主界面
基于 tkinter 的图片信息识别与分类整理工具 + AI多智能体自动回复
"""

import os
import sys
import threading
import traceback
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
from datetime import datetime
from typing import List, Dict, Any, Optional
from PIL import Image, ImageTk

# 添加项目根目录到 sys.path
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from config import (
    APP_NAME, APP_VERSION, SUPPORTED_IMAGE_FORMATS,
    THUMBNAIL_SIZE, PREVIEW_MAX_SIZE,
)
from core.ocr_engine import OCREngine
from core.image_analyzer import ImageAnalyzer
from core.extractor import InfoExtractor
from core.ui_analyzer import UIAnalyzer
from utils.exporter import Exporter
from core.agent_engine import AgentManager, PendingReply
from core.llm_client import LLMClient
from core.strategy_loader import StrategyLoader
from core.daemon_service import DaemonService


class MainWindow:
    """主窗口"""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title(f"{APP_NAME} v{APP_VERSION}")
        self.root.geometry("1280x800")
        self.root.minsize(1024, 600)

        # 数据状态
        self.image_files: List[str] = []           # 已加载的文件路径
        self.image_thumbnails: Dict[str, ImageTk.PhotoImage] = {}  # 缩略图缓存
        self.current_index: int = -1                # 当前选中的图片索引
        self.ocr_results: Dict[str, Any] = {}       # OCR 结果缓存（键为文件路径）
        self.image_analyses: Dict[str, Any] = {}    # 图片分析缓存
        self.summaries: Dict[str, Any] = {}         # 信息摘要缓存
        self.processing = False                     # 是否正在处理

        # OCR 引擎
        self.ocr_engine = OCREngine()

        # AI 智能体
        self.agent_manager = AgentManager()
        self.llm_client = LLMClient()
        self.daemon = DaemonService()
        self.current_ui_result: Optional[dict] = None  # 当前截图的UI分析结果
        self._agent_config_window = None

        # 守护进程回调
        self.daemon.on_status_change = self._on_daemon_status_change
        self.daemon.on_activity = self._on_daemon_activity
        self.daemon.on_reply_pending = self._on_daemon_reply_pending

        # 设置样式
        self._setup_style()
        # 构建界面
        self._build_menu()
        self._build_toolbar()
        self._build_main_area()
        self._build_statusbar()

        # 注册拖拽（Windows）
        self._setup_drag_drop()

        # 窗口关闭事件
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ===================== 启动 =====================

    def run(self):
        """启动主循环"""
        # 延迟初始化 OCR（在 GUI 显示后）
        self.root.after(500, self._init_ocr)
        self.root.mainloop()

    # ===================== 样式 =====================

    def _setup_style(self):
        """设置 ttk 样式"""
        style = ttk.Style()
        style.theme_use("clam")

        # 默认字体
        self.default_font = ("微软雅黑", 9)
        self.title_font = ("微软雅黑", 10, "bold")
        self.mono_font = ("Consolas", 9)

        style.configure(".", font=self.default_font)
        style.configure("Toolbutton.TButton", padding=6)
        style.configure("Title.TLabel", font=self.title_font)

        # 彩色标签
        style.configure("Success.TLabel", foreground="#2E7D32")
        style.configure("Error.TLabel", foreground="#C62828")
        style.configure("Info.TLabel", foreground="#1565C0")

    # ===================== 菜单栏 =====================

    def _build_menu(self):
        menubar = tk.Menu(self.root, font=self.default_font)

        # 文件菜单
        file_menu = tk.Menu(menubar, tearoff=0, font=self.default_font)
        file_menu.add_command(label="添加图片", command=self._add_images, accelerator="Ctrl+O")
        file_menu.add_command(label="添加文件夹", command=self._add_folder, accelerator="Ctrl+D")
        file_menu.add_separator()
        file_menu.add_command(label="导出 Excel", command=lambda: self._export("excel"), accelerator="Ctrl+E")
        file_menu.add_command(label="导出 CSV", command=lambda: self._export("csv"), accelerator="Ctrl+S")
        file_menu.add_separator()
        file_menu.add_command(label="清空列表", command=self._clear_all)
        file_menu.add_separator()
        file_menu.add_command(label="退出", command=self._on_close, accelerator="Alt+F4")
        menubar.add_cascade(label="文件", menu=file_menu)

        # 操作菜单
        action_menu = tk.Menu(menubar, tearoff=0, font=self.default_font)
        action_menu.add_command(label="识别当前图片", command=self._process_current, accelerator="F5")
        action_menu.add_command(label="批量识别全部", command=self._process_all, accelerator="Ctrl+R")
        menubar.add_cascade(label="操作", menu=action_menu)

        # 智能体菜单
        agent_menu = tk.Menu(menubar, tearoff=0, font=self.default_font)
        agent_menu.add_command(label="智能体配置", command=self._open_agent_config, accelerator="Ctrl+A")
        agent_menu.add_separator()
        agent_menu.add_command(label="启动后台监控", command=self._start_daemon)
        agent_menu.add_command(label="停止后台监控", command=self._stop_daemon)
        agent_menu.add_separator()
        agent_menu.add_command(label="审批队列", command=self._show_approval_queue)
        menubar.add_cascade(label="智能体", menu=agent_menu)

        # 帮助菜单
        help_menu = tk.Menu(menubar, tearoff=0, font=self.default_font)
        help_menu.add_command(label="关于", command=self._show_about)
        menubar.add_cascade(label="帮助", menu=help_menu)

        self.root.config(menu=menubar)

        # 快捷键
        self.root.bind("<Control-o>", lambda e: self._add_images())
        self.root.bind("<Control-d>", lambda e: self._add_folder())
        self.root.bind("<Control-e>", lambda e: self._export("excel"))
        self.root.bind("<Control-s>", lambda e: self._export("csv"))
        self.root.bind("<Control-r>", lambda e: self._process_all())
        self.root.bind("<F5>", lambda e: self._process_current())
        self.root.bind("<Delete>", lambda e: self._remove_selected())
        self.root.bind("<Control-a>", lambda e: self._open_agent_config())

    # ===================== 工具栏 =====================

    def _build_toolbar(self):
        toolbar = ttk.Frame(self.root, padding=4)
        toolbar.pack(side=tk.TOP, fill=tk.X)

        ttk.Button(toolbar, text="📁 添加图片", command=self._add_images,
                   style="Toolbutton.TButton").pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="📂 添加文件夹", command=self._add_folder,
                   style="Toolbutton.TButton").pack(side=tk.LEFT, padx=2)
        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6, pady=2)

        ttk.Button(toolbar, text="🔍 识别当前", command=self._process_current,
                   style="Toolbutton.TButton").pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="🔄 批量识别", command=self._process_all,
                   style="Toolbutton.TButton").pack(side=tk.LEFT, padx=2)
        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6, pady=2)

        ttk.Button(toolbar, text="📊 导出 Excel", command=lambda: self._export("excel"),
                   style="Toolbutton.TButton").pack(side=tk.LEFT, padx=2)
        ttk.Button(toolbar, text="📄 导出 CSV", command=lambda: self._export("csv"),
                   style="Toolbutton.TButton").pack(side=tk.LEFT, padx=2)
        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6, pady=2)

        ttk.Button(toolbar, text="🗑 清空", command=self._clear_all,
                   style="Toolbutton.TButton").pack(side=tk.LEFT, padx=2)

        ttk.Separator(toolbar, orient=tk.VERTICAL).pack(side=tk.LEFT, fill=tk.Y, padx=6, pady=2)

        self.daemon_btn = ttk.Button(toolbar, text="🤖 启动后台监控",
                                     command=self._toggle_daemon,
                                     style="Toolbutton.TButton")
        self.daemon_btn.pack(side=tk.LEFT, padx=2)

        ttk.Button(toolbar, text="⚙ 智能体配置", command=self._open_agent_config,
                   style="Toolbutton.TButton").pack(side=tk.LEFT, padx=2)

        # 右侧状态指示
        self.ocr_status_label = ttk.Label(toolbar, text="OCR: 未加载", foreground="gray")
        self.ocr_status_label.pack(side=tk.RIGHT, padx=8)

    # ===================== 主体区域 =====================

    def _build_main_area(self):
        """构建三栏布局"""
        main_frame = ttk.Frame(self.root)
        main_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=4, pady=2)

        # 使用 PanedWindow 实现可拖拽分隔
        self.paned = ttk.PanedWindow(main_frame, orient=tk.HORIZONTAL)
        self.paned.pack(fill=tk.BOTH, expand=True)

        # --- 左侧：图片列表 ---
        self._build_left_panel()
        # --- 中间：预览区 ---
        self._build_center_panel()
        # --- 右侧：结果面板 ---
        self._build_right_panel()

        # 设置三栏
        self.paned.add(self.left_frame, weight=1)
        self.paned.add(self.center_frame, weight=2)
        self.paned.add(self.right_frame, weight=3)

    def _build_left_panel(self):
        """左侧：图片列表"""
        self.left_frame = ttk.Frame(self.paned)

        # 标题
        title_bar = ttk.Frame(self.left_frame)
        title_bar.pack(fill=tk.X, pady=2)
        ttk.Label(title_bar, text="📋 图片列表", style="Title.TLabel").pack(side=tk.LEFT, padx=4)
        self.count_label = ttk.Label(title_bar, text="(0)", foreground="gray")
        self.count_label.pack(side=tk.LEFT)

        # 图片列表框（带滚动条）
        list_container = ttk.Frame(self.left_frame)
        list_container.pack(fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(list_container)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.listbox = tk.Listbox(
            list_container,
            font=self.default_font,
            selectmode=tk.EXTENDED,
            yscrollcommand=scrollbar.set,
            activestyle="none",
        )
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.listbox.bind("<<ListboxSelect>>", self._on_list_select)
        self.listbox.bind("<Delete>", lambda e: self._remove_selected())
        scrollbar.config(command=self.listbox.yview)

        # 右键菜单
        self.listbox_menu = tk.Menu(self.listbox, tearoff=0, font=self.default_font)
        self.listbox_menu.add_command(label="删除选中", command=self._remove_selected)
        self.listbox_menu.add_command(label="识别选中", command=self._process_selected)
        self.listbox.bind("<Button-3>", self._on_list_right_click)

    def _build_center_panel(self):
        """中间：图片预览"""
        self.center_frame = ttk.Frame(self.paned)

        ttk.Label(self.center_frame, text="🖼 图片预览", style="Title.TLabel").pack(anchor=tk.W, padx=4, pady=2)

        # 预览容器
        preview_container = ttk.Frame(self.center_frame, relief=tk.SUNKEN, borderwidth=1)
        preview_container.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)

        self.preview_label = ttk.Label(
            preview_container,
            text="请添加图片\n\n点击 📁添加图片 按钮\n或拖拽图片到此窗口",
            anchor=tk.CENTER,
            justify=tk.CENTER,
            foreground="gray",
        )
        self.preview_label.pack(fill=tk.BOTH, expand=True)

        # 图片信息标签
        self.preview_info = ttk.Label(
            self.center_frame,
            text="",
            anchor=tk.W,
            foreground="gray",
        )
        self.preview_info.pack(fill=tk.X, padx=4, pady=2)

    def _build_right_panel(self):
        """右侧：结果面板（Notebook 多标签）"""
        self.right_frame = ttk.Frame(self.paned)

        ttk.Label(self.right_frame, text="📊 识别结果", style="Title.TLabel").pack(anchor=tk.W, padx=4, pady=2)

        self.notebook = ttk.Notebook(self.right_frame)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        # --- Tab 1: 文字识别 ---
        self.tab_text = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_text, text="文字识别")

        self.ocr_text_widget = scrolledtext.ScrolledText(
            self.tab_text,
            font=self.mono_font,
            wrap=tk.WORD,
            state=tk.DISABLED,
        )
        self.ocr_text_widget.pack(fill=tk.BOTH, expand=True)

        # --- Tab 2: 图片属性 ---
        self.tab_props = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_props, text="图片属性")

        self.props_text = scrolledtext.ScrolledText(
            self.tab_props,
            font=self.mono_font,
            wrap=tk.WORD,
            state=tk.DISABLED,
            height=20,
        )
        self.props_text.pack(fill=tk.BOTH, expand=True)

        # --- Tab 3: 关键信息 ---
        self.tab_fields = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_fields, text="关键信息")

        # 使用 Treeview 展示关键字段
        self.fields_tree = ttk.Treeview(
            self.tab_fields,
            columns=("field", "value"),
            show="headings",
            height=20,
        )
        self.fields_tree.heading("field", text="字段类型")
        self.fields_tree.heading("value", text="提取结果")
        self.fields_tree.column("field", width=100, anchor=tk.CENTER)
        self.fields_tree.column("value", width=400, anchor=tk.W)
        self.fields_tree.pack(fill=tk.BOTH, expand=True, side=tk.LEFT)

        tree_scroll = ttk.Scrollbar(self.tab_fields, orient=tk.VERTICAL, command=self.fields_tree.yview)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.fields_tree.configure(yscrollcommand=tree_scroll.set)

        # --- Tab 4: 文档分类 ---
        self.tab_doc = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_doc, text="文档分类")

        self.doc_type_label = ttk.Label(self.tab_doc, text="", font=self.title_font)
        self.doc_type_label.pack(pady=10)

        self.doc_confidence_label = ttk.Label(self.tab_doc, text="")
        self.doc_confidence_label.pack(pady=4)

        # --- Tab 5: UI 分析 ---
        self.tab_ui = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_ui, text="UI分析")

        self.ui_text = scrolledtext.ScrolledText(
            self.tab_ui,
            font=self.mono_font,
            wrap=tk.WORD,
            state=tk.DISABLED,
        )
        self.ui_text.pack(fill=tk.BOTH, expand=True)

        # --- Tab 6: AI 助手 ---
        self._build_ai_assistant_tab()

        # --- Tab 7: 监控面板 ---
        self._build_daemon_monitor_tab()

    # ===================== 状态栏 =====================

    def _build_statusbar(self):
        self.statusbar = ttk.Frame(self.root, relief=tk.SUNKEN, padding=2)
        self.statusbar.pack(side=tk.BOTTOM, fill=tk.X)

        self.status_label = ttk.Label(self.statusbar, text="就绪", anchor=tk.W)
        self.status_label.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)

        self.progress_bar = ttk.Progressbar(
            self.statusbar,
            mode="determinate",
            length=200,
        )
        self.progress_bar.pack(side=tk.RIGHT, padx=4)

    # ===================== 拖拽支持（Windows） =====================

    def _setup_drag_drop(self):
        """设置文件拖拽支持"""
        try:
            import ctypes
            from ctypes import wintypes
            import tkinter as tk

            # Windows 拖拽常量和函数
            GWL_EXSTYLE = -20
            WS_EX_ACCEPTFILES = 0x00000010
            WM_DROPFILES = 0x0233

            user32 = ctypes.windll.user32
            shell32 = ctypes.windll.shell32

            # 为窗口启用文件拖拽
            hwnd = self.root.winfo_id() if self.root.winfo_id() else self.root.frame().winfo_id()

            # 获取扩展样式并添加 WS_EX_ACCEPTFILES
            ex_style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex_style | WS_EX_ACCEPTFILES)

            # 注册 DragAcceptFiles
            shell32.DragAcceptFiles(hwnd, True)

            # 子系统消息处理器
            # 我们需要一个自定义的消息处理来拦截 WM_DROPFILES
            # tkinter 在 Windows 上内部处理 WM_DROPFILES 并通过虚拟事件传递

            # 直接使用 tkinter 的 dnd 虚拟事件（如果可用）
            try:
                self.root.tk.call("package", "require", "tkdnd")
                self.root.tk.call("tkdnd::drop_target", "register", self.root, "*")
                self.root.bind("<<Drop>>", self._on_drop_tkdnd)
                self._using_tkdnd = True
            except tk.TclError:
                self._using_tkdnd = False
                # 使用替代方案：定时检测 + 文件对话框
                # 绑定 <<DropFile>> 事件（Windows 特定）
                self.root.bind("<<DropFile>>", self._on_drop_file)

        except Exception:
            # 拖拽不可用时，仅使用文件对话框
            pass

    def _on_drop_tkdnd(self, event):
        """处理 tkdnd 拖拽事件"""
        files = event.data
        if isinstance(files, str):
            # Tcl 列表格式
            files = files.strip("{}").split("} {")
        elif isinstance(files, (list, tuple)):
            files = list(files)
        else:
            files = [str(files)]

        valid_files = [f for f in files if f.lower().endswith(SUPPORTED_IMAGE_FORMATS)]
        if valid_files:
            self._add_files_to_list(valid_files)
        else:
            self._set_status("拖拽的文件中没有支持的图片格式")

    def _on_drop_file(self, event):
        """处理 Windows <<DropFile>> 事件"""
        try:
            data = event.data
            if isinstance(data, str):
                files = data.split()
            elif isinstance(data, (list, tuple)):
                files = list(data)
            else:
                return

            valid_files = [f for f in files if f.lower().endswith(SUPPORTED_IMAGE_FORMATS)]
            if valid_files:
                self._add_files_to_list(valid_files)
        except Exception:
            pass

    # ===================== 图片管理 =====================

    def _add_images(self):
        """打开文件对话框添加图片"""
        formats = " ".join([f"*{ext}" for ext in SUPPORTED_IMAGE_FORMATS])
        files = filedialog.askopenfilenames(
            title="选择图片文件",
            filetypes=[
                ("图片文件", formats),
                ("所有文件", "*.*"),
            ],
        )
        if files:
            self._add_files_to_list(list(files))

    def _add_folder(self):
        """添加文件夹中的所有图片"""
        folder = filedialog.askdirectory(title="选择包含图片的文件夹")
        if not folder:
            return

        found = []
        for root_dir, _, filenames in os.walk(folder):
            for fname in filenames:
                if fname.lower().endswith(SUPPORTED_IMAGE_FORMATS):
                    found.append(os.path.join(root_dir, fname))

        if found:
            self._add_files_to_list(found)
            self._set_status(f"从文件夹加载了 {len(found)} 张图片")
        else:
            messagebox.showinfo("提示", "所选文件夹中没有支持的图片文件")

    def _add_files_to_list(self, file_paths: List[str]):
        """添加文件到列表（去重）"""
        added = 0
        for fp in file_paths:
            # 转换为绝对路径
            abs_path = os.path.abspath(fp)
            if abs_path not in self.image_files:
                self.image_files.append(abs_path)
                filename = os.path.basename(abs_path)
                self.listbox.insert(tk.END, filename)
                added += 1

        if added > 0:
            self._update_count_label()
            self._set_status(f"已添加 {added} 张图片，共 {len(self.image_files)} 张")

            # 如果之前没有选中，自动选中第一张
            if self.current_index < 0 and self.image_files:
                self.listbox.selection_set(0)
                self.current_index = 0
                self._show_preview(0)

    def _remove_selected(self):
        """删除选中的图片"""
        selected = self.listbox.curselection()
        if not selected:
            return

        # 从大到小删除（避免索引错乱）
        for idx in sorted(selected, reverse=True):
            self.listbox.delete(idx)
            file_path = self.image_files.pop(idx)

            # 清理缓存
            self.ocr_results.pop(file_path, None)
            self.image_analyses.pop(file_path, None)
            self.summaries.pop(file_path, None)
            self.image_thumbnails.pop(file_path, None)

        self._update_count_label()

        # 更新选中索引
        if self.image_files:
            new_idx = min(selected[0], len(self.image_files) - 1)
            self.current_index = new_idx
            self.listbox.selection_set(new_idx)
            self._show_preview(new_idx)
        else:
            self.current_index = -1
            self._clear_preview()
            self._clear_results()

        self._set_status(f"剩余 {len(self.image_files)} 张图片")

    def _clear_all(self):
        """清空所有图片"""
        if not self.image_files:
            return
        if messagebox.askyesno("确认", f"确定要清空所有 {len(self.image_files)} 张图片吗？"):
            self.listbox.delete(0, tk.END)
            self.image_files.clear()
            self.ocr_results.clear()
            self.image_analyses.clear()
            self.summaries.clear()
            self.image_thumbnails.clear()
            self.current_index = -1
            self._update_count_label()
            self._clear_preview()
            self._clear_results()
            self._set_status("已清空")

    # ===================== 预览与选中 =====================

    def _on_list_select(self, event=None):
        """列表选中事件"""
        selected = self.listbox.curselection()
        if not selected:
            return
        self.current_index = selected[0]
        self._show_preview(self.current_index)

        # 如果已有识别结果，直接展示
        file_path = self.image_files[self.current_index]
        if file_path in self.summaries:
            self._display_summary(file_path)
        elif file_path in self.ocr_results:
            self._display_ocr_result(file_path)

    def _on_list_right_click(self, event):
        """列表右键菜单"""
        try:
            self.listbox.selection_clear(0, tk.END)
            idx = self.listbox.nearest(event.y)
            self.listbox.selection_set(idx)
            self.current_index = idx
            self.listbox_menu.post(event.x_root, event.y_root)
        finally:
            pass

    def _show_preview(self, index: int):
        """显示第 index 张图片的预览"""
        if index < 0 or index >= len(self.image_files):
            self._clear_preview()
            return

        file_path = self.image_files[index]
        try:
            img = Image.open(file_path)
            # 生成预览图
            img_preview = img.copy()
            img_preview.thumbnail(PREVIEW_MAX_SIZE, Image.LANCZOS)

            # 生成缩略图（存入缓存）
            img_thumb = img.copy()
            img_thumb.thumbnail(THUMBNAIL_SIZE, Image.LANCZOS)
            photo_img = ImageTk.PhotoImage(img_thumb)
            self.image_thumbnails[file_path] = photo_img

            # 显示预览图
            preview_photo = ImageTk.PhotoImage(img_preview)
            self.preview_label.configure(
                image=preview_photo,
                text="",
                compound=tk.CENTER,
            )
            self.preview_label.image = preview_photo  # 保持引用

            # 更新信息标签
            info_text = (
                f"📷 {os.path.basename(file_path)}  |  "
                f"{img.width}×{img.height}  |  "
                f"{img.format or '未知'}"
            )
            self.preview_info.configure(text=info_text)

        except Exception as e:
            self.preview_label.configure(
                image="",
                text=f"无法预览\n{os.path.basename(file_path)}\n\n错误: {e}",
                compound=tk.CENTER,
            )
            self.preview_label.image = None
            self.preview_info.configure(text="")

    def _clear_preview(self):
        """清除预览"""
        self.preview_label.configure(
            image="",
            text="请添加图片\n\n点击 📁添加图片 按钮\n或拖拽图片到此窗口",
            compound=tk.CENTER,
        )
        self.preview_label.image = None
        self.preview_info.configure(text="")

    # ===================== OCR 处理 =====================

    def _init_ocr(self):
        """延迟初始化 OCR 引擎（带超时保护）"""
        self._set_status("正在初始化 OCR 引擎...")
        self.ocr_status_label.configure(text="OCR: 加载中...", foreground="orange")
        self._ocr_start_time = __import__('time').time()

        def _do_init():
            success = OCREngine.init_reader(
                callback=lambda msg: self.root.after(0, self._set_status, msg)
            )
            self.root.after(0, self._on_ocr_initialized, success)

        threading.Thread(target=_do_init, daemon=True).start()

        # 60秒超时看门狗
        def _watchdog():
            if not OCREngine.is_ready() and hasattr(self, '_ocr_start_time'):
                elapsed = __import__('time').time() - self._ocr_start_time
                if elapsed > 60:
                    self.ocr_status_label.configure(
                        text="OCR: 超时（可继续使用其他功能）", foreground="#E65100"
                    )
                    self._set_status("OCR 加载超时，图片属性和分类功能仍可使用")
                    return
            if OCREngine.is_ready():
                return
            self.root.after(3000, _watchdog)

        self.root.after(3000, _watchdog)

    def _on_ocr_initialized(self, success: bool):
        """OCR 初始化完成回调"""
        if hasattr(self, '_ocr_start_time'):
            del self._ocr_start_time
        if success:
            self.ocr_status_label.configure(text="OCR: 就绪 ✓", foreground="green")
            self._set_status("OCR 引擎就绪")
        else:
            err = OCREngine.get_error()
            self.ocr_status_label.configure(text="OCR: 失败 ✗", foreground="red")
            self._set_status(f"OCR 加载失败: {err[:60]}")

    def _process_current(self):
        """处理当前选中的图片"""
        if self.processing:
            messagebox.showwarning("提示", "正在处理中，请稍候...")
            return
        if self.current_index < 0:
            messagebox.showinfo("提示", "请先选择一张图片")
            return

        file_path = self.image_files[self.current_index]
        self._process_files([file_path])

    def _process_selected(self):
        """处理列表选中的图片"""
        if self.processing:
            messagebox.showwarning("提示", "正在处理中，请稍候...")
            return

        selected = self.listbox.curselection()
        if not selected:
            messagebox.showinfo("提示", "请先在列表中选择图片")
            return

        files = [self.image_files[i] for i in selected]
        self._process_files(files)

    def _process_all(self):
        """批量处理全部图片"""
        if self.processing:
            messagebox.showwarning("提示", "正在处理中，请稍候...")
            return
        if not self.image_files:
            messagebox.showinfo("提示", "请先添加图片")
            return

        if len(self.image_files) > 10:
            if not messagebox.askyesno("确认", f"即将处理 {len(self.image_files)} 张图片，可能需要较长时间。\n是否继续？"):
                return

        self._process_files(self.image_files)

    def _process_files(self, file_paths: List[str]):
        """后台线程处理图片"""
        self.processing = True
        self.progress_bar["value"] = 0
        self.progress_bar["maximum"] = len(file_paths)
        self._set_status(f"正在处理 {len(file_paths)} 张图片...")

        def _work():
            try:
                total_steps = len(file_paths) * 2 if OCREngine.is_ready() else len(file_paths)
                # Step 1: 图片分析
                analyses = {}
                for i, fp in enumerate(file_paths):
                    self.root.after(0, self._update_progress, i + 1, total_steps,
                                    f"分析图片属性: {os.path.basename(fp)}")
                    analyses[fp] = ImageAnalyzer.analyze(fp)
                    self.image_analyses[fp] = analyses[fp]

                # Step 2: OCR 识别（如果可用）
                ocr_batch = []
                if OCREngine.is_ready():
                    ocr_batch = self.ocr_engine.recognize_batch(
                        file_paths,
                        progress_callback=lambda cur, total, name: self.root.after(
                            0, self._update_progress,
                            cur + len(file_paths), total + len(file_paths),
                            f"OCR 识别: {name} ({cur}/{total})"
                        ),
                    )
                    for item in ocr_batch:
                        self.ocr_results[item["file"]] = item
                else:
                    # 无 OCR：创建空结果
                    for fp in file_paths:
                        self.ocr_results[fp] = {
                            "file": fp, "text": "", "results": [],
                            "error": "OCR 未加载"
                        }
                    ocr_batch = list(self.ocr_results.values())

                # Step 3: 信息提取与分类
                summaries = InfoExtractor.batch_summarize(ocr_batch, analyses)
                for s in summaries:
                    self.summaries[s["文件路径"]] = s

                # Step 4: UI 截图分析（如果是招聘软件截图）
                for fp in file_paths:
                    ocr_item = self.ocr_results.get(fp, {})
                    ocr_list = ocr_item.get("results", [])
                    if ocr_list:
                        ui_result = UIAnalyzer.comprehensive_analysis(ocr_list)
                        if ui_result.get("平台") != "通用":
                            if fp in self.summaries:
                                self.summaries[fp]["UI分析"] = ui_result

                self.root.after(0, self._on_process_complete, file_paths, summaries)
            except Exception as e:
                tb = traceback.format_exc()
                self.root.after(0, self._on_process_error, str(e), tb)

        threading.Thread(target=_work, daemon=True).start()

    def _update_progress(self, current: int, total: int, status: str):
        """更新进度条"""
        self.progress_bar["maximum"] = total
        self.progress_bar["value"] = current
        self._set_status(status)

    def _on_process_error(self, error_msg: str, traceback_str: str):
        """处理出错回调"""
        self.processing = False
        self.progress_bar["value"] = 0
        self._set_status(f"处理出错: {error_msg}")
        messagebox.showerror("处理错误", f"错误信息:\n{error_msg}\n\n详细:\n{traceback_str[:500]}")

    # ===================== 结果展示 =====================

    def _display_summary(self, file_path: str):
        """展示完整的信息摘要"""
        s = self.summaries.get(file_path)
        if not s:
            self._clear_results()
            return

        # --- Tab 1: 文字识别 ---
        self.ocr_text_widget.configure(state=tk.NORMAL)
        self.ocr_text_widget.delete(1.0, tk.END)

        # 带置信度的文字
        ocr_item = self.ocr_results.get(file_path, {})
        for r in ocr_item.get("results", []):
            conf = r.get("confidence", 0)
            conf_mark = "✓" if conf >= 0.7 else ("△" if conf >= 0.4 else "✗")
            self.ocr_text_widget.insert(tk.END, f"[{conf_mark} {conf:.2f}] {r['text']}\n")

        if not ocr_item.get("results"):
            self.ocr_text_widget.insert(tk.END, "（未识别到文字）")

        self.ocr_text_widget.configure(state=tk.DISABLED)

        # --- Tab 2: 图片属性 ---
        self.props_text.configure(state=tk.NORMAL)
        self.props_text.delete(1.0, tk.END)

        props = s.get("图片属性", {})
        self.props_text.insert(tk.END, "═══ 基本属性 ═══\n")
        for k, v in props.items():
            self.props_text.insert(tk.END, f"  {k}: {v}\n")

        exif = s.get("EXIF信息", {})
        if exif:
            self.props_text.insert(tk.END, "\n═══ EXIF 元数据 ═══\n")
            for k, v in exif.items():
                self.props_text.insert(tk.END, f"  {k}: {v}\n")

        color = s.get("色彩特征", {})
        if color:
            self.props_text.insert(tk.END, "\n═══ 色彩特征 ═══\n")
            for k, v in color.items():
                self.props_text.insert(tk.END, f"  {k}: {v}\n")

        hash_val = s.get("图片哈希", "")
        if hash_val:
            self.props_text.insert(tk.END, f"\n  MD5: {hash_val}\n")

        self.props_text.configure(state=tk.DISABLED)

        # --- Tab 3: 关键信息 ---
        for item in self.fields_tree.get_children():
            self.fields_tree.delete(item)

        key_fields = s.get("关键字段", {})
        if key_fields:
            for field_name, values in key_fields.items():
                self.fields_tree.insert("", tk.END, values=(field_name, ", ".join(values)))
        else:
            self.fields_tree.insert("", tk.END, values=("(无)", "未提取到关键字段"))

        # --- Tab 4: 文档分类 ---
        doc_type = s.get("文档类型", "未知")
        confidence = s.get("类型置信度", 0)

        self.doc_type_label.configure(
            text=f"📄 {doc_type}",
            foreground="#1565C0" if confidence >= 0.5 else "#E65100",
        )
        self.doc_confidence_label.configure(
            text=f"置信度: {confidence:.0%}",
            font=self.default_font,
        )

        # --- Tab 5: UI 分析 ---
        self.ui_text.configure(state=tk.NORMAL)
        self.ui_text.delete(1.0, tk.END)

        ui_result = s.get("UI分析")
        if ui_result:
            self._display_ui_analysis(ui_result)
        else:
            self.ui_text.insert(tk.END, "（此图片未检测到 UI 界面特征）")

        self.ui_text.configure(state=tk.DISABLED)

    def _display_ocr_result(self, file_path: str):
        """仅展示 OCR 结果（无完整 summary）"""
        ocr_item = self.ocr_results.get(file_path)
        if not ocr_item:
            self._clear_results()
            return

        # Tab 1: 文字
        self.ocr_text_widget.configure(state=tk.NORMAL)
        self.ocr_text_widget.delete(1.0, tk.END)
        for r in ocr_item.get("results", []):
            self.ocr_text_widget.insert(tk.END, f"[{r.get('confidence', 0):.2f}] {r['text']}\n")
        self.ocr_text_widget.configure(state=tk.DISABLED)

        # 其余 tab 清空
        self.props_text.configure(state=tk.NORMAL)
        self.props_text.delete(1.0, tk.END)
        self.props_text.insert(tk.END, "（请执行完整分析以查看图片属性）")
        self.props_text.configure(state=tk.DISABLED)

        for item in self.fields_tree.get_children():
            self.fields_tree.delete(item)
        self.fields_tree.insert("", tk.END, values=("(无)", "请执行完整分析"))

        self.doc_type_label.configure(text="")
        self.doc_confidence_label.configure(text="")

    def _display_ui_analysis(self, ui_result: dict):
        """在 UI 分析 Tab 中展示结构化结果"""
        t = self.ui_text
        t.insert(tk.END, f"═══ 平台识别 ═══\n")
        t.insert(tk.END, f"  平台: {ui_result.get('平台', '未知')}\n\n")

        # 统计概览
        stats = ui_result.get("统计", {})
        t.insert(tk.END, f"═══ 统计概览 ═══\n")
        t.insert(tk.END, f"  候选人总数: {stats.get('候选人总数', 0)}\n")
        t.insert(tk.END, f"  未读消息数: {stats.get('未读消息数', 0)}\n")
        t.insert(tk.END, f"  新招呼数:   {stats.get('新招呼数', 0)}\n")
        t.insert(tk.END, f"  识别文字数: {stats.get('识别文字总数', 0)}\n\n")

        # 导航栏
        nav = ui_result.get("导航", {})
        t.insert(tk.END, f"═══ 导航栏 ═══\n")
        t.insert(tk.END, f"  活跃Tab: {nav.get('active_tab', '')}\n")
        tabs = nav.get("tabs", [])
        if tabs:
            t.insert(tk.END, f"  导航项: {' > '.join(tabs[:6])}\n")
        t.insert(tk.END, f"\n")

        # 候选人列表
        candidates = ui_result.get("左侧_候选人列表", [])
        t.insert(tk.END, f"═══ 候选人列表 ═══ ({len(candidates)}人)\n\n")
        for i, c in enumerate(candidates, 1):
            status_icon = "🔴" if c.get("status") == "未读" else "⚪"
            t.insert(tk.END, f"  [{i}] {status_icon} {c.get('name', '?')}\n")
            t.insert(tk.END, f"      职位: {c.get('job_title', '-')}\n")
            t.insert(tk.END, f"      时间: {c.get('time', '-')}\n")
            t.insert(tk.END, f"      状态: {c.get('status', '-')}\n")
            last_msg = c.get('last_message', '')
            if last_msg:
                t.insert(tk.END, f"      最后消息: {last_msg}\n")
            tags = c.get('tags', [])
            if tags:
                t.insert(tk.END, f"      标签: {', '.join(tags)}\n")
            t.insert(tk.END, f"\n")

        # 右侧详情
        right = ui_result.get("右侧_详情面板", {})
        if right.get("candidate_name"):
            t.insert(tk.END, f"═══ 当前查看候选人 ═══\n")
            t.insert(tk.END, f"  姓名: {right.get('candidate_name', '')}\n")
            t.insert(tk.END, f"  状态: {right.get('status', '')}\n")
            info = right.get("personal_info", {})
            if info:
                for k, v in info.items():
                    t.insert(tk.END, f"  {k}: {v}\n")
            t.insert(tk.END, f"  沟通职位: {right.get('job_position', '')}\n\n")

            # 消息内容
            messages = right.get("messages", [])
            if messages:
                t.insert(tk.END, f"  ─── 聊天记录 ───\n")
                for m in messages:
                    sender = m.get("sender", "?")
                    text = m.get("text", "")
                    prefix = "  👤" if sender == "对方" else "  🫵"
                    t.insert(tk.END, f"{prefix} [{sender}] {text}\n")

            # 操作按钮
            actions = right.get("actions", [])
            if actions:
                t.insert(tk.END, f"\n  ─── 操作按钮 ───\n")
                t.insert(tk.END, f"  {' | '.join(actions)}\n")

    def _clear_results(self):
        """清除所有结果显示"""
        for widget, state_key in [
            (self.ocr_text_widget, tk.NORMAL),
            (self.props_text, tk.NORMAL),
            (self.ui_text, tk.NORMAL),
        ]:
            widget.configure(state=tk.NORMAL)
            widget.delete(1.0, tk.END)
            widget.configure(state=tk.DISABLED)

        for item in self.fields_tree.get_children():
            self.fields_tree.delete(item)

        self.doc_type_label.configure(text="")
        self.doc_confidence_label.configure(text="")

    # ===================== 列表刷新 =====================

    def _refresh_list_display(self):
        """刷新列表显示（标记已处理的文件）"""
        self.listbox.delete(0, tk.END)
        for fp in self.image_files:
            name = os.path.basename(fp)
            if fp in self.summaries:
                doc_type = self.summaries[fp].get("文档类型", "")
                name = f"[{doc_type}] {name}"
            elif fp in self.ocr_results:
                name = f"[已识别] {name}"
            self.listbox.insert(tk.END, name)
        self._update_count_label()

    def _update_count_label(self):
        """更新图片计数"""
        self.count_label.configure(text=f"({len(self.image_files)})")

    # ===================== 导出 =====================

    def _export(self, format_type: str):
        """导出结果"""
        if not self.summaries:
            # 检查是否有 OCR 结果但未 summary
            pending = [fp for fp in self.ocr_results if fp not in self.summaries]
            if pending and self.image_analyses:
                # 自动补全 summaries
                ocr_batch = [self.ocr_results[fp] for fp in pending]
                summaries = InfoExtractor.batch_summarize(ocr_batch, self.image_analyses)
                for s in summaries:
                    self.summaries[s["文件路径"]] = s

        if not self.summaries:
            messagebox.showinfo("提示", "没有可导出的结果，请先进行图片识别")
            return

        try:
            summary_list = list(self.summaries.values())
            if format_type == "excel":
                path = Exporter.export_excel(summary_list)
                self._set_status(f"已导出 Excel: {path}")
                messagebox.showinfo("导出成功", f"Excel 文件已保存到:\n{path}")
            else:
                path = Exporter.export_csv(summary_list)
                self._set_status(f"已导出 CSV: {path}")
                messagebox.showinfo("导出成功", f"CSV 文件已保存到:\n{path}")
        except Exception as e:
            messagebox.showerror("导出失败", f"导出时出错:\n{e}")

    # ===================== 状态与对话框 =====================

    def _set_status(self, text: str):
        """设置状态栏文字"""
        self.status_label.configure(text=text)

    def _show_about(self):
        """关于对话框"""
        messagebox.showinfo(
            "关于",
            f"{APP_NAME}\n"
            f"版本: {APP_VERSION}\n\n"
            f"功能:\n"
            f"  • OCR 文字识别（中英文）\n"
            f"  • 图片属性提取（EXIF、色彩等）\n"
            f"  • 关键信息提取（日期/金额/证件号等）\n"
            f"  • 文档类型自动分类\n"
            f"  • 结果导出 Excel / CSV\n\n"
            f"技术: Python + EasyOCR + tkinter",
        )

    # ===================== Tab 6: AI 助手 =====================

    def _build_ai_assistant_tab(self):
        """构建 AI 助手 Tab"""
        self.tab_ai = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_ai, text="AI助手")

        ai_main = ttk.Frame(self.tab_ai)
        ai_main.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        # --- 智能体状态区 ---
        status_frame = ttk.LabelFrame(ai_main, text="智能体状态", padding=4)
        status_frame.pack(fill=tk.X, pady=(0, 4))

        self.ai_status_text = tk.Text(
            status_frame, font=self.mono_font, height=3,
            wrap=tk.WORD, state=tk.DISABLED,
        )
        self.ai_status_text.pack(fill=tk.X)

        # --- 操作按钮 ---
        btn_frame = ttk.Frame(ai_main)
        btn_frame.pack(fill=tk.X, pady=4)

        ttk.Button(btn_frame, text="🔍 分析当前截图并生成回复",
                   command=self._ai_process_current).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="🔄 刷新状态",
                   command=self._ai_refresh_status).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="📋 查看审批队列",
                   command=self._show_approval_queue).pack(side=tk.LEFT, padx=2)

        # --- 待审批回复 ---
        pending_frame = ttk.LabelFrame(ai_main, text="待审批回复", padding=4)
        pending_frame.pack(fill=tk.BOTH, expand=True, pady=4)

        self.pending_tree = ttk.Treeview(
            pending_frame,
            columns=("time", "candidate", "reply", "type"),
            show="headings",
            height=6,
        )
        self.pending_tree.heading("time", text="时间")
        self.pending_tree.heading("candidate", text="候选人")
        self.pending_tree.heading("reply", text="回复内容")
        self.pending_tree.heading("type", text="类型")
        self.pending_tree.column("time", width=60, anchor=tk.CENTER)
        self.pending_tree.column("candidate", width=80, anchor=tk.CENTER)
        self.pending_tree.column("reply", width=300, anchor=tk.W)
        self.pending_tree.column("type", width=60, anchor=tk.CENTER)
        self.pending_tree.pack(fill=tk.BOTH, expand=True, side=tk.LEFT)

        pending_scroll = ttk.Scrollbar(
            pending_frame, orient=tk.VERTICAL, command=self.pending_tree.yview
        )
        pending_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.pending_tree.configure(yscrollcommand=pending_scroll.set)

        # 审批操作
        approval_btn_frame = ttk.Frame(ai_main)
        approval_btn_frame.pack(fill=tk.X, pady=4)

        ttk.Button(approval_btn_frame, text="✅ 批准发送",
                   command=self._approve_selected_reply).pack(side=tk.LEFT, padx=2)
        ttk.Button(approval_btn_frame, text="✏️ 编辑后发送",
                   command=self._edit_and_approve_reply).pack(side=tk.LEFT, padx=2)
        ttk.Button(approval_btn_frame, text="❌ 拒绝",
                   command=self._reject_selected_reply).pack(side=tk.LEFT, padx=2)
        ttk.Button(approval_btn_frame, text="✅ 全部批准",
                   command=self._approve_all_replies).pack(side=tk.LEFT, padx=2)

        # --- 最近回复记录 ---
        history_frame = ttk.LabelFrame(ai_main, text="最近回复记录", padding=4)
        history_frame.pack(fill=tk.BOTH, expand=True, pady=4)

        self.history_tree = ttk.Treeview(
            history_frame,
            columns=("time", "candidate", "reply", "auto"),
            show="headings",
            height=5,
        )
        self.history_tree.heading("time", text="时间")
        self.history_tree.heading("candidate", text="候选人")
        self.history_tree.heading("reply", text="回复内容")
        self.history_tree.heading("auto", text="模式")
        self.history_tree.column("time", width=60, anchor=tk.CENTER)
        self.history_tree.column("candidate", width=80, anchor=tk.CENTER)
        self.history_tree.column("reply", width=300, anchor=tk.W)
        self.history_tree.column("auto", width=50, anchor=tk.CENTER)
        self.history_tree.pack(fill=tk.BOTH, expand=True, side=tk.LEFT)

        history_scroll = ttk.Scrollbar(
            history_frame, orient=tk.VERTICAL, command=self.history_tree.yview
        )
        history_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.history_tree.configure(yscrollcommand=history_scroll.set)

    # ===================== Tab 7: 监控面板 =====================

    def _build_daemon_monitor_tab(self):
        """构建监控面板 Tab"""
        self.tab_monitor = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_monitor, text="监控面板")

        mon_main = ttk.Frame(self.tab_monitor)
        mon_main.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        # --- 守护进程控制 ---
        ctrl_frame = ttk.LabelFrame(mon_main, text="守护进程控制", padding=4)
        ctrl_frame.pack(fill=tk.X, pady=(0, 4))

        ctrl_btns = ttk.Frame(ctrl_frame)
        ctrl_btns.pack(fill=tk.X, pady=2)

        self.daemon_start_btn = ttk.Button(
            ctrl_btns, text="▶ 启动", command=self._start_daemon
        )
        self.daemon_start_btn.pack(side=tk.LEFT, padx=2)

        self.daemon_pause_btn = ttk.Button(
            ctrl_btns, text="⏸ 暂停", command=self._pause_daemon, state=tk.DISABLED
        )
        self.daemon_pause_btn.pack(side=tk.LEFT, padx=2)

        self.daemon_stop_btn = ttk.Button(
            ctrl_btns, text="⏹ 停止", command=self._stop_daemon, state=tk.DISABLED
        )
        self.daemon_stop_btn.pack(side=tk.LEFT, padx=2)

        self.daemon_status_label = ttk.Label(
            ctrl_btns, text="状态: 已停止", foreground="gray"
        )
        self.daemon_status_label.pack(side=tk.LEFT, padx=16)

        # 统计信息
        stats_frame = ttk.Frame(ctrl_frame)
        stats_frame.pack(fill=tk.X, pady=2)

        self.daemon_stats_text = tk.Text(
            stats_frame, font=self.mono_font, height=4,
            wrap=tk.WORD, state=tk.DISABLED,
        )
        self.daemon_stats_text.pack(fill=tk.X)

        # --- 活动日志 ---
        log_frame = ttk.LabelFrame(mon_main, text="活动日志", padding=4)
        log_frame.pack(fill=tk.BOTH, expand=True)

        self.daemon_log_text = scrolledtext.ScrolledText(
            log_frame, font=self.mono_font, height=15,
            wrap=tk.WORD, state=tk.DISABLED,
        )
        self.daemon_log_text.pack(fill=tk.BOTH, expand=True)

        # 日志控制
        log_btn_frame = ttk.Frame(mon_main)
        log_btn_frame.pack(fill=tk.X, pady=4)
        ttk.Button(log_btn_frame, text="🔄 刷新日志",
                   command=self._refresh_daemon_log).pack(side=tk.LEFT, padx=2)
        ttk.Button(log_btn_frame, text="🗑 清空日志",
                   command=self._clear_daemon_log).pack(side=tk.LEFT, padx=2)

    # ===================== AI 助手操作 =====================

    def _ai_process_current(self):
        """分析当前截图并调用AI生成回复"""
        if self.current_index < 0:
            messagebox.showinfo("提示", "请先选择一张图片")
            return

        file_path = self.image_files[self.current_index]
        # 需要先有OCR结果
        if file_path not in self.ocr_results or not self.ocr_results[file_path].get("results"):
            messagebox.showinfo("提示", "请先执行文字识别（F5）")
            return

        ocr_item = self.ocr_results[file_path]
        ocr_list = ocr_item.get("results", [])
        if not ocr_list:
            messagebox.showinfo("提示", "未识别到文字内容")
            return

        # UI分析
        ui_result = UIAnalyzer.comprehensive_analysis(ocr_list)
        self.current_ui_result = ui_result

        platform = ui_result.get("平台", "通用")
        if platform == "通用":
            messagebox.showinfo("提示", "未检测到BOSS直聘界面，AI助手仅支持招聘聊天截图")
            return

        # 加载或获取Agent
        self._ai_refresh_status()

        # 让用户选择岗位
        self._show_position_selector(ui_result)

    def _show_position_selector(self, ui_result: dict):
        """弹出岗位选择对话框，然后处理"""
        positions = StrategyLoader().list_positions()
        if not positions:
            # 使用默认
            self._run_ai_processing(ui_result, "front_desk")
            return

        # 弹出选择框
        dialog = tk.Toplevel(self.root)
        dialog.title("选择岗位")
        dialog.geometry("300x200")
        dialog.transient(self.root)
        dialog.grab_set()

        ttk.Label(dialog, text="请选择此截图对应的岗位:",
                  font=self.default_font).pack(pady=10)

        pos_var = tk.StringVar()
        pos_combo = ttk.Combobox(
            dialog, textvariable=pos_var, state="readonly",
            values=[f"{p['position_name']} ({p['position_id']})" for p in positions],
            width=35,
        )
        pos_combo.pack(pady=6)
        if positions:
            pos_combo.current(0)

        def on_ok():
            sel = pos_var.get()
            if not sel:
                return
            import re
            m = re.search(r"\(([^)]+)\)$", sel)
            if m:
                pos_id = m.group(1)
                dialog.destroy()
                self._run_ai_processing(ui_result, pos_id)

        ttk.Button(dialog, text="确定", command=on_ok).pack(pady=8)
        ttk.Button(dialog, text="取消", command=dialog.destroy).pack()

    def _run_ai_processing(self, ui_result: dict, position_id: str):
        """在后台线程中运行AI处理"""
        def _work():
            try:
                # 加载Agent
                self.root.after(0, self._set_status, f"加载智能体: {position_id}...")
                agent, err = self.agent_manager.load_agent(position_id)
                if err:
                    self.root.after(0, messagebox.showerror, "错误", f"加载智能体失败: {err}")
                    return

                # 处理（白天模式强制审批）
                is_night = agent._is_night_now()
                force_approval = not (agent.position.get("auto_reply", {}).get("enabled") and is_night)

                self.root.after(0, self._set_status, "AI生成回复中...")
                replies = agent.process_ui_result(
                    ui_result=ui_result,
                    platform=ui_result.get("平台", "BOSS直聘"),
                    force_approval=force_approval,
                )

                self.root.after(0, self._on_ai_process_complete, replies, agent, position_id)
            except Exception as e:
                self.root.after(0, self._set_status, f"AI处理出错: {e}")
                self.root.after(0, messagebox.showerror, "AI处理错误", str(e))

        threading.Thread(target=_work, daemon=True).start()

    def _on_ai_process_complete(self, replies: list, agent, position_id: str):
        """AI处理完成回调"""
        auto_count = sum(1 for r in replies if r.auto_send)
        pending_count = len(replies) - auto_count

        self._set_status(
            f"AI处理完成: {auto_count}条自动发送, {pending_count}条待审批"
        )
        self._refresh_pending_tree()
        self._refresh_history_tree()
        self._ai_refresh_status()

        # 如果有自动发送的，弹提示
        if auto_count > 0:
            messagebox.showinfo(
                "AI助手",
                f"岗位「{agent.position.get('position_name', position_id)}」处理完成:\n"
                f"  - 自动发送: {auto_count} 条\n"
                f"  - 待审批: {pending_count} 条\n\n"
                f"请切换到「AI助手」Tab查看详情。"
            )
        elif pending_count > 0:
            messagebox.showinfo(
                "AI助手",
                f"生成了 {pending_count} 条回复，请在「AI助手」Tab中审批。"
            )
        else:
            messagebox.showinfo("AI助手", "当前没有需要回复的消息。")

    # ==================== 审批操作 ====================

    def _refresh_pending_tree(self):
        """刷新待审批列表"""
        for item in self.pending_tree.get_children():
            self.pending_tree.delete(item)

        for agent in self.agent_manager.agents.values():
            for reply in agent.get_pending_replies():
                self.pending_tree.insert("", tk.END, values=(
                    reply.timestamp[-8:-3] if len(reply.timestamp) > 8 else reply.timestamp,
                    reply.candidate_name,
                    reply.reply_text[:60] + ("..." if len(reply.reply_text) > 60 else ""),
                    {"greet": "新招呼", "reply": "回复", "follow_up": "跟进"}.get(
                        reply.reply_type, reply.reply_type
                    ),
                ), tags=(f"{reply.reply_id}:{agent.position_id}",))

    def _refresh_history_tree(self):
        """刷新最近回复记录"""
        for item in self.history_tree.get_children():
            self.history_tree.delete(item)

        for agent in self.agent_manager.agents.values():
            for rec in agent.get_recent_history(20):
                self.history_tree.insert("", tk.END, values=(
                    rec.timestamp[-8:-3] if len(rec.timestamp) > 8 else rec.timestamp,
                    rec.candidate_name,
                    rec.reply_text[:60] + ("..." if len(rec.reply_text) > 60 else ""),
                    "自动" if rec.auto_sent else "手动",
                ))

    def _get_selected_pending(self):
        """获取当前选中的待审批回复"""
        sel = self.pending_tree.selection()
        if not sel:
            messagebox.showinfo("提示", "请先在待审批列表中选择一条回复")
            return None, None, None

        tags = self.pending_tree.item(sel[0], "tags")
        if not tags:
            return None, None, None

        parts = tags[0].split(":")
        reply_id = parts[0]
        position_id = parts[1] if len(parts) > 1 else ""

        agent = self.agent_manager.get_agent(position_id)
        if not agent:
            return None, None, None

        # 找到对应的reply对象
        for reply in agent.get_pending_replies():
            if reply.reply_id == reply_id:
                return reply, agent, position_id

        return None, None, None

    def _approve_selected_reply(self):
        """批准选中的回复"""
        reply, agent, pos_id = self._get_selected_pending()
        if reply is None:
            return

        if agent.approve_reply(reply.reply_id):
            self._set_status(f"已批准发送给 {reply.candidate_name}")
            self._refresh_pending_tree()
            self._refresh_history_tree()

    def _edit_and_approve_reply(self):
        """编辑并批准回复"""
        reply, agent, pos_id = self._get_selected_pending()
        if reply is None:
            return

        # 弹出编辑对话框
        dialog = tk.Toplevel(self.root)
        dialog.title(f"编辑回复 - {reply.candidate_name}")
        dialog.geometry("500x250")
        dialog.transient(self.root)
        dialog.grab_set()

        ttk.Label(dialog, text="编辑回复内容:", font=self.default_font).pack(pady=4)

        edit_text = scrolledtext.ScrolledText(dialog, font=self.mono_font, height=8)
        edit_text.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)
        edit_text.insert(1.0, reply.reply_text)

        def on_send():
            edited = edit_text.get(1.0, tk.END).strip()
            if edited:
                agent.approve_reply(reply.reply_id, edited_text=edited)
                self._set_status(f"已编辑并批准发送给 {reply.candidate_name}")
                self._refresh_pending_tree()
                self._refresh_history_tree()
                dialog.destroy()

        ttk.Button(dialog, text="发送", command=on_send).pack(pady=4)

    def _reject_selected_reply(self):
        """拒绝选中的回复"""
        reply, agent, pos_id = self._get_selected_pending()
        if reply is None:
            return

        if agent.reject_reply(reply.reply_id):
            self._set_status(f"已拒绝发送给 {reply.candidate_name}")
            self._refresh_pending_tree()

    def _approve_all_replies(self):
        """一键批准所有待审批回复"""
        total = 0
        for agent in self.agent_manager.agents.values():
            for reply in agent.get_pending_replies():
                agent.approve_reply(reply.reply_id)
                total += 1

        if total > 0:
            self._set_status(f"已批准全部 {total} 条回复")
            self._refresh_pending_tree()
            self._refresh_history_tree()
        else:
            messagebox.showinfo("提示", "没有待审批的回复")

    def _show_approval_queue(self):
        """显示审批队列摘要并切换到AI助手Tab"""
        total = sum(
            len(a.get_pending_replies())
            for a in self.agent_manager.agents.values()
        )
        if total == 0:
            messagebox.showinfo("审批队列", "当前没有待审批的回复。")
        else:
            self.notebook.select(self.tab_ai)
            self._refresh_pending_tree()

    # ==================== 智能体状态 ====================

    def _ai_refresh_status(self):
        """刷新智能体状态显示"""
        self.ai_status_text.configure(state=tk.NORMAL)
        self.ai_status_text.delete(1.0, tk.END)

        llm_ok = self.llm_client.is_available()
        self.ai_status_text.insert(tk.END,
            f"LLM 服务: {'✓ 可用' if llm_ok else '✗ 不可用 (请启动Ollama)'}  |  "
        )

        agents = self.agent_manager.list_agents()
        if agents:
            self.ai_status_text.insert(tk.END,
                f"已加载智能体: {len(agents)} 个\n"
            )
            for a in agents:
                night_mark = "🌙" if a.get("is_night_now") else "☀️"
                auto_mark = "🤖" if a.get("auto_reply_enabled") else "👤"
                self.ai_status_text.insert(tk.END,
                    f"  {auto_mark} {night_mark} {a['position_name']}: "
                    f"{a['pending_approvals']}条待审批, "
                    f"今日已发{a['total_replies_today']}条, "
                    f"跟踪{a['candidates_tracked']}人\n"
                )
        else:
            self.ai_status_text.insert(tk.END,
                "未加载智能体。请先配置岗位并点击「分析当前截图」自动加载。\n"
                "或使用「智能体配置」菜单管理岗位。"
            )

        self.ai_status_text.configure(state=tk.DISABLED)

    def _open_agent_config(self):
        """打开智能体配置窗口"""
        if self._agent_config_window is None or not self._agent_config_window.window.winfo_exists():
            from gui.agent_config_window import AgentConfigWindow
            self._agent_config_window = AgentConfigWindow(
                self.root, self.agent_manager
            )
        self._agent_config_window.show()

    # ==================== 守护进程控制 ====================

    def _toggle_daemon(self):
        """切换守护进程状态"""
        if self.daemon.state in ("stopped",):
            self._start_daemon()
        elif self.daemon.state == "running":
            self._pause_daemon()
        elif self.daemon.state == "paused":
            self._resume_daemon()

    def _start_daemon(self):
        """启动守护进程"""
        if self.daemon.state in ("running", "starting", "paused"):
            if self.daemon.state == "paused":
                self._resume_daemon()
            return

        # 检查LLM
        if not self.llm_client.is_available():
            if not messagebox.askyesno("提示",
                "LLM服务不可用，守护进程将无法生成回复。\n是否继续启动？"):
                return

        self.daemon.start(use_browser=False)  # 默认不使用浏览器，用截图模式
        self._set_status("守护进程已启动")

    def _stop_daemon(self):
        """停止守护进程"""
        self.daemon.stop()
        self._set_status("守护进程已停止")

    def _pause_daemon(self):
        """暂停守护进程"""
        self.daemon.pause()
        self._set_status("守护进程已暂停")

    def _resume_daemon(self):
        """恢复守护进程"""
        self.daemon.resume()
        self._set_status("守护进程已恢复")

    def _on_daemon_status_change(self, state: str):
        """守护进程状态变化回调"""
        state_texts = {
            "stopped": "已停止",
            "starting": "启动中...",
            "running": "运行中",
            "paused": "已暂停",
            "stopping": "停止中...",
        }
        text = state_texts.get(state, state)

        colors = {
            "running": "green",
            "stopped": "gray",
            "paused": "orange",
            "starting": "orange",
            "stopping": "orange",
        }
        color = colors.get(state, "gray")

        self.root.after(0, lambda: self.daemon_status_label.configure(
            text=f"状态: {text}", foreground=color
        ))

        # 更新按钮状态
        self.root.after(0, self._update_daemon_buttons)

    def _update_daemon_buttons(self):
        """更新守护进程按钮状态"""
        state = self.daemon.state

        if state == "running":
            self.daemon_start_btn.configure(state=tk.DISABLED)
            self.daemon_pause_btn.configure(state=tk.NORMAL)
            self.daemon_stop_btn.configure(state=tk.NORMAL)
            self.daemon_btn.configure(text="⏸ 暂停监控")
        elif state == "paused":
            self.daemon_start_btn.configure(text="▶ 恢复", state=tk.NORMAL)
            self.daemon_pause_btn.configure(state=tk.DISABLED)
            self.daemon_stop_btn.configure(state=tk.NORMAL)
            self.daemon_btn.configure(text="▶ 恢复监控")
        else:
            self.daemon_start_btn.configure(text="▶ 启动", state=tk.NORMAL)
            self.daemon_pause_btn.configure(state=tk.DISABLED)
            self.daemon_stop_btn.configure(state=tk.DISABLED)
            self.daemon_btn.configure(text="🤖 启动后台监控")

        self._refresh_daemon_stats()

    def _on_daemon_activity(self, entry: dict):
        """守护进程活动回调"""
        self.root.after(0, lambda: self._append_daemon_log(entry))

    def _on_daemon_reply_pending(self, reply):
        """守护进程有新回复待审批"""
        self.root.after(0, self._refresh_pending_tree)
        self.root.after(0, self._refresh_history_tree)

    def _append_daemon_log(self, entry: dict):
        """追加守护进程日志"""
        self.daemon_log_text.configure(state=tk.NORMAL)
        level_icons = {
            "system": "📌",
            "cycle": "🔄",
            "agent": "🤖",
            "reply_sent": "✉️",
            "follow_up": "📨",
            "error": "❌",
            "warning": "⚠️",
        }
        icon = level_icons.get(entry.get("level", ""), "•")
        self.daemon_log_text.insert(tk.END,
            f"[{entry['time']}] {icon} {entry['message']}\n"
        )
        self.daemon_log_text.see(tk.END)
        self.daemon_log_text.configure(state=tk.DISABLED)

    def _refresh_daemon_log(self):
        """刷新守护进程日志"""
        self.daemon_log_text.configure(state=tk.NORMAL)
        self.daemon_log_text.delete(1.0, tk.END)
        for entry in self.daemon.get_activity_log(100):
            self._append_daemon_log(entry)
        self.daemon_log_text.configure(state=tk.DISABLED)

    def _clear_daemon_log(self):
        """清空日志显示"""
        self.daemon_log_text.configure(state=tk.NORMAL)
        self.daemon_log_text.delete(1.0, tk.END)
        self.daemon_log_text.configure(state=tk.DISABLED)

    def _refresh_daemon_stats(self):
        """刷新守护进程统计"""
        self.daemon_stats_text.configure(state=tk.NORMAL)
        self.daemon_stats_text.delete(1.0, tk.END)

        status = self.daemon.get_status()
        self.daemon_stats_text.insert(tk.END,
            f"LLM: {'✓' if status['llm_available'] else '✗'}  |  "
            f"OCR: {'✓' if status['ocr_ready'] else '✗'}  |  "
            f"浏览器: {'✓' if status['browser_running'] else '✗'}  |  "
            f"检查间隔: {status['check_interval']}秒  |  "
            f"累计错误: {status['error_count']}\n\n"
            f"已加载智能体:\n"
        )

        for a in status.get("agents", []):
            night = "🌙夜间" if a.get("is_night") else "☀️白天"
            auto = "自动" if a.get("auto_reply_enabled") else "手动"
            self.daemon_stats_text.insert(tk.END,
                f"  [{a['position_id']}] {a['position_name']}: "
                f"{auto}模式 {night} | "
                f"待审批:{a['pending_approvals']} | "
                f"跟踪:{a['candidates_tracked']}人\n"
            )

        self.daemon_stats_text.configure(state=tk.DISABLED)

    # ===================== 处理流程扩展 =====================

    def _on_process_complete(self, file_paths: List[str], summaries: List[dict]):
        """处理完成回调（扩展版：增加AI处理入口）"""
        self.processing = False
        self.progress_bar["value"] = self.progress_bar["maximum"]
        self._set_status(f"处理完成，共识别 {len(file_paths)} 张图片")

        # 显示当前选中图片的结果
        if self.current_index >= 0 and self.current_index < len(self.image_files):
            file_path = self.image_files[self.current_index]
            if file_path in self.summaries:
                self._display_summary(file_path)
            elif file_path in self.ocr_results:
                self._display_ocr_result(file_path)

        # 刷新列表
        self._refresh_list_display()

        # 如果检测到BOSS直聘界面，自动刷新AI助手状态
        for fp in file_paths:
            if fp in self.summaries and self.summaries[fp].get("UI分析"):
                self._ai_refresh_status()
                break

    def _on_close(self):
        """关闭窗口"""
        if self.processing:
            if not messagebox.askyesno("确认", "正在处理中，确定要退出吗？"):
                return

        # 停止守护进程
        if self.daemon and self.daemon.state != "stopped":
            self.daemon.stop()

        # 清理
        self.image_thumbnails.clear()
        self.root.destroy()
