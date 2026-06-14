"""
浏览器自动化控制器 — BOSS直聘 web 操作
支持：登录/截图/DOM抓取/发送消息
"""

import os
import time
import json
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from PIL import Image
import io


class BrowserController:
    """
    BOSS直聘浏览器自动化

    使用 Selenium + undetected-chromedriver
    支持两种模式：
    - 截图模式：截图 → OCR 分析（兼容既有流程）
    - DOM 模式：直接从 DOM 抓取消息（更准确）
    """

    def __init__(
        self,
        headless: bool = True,
        session_dir: str = None,
        user_data_dir: str = None,
    ):
        self.headless = headless
        self.driver = None

        # 会话持久化路径
        if session_dir is None:
            session_dir = str(
                Path(__file__).parent.parent / "data" / "browser_session"
            )
        if user_data_dir is None:
            user_data_dir = str(
                Path(__file__).parent.parent / "data" / "chrome_profile"
            )

        self.session_dir = Path(session_dir)
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.user_data_dir = Path(user_data_dir)

        self._logged_in = False
        self._current_job_id = ""

    # ==================== 浏览器生命周期 ====================

    def start(self) -> bool:
        """
        启动浏览器驱动
        返回是否成功
        """
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            from selenium.webdriver.chrome.service import Service

            options = Options()

            # 用户数据目录（保存登录状态）
            options.add_argument(f"--user-data-dir={self.user_data_dir}")

            if self.headless:
                options.add_argument("--headless=new")
                options.add_argument("--window-size=1920,1080")

            # 反检测参数
            options.add_argument("--disable-blink-features=AutomationControlled")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--no-sandbox")
            options.add_experimental_option("excludeSwitches", ["enable-automation"])
            options.add_experimental_option("useAutomationExtension", False)

            # 避免被检测为bot
            options.add_argument(
                "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            )

            try:
                # 尝试 undetected-chromedriver
                import undetected_chromedriver as uc
                self.driver = uc.Chrome(options=options, headless=self.headless)
            except ImportError:
                # 回退到普通 chrome
                self.driver = webdriver.Chrome(options=options)

            # 隐藏 webdriver 特征
            self.driver.execute_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )

            self.driver.implicitly_wait(10)
            return True

        except Exception as e:
            print(f"启动浏览器失败: {e}")
            self.driver = None
            return False

    def close(self):
        """关闭浏览器"""
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None
        self._logged_in = False

    def is_running(self) -> bool:
        """检查浏览器是否运行中"""
        return self.driver is not None

    # ==================== 登录 ====================

    def login_saved_session(self) -> bool:
        """
        尝试使用已保存的会话登录
        如果会话有效，直接进入；否则返回 False
        """
        if not self.driver:
            return False

        try:
            self.driver.get("https://www.zhipin.com/web/chat/")
            time.sleep(3)

            # 检查是否跳转到登录页
            current_url = self.driver.current_url
            if "login" in current_url.lower():
                return False

            # 检查页面中是否有聊天列表
            try:
                self.driver.find_element(
                    "xpath", "//*[contains(@class, 'chat-list')]"
                )
                self._logged_in = True
                return True
            except Exception:
                pass

            # 尝试从 Cookie 恢复
            cookie_file = self.session_dir / "cookies.json"
            if cookie_file.exists():
                with open(cookie_file, "r") as f:
                    cookies = json.load(f)
                for cookie in cookies:
                    try:
                        self.driver.add_cookie(cookie)
                    except Exception:
                        pass
                self.driver.refresh()
                time.sleep(2)

                # 再次检查
                if "login" not in self.driver.current_url.lower():
                    self._logged_in = True
                    return True

            return False

        except Exception as e:
            print(f"登录检查失败: {e}")
            return False

    def login_with_qr(self, timeout: int = 120) -> bool:
        """
        打开登录页面，等待用户扫码
        阻塞直到登录成功或超时
        """
        if not self.driver:
            return False

        try:
            self.driver.get("https://www.zhipin.com/web/user/?ka=header-login")
            time.sleep(2)

            # 等待扫码
            print("请使用BOSS直聘APP扫描二维码登录...")
            start = time.time()
            while time.time() - start < timeout:
                current_url = self.driver.current_url
                if "login" not in current_url.lower() and "user" not in current_url.lower():
                    self._logged_in = True
                    self._save_cookies()
                    print("登录成功")
                    return True
                time.sleep(2)

            print("登录超时")
            return False

        except Exception as e:
            print(f"登录失败: {e}")
            return False

    def _save_cookies(self):
        """保存 Cookie 到文件"""
        if self.driver:
            cookies = self.driver.get_cookies()
            with open(self.session_dir / "cookies.json", "w") as f:
                json.dump(cookies, f)

    # ==================== 导航 ====================

    def navigate_to_chat_list(self) -> bool:
        """导航到聊天列表页"""
        if not self.driver or not self._logged_in:
            return False

        try:
            self.driver.get("https://www.zhipin.com/web/chat/")
            time.sleep(2)
            return True
        except Exception:
            return False

    def navigate_to_job_chats(self, job_id: str = "") -> bool:
        """
        导航到指定岗位的聊天页面
        BOSS直聘按岗位区分聊天列表
        """
        if not self.driver or not self._logged_in:
            return False

        try:
            if job_id:
                url = f"https://www.zhipin.com/web/chat/?job_id={job_id}"
            else:
                url = "https://www.zhipin.com/web/chat/"
            self.driver.get(url)
            self._current_job_id = job_id
            time.sleep(2)
            return True
        except Exception:
            return False

    def click_candidate(self, candidate_name: str) -> bool:
        """
        点击候选人名称打开聊天窗口
        """
        if not self.driver:
            return False

        try:
            # 尝试通过文本查找并点击
            candidates = self.driver.find_elements(
                "xpath",
                f"//*[contains(text(), '{candidate_name}')]"
            )
            for elem in candidates:
                if elem.is_displayed() and elem.tag_name in ("span", "div", "a", "li"):
                    try:
                        elem.click()
                        time.sleep(1)
                        return True
                    except Exception:
                        continue
            return False
        except Exception:
            return False

    # ==================== 截图 ====================

    def take_screenshot(self, region: str = "full") -> Image.Image:
        """
        截取浏览器截图

        region: "full" | "chat" | "list"
        """
        if not self.driver:
            return None

        try:
            png_data = self.driver.get_screenshot_as_png()
            return Image.open(io.BytesIO(png_data))
        except Exception:
            return None

    def take_chat_screenshot(self) -> Image.Image:
        """截取右侧聊天区域的截图"""
        if not self.driver:
            return None

        try:
            # 尝试找到聊天消息容器
            chat_area = self.driver.find_element(
                "xpath",
                "//*[contains(@class, 'chat-message') or contains(@class, 'message-list')]"
            )
            png_data = chat_area.screenshot_as_png
            return Image.open(io.BytesIO(png_data))
        except Exception:
            # 回退到全屏截图
            return self.take_screenshot()

    # ==================== DOM 抓取（比OCR更准确） ====================

    def get_chat_messages_dom(self) -> List[Dict[str, str]]:
        """
        从 DOM 直接抓取当前聊天消息（推荐：比OCR准确）

        返回: [{"sender": "对方", "content": "...", "time": "14:30"}, ...]
        """
        if not self.driver:
            return []

        messages = []
        try:
            # BOSS直聘聊天消息选择器（需要根据实际DOM调整）
            msg_elements = self.driver.find_elements(
                "xpath",
                "//*[contains(@class, 'msg-item') or contains(@class, 'message-item')]"
            )

            for elem in msg_elements:
                try:
                    text = elem.text.strip()
                    if not text:
                        continue

                    # 判断发送者
                    class_attr = elem.get_attribute("class") or ""
                    sender = "对方"
                    if "self" in class_attr or "me" in class_attr or "right" in class_attr:
                        sender = "我"

                    messages.append({
                        "sender": sender,
                        "content": text,
                        "time": "",
                    })
                except Exception:
                    continue

        except Exception as e:
            print(f"DOM 抓取消息失败: {e}")

        return messages

    def get_candidate_list_dom(self) -> List[Dict[str, str]]:
        """从 DOM 抓取候选人卡片列表"""
        if not self.driver:
            return []

        candidates = []
        try:
            items = self.driver.find_elements(
                "xpath",
                "//*[contains(@class, 'candidate') or contains(@class, 'chat-item')]"
            )

            for item in items:
                try:
                    text = item.text.strip()
                    lines = text.split("\n")
                    if len(lines) >= 2:
                        name = lines[0]
                        job_title = ""
                        time_str = ""
                        for line in lines[1:]:
                            if ":" in line or "." in line:
                                time_str = line
                            elif len(line) > 2:
                                job_title = line

                        candidates.append({
                            "name": name,
                            "job_title": job_title,
                            "time": time_str,
                            "status": "未读" if "未读" in text else "已读",
                        })
                except Exception:
                    continue

        except Exception as e:
            print(f"DOM 抓取候选人失败: {e}")

        return candidates

    # ==================== 消息发送 ====================

    def send_message(self, text: str) -> bool:
        """
        在聊天输入框输入并发送消息
        """
        if not self.driver:
            return False

        try:
            # 查找输入框
            input_box = self.driver.find_element(
                "xpath",
                "//*[contains(@class, 'input') or contains(@class, 'textarea')]"
                "[not(@disabled)]"
            )

            # 清空并输入
            input_box.clear()
            input_box.send_keys(text)
            time.sleep(0.5)

            # 查找发送按钮
            send_btn = self.driver.find_element(
                "xpath",
                "//*[contains(@class, 'send') or contains(text(), '发送')]"
                " | //button[contains(text(), '发送')]"
            )
            send_btn.click()
            time.sleep(1)

            return True

        except Exception as e:
            print(f"发送消息失败: {e}")
            return False

    # ==================== 状态检查 ====================

    def get_page_status(self) -> dict:
        """获取当前页面状态"""
        if not self.driver:
            return {"state": "browser_not_running"}

        try:
            url = self.driver.current_url
            title = self.driver.title
            return {
                "state": "ok",
                "url": url,
                "title": title,
                "logged_in": self._logged_in,
                "current_job_id": self._current_job_id,
            }
        except Exception as e:
            return {"state": "error", "error": str(e)}
