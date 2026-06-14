"""
OCR 文字识别引擎
基于 EasyOCR 实现中英文文字识别
支持 PyInstaller 打包后的模型文件加载
"""

import os
import sys
import threading
import time
from typing import List, Tuple, Optional, Callable
from PIL import Image

from config import OCR_LANGUAGES, OCR_GPU


class OCREngine:
    """EasyOCR 封装引擎"""

    _instance = None
    _reader = None
    _lock = threading.Lock()
    _initialized = False
    _init_error = ""

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """初始化（实际加载在 init_reader 中延迟执行）"""
        pass

    @staticmethod
    def _get_model_storage_dir() -> Optional[str]:
        """
        获取模型存储目录
        - 打包后：PyInstaller _MEIPASS 中的 .EasyOCR/model
        - 开发环境：用户目录下的 .EasyOCR/model
        """
        # 检查 PyInstaller 打包后的路径
        if getattr(sys, "frozen", False):
            bundled = os.path.join(sys._MEIPASS, ".EasyOCR", "model")
            if os.path.isdir(bundled) and os.listdir(bundled):
                return os.path.dirname(bundled)

        # 开发环境：检查默认路径
        default = os.path.join(os.path.expanduser("~"), ".EasyOCR", "model")
        if os.path.isdir(default) and os.listdir(default):
            return os.path.dirname(default)

        return None

    @classmethod
    def init_reader(cls, callback: Optional[Callable[[str], None]] = None) -> bool:
        """
        初始化 EasyOCR Reader
        callback: 进度回调，接收状态文字
        返回是否成功
        """
        with cls._lock:
            if cls._initialized:
                return True

            cls._init_error = ""
            try:
                if callback:
                    callback("正在加载 OCR 引擎...")

                import easyocr

                # 获取模型路径
                model_dir = cls._get_model_storage_dir()

                # 验证模型文件存在
                if model_dir:
                    model_path = os.path.join(model_dir, "model")
                    model_files = os.listdir(model_path) if os.path.isdir(model_path) else []
                    if callback:
                        callback(f"找到 {len(model_files)} 个模型文件，正在加载...")
                else:
                    if callback:
                        callback("未找到本地模型，将从网络下载（可能需要几分钟）...")

                if callback:
                    callback("加载检测模型中...")

                # 构建 Reader，禁止自动下载
                reader_kwargs = {
                    "lang_list": OCR_LANGUAGES,
                    "gpu": OCR_GPU,
                    "verbose": False,
                    "download_enabled": False,  # 关键：禁止网络下载，只用本地模型
                }
                if model_dir:
                    reader_kwargs["model_storage_directory"] = model_dir

                cls._reader = easyocr.Reader(**reader_kwargs)

                if callback:
                    callback("OCR ready")
                cls._initialized = True
                return True

            except Exception as e:
                cls._init_error = str(e)
                # 如果模型缺失，尝试启用下载重试
                if "missing" in str(e).lower() or "not found" in str(e).lower():
                    try:
                        if callback:
                            callback("Downloading models from network...")
                        import easyocr
                        cls._reader = easyocr.Reader(
                            OCR_LANGUAGES, gpu=OCR_GPU,
                            verbose=False, download_enabled=True,
                        )
                        cls._initialized = True
                        if callback:
                            callback("OCR ready (models downloaded)")
                        return True
                    except Exception as e2:
                        cls._init_error = str(e2)
                        if callback:
                            callback(f"OCR failed: {str(e2)[:80]}")
                        return False
                else:
                    if callback:
                        callback(f"OCR failed: {str(e)[:80]}")
                    return False

    @classmethod
    def is_ready(cls) -> bool:
        """检查 OCR 引擎是否已就绪"""
        return cls._initialized and cls._reader is not None

    @classmethod
    def get_error(cls) -> str:
        """获取初始化错误信息"""
        return cls._init_error

    def recognize(
        self,
        image: Image.Image,
        detail: int = 1,
    ) -> List[dict]:
        """
        识别单张图片中的文字
        """
        if not self.is_ready():
            raise RuntimeError("OCR 引擎未初始化，请先调用 init_reader()")

        import numpy as np
        img_array = np.array(image)

        if detail == 0:
            raw = self._reader.readtext(img_array, detail=0)
            return [{"text": r, "bbox": [], "confidence": 0.0} for r in raw]
        else:
            raw = self._reader.readtext(img_array, detail=1)
            return [
                {"text": r[1], "bbox": r[0], "confidence": round(float(r[2]), 4)}
                for r in raw
            ]

    def recognize_file(
        self, file_path: str, detail: int = 1,
    ) -> List[dict]:
        """识别图片文件中的文字"""
        image = Image.open(file_path)
        if image.mode not in ("RGB", "L"):
            image = image.convert("RGB")
        return self.recognize(image, detail=detail)

    def recognize_batch(
        self,
        file_paths: List[str],
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
    ) -> List[dict]:
        """批量识别多张图片"""
        results = []
        total = len(file_paths)
        for i, path in enumerate(file_paths):
            if progress_callback:
                progress_callback(i + 1, total, os.path.basename(path))
            try:
                ocr_results = self.recognize_file(path, detail=1)
                full_text = " ".join([r["text"] for r in ocr_results])
                results.append({
                    "file": path, "text": full_text,
                    "results": ocr_results, "error": None,
                })
            except Exception as e:
                results.append({
                    "file": path, "text": "",
                    "results": [], "error": str(e),
                })
        return results
