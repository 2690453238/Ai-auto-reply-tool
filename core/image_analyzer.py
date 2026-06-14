"""
图片分析器
提取图片的 EXIF 元数据、基本属性、视觉特征
"""

import os
import hashlib
from datetime import datetime
from typing import Dict, Any, Optional
from PIL import Image, ExifTags
from collections import Counter


# EXIF 标签映射（常用标签的中文名）
EXIF_LABELS = {
    "Make": "相机制造商",
    "Model": "相机型号",
    "DateTimeOriginal": "拍摄时间",
    "DateTimeDigitized": "数字化时间",
    "DateTime": "修改时间",
    "ExposureTime": "曝光时间",
    "FNumber": "光圈值",
    "ISOSpeedRatings": "ISO",
    "FocalLength": "焦距",
    "Flash": "闪光灯",
    "ExposureBiasValue": "曝光补偿",
    "MeteringMode": "测光模式",
    "WhiteBalance": "白平衡",
    "GPSInfo": "GPS信息",
    "Software": "软件",
    "Artist": "作者",
    "Copyright": "版权",
    "ImageDescription": "图片描述",
    "Orientation": "方向",
    "XResolution": "水平分辨率",
    "YResolution": "垂直分辨率",
    "ResolutionUnit": "分辨率单位",
    "ColorSpace": "色彩空间",
    "LensModel": "镜头型号",
}


class ImageAnalyzer:
    """图片属性分析器"""

    @staticmethod
    def get_exif_data(image: Image.Image) -> Dict[str, Any]:
        """
        提取图片 EXIF 元数据

        返回:
            {"相机制造商": "Canon", "拍摄时间": "2024-01-15 10:30:00", ...}
        """
        exif_data = {}
        try:
            raw_exif = image.getexif()
            if not raw_exif:
                return exif_data

            for tag_id, value in raw_exif.items():
                tag_name = ExifTags.TAGS.get(tag_id, str(tag_id))
                label = EXIF_LABELS.get(tag_name, tag_name)

                # 处理特殊类型
                if isinstance(value, bytes):
                    try:
                        value = value.decode("utf-8", errors="replace")
                    except Exception:
                        value = str(value)
                elif isinstance(value, tuple):
                    # 有理数类型
                    if len(value) == 2 and isinstance(value[0], int) and isinstance(value[1], int):
                        if value[1] != 0:
                            value = round(value[0] / value[1], 4)
                        else:
                            value = str(value)
                    else:
                        value = str(value)

                exif_data[label] = value

        except Exception as e:
            exif_data["EXIF提取错误"] = str(e)

        return exif_data

    @staticmethod
    def get_gps_info(image: Image.Image) -> Dict[str, Any]:
        """提取 GPS 信息（如果有）"""
        gps = {}
        try:
            exif = image.getexif()
            gps_info = exif.get_ifd(ExifTags.IFD.GPSInfo)
            if not gps_info:
                return gps

            for key, val in gps_info.items():
                tag_name = ExifTags.GPSTAGS.get(key, str(key))
                if isinstance(val, tuple) and len(val) == 3:
                    # GPS 坐标：度、分、秒
                    degrees = float(val[0])
                    minutes = float(val[1])
                    seconds = float(val[2])
                    decimal = degrees + minutes / 60 + seconds / 3600
                    gps[tag_name] = round(decimal, 6)
                else:
                    gps[tag_name] = str(val)
        except Exception:
            pass
        return gps

    @staticmethod
    def get_basic_info(image: Image.Image, file_path: Optional[str] = None) -> Dict[str, Any]:
        """
        提取图片基本属性

        返回:
            {"文件名": "xxx.jpg", "尺寸": "1920x1080", "格式": "JPEG", ...}
        """
        info = {}

        # 文件信息
        if file_path and os.path.exists(file_path):
            info["文件路径"] = file_path
            info["文件名"] = os.path.basename(file_path)
            info["文件大小"] = ImageAnalyzer._format_file_size(os.path.getsize(file_path))
            info["修改时间"] = datetime.fromtimestamp(
                os.path.getmtime(file_path)
            ).strftime("%Y-%m-%d %H:%M:%S")

        # 图像信息
        info["尺寸"] = f"{image.width} × {image.height}"
        info["格式"] = image.format or "未知"
        info["色彩模式"] = image.mode
        info["宽高比"] = f"{image.width / image.height:.2f}:1" if image.height > 0 else "N/A"

        return info

    @staticmethod
    def get_color_features(image: Image.Image) -> Dict[str, Any]:
        """
        分析图片色彩特征

        返回:
            {"主色调": "蓝色系", "平均亮度": 128.5, ...}
        """
        features = {}
        try:
            # 缩放到小图加速分析
            small = image.copy()
            small.thumbnail((100, 100))
            if small.mode != "RGB":
                small = small.convert("RGB")

            pixels = list(small.getdata())

            # 平均亮度
            total_brightness = sum(0.299 * r + 0.587 * g + 0.114 * b for r, g, b in pixels)
            avg_brightness = total_brightness / len(pixels) if pixels else 0
            features["平均亮度"] = round(avg_brightness, 1)

            # 主色调
            color_bins = Counter()
            for r, g, b in pixels:
                # 将颜色量化到粗粒度区间
                bin_r = (r // 50) * 50
                bin_g = (g // 50) * 50
                bin_b = (b // 50) * 50
                color_bins[(bin_r, bin_g, bin_b)] += 1

            if color_bins:
                dominant = color_bins.most_common(1)[0][0]
                features["主色调RGB"] = f"({dominant[0]}, {dominant[1]}, {dominant[2]})"
                features["主色调"] = ImageAnalyzer._rgb_to_color_name(*dominant)

        except Exception as e:
            features["色彩分析错误"] = str(e)

        return features

    @staticmethod
    def compute_hash(file_path: str, algorithm: str = "md5") -> str:
        """计算文件的哈希值"""
        h = hashlib.new(algorithm)
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()

    @staticmethod
    def analyze(file_path: str) -> Dict[str, Any]:
        """
        综合分析一张图片的所有属性

        返回:
            {
                "file": "路径",
                "basic": {...},
                "exif": {...},
                "gps": {...},
                "color": {...},
                "hash_md5": "..."
            }
        """
        if not os.path.exists(file_path):
            return {"error": f"文件不存在: {file_path}"}

        try:
            image = Image.open(file_path)
        except Exception as e:
            return {"error": f"无法打开图片: {e}"}

        result = {
            "file": file_path,
            "basic": ImageAnalyzer.get_basic_info(image, file_path),
            "exif": ImageAnalyzer.get_exif_data(image),
            "gps": ImageAnalyzer.get_gps_info(image),
            "color": ImageAnalyzer.get_color_features(image),
            "hash_md5": ImageAnalyzer.compute_hash(file_path),
        }

        return result

    # ----- 辅助方法 -----

    @staticmethod
    def _format_file_size(size_bytes: int) -> str:
        """格式化文件大小"""
        for unit in ["B", "KB", "MB", "GB"]:
            if size_bytes < 1024:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f} TB"

    @staticmethod
    def _rgb_to_color_name(r: int, g: int, b: int) -> str:
        """将 RGB 转换为颜色中文名称"""
        # 简单规则判断
        if max(r, g, b) - min(r, g, b) < 30:
            if r > 200:
                return "白色系"
            elif r < 50:
                return "黑色系"
            else:
                return "灰色系"
        if r > g and r > b:
            if g > 150:
                return "黄色系"
            return "红色系"
        if g > r and g > b:
            return "绿色系"
        if b > r and b > g:
            return "蓝色系"
        if r > 150 and g > 150:
            return "黄色系"
        if r > 150 and b > 150:
            return "紫色系"
        if g > 150 and b > 150:
            return "青色系"
        return "混合色系"
