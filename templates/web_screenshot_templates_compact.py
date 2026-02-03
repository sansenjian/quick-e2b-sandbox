"""
网页截图相关的代码模板 - 简洁版本
"""

# 支持相对导入和绝对导入
try:
    from ..models import Template
except ImportError:
    from models import Template


# 网页截图模板（简洁版 - 使用 Playwright）
WEB_SCREENSHOT_COMPACT = Template(
    name="web_screenshot_compact",
    description="网页截图（简洁版）",
    task_type="web",
    sub_type="screenshot",
    intent_keywords=["网页", "截图", "screenshot", "截屏", "抓图"],
    parameters={
        "url": {
            "type": "str",
            "required": True,
            "description": "要截图的网页 URL"
        }
    },
    success_rate=0.95,
    estimated_time=8.0,
    code_template="""
import sys
import subprocess

# ==================== 自动安装依赖（不要修改此部分） ====================
# 1. 安装 playwright 包
try:
    import playwright
    print(f"✅ playwright 已安装: {playwright.__version__}")
except ImportError:
    print("📦 正在安装 playwright...")
    result = subprocess.run(
        [sys.executable, '-m', 'pip', 'install', 'playwright'],
        capture_output=True,
        text=True
    )
    if result.returncode == 0:
        print("✅ playwright 包安装成功")
    else:
        print(f"❌ playwright 包安装失败: {result.stderr}")
        sys.exit(1)
    import playwright

# 2. 安装 Chromium 浏览器
print("📦 正在安装 Chromium 浏览器...")
result = subprocess.run(
    ['playwright', 'install', 'chromium'],
    capture_output=True,
    text=True
)
if result.returncode == 0:
    print("✅ Chromium 浏览器安装成功")
else:
    print(f"❌ Chromium 浏览器安装失败: {result.stderr}")
    sys.exit(1)

# 3. 安装系统依赖（Chromium 需要的库）
print("📦 正在安装系统依赖...")
subprocess.run(['apt-get', 'update'], capture_output=True)
subprocess.run(
    ['apt-get', 'install', '-y', 
     'libnss3', 'libnspr4', 'libatk1.0-0', 'libatk-bridge2.0-0',
     'libcups2', 'libdrm2', 'libxkbcommon0', 'libxcomposite1',
     'libxdamage1', 'libxfixes3', 'libxrandr2', 'libgbm1', 'libasound2'],
    capture_output=True
)
print("✅ 系统依赖安装完成")
# ====================================================================

from playwright.async_api import async_playwright
from PIL import Image
import io

# 网页截图函数（使用异步 API）
async def take_screenshot(url: str):
    \"\"\"网页截图\"\"\"
    print(f"🌐 开始截图: {url}")
    
    async with async_playwright() as p:
        # 启动浏览器
        browser = await p.chromium.launch(
            headless=True,
            args=['--no-sandbox', '--disable-dev-shm-usage']
        )
        
        try:
            # 创建页面并访问 URL
            page = await browser.new_page(viewport={{'width': 1920, 'height': 1080}})
            await page.goto(url, wait_until='networkidle', timeout=30000)
            
            # 等待页面渲染
            await page.wait_for_timeout(2000)
            
            # 截图（注意：PNG 格式不支持 quality 参数，不要添加）
            screenshot_bytes = await page.screenshot(full_page=True, type='png')
            
            # 保存文件
            with open('screenshot.png', 'wb') as f:
                f.write(screenshot_bytes)
            
            # 显示图片（E2B 会捕获）
            img = Image.open(io.BytesIO(screenshot_bytes))
            display(img)
            
            print(f"✅ 截图成功: {{len(screenshot_bytes)}} 字节")
            return True
            
        finally:
            await browser.close()

# 主函数
async def main():
    url = {url}
    result = await take_screenshot(url)
    return result

# ==================== 重要：不要修改以下代码 ====================
# E2B 环境已经在事件循环中运行，直接使用 await 即可
# 不要添加 try/except 或 asyncio.run()，这会导致错误
# ================================================================
await main()
""",
    examples=[
        {
            "user_request": "帮我截图 https://www.python.org",
            "parameters": {"url": "https://www.python.org"}
        },
        {
            "user_request": "给 https://github.com 截个图",
            "parameters": {"url": "https://github.com"}
        }
    ]
)
