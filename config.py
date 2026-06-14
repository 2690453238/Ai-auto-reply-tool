"""
图片信息识别与分类整理工具 - 全局配置
"""

# 应用信息
APP_NAME = "图片信息识别与分类整理工具"
APP_VERSION = "1.0.0"

# OCR 配置
OCR_LANGUAGES = ["ch_sim", "en"]  # 简体中文 + 英文
OCR_GPU = True  # 是否使用 GPU 加速

# 支持的文件格式
SUPPORTED_IMAGE_FORMATS = (".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".webp")

# 缩略图尺寸
THUMBNAIL_SIZE = (120, 120)

# 预览最大尺寸
PREVIEW_MAX_SIZE = (600, 600)

# 关键信息提取的正则模式
EXTRACTION_PATTERNS = {
    "日期": [
        r"\d{4}[-/年]\d{1,2}[-/月]\d{1,2}[日]?",
        r"\d{4}\.\d{1,2}\.\d{1,2}",
        r"\d{1,2}[-/月]\d{1,2}[-/日]?\s*\d{2}:\d{2}",
    ],
    "金额": [
        r"[¥￥]\s*\d+[.,]?\d*",
        r"\$\s*\d+[.,]?\d*",
        r"\d+[.,]?\d*\s*[元块]",
        r"人民币\s*\d+[.,]?\d*\s*[元块]?",
    ],
    "手机号": [
        r"1[3-9]\d{9}",
    ],
    "固定电话": [
        r"0\d{2,3}[-]\d{7,8}",
        r"\d{3,4}[-]\d{7,8}",
    ],
    "身份证号": [
        r"\d{17}[\dXx]",
    ],
    "邮箱": [
        r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
    ],
    "网址": [
        r"https?://[^\s]+",
        r"www\.[^\s]+",
    ],
}

# 文档类型分类关键词
DOC_TYPE_KEYWORDS = {
    "身份证": ["居民身份证", "中华人民共和国", "姓名", "性别", "民族", "出生", "住址", "公民身份号码"],
    "发票": ["发票", "Invoice", "INVOICE", "发票代码", "发票号码", "开票日期", "合计金额", "价税合计"],
    "名片": ["名片", "经理", "总监", "董事长", "总经理", "电话", "邮箱", "地址", "网址"],
    "收据": ["收据", "Receipt", "RECEIPT", "收到", "收款", "经手人"],
    "合同": ["合同", "协议", "甲方", "乙方", "Contract", "Agreement"],
    "营业执照": ["营业执照", "统一社会信用代码", "法定代表人", "注册资本", "经营范围"],
    "银行单据": ["银行", "Bank", "账号", "户名", "开户行", "流水号"],
}

# 导出配置
EXPORT_DEFAULT_DIR = ""  # 空表示默认导出到桌面

# ===== AI Agent 配置 =====

# Ollama API
OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_DEFAULT_MODEL = "qwen2.5:3b"
OLLAMA_TIMEOUT_SECONDS = 60
OLLAMA_MAX_RETRIES = 2

# 数据目录
import os
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
POSITIONS_DIR = os.path.join(DATA_DIR, "positions")
STRATEGIES_DIR = os.path.join(DATA_DIR, "strategies")
MEMORIES_DIR = os.path.join(DATA_DIR, "memories")

# 守护进程
DAEMON_DEFAULT_CHECK_INTERVAL = 300  # 秒
DAEMON_NIGHT_START_HOUR = 22
DAEMON_NIGHT_END_HOUR = 8
DAEMON_MAX_REPLIES_PER_HOUR = 20

# 浏览器自动化
BROWSER_HEADLESS = True
BROWSER_SESSION_DIR = os.path.join(DATA_DIR, "browser_session")
BROWSER_USER_DATA_DIR = os.path.join(DATA_DIR, "chrome_profile")

# 记忆系统
MEMORY_MAX_TURNS_BEFORE_SUMMARIZE = 15
MEMORY_MAX_CONTEXT_TURNS = 20

# 安全
BLOCKED_PHRASES = ["加微信", "私下联系", "转账", "支付宝", "银行卡号", "身份证号"]
AUTO_REJECT_KEYWORDS = ["不合适", "不考虑了", "已经找到工作", "暂时不需要"]
