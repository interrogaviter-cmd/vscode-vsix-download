import requests
import os
import time

# ================= 配置区域 =================

# 1. 目标平台 (你的服务器是 Linux x64)
TARGET_PLATFORM = "linux-x64"
# TARGET_PLATFORM = "windows"

# 2. 保存目录
SAVE_DIR = f"./{TARGET_PLATFORM}__vscode_extensions_offline"

# 3. 这里的列表是根据你提供的图片自动生成的
# 已去掉版本号后缀，保留了 Publisher.ExtensionName 格式
EXTENSIONS = [
    # --- Python & 数据科学核心 (重中之重) ---
    "ms-python.python",              # Python 语言支持 (含二进制)
    "ms-python.vscode-pylance",      # Pylance 语言服务器
    "ms-python.debugpy",             # 调试器 (含二进制)
    "ms-python.black-formatter",     # Black 格式化
    "eeyore.yapf",                   # YAPF 格式化
    "hoangkimlai.ipython",           # IPython 支持
    
    # --- Jupyter Notebook 套件 ---
    "ms-toolsai.jupyter",            # Jupyter 核心 (含二进制)
    "ms-toolsai.jupyter-keymap",     # 快捷键
    "ms-toolsai.jupyter-renderers",  # 渲染器
    "ms-toolsai.vscode-jupyter-cell-tags",
    "ms-toolsai.vscode-jupyter-slideshow",
    "ms-toolsai.datawrangler",       # 数据清洗工具
    "ms-toolsai.tensorboard",        # Tensorboard 支持
    "xelad0m.jupyter-toc",           # Notebook 目录生成

    # --- C/C++ 开发 ---
    "ms-vscode.cpptools",            # C++ 核心 (含二进制)
    "ms-vscode.makefile-tools",      # Makefile 支持
    "twxs.cmake",                    # CMake 支持

    # --- Git & 版本控制 ---
    "eamodio.gitlens",               # Git 增强神器
    "mhutchie.git-graph",            # Git 图形化历史
    "fabiospampinato.vscode-diff",   # 差异对比工具

    # --- 辅助工具 (CSV, YAML, Docker 等) ---
    "mechatroner.rainbow-csv",       # CSV 彩虹高亮
    "janisdd.vscode-edit-csv",       # CSV 编辑器
    "phplasma.csv-to-table",         # CSV 转表格
    "repreng.csv",                   # 另一种 CSV 工具
    "redhat.vscode-yaml",            # YAML 支持
    "ms-azuretools.vscode-docker",   # Docker 支持
    "quicktype.quicktype",           # JSON 转代码工具
    "mrmlnc.vscode-duplicate",       # 文件复制工具
    "christian-kohler.path-intellisense", # 路径自动补全

    # --- AI & 智能助手 ---
    "codebuddyai.codebuddy-ai",      # CodeBuddy
    "saoudrizwan.claude-dev",        # Claude Dev (现名 Cline)
    "ms-windows-ai-studio.windows-ai-studio", # AI Studio (含二进制)

    # --- 界面美化 & 中文包 ---
    "ms-ceintl.vscode-language-pack-zh-hans", # 中文语言包
    "esbenp.prettier-vscode",        # 代码美化
    "oderwat.indent-rainbow",        # 缩进彩虹色
    "anseki.vscode-color",           # 颜色拾取
    "stuart.unique-window-colors",   # 窗口颜色区分
    "kdcro101.favorites",            # 收藏夹
    "howardzuo.vscode-favorites",    # 另一个收藏夹
    "foam.foam-vscode",              # 知识管理/笔记
    "gera2ld.markmap-vscode"         # Markdown 思维导图
]

EXTENSIONS = ['openai.chatgpt']
EXTENSIONS = ['ms-playwright.playwright']
# ===========================================

def download_extension(extension_id):
    try:
        publisher, name = extension_id.split('.')
        # 构建 API URL
        base_url = f"https://marketplace.visualstudio.com/_apis/public/gallery/publishers/{publisher}/vsextensions/{name}/latest/vspackage"
        
        url_linux = f"{base_url}?targetPlatform={TARGET_PLATFORM}"
        url_universal = base_url
        
        filename = os.path.join(SAVE_DIR, f"{extension_id}.vsix")
        
        print(f"[{extension_id}] 正在处理...")
        
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Python-Downloader'}
        
        # 1. 优先尝试下载 Linux 专用版
        # 注意：像 Python, CppTools, Jupyter 这种必须下 Linux 版
        print(f"  -> 尝试下载 {TARGET_PLATFORM} 版本...")
        r = requests.get(url_linux, headers=headers, stream=True)
        
        if r.status_code == 200:
            print(f"  -> ✅ 成功锁定 Linux 专用版！")
        elif r.status_code in [404, 400]:
            # 2. 如果没有 Linux 版，说明是通用版 (Universal)
            print(f"  -> 无专用版，切换到通用版本...")
            r = requests.get(url_universal, headers=headers, stream=True)
            if r.status_code == 200:
                print(f"  -> ✅ 成功锁定 通用版本！")
            else:
                print(f"  -> ❌ 失败：通用版也无法下载 (HTTP {r.status_code})")
                return
        else:
            print(f"  -> ❌ 请求异常 (HTTP {r.status_code})")
            return

        # 写入文件
        with open(filename, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
        print(f"  -> 💾 已保存到: {filename}\n")

    except Exception as e:
        print(f"  -> ❌ 发生错误: {e}\n")

if __name__ == "__main__":
    if not os.path.exists(SAVE_DIR):
        os.makedirs(SAVE_DIR)
        
    print(f"=== 开始批量下载 {len(EXTENSIONS)} 个插件 ===")
    print(f"目标目录: {os.path.abspath(SAVE_DIR)}\n")
    
    for ext in EXTENSIONS:
        download_extension(ext)
        
    print("=== 所有任务完成 ===")
    print("请将文件夹打包上传至服务器，并运行: \nfor i in *.vsix; do code-server --install-extension \"$i\"; done")