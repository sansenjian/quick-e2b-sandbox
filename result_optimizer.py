"""
结果优化器

负责优化代码执行结果的展示，提供友好的输出格式和错误提示。
"""

from typing import Optional
from src.common.logger import get_logger

# 支持相对导入和绝对导入
try:
    from .models import ExecutionResult, Intent
except ImportError:
    from models import ExecutionResult, Intent

logger = get_logger("ResultOptimizer")


class ResultOptimizer:
    """结果优化器
    
    对代码执行结果进行优化，包括：
    - 结果分类（数值、图表、错误、长输出）
    - 格式美化（使用 Markdown 和 Emoji）
    - 错误分析（提供友好提示和建议）
    - 输出截断（处理过长输出）
    """
    
    def __init__(self, llm_client=None, config: dict = None):
        """初始化结果优化器
        
        Args:
            llm_client: LLM 客户端，用于结果总结（可选）
            config: 配置字典
        """
        self.llm = llm_client
        self.config = config or {}
        self.logger = get_logger("ResultOptimizer")
        
        # 配置项
        self.max_output_length = self.config.get("max_output_length", 1000)
        self.enable_llm_summary = self.config.get("enable_llm_summary", False)
    
    async def optimize(
        self,
        user_request: str,
        code: str,
        raw_result: ExecutionResult,
        intent: Optional[Intent] = None
    ) -> str:
        """优化执行结果
        
        Args:
            user_request: 用户原始请求
            code: 执行的代码
            raw_result: 原始执行结果
            intent: 用户意图（可选）
            
        Returns:
            优化后的结果字符串
        """
        try:
            # 1. 结果分类
            result_type = self._classify_result(raw_result, intent)
            
            # 2. 根据类型优化
            if result_type == "success_with_image":
                optimized = self._optimize_image_result(raw_result)
            elif result_type == "success_with_output":
                optimized = self._optimize_text_result(raw_result)
            elif result_type == "error":
                optimized = self._optimize_error_result(raw_result, code)
            else:
                optimized = self._optimize_generic_result(raw_result)
            
            # 3. 可选：使用 LLM 总结（如果启用）
            if self.enable_llm_summary and self.llm and result_type != "error":
                optimized = await self._add_llm_summary(
                    user_request, code, raw_result, optimized
                )
            
            self.logger.info(
                f"[ResultOptimizer] 结果优化完成 | "
                f"type={result_type}, "
                f"length={len(optimized)}"
            )
            
            return optimized
            
        except Exception as e:
            self.logger.error(f"[ResultOptimizer] 优化失败: {e}")
            # 降级：返回原始结果
            return self._format_raw_result(raw_result)
    
    def _classify_result(
        self,
        result: ExecutionResult,
        intent: Optional[Intent]
    ) -> str:
        """分类执行结果
        
        Args:
            result: 执行结果
            intent: 用户意图
            
        Returns:
            结果类型：success_with_image, success_with_output, error, empty
        """
        if not result.success:
            return "error"
        
        if result.images:
            return "success_with_image"
        
        if result.output and result.output.strip():
            return "success_with_output"
        
        return "empty"
    
    def _optimize_image_result(self, result: ExecutionResult) -> str:
        """优化图片结果
        
        Args:
            result: 执行结果
            
        Returns:
            优化后的结果字符串（不包含图片 base64 数据）
        """
        lines = ["✅ 图表生成成功", "━" * 40]
        
        # 添加输出信息（如果有）
        if result.output and result.output.strip():
            lines.append("📊 执行信息")
            lines.append("━" * 40)
            
            # 截断过长输出
            output = result.output.strip()
            if len(output) > self.max_output_length:
                output = output[:self.max_output_length] + "\n...(输出过长，已截断)"
            
            lines.append(output)
            lines.append("━" * 40)
        
        # 添加图片信息（只显示数量，不包含 base64 数据）
        if len(result.images) == 1:
            lines.append(f"📈 已生成 1 张图片")
        else:
            lines.append(f"📈 已生成 {len(result.images)} 张图片")
        
        # 提示：图片已通过其他方式发送
        lines.append("💡 图片已自动发送")
        
        return "\n".join(lines)
    
    def _optimize_text_result(self, result: ExecutionResult) -> str:
        """优化文本结果
        
        Args:
            result: 执行结果
            
        Returns:
            优化后的结果字符串
        """
        lines = ["✅ 执行完成", "━" * 40]
        
        # 处理输出
        output = result.output.strip()
        
        # 检查是否过长
        if len(output) > self.max_output_length:
            lines.append("📤 输出结果（已截断）")
            lines.append("━" * 40)
            lines.append(output[:self.max_output_length])
            lines.append("━" * 40)
            lines.append(f"💡 输出过长，已截取前 {self.max_output_length} 个字符")
        else:
            lines.append("📤 输出结果")
            lines.append("━" * 40)
            lines.append(output)
            lines.append("━" * 40)
        
        return "\n".join(lines)
    
    def _optimize_error_result(
        self,
        result: ExecutionResult,
        code: str
    ) -> str:
        """优化错误结果
        
        Args:
            result: 执行结果
            code: 执行的代码
            
        Returns:
            优化后的错误信息
        """
        lines = ["❌ 执行失败", "━" * 40]
        
        # 错误信息
        error_msg = result.error or "未知错误"
        lines.append("📋 错误信息")
        lines.append("━" * 40)
        lines.append(error_msg)
        lines.append("━" * 40)
        
        # 分析错误类型并提供建议
        suggestions = self._analyze_error(error_msg)
        if suggestions:
            lines.append("")
            lines.append("💡 可能的原因和建议")
            lines.append("━" * 40)
            for suggestion in suggestions:
                lines.append(f"  • {suggestion}")
            lines.append("━" * 40)
        
        return "\n".join(lines)
    
    def _optimize_generic_result(self, result: ExecutionResult) -> str:
        """优化通用结果（无输出）
        
        Args:
            result: 执行结果
            
        Returns:
            优化后的结果字符串
        """
        return "✅ 代码执行成功（无输出）"
    
    def _analyze_error(self, error_msg: str) -> list[str]:
        """分析错误并提供建议
        
        Args:
            error_msg: 错误信息
            
        Returns:
            建议列表
        """
        suggestions = []
        
        # ModuleNotFoundError
        if "ModuleNotFoundError" in error_msg or "No module named" in error_msg:
            suggestions.extend([
                "模块未找到：检查模块名称是否正确",
                "该模块可能未安装或不在支持列表中",
                "尝试使用其他可用的库"
            ])
        
        # SyntaxError
        elif "SyntaxError" in error_msg:
            suggestions.extend([
                "语法错误：检查代码的缩进和语法",
                "确保括号、引号正确匹配",
                "检查是否有拼写错误"
            ])
        
        # NameError
        elif "NameError" in error_msg:
            suggestions.extend([
                "变量或函数未定义",
                "检查变量名是否正确",
                "确保在使用前已定义变量"
            ])
        
        # TypeError
        elif "TypeError" in error_msg:
            suggestions.extend([
                "类型错误：检查数据类型是否匹配",
                "确保函数参数类型正确",
                "检查是否对不支持的类型进行了操作"
            ])
        
        # ValueError
        elif "ValueError" in error_msg:
            suggestions.extend([
                "值错误：检查输入数据是否有效",
                "确保数据格式符合要求",
                "检查数值范围是否合理"
            ])
        
        # IndexError
        elif "IndexError" in error_msg:
            suggestions.extend([
                "索引错误：检查列表或数组的索引范围",
                "确保索引不超出数据长度",
                "检查数据是否为空"
            ])
        
        # KeyError
        elif "KeyError" in error_msg:
            suggestions.extend([
                "键错误：检查字典的键是否存在",
                "使用 .get() 方法避免 KeyError",
                "检查数据结构是否正确"
            ])
        
        # FileNotFoundError
        elif "FileNotFoundError" in error_msg:
            suggestions.extend([
                "文件未找到：检查文件路径是否正确",
                "确保文件已上传到沙箱",
                "检查文件名是否拼写正确"
            ])
        
        # 通用建议
        else:
            suggestions.extend([
                "检查代码逻辑是否正确",
                "确保数据格式符合要求",
                "尝试简化代码逻辑"
            ])
        
        return suggestions
    
    async def _add_llm_summary(
        self,
        user_request: str,
        code: str,
        result: ExecutionResult,
        optimized: str
    ) -> str:
        """使用 LLM 添加结果总结（可选功能）
        
        Args:
            user_request: 用户请求
            code: 执行的代码
            result: 执行结果
            optimized: 已优化的结果
            
        Returns:
            添加总结后的结果
        """
        try:
            # 构建总结提示词
            prompt = f"""
你是一个代码执行结果分析专家。请对以下代码执行结果进行简短总结。

【用户需求】
{user_request}

【执行代码】
```python
{code}
```

【执行结果】
{result.output[:500] if result.output else "无输出"}

【要求】
1. 用 1-2 句话总结执行结果
2. 指出关键信息或数据
3. 如果有图表，说明图表内容
4. 语言简洁友好

只输出总结内容，不要有其他说明。
"""
            
            # 调用 LLM
            summary = await self.llm.generate(
                prompt=prompt,
                temperature=0.3,
                max_tokens=200
            )
            
            # 添加总结到结果前面
            return f"📝 执行总结\n{summary.strip()}\n\n{optimized}"
            
        except Exception as e:
            self.logger.warning(f"[ResultOptimizer] LLM 总结失败: {e}")
            # 降级：返回原优化结果
            return optimized
    
    def _format_raw_result(self, result: ExecutionResult) -> str:
        """格式化原始结果（降级方案）
        
        Args:
            result: 执行结果
            
        Returns:
            格式化后的结果字符串
        """
        if not result.success:
            return f"❌ 执行失败\n\n错误信息:\n{result.error}"
        
        if result.images:
            return f"✅ 执行成功\n\n生成的图片:\n" + "\n".join(result.images)
        
        if result.output:
            return f"✅ 执行成功\n\n输出:\n{result.output}"
        
        return "✅ 执行成功（无输出）"
