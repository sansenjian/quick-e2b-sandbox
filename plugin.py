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
        """执行 Python 代码的主方法（MVP 集成版）
        
        集成了 CodeGenerator、CodeExecutor 和 ResultOptimizer
        """
        logger.debug(f"[E2BSandboxTool] execute 方法被触发 | args: {list(function_args.keys())}")
        
        # 获取用户请求
        user_request = function_args.get("code", "").strip()
        if not user_request:
            return {"name": self.name, "content": "❌ 错误：代码参数为空。"}
        
        session_id = self.chat_id or "default_session"
        
        try:
            # ========== 阶段 1: 代码生成 ==========
            # 导入组件
            from .code_generator import CodeGenerator
            from .template_library import TemplateLibrary
            from .code_executor import CodeExecutor
            from .result_optimizer import ResultOptimizer
            from .models import Intent, Context
            
            # 初始化组件
            template_library = TemplateLibrary()
            code_generator = CodeGenerator(template_library, None, self.config)  # LLM 暂时为 None
            code_executor = CodeExecutor(self.config)
            result_optimizer = ResultOptimizer(None, self.config)  # LLM 暂时为 None
            
            logger.info(f"[E2BSandboxTool] 开始代码生成 | user_request: {user_request[:50]}...")
            
            # MVP 阶段：创建简单的 Intent 对象
            # 将 user_request 放在 parameters 中，让模板库进行关键词匹配
            simple_intent = Intent(
                task_type="unknown",
                sub_type=None,
                parameters={"user_request": user_request},
                confidence=1.0,
                needs_context=False,
                context_refs=[]
            )
            
            # MVP 阶段：创建空的 Context 对象
            simple_context = Context(
                messages=[],
                last_execution=None,
                last_result=None,
                last_code=None,
                last_images=[],
                variables={}
            )
            
            # 生成代码
            generated_code = await code_generator.generate(simple_intent, simple_context)
            
            logger.info(
                f"[E2BSandboxTool] 代码生成完成 | "
                f"source={generated_code.source}, "
                f"confidence={generated_code.confidence:.2f}"
            )
            
            # ========== 阶段 2: 代码执行 ==========
            logger.info(f"[E2BSandboxTool] 开始执行代码 | Session: {session_id}")
            
            # 执行代码（CodeExecutor 会从 self.config 读取配置）
            execution_result = await code_executor.execute(generated_code.code)
            
            logger.info(
                f"[E2BSandboxTool] 代码执行完成 | "
                f"success={execution_result.success}"
            )
            
            # ========== 阶段 3: 结果优化 ==========
            logger.info(f"[E2BSandboxTool] 开始结果优化")
            
            # 优化结果
            optimized_result = await result_optimizer.optimize(
                user_request=user_request,
                code=generated_code.code,
                raw_result=execution_result,
                intent=None  # MVP 阶段暂不使用意图
            )
            
            logger.info(f"[E2BSandboxTool] 结果优化完成")
            logger.debug(f"[E2BSandboxTool] 优化后的结果: {optimized_result[:200]}...")
            
            # 返回结果
            return {
                "name": self.name,
                "content": optimized_result
            }
            
        except ImportError as e:
            logger.error(f"[E2BSandboxTool] 导入组件失败: {e}")
            return {
                "name": self.name,
                "content": f"❌ 系统错误：无法加载必需的组件。\n\n技术详情：{str(e)}"
            }
        except Exception as e:
            logger.error(f"[E2BSandboxTool] 执行异常: {traceback.format_exc()}")
            return {
                "name": self.name,
                "content": f"❌ 运行时错误: {str(e)}"
            }


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
                "config_version": ConfigField(type=str, default="1.0.10", description="配置文件版本"),
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
                    description="E2B API Base URL（可选，国内用户建议配置代理）",
                    required=False,
                ),
                "timeout": ConfigField(
                    type=int,
                    default=60,
                    description="代码执行超时时间（秒）",
                    min=10,
                    max=300,
                ),
                "max_retries": ConfigField(
                    type=int,
                    default=2,
                    description="网络连接失败时的最大重试次数",
                    min=0,
                    max=5,
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
