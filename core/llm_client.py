"""
LLM 客户端 — Ollama API 封装
支持本地模型调用：generate / chat / 模型列表
"""

import json
import time
from typing import List, Dict, Optional, Tuple
import httpx


class LLMClient:
    """Ollama HTTP API 客户端"""

    def __init__(self, base_url: str = "http://localhost:11434",
                 default_model: str = "qwen2.5:7b",
                 timeout: int = 60, max_retries: int = 2):
        self.base_url = base_url.rstrip("/")
        self.default_model = default_model
        self.timeout = timeout
        self.max_retries = max_retries
        self._client = httpx.Client(timeout=httpx.Timeout(timeout))

    # ==================== 健康检查 ====================

    def is_available(self) -> bool:
        """检查 Ollama 服务是否可达"""
        try:
            resp = self._client.get(f"{self.base_url}/api/tags")
            return resp.status_code == 200
        except Exception:
            return False

    def list_models(self) -> List[str]:
        """获取已安装的模型列表"""
        try:
            resp = self._client.get(f"{self.base_url}/api/tags")
            if resp.status_code == 200:
                data = resp.json()
                return [m["name"] for m in data.get("models", [])]
            return []
        except Exception:
            return []

    def model_exists(self, model_name: str) -> bool:
        """检查指定模型是否已安装"""
        models = self.list_models()
        # 匹配 "qwen2.5:7b" 或 "qwen2.5:latest"
        return any(m == model_name or m.startswith(model_name.split(":")[0])
                   for m in models)

    def pull_model(self, model_name: str,
                   callback: Optional[callable] = None) -> bool:
        """下载模型（带进度回调）"""
        try:
            with self._client.stream(
                "POST", f"{self.base_url}/api/pull",
                json={"name": model_name, "stream": True},
                timeout=httpx.Timeout(600),  # 模型下载可能很久
            ) as resp:
                for line in resp.iter_lines():
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        status = data.get("status", "")
                        if callback and status:
                            callback(status)
                        if data.get("completed"):
                            return True
                    except json.JSONDecodeError:
                        continue
            return False
        except Exception:
            return False

    # ==================== 核心生成 ====================

    def generate(
        self,
        prompt: str,
        system_prompt: str = "",
        model: str = None,
        temperature: float = 0.7,
        max_tokens: int = 500,
        stop: List[str] = None,
    ) -> Tuple[str, bool]:
        """
        调用 /api/generate 生成文本（非流式）

        返回: (生成文本, 是否成功)
        """
        if model is None:
            model = self.default_model

        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        if system_prompt:
            payload["system"] = system_prompt
        if stop:
            payload["options"]["stop"] = stop

        last_error = ""
        for attempt in range(self.max_retries + 1):
            try:
                resp = self._client.post(
                    f"{self.base_url}/api/generate",
                    json=payload,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    response_text = data.get("response", "")
                    return response_text.strip(), True
                else:
                    last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
            except httpx.TimeoutException:
                last_error = f"请求超时 ({self.timeout}s)"
            except httpx.ConnectError:
                last_error = "无法连接 Ollama 服务，请确认已启动"
            except Exception as e:
                last_error = str(e)

            if attempt < self.max_retries:
                time.sleep(2 * (attempt + 1))

        return last_error, False

    def chat(
        self,
        messages: List[Dict[str, str]],
        system_prompt: str = "",
        model: str = None,
        temperature: float = 0.7,
        max_tokens: int = 500,
    ) -> Tuple[str, bool]:
        """
        调用 /api/chat 进行多轮对话

        返回: (生成文本, 是否成功)
        """
        if model is None:
            model = self.default_model

        formatted = []
        if system_prompt:
            formatted.append({"role": "system", "content": system_prompt})
        formatted.extend(messages)

        payload = {
            "model": model,
            "messages": formatted,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }

        last_error = ""
        for attempt in range(self.max_retries + 1):
            try:
                resp = self._client.post(
                    f"{self.base_url}/api/chat",
                    json=payload,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    content = data.get("message", {}).get("content", "")
                    return content.strip(), True
                else:
                    last_error = f"HTTP {resp.status_code}"
            except httpx.TimeoutException:
                last_error = f"请求超时 ({self.timeout}s)"
            except httpx.ConnectError:
                last_error = "无法连接 Ollama 服务"
            except Exception as e:
                last_error = str(e)

            if attempt < self.max_retries:
                time.sleep(2 * (attempt + 1))

        return last_error, False

    def generate_with_context(
        self,
        user_message: str,
        conversation_history: str,
        system_prompt: str,
        model: str = None,
        temperature: float = 0.7,
        max_tokens: int = 500,
    ) -> Tuple[str, bool]:
        """
        带对话历史的生成（组合 prompt 方式，兼容所有模型）
        将历史 + 新消息拼接为一个 prompt 发送
        """
        full_prompt = ""
        if conversation_history:
            full_prompt += "=== 之前的对话记录 ===\n"
            full_prompt += conversation_history + "\n\n"
        full_prompt += "=== 最新消息 ===\n"
        full_prompt += user_message + "\n\n"
        full_prompt += "请根据以上对话历史，生成合适的回复。只输出回复内容，不要包含任何前缀或说明。"

        return self.generate(
            prompt=full_prompt,
            system_prompt=system_prompt,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    def summarize(
        self, text: str, model: str = None, max_tokens: int = 200
    ) -> Tuple[str, bool]:
        """将长文本总结为简短摘要"""
        system = "你是一个文本摘要助手。将以下内容压缩为2-3句话的摘要，保留关键信息。"
        prompt = f"请总结以下内容：\n\n{text}\n\n摘要："
        return self.generate(
            prompt=prompt,
            system_prompt=system,
            model=model,
            temperature=0.3,
            max_tokens=max_tokens,
        )

    def close(self):
        """关闭客户端"""
        self._client.close()
