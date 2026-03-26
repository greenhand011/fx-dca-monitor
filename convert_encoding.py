import os

def convert_to_utf8(filepath):
    """尝试以不同编码读取文件并转换为 UTF-8"""
    encodings = ['utf-8', 'gbk', 'gb2312', 'gb18030', 'latin-1']
    content = None
    
    for enc in encodings:
        try:
            with open(filepath, 'r', encoding=enc) as f:
                content = f.read()
            # 如果成功读取且是中文文件，检查是否有乱码
            if enc != 'utf-8':
                print(f"  检测到编码: {enc}")
            break
        except (UnicodeDecodeError, UnicodeError):
            continue
    
    if content is None:
        print(f"  ❌ 无法读取: {filepath}")
        return False
    
    # 写入 UTF-8
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
    
    return True

# 转换所有 .py 文件
py_files = [f for f in os.listdir('.') if f.endswith('.py') and f != 'convert_encoding.py']

print(f"找到 {len(py_files)} 个 Python 文件\n")

for f in py_files:
    print(f"处理: {f}")
    if convert_to_utf8(f):
        print(f"  ✅ 已转换为 UTF-8\n")

print("转换完成！")
