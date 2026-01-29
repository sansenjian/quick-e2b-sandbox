# E2B 云沙箱插件
# 使用 E2B 云端沙箱安全执行 Python 代码

import re
import hashlib
import asyncio
import traceback
from typing import List, Tuple, Type, Optional, Dict, Any, Union

from src.common.logger import get_logger
from src.plugin_system import (
    BasePlugin,
    register_plugin,
    BaseTool,
    ComponentInfo,
    ConfigField,
    PythonDependency,
    ToolParamType,
)
from src.plugin_system.apis import send_api

# 尝试导入 E2B
try:
    from e2b_code_interpreter import AsyncSandbox
except ImportError:
    try:
        from e2b import AsyncSandbox
    except ImportError:
        AsyncSandbox = None

# 日志初始化
logger = get_logger("e2b_sandbox")


# ---------- Tool 组件定义 ----------

class E2BSandboxTool(BaseTool):
    """E2B 云沙箱 Tool 组件
    
    在云沙箱中执行 Python 代码，作为 LLM 的工具。
    支持绘图、联网、动态装库等功能。
    """
    
    # Tool 基本信息
    name = "quick_python_exec"
    description = """
在云沙箱中执行 Python 代码。

【核心能力】
1. **无状态环境**：每次调用都是全新的独立环境
2. **自动装库**：自动检测并安装常用库（matplotlib、numpy、pandas、requests、playwright 等）
3. **支持绘图**：matplotlib、PIL、seaborn 等可视化库
4. **支持联网**：可进行网络请求、API 调用、网页爬虫
5. **浏览器自动化**：支持 Playwright 进行网页操作
6. **动态装库**：支持在代码中通过 pip 安装第三方库。

【绘图规范】⚠️ 重要
- 必须将图片保存为文件（如 'plot.png'、'chart.jpg'）
- 严禁使用 plt.show()（会导致错误）

【输出建议】
- 使用 print() 输出关键信息和结果
- 避免输出过长的内容（建议 < 500 字符）
- 图表优于文本：复杂数据用图表展示

【常见场景】
✅ 数据分析和可视化
✅ 网络爬虫和 API 调用
✅ 机器学习模型训练
✅ 图像处理和生成
✅ 网页自动化和截图
✅ 数据库操作（SQLite）
"""
    
    # LLM 可用性
    available_for_llm = True
    
    # 参数定义：(参数名, 类型, 描述, 是否必需, 可选值)
    parameters = [
        ("code", ToolParamType.STRING, "要执行的 Python 代码", True, None),
    ]
    
    def __init__(self, plugin_config: Optional[dict] = None, chat_stream: Optional[Any] = None):
        """初始化 E2B 沙箱工具"""
        super().__init__(plugin_config, chat_stream)
        # 重复检测：session_id -> code_hash
        self.code_hashes: Dict[str, str] = {}
    
    def _clean_code(self, code: str) -> str:
        """清理 Markdown 代码块标记"""
        match = re.search(r"```(?:python)?\s*(.*?)```", code, re.DOTALL | re.IGNORECASE)
        return match.group(1).strip() if match else code.strip()

    def _is_curl_progress(self, stderr_text: str) -> bool:
        """检测是否是 curl 下载进度信息"""
        # curl 进度信息的特征：包含 "% Total", "Dload", "Speed" 等关键词
        curl_keywords = ["% Total", "% Received", "Dload", "Upload", "Speed", "Xferd"]
        return any(keyword in stderr_text for keyword in curl_keywords)

    def _check_duplicate(self, session_id: str, code: str) -> bool:
        """检测重复的代码执行请求"""
        code_hash = hashlib.md5(code.encode('utf-8')).hexdigest()
        if self.code_hashes.get(session_id) == code_hash:
            return True
        self.code_hashes[session_id] = code_hash
        return False

    async def _auto_install_dependencies(self, sandbox: Any, code: str):
        """自动检测并安装代码中引用的库"""
        common_libs = [
            'matplotlib', 'numpy', 'pandas', 'requests', 
            'bs4', 'wordcloud', 'jieba', 'seaborn', 'scipy', 'sklearn',
            'playwright'  # 浏览器自动化
        ]
        libs_to_install = [lib for lib in common_libs if re.search(rf'\b{lib}\b', code)]
        
        # 特殊情况：如果用了 plt 但没显式写 matplotlib
        if re.search(r'\bplt\b', code) and 'matplotlib' not in libs_to_install:
            libs_to_install.append('matplotlib')

        if libs_to_install:
            install_cmd = f"pip install {' '.join(libs_to_install)}"
            logger.info(f"[E2BSandboxTool] 正在自动安装依赖: {libs_to_install}")
            await sandbox.commands.run(install_cmd, timeout=120)

    def _get_setup_code(self) -> str:
        """获取环境初始化代码（绘图后端、中文字体等）"""
        return """
import os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm

def _configure_font():
    font_path = '/tmp/SimHei.ttf'
    if not os.path.exists(font_path):
        try:
            # 使用 -s 参数静默下载，避免进度信息污染 stderr
            os.system('curl -s -L -o /tmp/SimHei.ttf https://github.com/StellarCN/scp_zh/raw/master/fonts/SimHei.ttf')
        except: pass
            
    if os.path.exists(font_path):
        try:
            fm.fontManager.addfont(font_path)
            plt.rcParams['font.sans-serif'] = ['SimHei']
            plt.rcParams['axes.unicode_minus'] = False
        except: pass

try:
    _configure_font()
except: pass
"""

    async def execute(self, function_args: Dict[str, Any]) -> Dict[str, str]:
        """执行 Python 代码的主方法"""
        logger.debug(f"[E2BSandboxTool] execute 方法被触发 | args: {list(function_args.keys())}")
        code_raw = function_args.get("code", "").strip()
        if not code_raw:
            return {"name": self.name, "content": "❌ 错误：代码参数为空。"}

        code_to_run = self._clean_code(code_raw)
        session_id = self.chat_id or "default_session"

        # 1. 重复检测
        if self._check_duplicate(session_id, code_to_run):
            logger.warning(f"[E2BSandboxTool] 拦截到重复调用 | Session: {session_id}")
            return {"name": self.name, "content": "⚠️ 系统警告：检测到重复的代码执行请求。"}

        # 2. 配置获取（使用 self.get_config 最佳实践）
        api_key = self.get_config("e2b.api_key", "")
        api_base_url = self.get_config("e2b.api_base_url", "")
        timeout = self.get_config("e2b.timeout", 60)

        logger.debug(f"[E2BSandboxTool] 获取配置成功 | api_key: {api_key[:8] if api_key else 'None'}... | api_base_url: {api_base_url or 'Default'}")

        if not api_key:
            logger.error(f"[E2BSandboxTool] 错误：未配置 E2B API Key。当前配置: {self.config}")
            return {"name": self.name, "content": "❌ 错误：未配置 E2B API Key。请在插件配置中设置有效密钥。"}
        
        if AsyncSandbox is None:
            logger.error("[E2BSandboxTool] 错误：AsyncSandbox 未正确导入。")
            return {"name": self.name, "content": "❌ 错误：未安装 e2b_code_interpreter SDK。"}

        logger.info(f"[E2BSandboxTool] 启动沙箱执行 | Session: {session_id} | 超时: {timeout}s")
        
        sandbox = None
        llm_feedback = []

        try:
            # 3. 创建沙箱
            sandbox = await asyncio.wait_for(
                AsyncSandbox.create(
                    api_key=api_key,
                    api_url=api_base_url if api_base_url else None,
                    timeout=timeout + 30
                ),
                timeout=60 # 增加创建沙箱的超时时间，应对网络波动
            )

            # 4. 自动装库
            await self._auto_install_dependencies(sandbox, code_to_run)

            # 5. 执行代码
            full_code = self._get_setup_code() + "\n" + code_to_run
            execution = await asyncio.wait_for(
                sandbox.run_code(full_code),
                timeout=timeout
            )
            
            logger.info(f"[E2BSandboxTool] 代码执行完成 | Session: {session_id}")
            logger.debug(f"[E2BSandboxTool] 执行结果: {execution}")

            # 6. 处理结果
            # 6.1 处理图片
            has_sent_image = False
            if execution.results:
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
                        # 发送图片到流
                        if self.chat_id:
                            success = await send_api.image_to_stream(
                                image_base64=img_data,
                                stream_id=self.chat_id
                            )
                            if success:
                                has_sent_image = True
                                logger.debug(f"[E2BSandboxTool] 图片发送成功 | Session: {session_id}")

                if has_sent_image:
                    llm_feedback.append("[系统通知：检测到图表已生成，已自动发送给用户。]")

            # 6.2 处理日志
            debug_mode = self.get_config("e2b.debug_mode", False)
            
            if hasattr(execution, 'logs'):
                if execution.logs.stdout:
                    stdout_text = ''.join(execution.logs.stdout).strip()
                    logger.debug(f"[E2BSandboxTool] 标准输出 (原始): {stdout_text}")
                    
                    # 调试模式：输出原始内容
                    if debug_mode:
                        logger.info(f"[E2BSandboxTool] [DEBUG] 标准输出 (未过滤): {stdout_text}")
                    
                    # 限制输出长度，避免触发消息分割限制
                    max_stdout_len = self.get_config("e2b.max_stdout_length", 500)
                    if len(stdout_text) > max_stdout_len:
                        stdout_text = stdout_text[:max_stdout_len] + "\n...(输出已截断)"
                        logger.debug(f"[E2BSandboxTool] 标准输出 (截断后): {stdout_text}")
                    llm_feedback.append(f"📤 输出:\n{stdout_text}")
                    
                if execution.logs.stderr:
                    stderr_text = ''.join(execution.logs.stderr).strip()
                    
                    # 调试模式：始终输出 stderr 原始内容
                    if debug_mode:
                        logger.info(f"[E2BSandboxTool] [DEBUG] 错误输出 (未过滤): {stderr_text}")
                    
                    # 过滤 curl 下载进度信息
                    if self._is_curl_progress(stderr_text):
                        logger.debug(f"[E2BSandboxTool] 过滤掉 curl 进度信息")
                        # 调试模式：说明过滤了什么
                        if debug_mode:
                            logger.info(f"[E2BSandboxTool] [DEBUG] 已过滤 curl 进度信息")
                    else:
                        logger.warning(f"[E2BSandboxTool] 错误输出: {stderr_text}")
                        llm_feedback.append(f"⚠️ 错误:\n{stderr_text}")

            # 7. 最终反馈
            result_content = "\n\n".join(llm_feedback)
            if not result_content:
                result_content = "✅ 代码执行成功，但没有产生任何输出。"
            
            logger.debug(f"[E2BSandboxTool] 最终返回给 LLM 的内容: {result_content}")
            
            # 截断超长输出
            max_len = self.get_config("e2b.max_output_length", 2000)
            if len(result_content) > max_len:
                result_content = result_content[:max_len] + "\n...(输出已截断)"
                logger.debug(f"[E2BSandboxTool] 内容被截断，最终长度: {len(result_content)}")

            return {
                "name": self.name,
                "content": result_content
            }

        except asyncio.TimeoutError:
            logger.warning(f"[E2BSandboxTool] 代码执行超时 | Session: {session_id}")
            return {"name": self.name, "content": f"❌ 错误：代码执行超时（限时 {timeout} 秒）。"}
        except Exception as e:
            logger.error(f"[E2BSandboxTool] 执行异常: {traceback.format_exc()}")
            return {"name": self.name, "content": f"❌ 运行时错误: {str(e)}"}
        finally:
            if sandbox:
                try:
                    await asyncio.wait_for(sandbox.kill(), timeout=5)
                except Exception:
                    pass


# ---------- 插件注册（必须放在最后） ----------
# ⚠️ 重要：@register_plugin 必须放在文件末尾！
@register_plugin
class E2BSandboxPlugin(BasePlugin):
    """E2B 云沙箱插件 - 提供安全的代码执行环境"""

    # 插件基本信息
    plugin_name: str = "quick-e2b-sandbox"
    enable_plugin: bool = True
    dependencies: List[str] = []
    python_dependencies: List[PythonDependency] = [
        PythonDependency(
            package_name="e2b-code-interpreter",
            version=">=1.0.0",
            optional=False,
            description="E2B 代码解释器 SDK",
        ),
    ]
    config_file_name: str = "config.toml"

    # 配置段描述
    config_section_descriptions = {"plugin": "插件基本信息", "e2b": "E2B 云沙箱配置"}

    # 配置 schema
    config_schema: dict = {
            "plugin": {
                "config_version": ConfigField(type=str, default="1.0.9", description="配置文件版本"),
                "enabled": ConfigField(type=bool, default=True, description="是否启用插件"),
            },
            "e2b": {
                "api_key": ConfigField(
                    type=str,
                    default="",
                    description="E2B API Key",
                    required=True,
                    input_type="password",
                ),
                "api_base_url": ConfigField(
                    type=str,
                    default="",
                    description="E2B API Base URL（可选）",
                    required=False,
                ),
                "timeout": ConfigField(
                    type=int,
                    default=60,
                    description="代码执行超时时间（秒）",
                    min=10,
                    max=300,
                ),
                "max_output_length": ConfigField(
                    type=int,
                    default=2000,
                    description="最大输出长度（字符）",
                    min=500,
                    max=10000,
                ),
                "max_stdout_length": ConfigField(
                    type=int,
                    default=500,
                    description="标准输出最大长度（字符），避免触发消息分割限制",
                    min=100,
                    max=2000,
                ),
                "debug_mode": ConfigField(
                    type=bool,
                    default=False,
                    description="调试模式：开启后会输出 E2B 返回的所有原始信息（包括被过滤的内容）",
                ),
            },
        }

    def get_plugin_components(self) -> List[Tuple[ComponentInfo, Type]]:
        return [
            (E2BSandboxTool.get_tool_info(), E2BSandboxTool),
        ]
