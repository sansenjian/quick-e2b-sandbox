# E2B 云沙箱插件
# 使用 E2B 云端沙箱安全执行 Python 代码

import re
import hashlib
import asyncio
import traceback
import base64
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

# 尝试导入 Action 相关
try:
    from src.plugin_system import BaseAction, ActionActivationType
except ImportError:
    BaseAction = None
    ActionActivationType = None

# 日志初始化
logger = get_logger("e2b_sandbox")

# 全局变量：存储最近生成的图片路径
_recent_images: Dict[str, List[str]] = {}


# ---------- Tool 组件定义 ----------

class E2BSandboxTool(BaseTool):
    """E2B 云沙箱 Tool 组件
    
    在云沙箱中执行 Python 代码，作为 LLM 的工具。
    支持绘图、联网、动态装库等功能。
    """
    
    # Tool 基本信息
    name = "quick_python_exec"
    description = """
在云沙箱中执行 Python 代码。支持以下功能：

【网页内容获取】⭐ 重点
1. **抓取网页标题**：使用 requests + BeautifulSoup 获取网页 <title> 标签内容
2. **抓取网页正文**：提取网页主要文本内容、段落、链接等
3. **获取网页元数据**：description、keywords、author 等 meta 标签信息
4. **网页截图**：使用 Playwright 对任意网页进行全页面截图
5. **解析网页结构**：提取特定 HTML 元素、表格数据等

【数据处理与分析】
1. **数据分析**：使用 pandas、numpy 进行数据处理和统计分析
2. **数据可视化**：使用 matplotlib、seaborn 绘制图表（必须保存为文件，禁用 plt.show()）
3. **文件处理**：读写 CSV、JSON、Excel 等格式文件

【网络功能】
1. **API 调用**：调用第三方 API 获取数据（天气、翻译、搜索等）
2. **网页爬虫**：批量抓取网页数据
3. **文件下载**：下载网络资源

【环境特性】
- 每次调用都是全新的独立环境（无状态）
- 自动检测并安装常用库（requests、beautifulsoup4、matplotlib、numpy、pandas、playwright 等）
- 支持在代码中通过 pip 动态安装第三方库

【使用建议】
- 使用 print() 输出关键信息和结果
- 避免输出过长的内容（建议 < 500 字符）
- 图表必须保存为文件（如 'plot.png'），严禁使用 plt.show()

【典型应用场景】
✅ 查询网页信息（标题、内容、元数据）
✅ 网页截图和内容抓取
✅ 数据分析和可视化
✅ API 调用和网络请求
✅ 图像处理和生成
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
        # 保存配置
        self.config = plugin_config or {}
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
            # ========== 阶段 1: 意图识别 ==========
            # 导入组件
            from .code_generator import CodeGenerator
            from .template_library import TemplateLibrary
            from .code_executor import CodeExecutor
            from .result_optimizer import ResultOptimizer
            from .intent_recognizer import IntentRecognizer
            from .models import Intent, Context
            
            # 初始化组件
            template_library = TemplateLibrary()
            code_generator = CodeGenerator(template_library, self.config)  # 不再传递 llm_client
            code_executor = CodeExecutor(self.config)
            result_optimizer = ResultOptimizer(None, self.config)  # LLM 暂时为 None
            
            # 检查是否启用 LLM 意图识别
            enable_intent_recognition = self.config.get("llm", {}).get("enable_intent_recognition", True)
            
            if enable_intent_recognition:
                # 使用 IntentRecognizer 识别意图
                logger.info(f"[E2BSandboxTool] 开始意图识别 | user_request: {user_request[:50]}...")
                
                intent_recognizer = IntentRecognizer(self.config)
                intent = await intent_recognizer.recognize(user_request)
                
                logger.info(
                    f"[E2BSandboxTool] 意图识别完成 | "
                    f"task_type={intent.task_type}, "
                    f"sub_type={intent.sub_type}, "
                    f"confidence={intent.confidence:.2f}"
                )
            else:
                # MVP 模式：创建简单的 Intent 对象
                logger.info(f"[E2BSandboxTool] LLM 意图识别已禁用，使用简单模式")
                
                # 将 user_request 放在 parameters 中，让模板库进行关键词匹配
                parameters = {"user_request": user_request}
                
                # 简单的 URL 提取逻辑
                import re
                url_pattern = r'https?://[a-zA-Z0-9\-._~:/?#\[\]@!$&\'()*+,;=%]+'
                url_match = re.search(url_pattern, user_request)
                if url_match:
                    url = url_match.group(0).rstrip('"\'),.;!?')
                    parameters["url"] = url
                    logger.debug(f"[E2BSandboxTool] 提取到 URL: {parameters['url']}")
                
                intent = Intent(
                    task_type="unknown",
                    sub_type=None,
                    parameters=parameters,
                    confidence=1.0,
                    needs_context=False,
                    context_refs=[]
                )
            
            # ========== 阶段 2: 代码生成 ==========
            logger.info(f"[E2BSandboxTool] 开始代码生成")
            
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
            generated_code = await code_generator.generate(intent, simple_context)
            
            logger.info(
                f"[E2BSandboxTool] 代码生成完成 | "
                f"source={generated_code.source}, "
                f"confidence={generated_code.confidence:.2f}"
            )
            
            # 调试：保存生成的代码到文件
            debug_code_path = f"generated_code_{session_id}.py"
            try:
                with open(debug_code_path, 'w', encoding='utf-8') as f:
                    f.write(generated_code.code)
                logger.debug(f"[E2BSandboxTool] 生成的代码已保存到: {debug_code_path}")
            except Exception as e:
                logger.warning(f"[E2BSandboxTool] 保存代码失败: {e}")
            
            # 查找 url = 这一行
            import re
            url_line_match = re.search(r'^url = .+$', generated_code.code, re.MULTILINE)
            if url_line_match:
                logger.info(f"[E2BSandboxTool] URL 赋值行: {url_line_match.group(0)}")
            
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
            
            # ========== 阶段 4: 保存图片并发送给用户 ==========
            if execution_result.images:
                logger.info(f"[E2BSandboxTool] 检测到 {len(execution_result.images)} 张图片")
                
                import os
                import base64
                from datetime import datetime
                
                # 创建图片保存目录
                image_dir = os.path.join(os.path.dirname(__file__), "output_images")
                os.makedirs(image_dir, exist_ok=True)
                
                saved_images = []
                sent_count = 0
                
                for i, img_bytes in enumerate(execution_result.images):
                    try:
                        # 1. 保存图片到本地
                        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                        filename = f"output_{timestamp}_{i}.png"
                        filepath = os.path.join(image_dir, filename)
                        
                        with open(filepath, 'wb') as f:
                            f.write(img_bytes)
                        
                        saved_images.append(filepath)
                        logger.info(f"[E2BSandboxTool] 图片已保存: {filepath} | 大小={len(img_bytes)} 字节")
                        
                        # 2. 发送图片给用户
                        if self.chat_id:
                            # 转换为 base64
                            img_base64 = base64.b64encode(img_bytes).decode('utf-8')
                            
                            # 发送图片
                            success = await send_api.image_to_stream(
                                image_base64=img_base64,
                                stream_id=self.chat_id
                            )
                            
                            if success:
                                sent_count += 1
                                logger.info(f"[E2BSandboxTool] 图片已发送给用户 ({i+1}/{len(execution_result.images)})")
                            else:
                                logger.warning(f"[E2BSandboxTool] 图片发送失败 ({i+1}/{len(execution_result.images)})")
                        
                    except Exception as e:
                        logger.error(f"[E2BSandboxTool] 处理图片失败: {e}")
                
                # 在结果中添加图片信息
                if saved_images:
                    if sent_count > 0:
                        image_info = f"\n\n📸 已生成并发送 {sent_count} 张图片"
                    else:
                        image_info = f"\n\n📸 已生成 {len(saved_images)} 张图片（保存在本地）"
                    
                    optimized_result += image_info
                    logger.info(f"[E2BSandboxTool] 图片处理完成 | 保存={len(saved_images)}, 发送={sent_count}")
            
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
    config_section_descriptions = {
        "plugin": "插件基本信息",
        "e2b": "E2B 云沙箱配置",
        "unified_model": "模型配置",
        "separate_models": "分离模型（高级模式）",
        "llm": "LLM 功能开关和参数"
    }

    # 配置 schema
    config_schema: dict = {
            "plugin": {
                "config_version": ConfigField(type=str, default="2.0.1", description="配置文件版本"),
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
            "unified_model": {
                "model_name": ConfigField(
                    type=str,
                    default="replyer",
                    description="统一模型名称（当不使用分离模型时，意图识别和代码生成都使用此模型）",
                    choices=[
                        "replyer",
                        "utils",
                        "tool_use",
                        "planner",
                        "vlm",
                        "lpmm_entity_extract",
                        "lpmm_rdf_build",
                        "lpmm_qa",
                    ],
                ),
                "context_time_gap": ConfigField(
                    type=int,
                    default=300,
                    description="获取最近多少秒的全局聊天记录作为上下文"
                ),
                "context_max_limit": ConfigField(
                    type=int,
                    default=15,
                    description="最多获取多少条全局聊天记录作为上下文"
                ),
            },
            "separate_models": {
                "use_separate_models": ConfigField(
                    type=bool,
                    default=False,
                    description="是否为意图识别和代码生成使用不同的模型"
                ),
                "intent_model_name": ConfigField(
                    type=str,
                    default="replyer",
                    description="意图识别专用模型（仅在启用分离模型时生效）",
                    choices=[
                        "replyer",
                        "utils",
                        "tool_use",
                        "planner",
                        "vlm",
                        "lpmm_entity_extract",
                        "lpmm_rdf_build",
                        "lpmm_qa",
                    ],
                ),
                "generation_model_name": ConfigField(
                    type=str,
                    default="replyer",
                    description="代码生成专用模型（仅在启用分离模型时生效）",
                    choices=[
                        "replyer",
                        "utils",
                        "tool_use",
                        "planner",
                        "vlm",
                        "lpmm_entity_extract",
                        "lpmm_rdf_build",
                        "lpmm_qa",
                    ],
                ),
            },
            "llm": {
                "enable_intent_recognition": ConfigField(
                    type=bool,
                    default=True,
                    description="是否启用 LLM 意图识别"
                ),
                "enable_code_generation": ConfigField(
                    type=bool,
                    default=True,
                    description="是否启用 LLM 代码生成"
                ),
                "use_custom_temperature": ConfigField(
                    type=bool,
                    default=True,
                    description="是否使用自定义温度参数。关闭后将使用模型默认温度。"
                ),
                "intent_temperature": ConfigField(
                    type=float,
                    default=1.0,
                    description="意图识别温度（0-1）。仅在启用自定义温度时生效。"
                ),
                "generation_temperature": ConfigField(
                    type=float,
                    default=0.5,
                    description="代码生成温度（0-1）。仅在启用自定义温度时生效。"
                ),
                "max_tokens": ConfigField(
                    type=int,
                    default=2000,
                    description="最大 token 数"
                ),
            },
        }

    def get_plugin_components(self) -> List[Tuple[ComponentInfo, Type]]:
        return [
            (E2BSandboxTool.get_tool_info(), E2BSandboxTool),
        ]
