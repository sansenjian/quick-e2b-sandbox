"""
E2B 插件模板库

管理和提供预定义的代码模板
"""

from typing import Dict, Optional

# 支持相对导入和绝对导入
try:
    from .models import Template
except ImportError:
    from models import Template


class TemplateLibrary:
    """代码模板库
    
    管理所有预定义的代码模板，提供模板查询和匹配功能。
    
    Attributes:
        templates: 模板字典，key 为模板名称，value 为 Template 对象
    """
    
    def __init__(self):
        """初始化模板库"""
        self.templates: Dict[str, Template] = {}
        self._load_templates()
    
    def _load_templates(self):
        """加载所有模板
        
        从各个模板模块中导入模板并注册到库中。
        """
        # 导入网络请求模板
        from .templates.web_templates import WEB_SCRAPE_TITLE
        self.templates["web_scrape_title"] = WEB_SCRAPE_TITLE
        
        # 导入截图模板
        from .templates.screenshot_templates import WEB_SCREENSHOT
        self.templates["web_screenshot"] = WEB_SCREENSHOT
        
        # 导入绘图模板
        from .templates.plot_templates import PLOT_SINE_WAVE
        self.templates["plot_sine_wave"] = PLOT_SINE_WAVE
    
    def get(self, key: str) -> Optional[Template]:
        """获取指定名称的模板
        
        Args:
            key: 模板名称
            
        Returns:
            Template 对象，如果不存在则返回 None
        """
        return self.templates.get(key)
    
    def match(self, user_request: str) -> Optional[Template]:
        """根据用户请求匹配合适的模板
        
        使用简单的关键词匹配算法，查找最适合用户请求的模板。
        
        Args:
            user_request: 用户的请求文本
            
        Returns:
            匹配的 Template 对象，如果没有匹配则返回 None
        """
        import re  # 在函数最开头导入
        
        request_lower = user_request.lower()
        
        # 优先匹配更具体的模式（避免误匹配）
        
        # 匹配网页截图模板（需要有 URL）
        if any(kw in request_lower for kw in ["截图", "screenshot", "截屏", "抓图"]):
            # 检查是否包含 URL
            if re.search(r'https?://', request_lower):
                return self.get("web_screenshot")
        
        # 匹配网页抓取模板（需要有 URL 且提到网页/标题）
        if any(kw in request_lower for kw in ["网页", "抓取"]) or \
           (("标题" in request_lower or "title" in request_lower) and re.search(r'https?://', request_lower)):
            return self.get("web_scrape_title")
        
        # 匹配绘图模板
        if any(kw in request_lower for kw in ["正弦", "sin", "曲线", "sine"]):
            return self.get("plot_sine_wave")
        
        # 如果没有匹配到任何模板，返回 None（将使用 LLM 生成）
        return None
