"""
绘图相关的代码模板
"""
try:
    from ..models import Template
except ImportError:
    from models import Template


# 正弦曲线绘制模板
PLOT_SINE_WAVE = Template(
    name="plot_sine_wave",
    description="绘制正弦曲线",
    task_type="plot",
    sub_type="sine_wave",
    intent_keywords=["正弦", "sin", "sine", "曲线", "波形"],
    parameters={},
    success_rate=0.98,
    estimated_time=2.0,
    code_template="""
import numpy as np
import matplotlib.pyplot as plt
import matplotlib
import os

# 配置中文字体
matplotlib.rcParams['font.sans-serif'] = ['SimHei', 'DejaVu Sans']
matplotlib.rcParams['axes.unicode_minus'] = False

def plot_sine_wave():
    \"\"\"绘制正弦曲线\"\"\"
    try:
        # 生成数据
        x = np.linspace(0, 2 * np.pi, 100)
        y = np.sin(x)
        
        # 创建图形
        plt.figure(figsize=(10, 6))
        plt.plot(x, y, 'b-', linewidth=2, label='sin(x)')
        
        # 设置标题和标签
        plt.title('正弦曲线', fontsize=16, fontweight='bold')
        plt.xlabel('x', fontsize=12)
        plt.ylabel('sin(x)', fontsize=12)
        
        # 添加网格
        plt.grid(True, alpha=0.3)
        
        # 添加图例
        plt.legend(fontsize=12)
        
        # 设置坐标轴范围
        plt.xlim(0, 2 * np.pi)
        plt.ylim(-1.2, 1.2)
        
        # 添加 x 轴刻度标签
        plt.xticks([0, np.pi/2, np.pi, 3*np.pi/2, 2*np.pi],
                   ['0', 'π/2', 'π', '3π/2', '2π'])
        
        # 保存图片
        output_path = '/tmp/sine_wave.png'
        plt.savefig(output_path, dpi=150, bbox_inches='tight')
        plt.close()
        
        print(f"✅ 正弦曲线绘制成功！")
        print(f"图片已保存到: {output_path}")
        
        # 检查文件是否存在
        if os.path.exists(output_path):
            print(f"文件大小: {os.path.getsize(output_path)} 字节")
        
        return output_path
        
    except Exception as e:
        print(f"❌ 绘图失败: {str(e)}")
        return None

# 主程序
if __name__ == "__main__":
    print("正在绘制正弦曲线...")
    print("-" * 50)
    
    result = plot_sine_wave()
    
    if result:
        print("-" * 50)
        print("绘图完成！")
    else:
        print("-" * 50)
        print("绘图失败，请检查错误信息。")
""",
    examples=[
        {
            "user_request": "帮我画个正弦曲线",
            "parameters": {}
        },
        {
            "user_request": "绘制 sin(x) 函数图像",
            "parameters": {}
        }
    ]
)
