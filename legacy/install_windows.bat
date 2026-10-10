# 设置插件所在的根目录
$repoDir = ".\vscode_plugins_repo"

# 定义 Windows 需要安装的两个目录：Windows专用 + 通用
$targetDirs = @(
    Join-Path $repoDir "windows",
    Join-Path $repoDir "universe"
)

# 检查 code 命令是否可用
if (-not (Get-Command "code" -ErrorAction SilentlyContinue)) {
    Write-Error "未找到 'code' 命令。请确保已安装 VS Code 并将其添加到系统环境变量 PATH 中。"
    exit
}

Write-Host "=== 开始批量安装 VS Code 插件 (Windows) ===" -ForegroundColor Cyan

foreach ($dir in $targetDirs) {
    if (Test-Path $dir) {
        Write-Host "`n正在处理目录: $dir" -ForegroundColor Yellow
        
        # 获取目录下所有 .vsix 文件
        $plugins = Get-ChildItem -Path $dir -Filter *.vsix
        
        foreach ($plugin in $plugins) {
            Write-Host "正在安装: $($plugin.Name) ..." -NoNewline
            
            # 执行安装命令
            try {
                # 使用 cmd /c 或者是直接调用 code.cmd
                # --force 参数用于覆盖安装（如果是更新版本）
                $process = Start-Process -FilePath "code" -ArgumentList "--install-extension `"$($plugin.FullName)`" --force" -Wait -NoNewWindow -PassThru
                
                if ($process.ExitCode -eq 0) {
                    Write-Host " [成功]" -ForegroundColor Green
                } else {
                    Write-Host " [失败]" -ForegroundColor Red
                }
            }
            catch {
                Write-Host " [执行错误: $_]" -ForegroundColor Red
            }
        }
    } else {
        Write-Host "警告: 找不到目录 $dir" -ForegroundColor Red
    }
}

Write-Host "`n=== 所有任务完成 ===" -ForegroundColor Cyan
Pause