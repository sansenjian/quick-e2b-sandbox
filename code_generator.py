"""
E2B 插件代码生成引擎

负责根据意图生成可执行的 Python 代码
"""

import json
import re
import textwrap
import time
from typing import Dict, Any, Optional
from src.common.logger import get_logger
from src.plugin_system.apis import llm_api

# 支持相对导入和绝对导入
try:
    from .models import Intent, Context, GeneratedCode, Template
    from .template_library import TemplateLibrary
except ImportError:
    from models import Intent, Context, GeneratedCode, Template
    from template_library import TemplateLibrary


class CodeGenerator:
    """代码生成引擎
    
    根据用户意图生成 Python 代码，采用四层降级策略：
    1. 第一层：LLM + 模板（最佳，成功率 > 95%）
    2. 第二层：LLM 自由生成（降级，成功率 > 75%）
    3. 第三层：简单模板填充（兜底，成功率 > 90%）
    4. 第四层：返回错误（最终）
    
    Attributes:
        templates: 代码模板库
        config: 配置字典
        logger: 日志记录器
    """
    
    def __init__(
        self,
        template_library: TemplateLibrary,
        config: Dict[str, Any]
    ):
        """初始化代码生成引擎
        
        Args:
            template_library: 代码模板库实例
            config: 配置字典
        """
        self.templates = template_library
        self.config = config
        self.logger = get_logger("CodeGenerator")
    
    async def generate(
        self,
        intent: Intent,
        context: Context
    ) -> GeneratedCode:
        """生成代码（四层降级策略）
        
        Args:
            intent: 用户意图
            context: 对话上下文
            
        Returns:
            GeneratedCode: 生成的代码对象
            
        Raises:
            ValueError: 代码生成失败
        """
        try:
            # 检查 LLM 是否启用
            llm_enabled = self.config.get("llm", {}).get("enable_code_generation", True)
            
            # 第一层：LLM + 模板（最佳）
            if llm_enabled and self._should_use_template(intent):
                template = self._match_template(intent)
                if template:
                    self.logger.info(
                        f"[CodeGenerator] 使用第一层：LLM + 模板 | template={template.name}"
                    )
                    try:
                        code = await self._generate_from_template_with_llm(
                            template, intent, context
                        )
                        return GeneratedCode(
                            code=code,
                            source="llm_template",
                            template_name=template.name,
                            confidence=0.95,
                            estimated_time=template.estimated_time
                        )
                    except Exception as e:
                        self.logger.warning(
                            f"[CodeGenerator] 第一层失败: {e}，降级到第二层"
                        )
            
            # 第二层：LLM 自由生成（降级）
            if llm_enabled:
                self.logger.info("[CodeGenerator] 使用第二层：LLM 自由生成")
                try:
                    code = await self._generate_by_llm(intent, context)
                    return GeneratedCode(
                        code=code,
                        source="llm",
                        template_name=None,
                        confidence=0.75,
                        estimated_time=5.0
                    )
                except Exception as e:
                    self.logger.warning(
                        f"[CodeGenerator] 第二层失败: {e}，降级到第三层"
                    )
            
            # 第三层：简单模板填充（兜底）
            template = self._match_template(intent)
            if template:
                self.logger.info(
                    f"[CodeGenerator] 使用第三层：简单模板填充 | template={template.name}"
                )
                code = self._fill_template(template, intent.parameters)
                return GeneratedCode(
                    code=code,
                    source="template",
                    template_name=template.name,
                    confidence=0.90,
                    estimated_time=template.estimated_time
                )
            
            # 第四层：返回错误（最终）
            self.logger.error("[CodeGenerator] 所有方法都失败")
            raise ValueError(
                "无法生成代码：\n"
                "- 未找到匹配的模板\n"
                "- LLM 生成失败或未启用\n"
                "建议：检查配置或提供更明确的需求"
            )
            
        except Exception as e:
            self.logger.exception(f"[CodeGenerator] 代码生成失败: {e}")
            raise
    
    def _should_use_template(self, intent: Intent) -> bool:
        """判断是否应该使用模板
        
        Args:
            intent: 用户意图
            
        Returns:
            是否应该使用模板
        """
        # 高置信度且有明确任务类型时使用模板
        return intent.confidence > 0.7 and intent.task_type != "other"
    
    async def _generate_from_template_with_llm(
        self,
        template: Template,
        intent: Intent,
        context: Context
    ) -> str:
        """LLM 根据模板生成代码（第一层）
        
        Args:
            template: 代码模板
            intent: 用户意图
            context: 对话上下文
            
        Returns:
            生成的代码字符串
        """
        # 构建提示词
        prompt = self._build_template_prompt(template, intent, context)
        
        # 调用 LLM
        response = await self._call_llm(prompt, temperature=0.5)
        
        # 提取代码
        code = self._extract_code_from_response(response)
        
        # 验证代码
        if not self._validate_code(code):
            raise ValueError("生成的代码无效")
        
        return code
    
    async def _generate_by_llm(
        self,
        intent: Intent,
        context: Context
    ) -> str:
        """使用 LLM 生成代码（第二层）
        
        当模板匹配失败时，使用 LLM 生成代码作为降级方案。
        
        Args:
            intent: 用户意图
            context: 对话上下文
            
        Returns:
            生成的代码字符串
            
        Raises:
            ValueError: 代码生成失败或无效
        """
        # 构建提示词
        prompt = self._build_free_generation_prompt(intent, context)
        
        # 调用 LLM
        response = await self._call_llm(prompt, temperature=0.7)
        
        # 提取代码
        code = self._extract_code_from_response(response)
        
        # 验证代码
        if not self._validate_code(code):
            raise ValueError("生成的代码无效")
        
        return code
    
    def _build_template_prompt(
        self,
        template: Template,
        intent: Intent,
        context: Context
    ) -> str:
        """构建模板处理提示词
        
        Args:
            template: 代码模板
            intent: 用户意图
            context: 对话上下文
            
        Returns:
            提示词字符串
        """
        # 获取身份和时间提示
        identity_header = self._identity_header()
        
        # 构建参数字符串
        params_str = json.dumps(intent.parameters, ensure_ascii=False, indent=2)
        
        prompt = f"""{identity_header}

你是 Python 代码生成专家。根据模板和用户需求生成代码。

【用户需求】
{intent.parameters.get("user_request", "未指定")}

【识别的意图】
任务类型: {intent.task_type}
子类型: {intent.sub_type or "未指定"}
参数: {params_str}

【参考模板】
```python
{template.code_template}
```

【要求】
1. 基于模板调整，不要完全照搬
2. 根据用户需求填充参数
3. 可以添加额外功能或优化
4. 保持代码可读性
5. 添加中文注释
6. 如果是绘图，配置中文字体
7. 图片保存为 'plot.png'
8. ⚠️ 重要：PNG 截图不要添加 quality 参数（只有 JPEG 支持）
9. ⚠️ 关键：如果使用 Playwright，必须使用 async_playwright（异步 API），不要使用 sync_playwright（同步 API）
10. ⚠️ 关键：E2B 环境已经在事件循环中，直接使用 await，不要使用 asyncio.run()

【输出】
只输出 Python 代码，用 ```python 包裹。
"""
        return prompt
    
    def _build_free_generation_prompt(
        self,
        intent: Intent,
        context: Context
    ) -> str:
        """构建自由生成提示词
        
        Args:
            intent: 用户意图
            context: 对话上下文
            
        Returns:
            提示词字符串
        """
        # 获取身份和时间提示
        identity_header = self._identity_header()
        
        # 构建参数字符串
        params_str = json.dumps(intent.parameters, ensure_ascii=False, indent=2)
        
        prompt = f"""{identity_header}

你是 Python 代码生成专家。根据用户需求生成高质量代码。

【用户需求】
{intent.parameters.get("user_request", "未指定")}

【识别的意图】
任务类型: {intent.task_type}
子类型: {intent.sub_type or "未指定"}
参数: {params_str}

【代码要求】
1. 代码必须完整可执行
2. 包含必要的 import 语句
3. 包含错误处理（try-except）
4. 使用中文注释
5. 如果是绘图，配置中文字体：
   plt.rcParams['font.sans-serif'] = ['SimHei', 'DejaVu Sans']
   plt.rcParams['axes.unicode_minus'] = False
6. 如果生成图片，保存为 'plot.png'
7. 输出友好的提示信息（使用 emoji）
8. ⚠️ 关键：如果使用 Playwright，必须使用 async_playwright（异步 API），不要使用 sync_playwright（同步 API）
9. ⚠️ 关键：E2B 环境已经在事件循环中，直接使用 await，不要使用 asyncio.run()

【输出格式】
只输出 Python 代码，不要有其他说明文字。
代码用 ```python 包裹。
"""
        return prompt
    
    async def _call_llm(self, prompt: str, temperature: Optional[float] = None) -> str:
        """统一的 LLM 调用函数
        
        参考 google_search_plugin 的实现，使用系统 LLM API。
        
        Args:
            prompt: 发送给 LLM 的提示词
            temperature: 温度参数，如果为 None 则根据配置决定是否传递
            
        Returns:
            LLM 生成的文本响应
        """
        try:
            # 选择模型
            models = llm_api.get_available_models()
            if not models:
                raise ValueError("系统中没有可用的 LLM 模型配置。")

            # 检查是否启用分离模型
            use_separate_models = self.config.get("separate_models", {}).get("use_separate_models", False)
            
            # 根据配置选择模型名称
            if use_separate_models:
                # 使用代码生成专用模型
                target_model_name = self.config.get("separate_models", {}).get("generation_model_name", "replyer")
                self.logger.debug(f"[CodeGenerator] 使用分离模型模式，代码生成模型: {target_model_name}")
            else:
                # 使用统一模型
                target_model_name = self.config.get("unified_model", {}).get("model_name", "replyer")
                self.logger.debug(f"[CodeGenerator] 使用统一模型模式，模型: {target_model_name}")
            
            model_config = models.get(target_model_name)

            # 如果找不到指定模型，使用默认模型
            if not model_config:
                self.logger.warning(
                    f"[CodeGenerator] 在系统配置中未找到名为 '{target_model_name}' 的模型，"
                    f"将回退到系统默认模型。"
                )
                default_model_name, model_config = next(iter(models.items()))
                self.logger.info(f"[CodeGenerator] 使用系统默认模型: {default_model_name}")
            else:
                self.logger.info(f"[CodeGenerator] 使用模型: {target_model_name}")

            # 根据配置决定是否使用自定义温度
            use_custom_temp = self.config.get("llm", {}).get("use_custom_temperature", True)
            
            if temperature is None and use_custom_temp:
                # 如果没有指定温度且启用了自定义温度，使用配置值
                temperature = self.config.get("llm", {}).get("generation_temperature", 0.5)
            elif not use_custom_temp:
                # 如果禁用了自定义温度，不传递温度参数
                temperature = None

            # 调用系统 LLM API
            if temperature is not None:
                success, content, _, _ = await llm_api.generate_with_model(
                    prompt,
                    model_config,
                    temperature=temperature
                )
            else:
                success, content, _, _ = await llm_api.generate_with_model(
                    prompt,
                    model_config
                )
            
            if success:
                return content.strip() if content else ""
            else:
                self.logger.error(f"[CodeGenerator] 调用系统 LLM API 失败: {content}")
                raise ValueError(f"LLM 调用失败: {content}")
                
        except Exception as e:
            self.logger.exception(f"[CodeGenerator] 调用 LLM API 时出错: {e}")
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
    
    def _match_template(self, intent: Intent) -> Optional[Template]:
        """匹配代码模板
        
        根据意图的任务类型和子类型匹配合适的模板。
        
        Args:
            intent: 用户意图
            
        Returns:
            匹配的模板对象，如果没有匹配则返回 None
        """
        # 构建模板 key
        if intent.sub_type:
            template_key = f"{intent.task_type}_{intent.sub_type}"
        else:
            template_key = intent.task_type
        
        # 查找模板
        template = self.templates.get(template_key)
        
        if template:
            # 验证参数完整性
            is_valid, error_msg = template.validate_parameters(intent.parameters)
            if is_valid:
                return template
            else:
                self.logger.warning(
                    f"[CodeGenerator] 模板参数验证失败: {error_msg}"
                )
        
        # 尝试模糊匹配
        user_request = intent.parameters.get("user_request", "")
        if user_request:
            fuzzy_template = self.templates.match(user_request)
            if fuzzy_template:
                self.logger.info(
                    f"[CodeGenerator] 模糊匹配到模板: {fuzzy_template.name}"
                )
                return fuzzy_template
        
        return None
    
    def _fill_template(
        self,
        template: Template,
        parameters: Dict[str, Any]
    ) -> str:
        """填充模板参数
        
        将用户参数填充到代码模板中，生成可执行的代码。
        
        Args:
            template: 代码模板
            parameters: 参数字典
            
        Returns:
            填充后的代码字符串
        """
        code = template.code_template
        
        # 填充用户提供的参数
        for key, value in parameters.items():
            placeholder = f"{{{key}}}"
            if placeholder in code:
                # 根据类型格式化值（自动添加引号等）
                formatted_value = self._format_parameter_value(value)
                code = code.replace(placeholder, formatted_value)
        
        # 填充默认值
        for param_name, param_def in template.parameters.items():
            placeholder = f"{{{param_name}}}"
            if placeholder in code:
                default_value = param_def.get("default")
                if default_value is not None:
                    formatted_value = self._format_parameter_value(default_value)
                    code = code.replace(placeholder, formatted_value)
        
        return code
    
    def _format_parameter_value(self, value: Any) -> str:
        """格式化参数值为 Python 代码字符串
        
        Args:
            value: 参数值
            
        Returns:
            格式化后的字符串
        """
        if isinstance(value, str):
            # 使用 repr() 来安全地转义字符串，避免引号冲突
            return repr(value)
        elif isinstance(value, (list, dict)):
            return repr(value)
        elif value is None:
            return "None"
        else:
            return str(value)
    
    def _extract_code_from_response(self, response: str) -> str:
        """从 LLM 响应中提取代码
        
        Args:
            response: LLM 的响应文本
            
        Returns:
            提取的代码字符串
        """
        # 查找 ```python 代码块
        if "```python" in response:
            start = response.find("```python") + len("```python")
            end = response.find("```", start)
            if end != -1:
                return response[start:end].strip()
        
        # 查找 ``` 代码块
        if "```" in response:
            start = response.find("```") + len("```")
            end = response.find("```", start)
            if end != -1:
                return response[start:end].strip()
        
        # 没有代码块标记，返回整个响应
        return response.strip()
    
    def _validate_code(self, code: str) -> bool:
        """验证代码的基本有效性
        
        Args:
            code: 代码字符串
            
        Returns:
            代码是否有效
        """
        # 基本检查
        if not code or len(code) < 10:
            return False
        
        # 检查是否包含 Python 关键字
        python_keywords = ["import", "def", "class", "if", "for", "while", "try", "print"]
        has_keyword = any(keyword in code for keyword in python_keywords)
        
        if not has_keyword:
            return False
        
        # 尝试编译代码（语法检查）
        # 注意：使用 PyCF_ALLOW_TOP_LEVEL_AWAIT 标志支持顶层 await（E2B 环境需要）
        try:
            import ast
            compile(code, "<string>", "exec", flags=ast.PyCF_ALLOW_TOP_LEVEL_AWAIT)
            return True
        except SyntaxError as e:
            self.logger.warning(f"[CodeGenerator] 代码语法错误: {e}")
            return False
