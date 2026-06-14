"""
图片信息识别与分类整理工具 - 主入口
功能：加载图片 → OCR文字识别 → 图片属性提取 → 关键信息提取 → 分类导出
"""

import sys
import os

# 确保项目根目录在 sys.path 中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gui.main_window import MainWindow


def main():
    """启动主程序"""
    app = MainWindow()
    app.run()


if __name__ == "__main__":
    main()
