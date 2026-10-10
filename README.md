<<<<<<< HEAD
# VS Code 插件离线下载

统一使用 `download_vscode_extensions.py`，插件配置集中在 `extension_catalog.py`。
默认保存到 `vscode_plugins_vsix`，下载 Windows x64 和 Linux x64 最新可用稳定版；通用包保存在 `universe` 中。该下载目录已加入 `.gitignore`。

## 版本选择

| 脚本 | 处理结果 | 原因 |
| --- | --- | --- |
| `download_vscode_extensions.py` | 保留为唯一维护的下载器，合并配置和别名 | 按平台选稳定版、校验包内平台/身份/CRC、失败重试、原子保存、记录 SHA256 和依赖 |
| `download.py` | 原样归档至 `legacy/` | 列表被连续赋值覆盖，实际只下载最后一项；无超时和验包 |
| `download_new.py` | 原样归档至 `legacy/` | 取全局最新版本，未区分预发布和平台；失败后留下正式文件；可能漏下通用包 |
| `download_new_single.py` | 原样归档至 `legacy/` | 与上一版重复，仅插件选择和输出目录不同 |

合并前的主脚本也保存在 `legacy/download_vscode_extensions_before_merge.py`。历史下载包目录保留。
两个旧安装脚本归档至 `legacy/`：原 `install_windows.bat` 的内容实际是 PowerShell，且两个安装器的默认目录与当前下载目录不一致。

本次检查的 138 个历史 VSIX 均通过 ZIP CRC，但其中 24 个包内平台与目录/文件名不符：2 个实际是通用包，22 个是错误平台包。
例如 `vscode_plugins_single/windows/charliermarsh.ruff-2026.76.0-win32-x64.vsix` 的实际平台是 `linux-x64`。
旧包的文件名不能作为平台依据；新下载器会重新核对包内平台，校验失败会隔离旧文件并重新下载。

## 安装运行依赖

需要 Python 3.8 或更新版本。推荐在项目目录创建虚拟环境，Windows PowerShell 执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

下方示例中的 `python` 应使用安装了依赖的解释器：Windows 虚拟环境是 `.\.venv\Scripts\python.exe`，Linux 是 `.venv/bin/python`。
如果已在其他虚拟环境中，也可以直接执行：

```sh
python -m pip install -r requirements.txt
```

## 插件列表与别名

`extension_catalog.py` 中提供三个可编辑变量：

- `HISTORICAL_EXTENSIONS`：所有历史脚本中出现过的 **69 个**插件 ID，包含注释和被后续赋值覆盖的列表。
- `EXTENSIONS_CANDIDATES`：完整备选列表，包含历史插件及本次新增的 7 个插件，共 **76 个**。
- `EXTENSIONS_LIST`：默认实际下载列表，保留 Codex、Codex Audio，加入 Claude Code 和 Cline。

备选列表记录候选项，不能保证历史插件仍上架或适配当前 VS Code。

| 输入别名 | 实际插件 ID |
| --- | --- |
| `claude-code` / `claudecode` / `claude` | `anthropic.claude-code` |
| `cline` / `cli` / `claude-dev` | `saoudrizwan.claude-dev` |
| `codex` / `chatgpt` | `openai.chatgpt` |
| `codex-audio` | `openai.codex-audio` |
| `cloud-code` / `cloudcode` / `google-cloud-code` | `googlecloudtools.cloudcode` |
| `kilo` / `kilo-code` | `kilocode.kilo-code` |
| `llama` / `llama-vscode` | `ggml-org.llama-vscode` |
| `codegpt` | `danielsanmedium.dscodegpt` |
| `tabby` | `tabbyml.vscode-tabby` |
| `ollama` | `ollama.ollama` |
| `continue` | `continue.continue` |

按本次确认，用户所称 “Cloud Code 和 CLI” 指 **Claude Code 和 Cline**。
为避免混淆，`claude-code` 对应 Anthropic Claude Code；字面别名 `cloud-code` 对应独立的 Google Cloud Code。
别名和完整 ID 不区分大小写，重复输入同一插件只处理一次，也可以传入不在备选列表中的完整 `publisher.name`。

## 使用示例

```sh
# 查看全部备选 ID 和别名（不联网、不创建输出文件）
python download_vscode_extensions.py --list-extensions

# 查看下载配置，确认别名解析结果（不联网、不创建输出文件）
python download_vscode_extensions.py --extensions claude-code cli codex --dry-run

# 下载 Claude Code 和 Cline：默认同时下载 Windows x64、Linux x64
python download_vscode_extensions.py --extensions claude-code cline

# 只下载 Linux x64 的本地模型工具
python download_vscode_extensions.py --extensions kilo llama codegpt --platforms linux-x64

# 下载完整备选列表（历史条目可能已下架）
python download_vscode_extensions.py --all

# 指定输出目录
python download_vscode_extensions.py --extensions cline --output ./vscode_plugins_repo

# 使用代理
python download_vscode_extensions.py --extensions cline --proxy http://127.0.0.1:10808

# 固定某个插件版本，用实际版本号替换 VERSION
python download_vscode_extensions.py --extensions cline --version VERSION
```

默认过滤预发布版本，需要时使用 `--pre-release`。固定版本时必须只选择一个去重后的插件。
各平台分别选择最新可用稳定版本，因此 Windows/Linux 的版本可能不同；同版本优先选择平台专用包，没有专用包时使用通用包。

成功包先下载到临时 `.part` 文件，验包成功后才成为正式 `.vsix`。已有包通过校验后跳过，失败的旧包改名隔离。
每次运行写入 `download_manifest.json`，记录本次各平台处理结果、路径、SHA256、VS Code 版本要求及依赖名称；失败返回退出码 1。
它只下载扩展包，不安装、不递归下载依赖，也不自动配置本地模型；`vscode_engine` 可用于检查离线机器的 VS Code 版本要求。
安装时选择本次清单中目标平台成功记录对应的文件，例如 `code --install-extension "/path/to/package.vsix"`。

## 本地模型工具备选

以下依据官方资料核对于 **2026-10-10**；扩展下载 ID 已加入备选变量。

| 工具 | 推荐用途 | 本地连接方式与官方资料 |
| --- | --- | --- |
| Kilo Code | 修改多个文件、执行命令、调试的 Agent 工作 | [Ollama](https://kilo.ai/docs/ai-providers/ollama)、[LM Studio](https://kilo.ai/docs/ai-providers/lmstudio) |
| llama.vscode | 优先考虑本地 Tab 补全，也提供聊天/Agent | [本地 llama.cpp 服务、FIM 补全](https://github.com/ggml-org/llama.vscode) |
| CodeGPT | 本地聊天、编辑，自定义局域网 API | [Ollama 或 LM Studio / OpenAI 兼容服务](https://www.codegpt.co/docs/local-models) |
| Tabby | 团队共享本地补全/聊天服务 | 插件先连接 Tabby Server，再由服务端[配置本地模型](https://tabby.tabbyml.com/docs/administration/model/) |
| Ollama 官方扩展 | 将自定义 Ollama 服务加入 VS Code Chat 模型选择器 | [官方扩展说明](https://github.com/ollama/ollama-vscode)，要求 VS Code 1.127+ |

Cline 也支持 [Ollama / LM Studio 本地模型](https://docs.cline.bot/running-models-locally/overview)。
通常 Ollama 地址是 `http://localhost:11434`；LM Studio 的 OpenAI 兼容地址是 `http://localhost:1234/v1`，以你的服务实际配置为准。
本地 Agent 还需要模型具备工具调用能力；Tab 补全优先选择支持 FIM 的代码模型。
Kilo 的本地模型接入用于 Agent；其当前 [Tab 补全技术文档](https://kilo.ai/docs/code-with-ai/features/autocomplete) 描述的是 Kilo Gateway 模型，不能据此保证本地 Tab 补全。

`continue.continue` 保留在历史备选中，但 [官方仓库](https://github.com/continuedev/continue) 已声明停止积极维护并转为只读。
[Roo Code 官方仓库](https://github.com/RooCodeInc/Roo-Code) 也已归档，并声明扩展于 2026-05-15 关闭，因此未将它加入新增推荐。

## 验证

```sh
python -m unittest discover -s tests -v
```

测试使用构造的 VSIX 和模拟 HTTP，不会下载真实插件或调用本地 VS Code 安装命令。
=======
# vscode-vsix-download
download vsix for vscode
>>>>>>> d698bb27257cde01a7e6014bdee7f4c1b88bac29
