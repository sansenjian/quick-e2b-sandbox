"""
E2B 插件意图识别器

使用 LLM 分析用户请求，识别任务类型和参数
"""

import json
import re
import time
from typing import Optional, Dict, Any
from src.common.logger import get_logger
from src.plugin_system.apis import llm_api

# 支持相对导入和绝对导入
try:
    from .models import Intent
except ImportError:
    from models import Intent


class IntentRecognizer:
    """意图识别器 - 使用 LLM 分析用户意图
    
    通过 LLM 分析用户请求，识别出任务类型、子类型和参数，
    返回结构化的 Intent 对象。
    
    Attributes:
        config: 配置字典
        logger: 日志记录器
    """
    
    def __init__(self, config: Dict[str, Any]):
        """初始化意图识别器
        
        Args:
            config: 配置字典
        """
        self.config = config
        self.logger = get_logger("IntentRecognizer")
    
    async def recognize(
        self,
        user_request: str,
        context: Optional[Dict] = None
    ) -> Intent:
        """识别用户意图
        
        Args:
            user_request: 用户原始请求
            context: 对话上下文（可选）
            
        Returns:
            Intent: 结构化的意图对象
        """
        try:
            # 1. 构建提示词
            prompt = self._build_prompt(user_request, context)
            
            # 2. 调用 LLM
            response = await self._call_llm(
                prompt,
                temperature=self.config.get("llm", {}).get("intent_temperature", 0.3)
            )
            
            # 3. 解析 JSON
            intent_data = self._parse_response(response)
            
            # 4. 创建 Intent 对象
            intent = Intent(
                task_type=intent_data.get("task_type", "other"),
                sub_type=intent_data.get("sub_type"),
                parameters=intent_data.get("parameters", {}),
                confidence=intent_data.get("confidence", 0.5),
                needs_context=intent_data.get("needs_context", False),
                context_refs=intent_data.get("context_refs", [])
            )
            
            # 确保 user_request 在 parameters 中
            if "user_request" not in intent.parameters:
                intent.parameters["user_request"] = user_request
            
            self.logger.info(
                f"[IntentRecognizer] 识别完成 | "
                f"task_type={intent.task_type}, "
                f"sub_type={intent.sub_type}, "
                f"confidence={intent.confidence:.2f}"
            )
            
            return intent
            
        except Exception as e:
            self.logger.exception(f"[IntentRecognizer] 意图识别失败: {e}")
            # 返回默认 Intent
            return Intent(
                task_type="other",
                sub_type=None,
                parameters={"user_request": user_request},
                confidence=0.3,
                needs_context=False,
                context_refs=[]
            )
    
    def _build_prompt(self, user_request: str, context: Optional[Dict]) -> str:
        """构建意图识别提示词
        
        Args:
            user_request: 用户请求
            context: 对话上下文
            
        Returns:
            提示词字符串
        """
        # 获取身份和时间提示
        identity_header = self._identity_header()
        
        # 构建上下文部分
        context_section = ""
        if context and context.get("messages"):
            context_section = "\n【对话上下文】\n"
            for msg in context["messages"][-3:]:  # 只取最近 3 条
                role = msg.get("role", "unknown")
                content = msg.get("content", "")
                context_section += f"{role}: {content}\n"
            context_section += "\n"
        
        prompt = f"""{identity_header}

你是一个意图识别专家。分析用户的请求，识别出任务类型和参数。
{context_section}
【用户请求】
{user_request}

【任务类型】
- plot: 绘图（折线图、柱状图、饼图、正弦曲线等）
- data_analysis: 数据分析（统计、排序、筛选）
- web: 网页操作（截图、爬虫、API 调用）
- file: 文件处理（读写、转换）
- math: 数学计算（方程、序列）
- other: 其他任务

【输出格式】
返回 JSON 格式：
{{
    "task_type": "plot",
    "sub_type": "sine_wave",
    "parameters": {{
        "x_range": [-10, 10],
        "color": "blue",
        "title": "正弦曲线"
    }},
    "confidence": 0.9,
    "needs_context": false,
    "context_refs": []
}}

【要求】
1. task_type 必须是上述类型之一
2. sub_type 可以更具体（如 sine_wave, bar_chart, statistics）
3. parameters 提取关键参数（数值、颜色、标题、URL 等）
4. confidence 评估识别的置信度（0-1）
5. needs_context 判断是否需要上下文（如"它"、"再"等引用）
6. context_refs 列出上下文引用词
7. 只返回 JSON，不要其他说明文字
"""
        return prompt
    
    def _parse_response(self, response: str) -> Dict[str, Any]:
        """解析 LLM 响应
        
        Args:
            response: LLM 响应文本
            
        Returns:
            解析后的字典
        """
        # 默认值
        default_intent = {
            "task_type": "other",
            "sub_type": None,
            "parameters": {},
            "confidence": 0.3,
            "needs_context": False,
            "context_refs": []
        }
        
        # 提取 JSON
        json_match = re.search(r'\{.*\}', response, re.DOTALL)
        if not json_match:
            self.logger.warning("[IntentRecognizer] 无法提取 JSON，使用默认值")
            return default_intent
        
        try:
            intent_data = json.loads(json_match.group())
            # 合并默认值，确保所有字段都存在
            result = default_intent.copy()
            result.update(intent_data)
            return result
        except json.JSONDecodeError as e:
            self.logger.error(f"[IntentRecognizer] JSON 解析失败: {e}")
            return default_intent
    
    async def _call_llm(self, prompt: str, temperature: float = 0.3) -> str:
        """统一的 LLM 调用函数
        
        参考 google_search_plugin 的实现，使用系统 LLM API。
        
        Args:
            prompt: 发送给 LLM 的提示词
            temperature: 温度参数
            
        Returns:
            LLM 生成的文本响应
        """
        try:
            # 选择模型
            models = llm_api.get_available_models()
            if not models:
                raise ValueError("系统中没有可用的 LLM 模型配置。")

            # 从配置中获取目标模型名称
            target_model_name = self.config.get("model_config", {}).get("model_name", "replyer")
            model_config = models.get(target_model_name)

            # 如果找不到指定模型，使用默认模型
            if not model_config:
                self.logger.warning(
                    f"[IntentRecognizer] 在系统配置中未找到名为 '{target_model_name}' 的模型，"
                    f"将回退到系统默认模型。"
                )
                default_model_name, model_config = next(iter(models.items()))
                self.logger.info(f"[IntentRecognizer] 使用系统默认模型: {default_model_name}")
            else:
                self.logger.info(f"[IntentRecognizer] 使用模型: {target_model_name}")

            # 调用系统 LLM API
            success, content, _, _ = await llm_api.generate_with_model(
                prompt,
                model_config,
                temperature=temperature
            )
            
            if success:
                return content.strip() if content else ""
            else:
                self.logger.error(f"[IntentRecognizer] 调用系统 LLM API 失败: {content}")
                raise ValueError(f"LLM 调用失败: {content}")
                
        except Exception as e:
            self.logger.exception(f"[IntentRecognizer] 调用 LLM API 时出错: {e}")
            raise
    
    def _identity_header(self) -> str:
        """提供给 LLM 的身份与时间提示，降低时间误判
        
        参考 google_search_plugin 的实现。
        
        Returns:
            身份和时间提示字符串
        """
        try:
            from src.config.global_config import global_config
            bot = getattr(global_config, "bot", None)
            bot_name = getattr(bot, "nickname", None) or "机器人"
        except:
            bot_name = "机器人"
        
        time_now = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        return f"你的名字是{bot_name}。现在是{time_now}。"
