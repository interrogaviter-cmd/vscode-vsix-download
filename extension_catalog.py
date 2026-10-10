"""下载配置：历史插件全集、备选列表和便于输入的别名。

Marketplace ID 不区分大小写。历史条目只记录出现过，不保证仍在上架。
编辑 EXTENSIONS_LIST 选择默认下载项，或使用主脚本的 --extensions 参数。
"""
import re


# 四个历史脚本的并集，包含注释、被后续赋值覆盖的列表；共 69 个。
HISTORICAL_EXTENSIONS = [
    # Python / 数据科学
    "ms-python.python",
    "ms-python.vscode-pylance",
    "ms-python.debugpy",
    "ms-python.black-formatter",
    "eeyore.yapf",
    "hoangkimlai.ipython",
    "charliermarsh.ruff",
    # Jupyter
    "ms-toolsai.jupyter",
    "ms-toolsai.jupyter-keymap",
    "ms-toolsai.jupyter-renderers",
    "ms-toolsai.vscode-jupyter-cell-tags",
    "ms-toolsai.vscode-jupyter-slideshow",
    "ms-toolsai.datawrangler",
    "ms-toolsai.tensorboard",
    "xelad0m.jupyter-toc",
    # C / C++
    "ms-vscode.cpptools",
    "ms-vscode.makefile-tools",
    "twxs.cmake",
    "jeff-hykin.better-cpp-syntax",
    # Git / 远程开发
    "eamodio.gitlens",
    "mhutchie.git-graph",
    "fabiospampinato.vscode-diff",
    "github.remotehub",
    "ms-vscode-remote.remote-ssh",
    "ms-vscode-remote.remote-ssh-edit",
    "ms-vscode.remote-explorer",
    # 数据 / 文件 / 开发工具
    "mechatroner.rainbow-csv",
    "janisdd.vscode-edit-csv",
    "phplasma.csv-to-table",
    "repreng.csv",
    "grapecity.gc-excelviewer",
    "redhat.vscode-yaml",
    "ms-azuretools.vscode-docker",
    "quicktype.quicktype",
    "mrmlnc.vscode-duplicate",
    "christian-kohler.path-intellisense",
    "alefragnani.project-manager",
    "hediet.vscode-drawio",
    "inu1255.easy-snippet",
    "tomoki1207.pdf",
    "usernamehw.errorlens",
    "yzhang.markdown-all-in-one",
    "changkaiyan.tf2snippets",
    "quarto.quarto",
    "mtxr.sqltools",
    "mtxr.sqltools-driver-pg",
    "ms-playwright.playwright",
    # AI 助手（Continue 保留为历史备选，官方仓库已停止积极维护）
    "codebuddyai.codebuddy-ai",
    "saoudrizwan.claude-dev",  # Cline；历史名称 Claude Dev
    "ms-windows-ai-studio.windows-ai-studio",
    "continue.continue",
    "tanishqkancharla.opencode-vscode",
    "sst-dev.opencode",
    "openai.chatgpt",  # Codex 的 Marketplace ID
    "openai.codex-audio",
    # 界面 / 主题 / 笔记
    "ms-ceintl.vscode-language-pack-zh-hans",
    "esbenp.prettier-vscode",
    "oderwat.indent-rainbow",
    "anseki.vscode-color",
    "stuart.unique-window-colors",
    "kdcro101.favorites",
    "howardzuo.vscode-favorites",
    "foam.foam-vscode",
    "gera2ld.markmap-vscode",
    "aryanahire.sublime-monokai",
    "jprestidge.theme-material-theme",
    "monokai.theme-monokai-pro-vscode",
    "maximetinu.identical-sublime-monokai-csharp-theme-colorizer",
    "johnpapa.vscode-peacock",
]

# 本次补充的插件；下载插件不会安装/启动本地模型服务。
ADDITIONAL_EXTENSIONS = [
    "anthropic.claude-code",       # Claude Code（Anthropic）
    "googlecloudtools.cloudcode",  # Google Cloud Code，独立于 Claude Code
    "kilocode.kilo-code",          # Kilo Code：本地模型 Agent
    "ggml-org.llama-vscode",        # llama.vscode：llama.cpp 本地补全/聊天
    "danielsanmedium.dscodegpt",    # CodeGPT：Ollama / OpenAI 兼容端点
    "tabbyml.vscode-tabby",         # Tabby：连接自部署 Tabby Server
    "ollama.ollama",               # Ollama 官方模型连接扩展
]

# 完整备选变量列表，默认不全量下载。--all 会选择这个列表。
EXTENSIONS_CANDIDATES = list(dict.fromkeys(HISTORICAL_EXTENSIONS + ADDITIONAL_EXTENSIONS))

# 默认下载列表；只维护这一处，避免旧版本中的反复赋值覆盖。
EXTENSIONS_LIST = [
    "openai.chatgpt",
    "openai.codex-audio",
    "anthropic.claude-code",
    "saoudrizwan.claude-dev",
]

EXTENSION_ALIASES = {
    "codex": "openai.chatgpt",
    "chatgpt": "openai.chatgpt",
    "codex-audio": "openai.codex-audio",
    "claude-code": "anthropic.claude-code",
    "claudecode": "anthropic.claude-code",
    "claude": "anthropic.claude-code",
    "cline": "saoudrizwan.claude-dev",
    "claude-dev": "saoudrizwan.claude-dev",
    "cli": "saoudrizwan.claude-dev",  # 按用户确认，CLI 指 Cline
    "cloud-code": "googlecloudtools.cloudcode",
    "cloudcode": "googlecloudtools.cloudcode",
    "google-cloud-code": "googlecloudtools.cloudcode",
    "continue": "continue.continue",
    "kilo": "kilocode.kilo-code",
    "kilo-code": "kilocode.kilo-code",
    "llama": "ggml-org.llama-vscode",
    "llama-vscode": "ggml-org.llama-vscode",
    "codegpt": "danielsanmedium.dscodegpt",
    "tabby": "tabbyml.vscode-tabby",
    "ollama": "ollama.ollama",
}


def resolve_extensions(names):
    """解析别名或完整 ID，按大小写不敏感去重并保持输入顺序。"""
    resolved = []
    for name in names:
        token = name.strip().lower()
        alias_key = re.sub(r"[\s_]+", "-", token)
        extension_id = EXTENSION_ALIASES.get(alias_key, token)
        if not re.fullmatch(r"[a-z0-9_-]+\.[a-z0-9_-]+", extension_id):
            raise ValueError(f"未知插件别名 {name!r}；请使用 --list-extensions 查看，或填写 publisher.name")
        if extension_id not in resolved:
            resolved.append(extension_id)
    return resolved
