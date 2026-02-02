"""
E2B 插件代码生成引擎

负责根据意图生成可执行的 Python 代码
"""

import json
import textwrap
import time
from typing import Dict, Any, Optional
from src.common.logger import get_logger
from .models import Intent, Context, GeneratedCode, Template
from .template_library import TemplateLibrary


class CodeGenerator:
    """代码生成引擎
    
    根据用户意图生成 Python 代码，采用模板优先策略：
    1. 优先匹配代码模板（成功率 > 95%，响应快）
    2. 模板匹配失败时使用 LLM 生成（降级方案）
    
    Attributes:
        templates: 代码模板库
        llm: LLM 客户端
        config: 配置字典
        logger: 日志记录器
    """
    
    def __init__(
        self,
        template_library: TemplateLibrary,
        llm_client,
        config: Dict[str, Any]
    ):
        """初始化代码生成引擎
        
        Args:
            template_library: 代码模板库实例
            llm_client: LLM 客户端实例
            config: 配置字典
        """
        self.templates = template_library
        self.llm = llm_client
        self.config = config
        self.logger = get_logger("CodeGenerator")
    
    async def generate(
        self,
        intent: Intent,
        context: Context
    ) -> GeneratedCode:
        """生成代码（模板优先，LLM 降级）
        
        Args:
            intent: 用户意图
            context: 对话上下文
            
        Returns:
            GeneratedCode: 生成的代码对象
            
        Raises:
            ValueError: 代码生成失败
        """
        try:
            # 1. 尝试匹配模板
            template = self._match_template(intent)
            
            if template:
                # 使用模板生成代码
                self.logger.info(
                    f"[CodeGenerator] 匹配到模板: {template.name}"
                )
                
                code = self._fill_template(template, intent.parameters)
                
                return GeneratedCode(
                    code=code,
                    source="template",
                    template_name=template.name,
                    confidence=0.95,
                    estimated_time=template.estimated_time
                )
            
            # 2. 模板匹配失败，使用 LLM 生成
            self.logger.info(
                "[CodeGenerator] 未匹配到模板，使用 LLM 生成"
            )
            
            code = await self._generate_by_llm(intent, context)
            
            return GeneratedCode(
                code=code,
                source="llm",
                template_name=None,
                confidence=0.75,
                estimated_time=5.0
            )
            
        except Exception as e:
            self.logger.error(f"[CodeGenerator] 代码生成失败: {e}")
            raise
    
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
            return f"'{value}'"
        elif isinstance(value, (list, dict)):
            return repr(value)
        elif value is None:
            return "None"
        else:
            return str(value)
    
    async def _generate_by_llm(
        self,
        intent: Intent,
        context: Context
    ) -> str:
        """使用 LLM 生成代码
        
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
        prompt = self._build_code_generation_prompt(intent, context)
        
        # 调用 LLM
        response = await self.llm.generate(
            prompt=prompt,
            temperature=self.config.get("model", {}).get("temperature", 0.3),
            max_tokens=1000
        )
        
        # 提取代码
        code = self._extract_code_from_response(response)
        
        # 验证代码
        if not self._validate_code(code):
            raise ValueError("生成的代码无效")
        
        return code
    
    def _build_code_generation_prompt(
        self,
        intent: Intent,
        context: Context
    ) -> str:
        """构建代码生成提示词
        
        Args:
            intent: 用户意图
            context: 对话上下文
            
        Returns:
            提示词字符串
        """
        # 获取机器人名称和当前时间
        from src.config.global_config import global_config
        bot_name = getattr(global_config.bot, "nickname", None) or "助手"
        time_now = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        
        # 构建上下文字符串
        context_str = ""
        if context.last_result:
            context_str = f"\n【上一次执行结果】\n{context.last_result}\n"
        
        # 构建参数字符串
        params_str = json.dumps(intent.parameters, ensure_ascii=False, indent=2)
        
        return textwrap.dedent(f"""
            你的名字是{bot_name}。现在是{time_now}。
            
            你是一个 Python 代码生成专家。根据用户需求生成高质量的 Python 代码。
            
            【用户需求】
            任务类型: {intent.task_type}
            子类型: {intent.sub_type or "未指定"}
            参数: {params_str}
            {context_str}
            
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
            
            【输出格式】
            只输出 Python 代码，不要有其他说明文字。
            代码用 ```python 包裹。
        """).strip()
    
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
        try:
            compile(code, "<string>", "exec")
            return True
        except SyntaxError as e:
            self.logger.warning(f"[CodeGenerator] 代码语法错误: {e}")
            return False
