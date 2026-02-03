"""
E2B 插件代码执行引擎

负责在 E2B 沙箱中执行 Python 代码
"""

import asyncio
from typing import Dict, Any, Optional
from src.common.logger import get_logger

# 支持相对导入和绝对导入
try:
    from .models import ExecutionResult
except ImportError:
    from models import ExecutionResult

# 尝试导入 E2B SDK
try:
    from e2b_code_interpreter import AsyncSandbox
except ImportError:
    try:
        from e2b import AsyncSandbox
    except ImportError:
        AsyncSandbox = None


class CodeExecutor:
    """代码执行引擎
    
    在 E2B 云沙箱中安全执行 Python 代码。
    
    Attributes:
        config: 配置字典
        logger: 日志记录器
        sandbox: E2B 沙箱实例（执行时创建）
    """
    
    def __init__(self, config: Dict[str, Any]):
        """初始化代码执行引擎
        
        Args:
            config: 配置字典，包含 E2B API 密钥、超时时间等
        """
        self.config = config
        self.logger = get_logger("CodeExecutor")
        self.sandbox: Optional[Any] = None
        
        # 验证 E2B SDK 是否可用
        if AsyncSandbox is None:
            self.logger.error("[CodeExecutor] E2B SDK 未安装")
            raise ImportError("未安装 e2b_code_interpreter SDK")
    
    async def execute(self, code: str) -> ExecutionResult:
        """执行 Python 代码
        
        在 E2B 沙箱中执行代码，捕获输出和错误。
        
        Args:
            code: 要执行的 Python 代码
            
        Returns:
            ExecutionResult: 执行结果对象
            
        Raises:
            ValueError: 配置错误或代码为空
            RuntimeError: 沙箱创建或执行失败
        """
        # 验证代码
        if not code or not code.strip():
            raise ValueError("代码不能为空")
        
        # 获取配置
        api_key = self.config.get("e2b", {}).get("api_key", "")
        if not api_key:
            raise ValueError("未配置 E2B API Key")
        
        api_base_url = self.config.get("e2b", {}).get("api_base_url", "")
        timeout = self.config.get("e2b", {}).get("timeout", 60)
        max_retries = self.config.get("e2b", {}).get("max_retries", 2)
        
        self.logger.info(
            f"[CodeExecutor] 开始执行代码 | "
            f"timeout={timeout}s, max_retries={max_retries}"
        )
        
        # 重试机制
        last_error = None
        for attempt in range(max_retries):
            try:
                # 创建沙箱
                self.logger.info(
                    f"[CodeExecutor] 创建沙箱 (第 {attempt + 1}/{max_retries} 次)"
                )
                
                self.sandbox = await asyncio.wait_for(
                    AsyncSandbox.create(
                        api_key=api_key,
                        api_url=api_base_url if api_base_url else None,
                        timeout=timeout + 30
                    ),
                    timeout=60
                )
                
                # 创建成功，跳出重试循环
                self.logger.info("[CodeExecutor] 沙箱创建成功")
                break
                
            except asyncio.TimeoutError as e:
                last_error = f"创建沙箱超时（第 {attempt + 1} 次尝试）"
                self.logger.warning(f"[CodeExecutor] {last_error}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2)  # 等待 2 秒后重试
                continue
                
            except Exception as e:
                error_msg = str(e)
                last_error = error_msg
                
                # 判断错误类型
                if "ConnectError" in error_msg or "connection" in error_msg.lower():
                    self.logger.error(
                        f"[CodeExecutor] 网络连接失败 (第 {attempt + 1} 次): {error_msg}"
                    )
                    if attempt < max_retries - 1:
                        self.logger.info("[CodeExecutor] 等待 3 秒后重试...")
                        await asyncio.sleep(3)
                        continue
                    else:
                        # 最后一次尝试失败
                        raise RuntimeError(
                            f"网络连接错误：无法连接到 E2B 服务器。\n"
                            f"可能原因：\n"
                            f"1. 代理服务器不可用\n"
                            f"2. 网络连接问题\n"
                            f"3. API 密钥无效\n\n"
                            f"技术详情：{error_msg}"
                        )
                else:
                    # 其他错误，直接抛出
                    raise
        
        # 如果所有重试都失败
        if self.sandbox is None:
            raise RuntimeError(
                f"创建沙箱失败：已重试 {max_retries} 次。\n"
                f"最后错误：{last_error}"
            )
        
        try:
            # 执行代码
            self.logger.info("[CodeExecutor] 开始执行代码")
            
            execution = await asyncio.wait_for(
                self.sandbox.run_code(code),
                timeout=timeout
            )
            
            self.logger.info("[CodeExecutor] 代码执行完成")
            
            # 处理执行结果
            return self._process_execution_result(execution)
            
        except asyncio.TimeoutError:
            self.logger.warning(f"[CodeExecutor] 代码执行超时")
            return ExecutionResult(
                success=False,
                output="",
                error=f"代码执行超时（限时 {timeout} 秒）",
                images=[]
            )
            
        except Exception as e:
            self.logger.error(f"[CodeExecutor] 执行异常: {e}")
            return ExecutionResult(
                success=False,
                output="",
                error=f"运行时错误: {str(e)}",
                images=[]
            )
            
        finally:
            # 清理沙箱
            await self._cleanup_sandbox()
    
    def _process_execution_result(self, execution: Any) -> ExecutionResult:
        """处理执行结果
        
        从 E2B 执行结果中提取输出、错误和图片。
        
        Args:
            execution: E2B 执行结果对象
            
        Returns:
            ExecutionResult: 处理后的执行结果
        """
        output_parts = []
        error_parts = []
        images = []
        
        # 调试：打印执行结果的详细结构（debug 级别）
        self.logger.debug(f"[CodeExecutor] 执行结果类型: {type(execution)}")
        self.logger.debug(f"[CodeExecutor] 执行结果属性: {dir(execution)}")
        
        # 尝试打印执行结果的所有属性值（debug 级别）
        for attr in dir(execution):
            if not attr.startswith('_'):
                try:
                    value = getattr(execution, attr)
                    if not callable(value):
                        self.logger.debug(f"[CodeExecutor]   {attr} = {value}")
                except Exception as e:
                    self.logger.debug(f"[CodeExecutor]   {attr} = <无法访问: {e}>")
        
        # 打印关键属性摘要（info 级别 - 简洁格式）
        key_attrs = ['error', 'execution_count', 'logs', 'results', 'text']
        for attr in key_attrs:
            if hasattr(execution, attr):
                try:
                    value = getattr(execution, attr)
                    if not callable(value):
                        # 格式化输出
                        if attr == 'logs':
                            # 日志对象特殊处理
                            stdout_count = len(value.stdout) if hasattr(value, 'stdout') else 0
                            stderr_count = len(value.stderr) if hasattr(value, 'stderr') else 0
                            self.logger.info(f"[CodeExecutor]   {attr}: stdout={stdout_count}行, stderr={stderr_count}行")
                        elif attr == 'results':
                            # 结果列表特殊处理
                            self.logger.info(f"[CodeExecutor]   {attr}: {len(value)}个结果")
                        elif attr == 'error':
                            # 错误对象特殊处理
                            if value:
                                self.logger.info(f"[CodeExecutor]   {attr}: {value.name}")
                            else:
                                self.logger.info(f"[CodeExecutor]   {attr}: None")
                        else:
                            # 其他属性直接输出
                            self.logger.info(f"[CodeExecutor]   {attr}: {value}")
                except Exception as e:
                    self.logger.debug(f"[CodeExecutor]   {attr}: <无法访问>")
        
        # 首先检查 execution.error 属性
        if hasattr(execution, 'error') and execution.error:
            error_obj = execution.error
            error_msg = f"{error_obj.name}: {error_obj.value}"
            if hasattr(error_obj, 'traceback') and error_obj.traceback:
                error_msg += f"\n{error_obj.traceback}"
            error_parts.append(error_msg)
            self.logger.warning(f"[CodeExecutor] 检测到执行错误: {error_obj.name}")
        
        # 处理图片
        if hasattr(execution, 'results') and execution.results:
            for res in execution.results:
                img_data = None
                
                # 兼容不同版本的 SDK 属性
                if hasattr(res, 'png') and res.png:
                    img_data = res.png
                elif hasattr(res, 'jpeg') and res.jpeg:
                    img_data = res.jpeg
                elif hasattr(res, 'formats'):
                    formats = res.formats() if callable(res.formats) else res.formats
                    if isinstance(formats, dict):
                        img_data = formats.get('png') or formats.get('jpeg')
                
                if img_data:
                    # 转换 PIL Image 对象为字节数据
                    img_bytes = self._convert_image_to_bytes(img_data)
                    if img_bytes:
                        images.append(img_bytes)
                        self.logger.debug(f"[CodeExecutor] 检测到图片输出 | 大小={len(img_bytes)} 字节")
        
        # 处理日志
        logs_obj = None
        if hasattr(execution, 'logs'):
            logs_obj = execution.logs
        elif hasattr(execution, 'log'):
            logs_obj = execution.log
        
        if logs_obj:
            # 标准输出
            stdout_text = None
            if hasattr(logs_obj, 'stdout'):
                stdout_data = logs_obj.stdout
                if isinstance(stdout_data, list):
                    stdout_text = ''.join(stdout_data).strip()
                elif isinstance(stdout_data, str):
                    stdout_text = stdout_data.strip()
            elif hasattr(logs_obj, 'out'):
                stdout_data = logs_obj.out
                if isinstance(stdout_data, list):
                    stdout_text = ''.join(stdout_data).strip()
                elif isinstance(stdout_data, str):
                    stdout_text = stdout_data.strip()
            
            if stdout_text:
                # 限制输出长度
                max_stdout_len = self.config.get("e2b", {}).get("max_stdout_length", 5000)
                if len(stdout_text) > max_stdout_len:
                    stdout_text = stdout_text[:max_stdout_len] + "\n...(输出已截断)"
                output_parts.append(stdout_text)
                
                # 简洁输出（info 级别）
                line_count = stdout_text.count('\n') + 1
                self.logger.info(f"[CodeExecutor] 标准输出: {line_count}行, {len(stdout_text)}字符")
            else:
                self.logger.debug("[CodeExecutor] 无标准输出")
            
            # 错误输出
            stderr_text = None
            if hasattr(logs_obj, 'stderr'):
                stderr_data = logs_obj.stderr
                if isinstance(stderr_data, list):
                    stderr_text = ''.join(stderr_data).strip()
                elif isinstance(stderr_data, str):
                    stderr_text = stderr_data.strip()
            elif hasattr(logs_obj, 'err'):
                stderr_data = logs_obj.err
                if isinstance(stderr_data, list):
                    stderr_text = ''.join(stderr_data).strip()
                elif isinstance(stderr_data, str):
                    stderr_text = stderr_data.strip()
            
            if stderr_text:
                # 过滤 curl 下载进度信息和 IPython 警告
                if not self._is_curl_progress(stderr_text) and not self._is_ipython_warning(stderr_text):
                    error_parts.append(stderr_text)
                    # 优化日志输出：只显示前100字符
                    preview = stderr_text[:100].replace('\n', ' ')
                    self.logger.warning(f"[CodeExecutor] 错误输出: {preview}...")
                else:
                    self.logger.debug(f"[CodeExecutor] 已过滤的输出（进度/警告）")
        else:
            self.logger.warning("[CodeExecutor] 未找到日志对象")
        
        # 构建结果
        output = "\n".join(output_parts) if output_parts else ""
        error = "\n".join(error_parts) if error_parts else None
        success = error is None
        
        return ExecutionResult(
            success=success,
            output=output,
            error=error,
            images=images
        )
    
    def _convert_image_to_bytes(self, img_data: Any) -> Optional[bytes]:
        """将图片数据转换为字节
        
        Args:
            img_data: 图片数据，可能是 PIL Image 对象、字节或字符串
            
        Returns:
            图片字节数据，转换失败返回 None
        """
        try:
            # 如果已经是字节，直接返回
            if isinstance(img_data, bytes):
                return img_data
            
            # 如果是字符串，尝试解码 base64
            if isinstance(img_data, str):
                import base64
                try:
                    return base64.b64decode(img_data)
                except Exception:
                    self.logger.warning("[CodeExecutor] 无法解码 base64 字符串")
                    return None
            
            # 如果是 PIL Image 对象
            try:
                from PIL import Image
                import io
                
                if isinstance(img_data, Image.Image):
                    # 转换为字节
                    img_buffer = io.BytesIO()
                    img_data.save(img_buffer, format='PNG')
                    img_bytes = img_buffer.getvalue()
                    self.logger.debug(f"[CodeExecutor] PIL Image 转换为字节 | 大小={len(img_bytes)}")
                    return img_bytes
            except ImportError:
                self.logger.warning("[CodeExecutor] PIL 未安装，无法转换 Image 对象")
            except Exception as e:
                self.logger.warning(f"[CodeExecutor] PIL Image 转换失败: {e}")
            
            # 尝试检查是否有 PIL.Image.Image 类型（字符串比较）
            img_type_str = str(type(img_data))
            if 'PIL' in img_type_str and 'Image' in img_type_str:
                try:
                    import io
                    img_buffer = io.BytesIO()
                    img_data.save(img_buffer, format='PNG')
                    img_bytes = img_buffer.getvalue()
                    self.logger.debug(f"[CodeExecutor] PIL Image 转换为字节（备用方法） | 大小={len(img_bytes)}")
                    return img_bytes
                except Exception as e:
                    self.logger.warning(f"[CodeExecutor] PIL Image 转换失败（备用方法）: {e}")
            
            self.logger.warning(f"[CodeExecutor] 未知的图片数据类型: {type(img_data)}")
            return None
            
        except Exception as e:
            self.logger.error(f"[CodeExecutor] 图片转换异常: {e}")
            return None
    
    def _is_curl_progress(self, stderr_text: str) -> bool:
        """检测是否是 curl 下载进度信息
        
        Args:
            stderr_text: 错误输出文本
            
        Returns:
            是否是 curl 进度信息
        """
        # curl 进度信息的特征关键词
        curl_keywords = ["% Total", "% Received", "Dload", "Upload", "Speed", "Xferd"]
        return any(keyword in stderr_text for keyword in curl_keywords)
    
    def _is_ipython_warning(self, stderr_text: str) -> bool:
        """检测是否是 IPython 警告信息
        
        Args:
            stderr_text: 错误输出文本
            
        Returns:
            是否是 IPython 警告信息
        """
        # IPython 警告信息的特征关键词
        ipython_keywords = [
            "IPython",
            "ipykernel",
            "jupyter",
            "DeprecationWarning",
            "FutureWarning"
        ]
        return any(keyword in stderr_text for keyword in ipython_keywords)
    
    async def _cleanup_sandbox(self):
        """清理沙箱资源"""
        if self.sandbox:
            try:
                self.logger.debug("[CodeExecutor] 清理沙箱")
                # 检查事件循环是否仍在运行
                loop = asyncio.get_event_loop()
                if loop.is_closed():
                    self.logger.warning("[CodeExecutor] 事件循环已关闭，跳过沙箱清理")
                    self.sandbox = None
                    return
                
                # 使用 shield 保护清理操作，防止被取消
                await asyncio.shield(
                    asyncio.wait_for(self.sandbox.kill(), timeout=5)
                )
                self.sandbox = None
            except asyncio.CancelledError:
                self.logger.warning("[CodeExecutor] 清理操作被取消")
                self.sandbox = None
            except Exception as e:
                self.logger.warning(f"[CodeExecutor] 清理沙箱失败: {e}")
                self.sandbox = None
