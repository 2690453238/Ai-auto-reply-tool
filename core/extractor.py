"""
信息提取器
从 OCR 识别文字中提取结构化关键信息，并进行文档类型分类
"""

import re
from typing import Dict, Any, List, Tuple
from config import EXTRACTION_PATTERNS, DOC_TYPE_KEYWORDS


class InfoExtractor:
    """关键信息提取与文档分类"""

    @staticmethod
    def extract_key_fields(text: str) -> Dict[str, List[str]]:
        """
        从文本中提取关键结构化字段

        参数:
            text: OCR 识别的完整文本

        返回:
            {"日期": ["2024-01-15", ...], "金额": ["¥100.00", ...], ...}
        """
        results = {}

        for field_name, patterns in EXTRACTION_PATTERNS.items():
            matches = set()  # 使用 set 去重
            for pattern in patterns:
                found = re.findall(pattern, text)
                for m in found:
                    # 清理空白
                    cleaned = re.sub(r"\s+", "", m) if isinstance(m, str) else str(m)
                    if cleaned:
                        matches.add(cleaned)
            if matches:
                results[field_name] = sorted(list(matches))

        return results

    @staticmethod
    def classify_document(text: str) -> Tuple[str, float]:
        """
        根据文字内容自动判断文档类型

        参数:
            text: OCR 识别的完整文本

        返回:
            (文档类型, 置信度 0~1)
        """
        if not text or not text.strip():
            return "未知", 0.0

        scores = {}
        for doc_type, keywords in DOC_TYPE_KEYWORDS.items():
            score = 0
            for kw in keywords:
                if kw.lower() in text.lower():
                    score += 1
            if score > 0:
                scores[doc_type] = score / len(keywords)

        if not scores:
            return "通用图片", 0.3

        # 返回得分最高的类型
        best_type = max(scores, key=scores.get)
        best_score = scores[best_type]

        # 根据匹配度调整置信度
        if best_score >= 0.3:
            return best_type, min(best_score * 1.5, 1.0)
        else:
            return "通用图片", 0.3

    @staticmethod
    def generate_summary(
        ocr_text: str,
        ocr_results: List[dict],
        image_analysis: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        为一张图片生成完整的信息摘要

        参数:
            ocr_text: 识别的完整文字
            ocr_results: OCR 详细结果列表
            image_analysis: ImageAnalyzer.analyze() 的结果

        返回:
            {
                "文档类型": "发票",
                "类型置信度": 0.85,
                "识别文字摘要": "...",
                "关键字段": {...},
                "图片属性": {...},
                "文字行数": N,
                "高置信度文字": [...],
            }
        """
        # 分类
        doc_type, confidence = InfoExtractor.classify_document(ocr_text)

        # 提取关键字段
        key_fields = InfoExtractor.extract_key_fields(ocr_text)

        # 高置信度文字（confidence >= 0.7）
        high_conf_text = [
            r for r in ocr_results
            if r.get("confidence", 0) >= 0.7
        ]

        # 文字摘要（取前200字）
        text_summary = ocr_text[:200] + ("..." if len(ocr_text) > 200 else "")

        summary = {
            "文档类型": doc_type,
            "类型置信度": round(confidence, 2),
            "识别文字摘要": text_summary,
            "识别文字全文": ocr_text,
            "关键字段": key_fields,
            "图片属性": image_analysis.get("basic", {}),
            "EXIF信息": image_analysis.get("exif", {}),
            "色彩特征": image_analysis.get("color", {}),
            "图片哈希": image_analysis.get("hash_md5", ""),
            "文字行数": len(ocr_results),
            "高置信度文字行数": len(high_conf_text),
        }

        return summary

    @staticmethod
    def batch_summarize(
        ocr_batch_results: List[dict],
        image_analyses: Dict[str, Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        批量生成信息摘要

        参数:
            ocr_batch_results: OCR 批量识别结果
            image_analyses: {"文件路径": analyze()结果, ...}

        返回:
            [summary1, summary2, ...]
        """
        summaries = []
        for ocr_item in ocr_batch_results:
            file_path = ocr_item["file"]
            analysis = image_analyses.get(file_path, {})

            summary = InfoExtractor.generate_summary(
                ocr_text=ocr_item.get("text", ""),
                ocr_results=ocr_item.get("results", []),
                image_analysis=analysis,
            )
            summary["文件路径"] = file_path
            summary["文件名"] = ocr_item.get("file", "").split("\\")[-1].split("/")[-1] if ocr_item.get("file") else "未知"
            summary["识别状态"] = "失败" if ocr_item.get("error") else "成功"
            if ocr_item.get("error"):
                summary["错误信息"] = ocr_item["error"]

            summaries.append(summary)

        return summaries
