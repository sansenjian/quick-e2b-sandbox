"""
网络请求相关的代码模板
"""

from ..models import Template


# 网页标题抓取模板
WEB_SCRAPE_TITLE = Template(
    name="web_scrape_title",
    description="抓取网页标题",
    task_type="web",
    sub_type="scrape_title",
    intent_keywords=["网页", "标题", "title", "抓取", "爬取"],
    parameters={
        "url": {
            "type": "str",
            "required": True,
            "description": "要抓取的网页 URL"
        }
    },
    success_rate=0.95,
    estimated_time=3.0,
    code_template="""
import requests
from bs4 import BeautifulSoup

def scrape_title(url: str) -> str:
    \"\"\"抓取网页标题
    
    Args:
        url: 网页 URL
        
    Returns:
        网页标题
    \"\"\"
    try:
        # 设置请求头，模拟浏览器访问
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        # 发送请求，设置超时时间
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()  # 检查 HTTP 状态码
        
        # 解析 HTML
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # 提取标题
        title = soup.find('title')
        if title:
            return title.get_text().strip()
        else:
            return "未找到标题"
            
    except requests.exceptions.Timeout:
        return "错误：请求超时，请检查网络连接或稍后重试"
    except requests.exceptions.ConnectionError:
        return "错误：无法连接到服务器，请检查 URL 是否正确"
    except requests.exceptions.HTTPError as e:
        return f"错误：HTTP 错误 {e.response.status_code}"
    except Exception as e:
        return f"错误：{str(e)}"

# 主程序
if __name__ == "__main__":
    # URL 占位符（会被自动格式化为带引号的字符串）
    url = {url}
    
    print(f"正在抓取网页标题...")
    print(f"URL: {url}")
    print("-" * 50)
    
    title = scrape_title(url)
    print(f"标题: {title}")
""",
    examples=[
        {
            "user_request": "帮我抓取 https://www.python.org 的标题",
            "parameters": {"url": "https://www.python.org"}
        }
    ]
)
