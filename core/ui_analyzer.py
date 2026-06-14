"""
UI 截图分析器
专门针对招聘软件（BOSS直聘等）聊天界面的结构化信息提取
"""

import re
from typing import List, Dict, Any, Optional, Tuple
from collections import defaultdict


class UIAnalyzer:
    """UI 截图结构化分析"""

    JOB_KEYWORDS = [
        "前台", "日结", "包吃住", "自拍馆", "自掊馆", "销售", "客服",
        "运营", "经理", "助理", "主管", "专员", "顾问", "店长", "服务员",
        "收银", "快递", "骑手", "司机", "保安", "保洁", "厨师", "服务员",
    ]

    NAV_KEYWORDS = ["消息", "意向沟通", "推荐", "职位", "数据", "面", "搜索", "工具",
                    "账号权益", "新招呼", "已约面", "全部"]

    # 匹配时间格式: 14:38, 14.38, 14-38, 09.18, 06-47, 14-1(=14:01)
    TIME_PATTERN = re.compile(r"^\d{1,2}[.:-]\d{2}$")

    @staticmethod
    def _parse_time(text: str) -> Optional[str]:
        """Normalize various time formats to HH:MM"""
        t = text.strip()
        m = re.match(r"^(\d{1,2})[.:-](\d{2})$", t)
        if m:
            return f"{int(m.group(1)):02d}:{m.group(2)}"
        # Also match "14-1" → "14:01"
        m2 = re.match(r"^(\d{1,2})[.:-](\d{1})$", t)
        if m2:
            return f"{int(m2.group(1)):02d}:0{m2.group(2)}"
        return None

    @staticmethod
    def detect_layout(ocr_results: List[dict]) -> Dict[str, Any]:
        """Detect UI layout structure from OCR results."""
        if not ocr_results:
            return {"error": "无 OCR 结果"}

        all_x = [int(r["bbox"][0][0]) for r in ocr_results] + [int(r["bbox"][2][0]) for r in ocr_results]
        all_y = [int(r["bbox"][0][1]) for r in ocr_results] + [int(r["bbox"][2][1]) for r in ocr_results]
        img_w = max(all_x) + 50 if all_x else 1600
        img_h = max(all_y) + 50 if all_y else 1000

        return {"image_size": (img_w, img_h)}

    @staticmethod
    def extract_navigation(ocr_results: List[dict]) -> Dict[str, Any]:
        """Extract left navigation bar info (unread count, tabs)."""
        nav = {
            "active_tab": "消息",
            "unread_count": 0,
            "tabs": [],
        }

        nav_items = [r for r in ocr_results if r["bbox"][0][0] < 200]
        nav_items.sort(key=lambda r: r["bbox"][0][1])

        for item in nav_items:
            text = item["text"]
            y = int(item["bbox"][0][1])

            # Tabs (y < 1000, skip detail panel text)
            if y < 1000:
                for kw in UIAnalyzer.NAV_KEYWORDS:
                    if kw in text and text not in nav["tabs"]:
                        nav["tabs"].append(text)
                        break

            # Unread count — a number near "消息" tab
            if text.strip().isdigit() and y < 300:
                count = int(text.strip())
                if count > nav["unread_count"]:
                    nav["unread_count"] = count

        return nav

    @staticmethod
    def extract_candidate_cards(ocr_results: List[dict]) -> List[Dict[str, Any]]:
        """
        Extract candidate cards from the left list.
        Uses Y-position clustering to group items into cards.
        """
        # Filter: items in the left list area (x 200-650, y > 170, y < 920)
        card_items = [
            r for r in ocr_results
            if 200 <= r["bbox"][0][0] <= 650
            and 170 <= r["bbox"][0][1] <= 920
        ]
        card_items.sort(key=lambda r: (r["bbox"][0][1], r["bbox"][0][0]))

        # Cluster by Y position (gap > 30px = new card)
        cards = []
        current_items = []

        for i, item in enumerate(card_items):
            y = int(item["bbox"][0][1])
            if current_items:
                last_y = int(current_items[-1]["bbox"][0][1])
                if y - last_y > 50:  # New card starts
                    cards.append(current_items)
                    current_items = [item]
                else:
                    current_items.append(item)
            else:
                current_items.append(item)

        if current_items:
            cards.append(current_items)

        # Parse each card
        parsed = []
        for card in cards:
            if not card:
                continue

            # Sort by Y then X
            card.sort(key=lambda r: (r["bbox"][0][1], r["bbox"][0][0]))

            name = ""
            job_title = ""
            time_str = ""
            last_message = ""
            status = ""

            for item in card:
                text = item["text"]
                x = int(item["bbox"][0][0])
                y = int(item["bbox"][0][1])
                conf = item.get("confidence", 0)

                # Check if this is the "primary" line (name + job) — typically the first line with job keywords
                has_job_kw = any(kw in text for kw in UIAnalyzer.JOB_KEYWORDS)

                # Time — at right edge (x > 570)
                parsed_time = UIAnalyzer._parse_time(text)
                if parsed_time and x > 550:
                    time_str = parsed_time

                # Main name+job line
                if has_job_kw and len(text) > 5:
                    parts = UIAnalyzer._parse_name_job(text)
                    if parts["name"]:
                        name = parts["name"]
                    if parts["job"]:
                        job_title = parts["job"]

                # Message preview — shorter line between name and next card
                elif not has_job_kw and not parsed_time and len(text) > 2:
                    # Exclude education/expectation lines (these have 2022-2025 style)
                    if not re.match(r"^\d{4}[-]\d{4}$", text):
                        if not last_message:
                            last_message = text

                # Unread detection — "未读" or "末读" near middle of card
                if "未读" in text or "末读" in text:
                    status = "未读"

            if name:
                parsed.append({
                    "name": name,
                    "job_title": job_title,
                    "time": time_str,
                    "last_message": last_message,
                    "status": status if status else ("未读" if time_str == "" else "已读"),
                })

        # Deduplicate by name + y (same person at same position)
        seen = set()
        deduped = []
        for c in parsed:
            key = c["name"]
            if key not in seen:
                seen.add(key)
                deduped.append(c)

        return deduped

    @staticmethod
    def extract_right_panel(ocr_results: List[dict]) -> Dict[str, Any]:
        """
        Extract right panel: candidate detail + chat messages.
        Right panel is roughly x > 650.
        """
        right_items = [r for r in ocr_results if r["bbox"][0][0] > 400]
        right_items.sort(key=lambda r: (r["bbox"][0][1], r["bbox"][0][0]))

        panel = {
            "candidate_name": "",
            "status": "",
            "personal_info": {},
            "job_position": "",
            "messages": [],
            "actions": [],
        }

        # --- Top area (y < 240): candidate detail ---
        detail_items = [r for r in right_items if r["bbox"][0][1] < 240]
        for item in sorted(detail_items, key=lambda r: (r["bbox"][0][1], r["bbox"][0][0])):
            text = item["text"]
            x = int(item["bbox"][0][0])
            y = int(item["bbox"][0][1])

            # Candidate name (left side of detail header, ~x 660-700)
            if x < 750 and y < 100 and len(text) <= 4:
                panel["candidate_name"] = text

            # Status badge
            if ("活跃" in text or "在线" in text) and y < 100:
                panel["status"] = text

            # Personal info tags
            if "岁" in text:
                panel["personal_info"]["年龄"] = text
            elif "应届" in text or "届" in text:
                panel["personal_info"]["届别"] = text
            elif any(e in text for e in ["高中", "本科", "大专", "硕士", "初中"]):
                panel["personal_info"]["学历"] = text

            # Work experience / education
            if re.match(r"\d{4}-\d{4}", text):
                panel["personal_info"]["学历时段"] = text

        # --- Mid area (y 170-240): position info ---
        for item in detail_items:
            text = item["text"]
            x = int(item["bbox"][0][0])

            if "工作经历" in text:
                panel["personal_info"]["工作经历"] = text
            elif "沟通职位" in text and x > 1000:
                panel["job_position"] = text
            elif "期望" in text and x > 1000:
                panel["personal_info"]["期望"] = text

        # --- Messages (y 240-870) ---
        msg_items = [r for r in right_items if 240 <= r["bbox"][0][1] < 870]
        msg_items.sort(key=lambda r: (r["bbox"][0][1], r["bbox"][0][0]))

        # Group by Y line
        msg_lines = defaultdict(list)
        for item in msg_items:
            y_key = int(item["bbox"][0][1]) // 35
            msg_lines[y_key].append(item)

        for y_key in sorted(msg_lines.keys()):
            line_items = msg_lines[y_key]
            # Combine left-to-right
            line_items.sort(key=lambda r: r["bbox"][0][0])
            combined = " ".join([i["text"] for i in line_items if i["text"].strip()])
            if not combined.strip():
                continue

            avg_x = sum(i["bbox"][0][0] for i in line_items) / len(line_items)
            is_me = avg_x > 1100

            panel["messages"].append({
                "sender": "我" if is_me else "对方",
                "text": combined,
            })

        # --- Actions (y > 850) ---
        action_items = sorted(
            [r for r in right_items if r["bbox"][0][1] > 850],
            key=lambda r: r["bbox"][0][0],
        )
        panel["actions"] = [
            r["text"] for r in action_items
            if len(r["text"]) <= 6 and r["text"] not in ["06.47", "06:47"]
        ]

        return panel

    @staticmethod
    def comprehensive_analysis(ocr_results: List[dict]) -> Dict[str, Any]:
        """Full UI analysis combining all components."""
        all_text = " ".join([r["text"] for r in ocr_results])
        platform = "通用"
        if "BOSS" in all_text.upper() or "B0Ss" in all_text or "直聘" in all_text:
            platform = "BOSS直聘"

        nav = UIAnalyzer.extract_navigation(ocr_results)
        candidates = UIAnalyzer.extract_candidate_cards(ocr_results)
        right_panel = UIAnalyzer.extract_right_panel(ocr_results)
        layout = UIAnalyzer.detect_layout(ocr_results)

        # New greet count from horizontal filter bar
        new_greet_count = 0
        for r in ocr_results:
            m = re.search(r"新招呼[\(（](\d+)[\)）]", r["text"])
            if m:
                new_greet_count = int(m.group(1))
                break

        return {
            "平台": platform,
            "导航": nav,
            "左侧_候选人列表": candidates,
            "右侧_详情面板": right_panel,
            "布局": {
                "图片尺寸": layout.get("image_size", (0, 0)),
            },
            "统计": {
                "候选人总数": len(candidates),
                "未读消息数": nav.get("unread_count", 0),
                "新招呼数": new_greet_count,
                "识别文字总数": len(ocr_results),
            },
        }

    # ===== Internal helpers =====

    @staticmethod
    def _parse_name_job(text: str) -> Dict[str, str]:
        """Split 'Name  JobTitle' into parts."""
        # Try double-space split first
        parts = re.split(r"\s{2,}", text.strip())
        if len(parts) >= 2:
            name = parts[0].strip()
            job = parts[-1].strip()
            # Validate name looks like a Chinese name
            if re.match(r"^[一-鿿•]+$", name) and len(name) <= 5:
                return {"name": name, "job": job}

        # Try splitting at first job keyword
        for kw in sorted(UIAnalyzer.JOB_KEYWORDS, key=len, reverse=True):
            idx = text.find(kw)
            if 1 < idx < 15:
                name = text[:idx].strip()
                job = text[idx:].strip()
                if re.match(r"^[一-鿿•]+$", name) and len(name) <= 6:
                    return {"name": name, "job": job}

        return {"name": "", "job": text.strip()}
