"""
网页截图相关的代码模板
"""

from ..models import Template


# 网页截图模板（使用 Playwright，带详细检查点）
WEB_SCREENSHOT = Template(
    name="web_screenshot",
    description="网页截图",
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
import os

# ========== 检查点 1: 环境检查 ==========
print("=" * 60)
print("[检查点 1] 环境检查")
print("=" * 60)
print(f"Python 版本: {sys.version}")
print(f"当前目录: {os.getcwd()}")
print()

# ========== 检查点 2: 依赖包检查和自动安装 ==========
print("=" * 60)
print("[检查点 2] 依赖包检查和自动安装")
print("=" * 60)

# 首先安装系统依赖（Chromium 需要的库）
print("[步骤 0/3] 安装系统依赖...")
print("[提示] 安装 Chromium 所需的系统库...")

import subprocess

# 安装必需的系统库
system_deps_result = subprocess.run(
    ['apt-get', 'update'],
    capture_output=True,
    text=True
)

if system_deps_result.returncode == 0:
    print("[成功] apt-get update 完成")
    
    # 安装 Chromium 依赖
    deps_install_result = subprocess.run(
        ['apt-get', 'install', '-y', 'libnss3', 'libnspr4', 'libatk1.0-0', 'libatk-bridge2.0-0', 
         'libcups2', 'libdrm2', 'libxkbcommon0', 'libxcomposite1', 'libxdamage1', 'libxfixes3',
         'libxrandr2', 'libgbm1', 'libasound2'],
        capture_output=True,
        text=True
    )
    
    if deps_install_result.returncode == 0:
        print("[成功] 系统依赖安装成功")
    else:
        print("[警告] 系统依赖安装失败，尝试继续...")
        print(f"   错误: {deps_install_result.stderr[:200]}")
else:
    print("[警告] apt-get update 失败，尝试继续...")

print()

# 检查并安装 playwright
try:
    import playwright
    print(f"[成功] playwright 已安装: {playwright.__version__}")
except ImportError:
    print("[警告] playwright 未安装，正在自动安装...")
    print("[提示] 这可能需要 30-60 秒，请稍候...")
    
    # 安装 playwright
    print("\\n[步骤 1/2] 安装 playwright 包...")
    result = subprocess.run(
        [sys.executable, '-m', 'pip', 'install', 'playwright'],
        capture_output=True,
        text=True
    )
    
    if result.returncode == 0:
        print("[成功] playwright 包安装成功")
    else:
        print("[失败] playwright 包安装失败:")
        print(result.stderr)
        sys.exit(1)
    
    # 安装 chromium 浏览器
    print("\\n[步骤 2/2] 安装 Chromium 浏览器...")
    result = subprocess.run(
        ['playwright', 'install', 'chromium'],
        capture_output=True,
        text=True
    )
    
    if result.returncode == 0:
        print("[成功] Chromium 浏览器安装成功")
    else:
        print("[失败] Chromium 浏览器安装失败:")
        print(result.stderr)
        sys.exit(1)
    
    print("\\n[完成] 所有依赖安装完成！")
    
    # 重新导入
    import playwright
    print("[成功] playwright 已安装")

# 检查 playwright.async_api
try:
    from playwright.async_api import async_playwright
    print("[成功] playwright.async_api 可用")
except ImportError as e:
    print(f"[失败] playwright.async_api 导入失败: {e}")
    sys.exit(1)

print()

import base64
import time
import asyncio

async def take_screenshot(url: str) -> dict:
    \"\"\"网页截图
    
    Args:
        url: 网页 URL
        
    Returns:
        包含截图信息的字典
    \"\"\"
    
    # ========== 检查点 3: 开始截图流程 ==========
    print("=" * 60)
    print("🔍 检查点 3: 开始截图流程")
    print("=" * 60)
    print(f"目标 URL: {url}")
    print()
    
    try:
        # ========== 检查点 4: 启动 Playwright ==========
        print("🚀 启动 Playwright...")
        async with async_playwright() as p:
            print("✅ Playwright 启动成功")
            print()
            
            # ========== 检查点 5: 启动浏览器 ==========
            print("🌐 启动 Chromium 浏览器...")
            try:
                browser = await p.chromium.launch(
                    headless=True,
                    args=[
                        '--no-sandbox',
                        '--disable-dev-shm-usage',
                        '--disable-gpu'
                    ]
                )
                print("✅ 浏览器启动成功")
            except Exception as e:
                print(f"❌ 浏览器启动失败: {e}")
                print(f"   错误类型: {type(e).__name__}")
                raise
            print()
            
            try:
                # ========== 检查点 6: 创建页面 ==========
                print("📄 创建新页面...")
                page = await browser.new_page(
                    viewport={'width': 1920, 'height': 1080},
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                )
                print("✅ 页面创建成功")
                print()
                
                # ========== 检查点 7: 访问网页 ==========
                print(f"📡 访问网页: {url}")
                try:
                    await page.goto(url, wait_until='networkidle', timeout=30000)
                    print("✅ 网页访问成功")
                    print(f"   当前 URL: {page.url}")
                    print(f"   页面标题: {await page.title()}")
                except Exception as e:
                    print(f"❌ 网页访问失败: {e}")
                    raise
                print()
                
                # ========== 检查点 8: 等待页面加载 ==========
                print("⏳ 等待页面完全加载...")
                await page.wait_for_timeout(2000)  # 等待 2 秒
                print("✅ 等待完成")
                print()
                
                # ========== 检查点 9: 截图 ==========
                print("📸 开始截图...")
                try:
                    screenshot_bytes = await page.screenshot(
                        full_page=True,
                        type='png'
                    )
                    print("✅ 截图成功")
                    print(f"   截图大小: {len(screenshot_bytes)} 字节")
                except Exception as e:
                    print(f"❌ 截图失败: {e}")
                    raise
                print()
                
                # ========== 检查点 10: 转换为 base64 ==========
                print("🔄 转换为 base64...")
                screenshot_base64 = base64.b64encode(screenshot_bytes).decode('utf-8')
                print("✅ 转换成功")
                print(f"   base64 长度: {len(screenshot_base64)} 字符")
                print()
                
                # ========== 检查点 11: 保存到文件 ==========
                print("💾 保存到文件...")
                try:
                    with open('screenshot.png', 'wb') as f:
                        f.write(screenshot_bytes)
                    print("✅ 文件保存成功: screenshot.png")
                except Exception as e:
                    print(f"⚠️ 文件保存失败: {e}")
                print()
                
                # ========== 检查点 12: 显示图片（让 E2B 捕获） ==========
                print("🖼️  显示图片...")
                try:
                    from PIL import Image
                    import io
                    
                    # 从字节创建图片对象
                    img = Image.open(io.BytesIO(screenshot_bytes))
                    print(f"✅ 图片加载成功: {img.size[0]}x{img.size[1]} 像素")
                    
                    # 显示图片（E2B 会捕获）
                    display(img)
                    print("✅ 图片已显示")
                except Exception as e:
                    print(f"⚠️ 图片显示失败: {e}")
                print()
                
                # ========== 检查点 13: 返回结果 ==========
                print("=" * 60)
                print("✅ 截图流程完成")
                print("=" * 60)
                
                return {
                    'success': True,
                    'screenshot': screenshot_base64,
                    'format': 'png',
                    'size': len(screenshot_bytes),
                    'message': '截图成功'
                }
                
            finally:
                # ========== 检查点 14: 关闭浏览器 ==========
                print()
                print("🔒 关闭浏览器...")
                try:
                    await browser.close()
                    print("✅ 浏览器已关闭")
                except Exception as e:
                    print(f"⚠️ 关闭浏览器时出错: {e}")
        
    except Exception as e:
        error_msg = f'截图失败: {str(e)}'
        print()
        print("=" * 60)
        print(f"❌ 截图流程失败")
        print("=" * 60)
        print(f"错误信息: {error_msg}")
        print(f"错误类型: {type(e).__name__}")
        
        import traceback
        print()
        print("详细错误堆栈:")
        print("-" * 60)
        traceback.print_exc()
        print("-" * 60)
        
        return {
            'success': False,
            'screenshot': None,
            'format': None,
            'size': 0,
            'message': error_msg
        }

# 主程序 - 直接执行（E2B 环境中已在事件循环中）
url = {url}

print()
print("=" * 60)
print("🌐 网页截图工具 (Playwright Async)")
print("=" * 60)
print(f"目标 URL: {url}")
print("=" * 60)
print()

result = await take_screenshot(url)

print()
print("=" * 60)
if result['success']:
    print("✅ 截图完成")
    print(f"📊 格式: {result['format']}")
    print(f"📦 大小: {result['size']} 字节")
    print(f"📦 Base64 长度: {len(result['screenshot'])} 字符")
else:
    print("❌ 截图失败")
    print(f"💬 错误: {result['message']}")
print("=" * 60)
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
