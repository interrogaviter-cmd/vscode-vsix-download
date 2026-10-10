#!/bin/bash

# install_linux.sh

# 设置插件所在的根目录
REPO_DIR="./vscode_plugins_repo"

# 定义 Linux 需要安装的目录：Linux专用 + 通用
DIRS=("$REPO_DIR/linux64" "$REPO_DIR/universe")

# 检查 code 命令是否存在
if ! command -v code &> /dev/null; then
    echo "错误: 未找到 'code' 命令。"
    echo "如果是服务器环境(VS Code Server)，请尝试使用 'code-server' 命令，或者确保 bin 目录在 PATH 中。"
    exit 1
fi

echo "=== 开始批量安装 VS Code 插件 (Linux) ==="

for dir in "${DIRS[@]}"; do
    if [ -d "$dir" ]; then
        echo ""
        echo "正在处理目录: $dir"
        
        # 查找所有 .vsix 文件并逐个安装
        # 使用 find 命令可以避免目录为空时报错
        find "$dir" -name "*.vsix" -print0 | while IFS= read -r -d '' file; do
            filename=$(basename "$file")
            echo -n "正在安装: $filename ... "
            
            # 执行安装 (--force 覆盖安装)
            code --install-extension "$file" --force > /dev/null 2>&1
            
            if [ $? -eq 0 ]; then
                echo -e "\033[32m[成功]\033[0m"
            else
                echo -e "\033[31m[失败]\033[0m"
            fi
        done
    else
        echo "警告: 找不到目录 $dir"
    fi
done

echo ""
echo "=== 所有任务完成 ==="