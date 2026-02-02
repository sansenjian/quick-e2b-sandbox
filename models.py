"""
E2B 插件数据模型

定义插件使用的核心数据结构
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List


@dataclass
class Intent:
    """用户意图数据类
    
    封装从用户请求中识别出的意图信息。
    
    Attributes:
        task_type: 任务类型（plot/data_analysis/file/web/math/other）
        sub_type: 子类型（如 line/bar/sine_wave/statistics 等）
        parameters: 任务参数字典
        confidence: 意图识别的置信度（0.0-1.0）
        needs_context: 是否需要上下文信息
        context_refs: 上下文引用列表（如 ["它", "再"]）
    """
    
    task_type: str
    sub_type: Optional[str] = None
    parameters: Dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    needs_context: bool = False
    context_refs: List[str] = field(default_factory=list)


@dataclass
class Context:
    """对话上下文数据类
    
    封装从 chat_history 中提取的上下文信息。
    
    Attributes:
        messages: 最近的消息列表
        last_execution: 最近的代码执行记录
        last_result: 最近的执行结果
        last_code: 最近执行的代码
        last_images: 最近生成的图片列表
        variables: 可用的变量字典
    """
    
    messages: List[Dict[str, Any]] = field(default_factory=list)
    last_execution: Optional[Dict] = None
    last_result: Optional[str] = None
    last_code: Optional[str] = None
    last_images: List[str] = field(default_factory=list)
    variables: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Template:
    """代码模板数据类
    
    用于存储预定义的高质量代码模板，提高代码生成的成功率和效率。
    
    Attributes:
        name: 模板名称，唯一标识符
        description: 模板功能描述
        task_type: 任务类型（如 plot, data_analysis, file, web, math）
        sub_type: 子类型（如 line, bar, sine_wave, statistics）
        intent_keywords: 意图关键词列表，用于模糊匹配
        parameters: 参数定义字典
        code_template: 代码模板字符串，可包含占位符
        success_rate: 历史成功率（0.0-1.0）
        estimated_time: 预估执行时间（秒）
        examples: 使用示例列表
    """
    
    name: str
    description: str
    task_type: str
    sub_type: str
    intent_keywords: List[str]
    parameters: Dict[str, Dict]
    code_template: str
    success_rate: float
    estimated_time: float
    examples: List[Dict[str, Any]] = field(default_factory=list)
    
    def validate_parameters(
        self,
        params: Dict[str, Any]
    ) -> tuple[bool, Optional[str]]:
        """验证参数完整性
        
        Args:
            params: 要验证的参数字典
            
        Returns:
            (是否有效, 错误信息)
        """
        for param_name, param_def in self.parameters.items():
            if param_def.get("required", False):
                if param_name not in params:
                    return False, f"缺少必需参数: {param_name}"
        return True, None


@dataclass
class GeneratedCode:
    """生成的代码数据类
    
    封装代码生成的结果，包含代码内容、来源和置信度等信息。
    
    Attributes:
        code: 生成的 Python 代码字符串
        source: 代码来源，"template" 表示使用模板，"llm" 表示 LLM 生成
        template_name: 使用的模板名称，LLM 生成时为 None
        confidence: 代码质量置信度（0.0-1.0），模板通常为 0.95，LLM 为 0.75
        estimated_time: 预估执行时间（秒）
    """
    
    code: str
    source: str  # "template" 或 "llm"
    template_name: Optional[str]
    confidence: float
    estimated_time: float


@dataclass
class ExecutionResult:
    """代码执行结果数据类
    
    封装代码执行的结果，包含成功状态、输出、错误信息和生成的图片。
    
    Attributes:
        success: 执行是否成功
        output: 标准输出内容
        error: 错误信息，执行成功时为 None
        images: 生成的图片路径列表
    """
    
    success: bool
    output: str
    error: Optional[str]
    images: List[str]
