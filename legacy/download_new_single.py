import os
import requests
import logging
import time

# --- 配置部分 ---
BASE_SAVE_DIR = "./vscode_plugins_single"
LOG_FILE = "download_error.log"

# 定义目标目录
DIRS = {
    "windows": os.path.join(BASE_SAVE_DIR, "windows"),   # 存放 win32-x64
    "linux": os.path.join(BASE_SAVE_DIR, "linux64"),     # 存放 linux-x64
    "universe": os.path.join(BASE_SAVE_DIR, "universe")  # 存放 通用版
}


# 扩展列表：合并了您提供的所有截图内容
EXTENSIONS_LIST = [
    # "repreng.csv",
    # "mechatroner.rainbow-csv",
    # "grapecity.gc-excelviewer",
    # "phplasma.csv-to-table"
    # 'ms-python.debugpy',
    # 'charliermarsh.ruff',
    # 'mhutchie.git-graph',
    # 'eamodio.gitlens'
    'openai.chatgpt',
    'openai.codex-audio'
]



# --- VS Code Marketplace API ---
API_URL = "https://marketplace.visualstudio.com/_apis/public/gallery/extensionquery"

HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json;api-version=3.0-preview.1",
    "User-Agent": "VSCode-Extension-Downloader-Script"
}

# --- 日志设置 ---
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.ERROR,
    format='%(asctime)s - %(message)s',
    encoding='utf-8'
)

class ExtensionDownloader:
    def __init__(self):
        self._init_dirs()

    def _init_dirs(self):
        for path in DIRS.values():
            os.makedirs(path, exist_ok=True)

    def get_extension_info(self, extension_id):
        """查询插件的所有版本信息"""
        payload = {
            "filters": [{
                "criteria": [{"filterType": 7, "value": extension_id}]
            }],
            "flags": 914
        }
        
        try:
            r = requests.post(API_URL, json=payload, headers=HEADERS, timeout=15)
            r.raise_for_status()
            data = r.json()
            
            if not data['results'][0]['extensions']:
                return None
                
            return data['results'][0]['extensions'][0]
        except Exception as e:
            logging.error(f"API 查询失败 [{extension_id}]: {e}")
            print(f"  [!] API 查询失败: {e}")
            return None

    def download_file(self, url, save_dir, filename):
        """通用下载函数"""
        save_path = os.path.join(save_dir, filename)
        if os.path.exists(save_path):
            print(f"    -> 文件已存在，跳过: {filename}")
            return

        print(f"    -> 正在下载: {filename} ...")
        try:
            with requests.get(url, stream=True, timeout=30) as r:
                r.raise_for_status()
                with open(save_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)
            print("       下载完成!")
        except Exception as e:
            error_msg = f"下载文件失败 [{filename}]: {e}"
            print(f"       [X] {error_msg}")
            logging.error(error_msg)

    def process_extension(self, ext_id):
        print(f"\n--- 处理插件: {ext_id} ---")
        ext_data = self.get_extension_info(ext_id)
        
        if not ext_data:
            msg = f"插件不存在或无法访问: {ext_id}"
            print(f"  [X] {msg}")
            logging.error(msg)
            return

        versions = ext_data.get('versions', [])
        if not versions:
            logging.error(f"插件 [{ext_id}] 没有版本信息")
            return

        # 获取最新版本号
        latest_version_str = versions[0]['version']
        
        # 筛选最新版本的所有构建 (Windows, Linux, Universal)
        latest_builds = [v for v in versions if v['version'] == latest_version_str]
        
        # 提取下载链接
        url_map = {
            "win32-x64": None,
            "linux-x64": None,
            "universal": None
        }

        for build in latest_builds:
            target_platform = build.get('targetPlatform') 
            
            # 尝试获取 VSIX 链接
            asset_url = next((f['source'] for f in build['files'] if f['assetType'] == "Microsoft.VisualStudio.Services.VSIXPackage"), None)
            
            if not asset_url: 
                publisher = ext_data['publisher']['publisherName']
                name = ext_data['extensionName']
                version = build['version']
                base_dl = f"https://marketplace.visualstudio.com/_apis/public/gallery/publishers/{publisher}/vsextensions/{name}/{version}/vspackage"
                
                if target_platform:
                    asset_url = f"{base_dl}?targetPlatform={target_platform}"
                else:
                    asset_url = base_dl

            if target_platform == "win32-x64":
                url_map["win32-x64"] = asset_url
            elif target_platform == "linux-x64":
                url_map["linux-x64"] = asset_url
            elif target_platform is None or target_platform == "universal":
                url_map["universal"] = asset_url

        # 核心逻辑：优先专用版，无专用版则通用版
        has_windows = url_map["win32-x64"] is not None
        has_linux = url_map["linux-x64"] is not None
        has_universal = url_map["universal"] is not None

        processed_any = False
        
        if has_windows:
            fname = f"{ext_id}-{latest_version_str}-win32-x64.vsix"
            self.download_file(url_map["win32-x64"], DIRS["windows"], fname)
            processed_any = True
            
        if has_linux:
            fname = f"{ext_id}-{latest_version_str}-linux-x64.vsix"
            self.download_file(url_map["linux-x64"], DIRS["linux"], fname)
            processed_any = True

        if not processed_any:
            if has_universal:
                fname = f"{ext_id}-{latest_version_str}.vsix"
                self.download_file(url_map["universal"], DIRS["universe"], fname)
            else:
                msg = f"插件 [{ext_id}] 未找到 Windows, Linux 或 Universal 版本"
                print(f"  [!] {msg}")
                logging.error(msg)

if __name__ == "__main__":
    downloader = ExtensionDownloader()    
    for i, ext in enumerate(EXTENSIONS_LIST):
        downloader.process_extension(ext)
        time.sleep(0.5) # 避免请求过快
    print("\n所有任务执行完毕。如有失败，请检查 download_error.log")