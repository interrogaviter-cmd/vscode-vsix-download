#!/usr/bin/env python3
"""下载并验证 VSIX。Python >=3.8；pip install requests packaging

默认下载 Windows x64、Linux x64；通用包只保存一次到 universe。
示例：python download_vscode_extensions.py --platforms linux-x64
不自动安装，不修改 VSIX，不递归下载依赖；依赖名称记录在下载清单中。
"""
import argparse
import hashlib
import json
import logging
import os
import re
import struct
import sys
import time
import zipfile
from pathlib import Path
from urllib.parse import quote
import xml.etree.ElementTree as ET

import requests
from packaging.version import Version, InvalidVersion

EXTENSIONS_LIST = ["openai.chatgpt", "openai.codex-audio"]
BASE_SAVE_DIR = "./vscode_plugins_single"
API_URL = "https://marketplace.visualstudio.com/_apis/public/gallery/extensionquery"
FOLDERS = {"win32-x64": "windows", "linux-x64": "linux64", "universal": "universe"}
PRE_RELEASE = "Microsoft.VisualStudio.Code.PreRelease"


def platform_of(build):
    return build.get("targetPlatform") or "universal"


def is_preview(build):
    return any(p.get("key") == PRE_RELEASE and str(p.get("value")).lower() == "true"
               for p in build.get("properties", []))


def select_build(builds, target, pinned=None, allow_preview=False):
    """先选目标平台可用的最新版本；同版本专用包优先。绝不回退其他架构。"""
    candidates = []
    for b in builds:
        if platform_of(b) not in (target, "universal"):
            continue
        if pinned and b["version"] != pinned:
            continue
        try:
            v = Version(b["version"])
        except InvalidVersion:
            continue
        if not allow_preview and (is_preview(b) or v.is_prerelease):
            continue
        candidates.append((v, platform_of(b) == target, b))
    if not candidates:
        raise ValueError(f"没有可用的 {target}/universal 构建（版本={pinned or '最新稳定版'}）")
    return max(candidates, key=lambda x: (x[0], x[1]))[2]


def verify_codex_binary(zf, target):
    """核对实际 ELF/PE 机器类型，不能仅凭目录名或 manifest 判断。"""
    paths = {
        "linux-x64": "extension/bin/linux-x86_64/codex",
        "win32-x64": "extension/bin/windows-x86_64/codex.exe",
    }
    path = paths[target]
    try:
        with zf.open(path) as f:
            header = f.read(4096)
    except KeyError:
        raise ValueError(f"Codex 包缺少目标程序：{path}")
    if target == "linux-x64":
        if (len(header) < 20 or header[:4] != b"\x7fELF" or header[4] != 2
                or header[5] != 1 or struct.unpack_from("<H", header, 18)[0] != 62):
            raise ValueError("Codex 程序不是 Linux x86_64 ELF")
    else:
        if len(header) < 64 or header[:2] != b"MZ":
            raise ValueError("Codex 程序不是 Windows PE")
        offset = struct.unpack_from("<I", header, 60)[0]
        with zf.open(path) as f:
            f.seek(offset)
            pe = f.read(6)
        if len(pe) != 6 or pe[:4] != b"PE\0\0" or struct.unpack_from("<H", pe, 4)[0] != 0x8664:
            raise ValueError("Codex 程序不是 Windows x64")


def validate_vsix(path, ext_id, version, actual_platform, target):
    with zipfile.ZipFile(path) as zf:
        bad = zf.testzip()
        if bad:
            raise ValueError(f"ZIP CRC 校验失败：{bad}")
        pkg = json.loads(zf.read("extension/package.json"))
        xml = ET.fromstring(zf.read("extension.vsixmanifest"))
        ident = next((e for e in xml.iter() if e.tag.split("}")[-1] == "Identity"), None)
        if ident is None:
            raise ValueError("VSIX 缺少 Identity")
        pkg_id = f"{pkg.get('publisher')}.{pkg.get('name')}"
        xml_id = ident.get("Id", "")
        if not xml_id.lower().startswith(str(ident.get("Publisher", "")).lower() + "."):
            xml_id = f"{ident.get('Publisher')}.{xml_id}"
        if pkg_id.lower() != ext_id.lower() or xml_id.lower() != ext_id.lower():
            raise ValueError(f"扩展 ID 不匹配：{pkg_id} / {xml_id}")
        if pkg.get("version") != version or ident.get("Version") != version:
            raise ValueError("下载包与查询结果的版本不匹配")
        declared = ident.get("TargetPlatform") or "universal"
        if declared != actual_platform:
            raise ValueError(f"平台不匹配：期望 {actual_platform}，实际 {declared}")
        if declared not in (target, "universal"):
            raise ValueError(f"{declared} 无法用于 {target}")
        if ext_id.lower() == "openai.chatgpt":
            verify_codex_binary(zf, target)
        return {"declared_platform": declared,
                "vscode_engine": pkg.get("engines", {}).get("vscode"),
                "dependencies": pkg.get("extensionDependencies", []),
                "extension_pack": pkg.get("extensionPack", [])}


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class ExtensionDownloader:
    def __init__(self, output, attempts=3, proxy=None):
        self.output = Path(output).resolve()
        self.output.mkdir(parents=True, exist_ok=True)
        self.attempts = attempts
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "Verified-VSIX-Downloader/1.0"
        if proxy:
            self.session.trust_env = False
            self.session.proxies.update({"http": proxy, "https": proxy})

    def get_extension_info(self, ext_id):
        # IncludeVersions(1) | IncludeFiles(2) | IncludeVersionProperties(16)
        # | IncludeAssetUri(128)。不使用 IncludeLatestVersionOnly(512)。
        payload = {"filters": [{"criteria": [{"filterType": 7, "value": ext_id}],
                                "pageNumber": 1, "pageSize": 1}], "flags": 147}
        for attempt in range(1, self.attempts + 1):
            try:
                with self.session.post(API_URL, json=payload, headers={
                    "Accept": "application/json;api-version=3.0-preview.1"
                }, timeout=(15, 60)) as r:
                    r.raise_for_status()
                    data = r.json()
                for result in data.get("results", []):
                    for ext in result.get("extensions", []):
                        found = f"{ext['publisher']['publisherName']}.{ext['extensionName']}"
                        if found.lower() == ext_id.lower():
                            return ext
                raise ValueError(f"未找到扩展 {ext_id}")
            except (requests.RequestException, ValueError, KeyError):
                if attempt == self.attempts:
                    raise
                time.sleep(min(2 ** attempt, 8))

    def download_build(self, ext_id, build, target):
        actual = platform_of(build)
        version = build["version"]
        # 验证版本字符串，同时阻止元数据参与构造不安全的文件路径。
        Version(version)
        if not re.fullmatch(r"[A-Za-z0-9.+_-]+", version):
            raise ValueError("版本字符串包含非法字符")
        folder = self.output / FOLDERS[actual]
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{ext_id}-{version}-{actual}.vsix"
        if path.exists():
            try:
                meta = validate_vsix(path, ext_id, version, actual, target)
                print(f"  [已校验，跳过] {path.name}")
                return path, meta, "existing"
            except Exception as e:
                # 不丢弃旧文件；隔离后重新获取。
                quarantine = path.with_name(path.name + f".invalid-{time.time_ns()}")
                path.rename(quarantine)
                logging.warning("旧文件无效 %s：%s", path, e)
                print(f"  [旧包校验失败] {e}；已改名隔离")
        publisher, name = ext_id.split(".", 1)
        url = ("https://marketplace.visualstudio.com/_apis/public/gallery/publishers/"
               f"{quote(publisher, safe='')}/vsextensions/{quote(name, safe='')}/"
               f"{quote(version, safe='')}/vspackage")
        # 专用包显式指定平台。通用包不传 targetPlatform，随后严格检查包内平台。
        params = {} if actual == "universal" else {"targetPlatform": actual}
        part = path.with_name(path.name + f".{os.getpid()}.part")
        for attempt in range(1, self.attempts + 1):
            try:
                print(f"  [下载 {attempt}/{self.attempts}] {ext_id} {version} {actual}")
                with self.session.get(url, params=params, stream=True,
                                      timeout=(15, 120)) as r:
                    r.raise_for_status()
                    with part.open("wb") as f:
                        for chunk in r.iter_content(1024 * 1024):
                            if chunk:
                                f.write(chunk)
                meta = validate_vsix(part, ext_id, version, actual, target)
                os.replace(part, path)
                print(f"  [校验成功] {path.name}")
                return path, meta, "downloaded"
            except (requests.RequestException, OSError, ValueError, KeyError,
                    zipfile.BadZipFile, ET.ParseError) as e:
                logging.error("下载/校验失败 %s %s：%s", ext_id, target, e)
                if attempt == self.attempts:
                    raise
                time.sleep(min(2 ** attempt, 8))
            finally:
                if part.exists():
                    part.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extensions", nargs="+", default=EXTENSIONS_LIST)
    parser.add_argument("--platforms", nargs="+", choices=["win32-x64", "linux-x64"],
                        default=["win32-x64", "linux-x64"])
    parser.add_argument("--output", default=BASE_SAVE_DIR)
    parser.add_argument("--version", help="固定版本；一次只能配合一个扩展使用")
    parser.add_argument("--pre-release", action="store_true", help="允许预发布版本")
    parser.add_argument("--proxy", help="例如 http://127.0.0.1:10808；默认遵循 requests 环境代理")
    parser.add_argument("--attempts", type=int, default=3)
    args = parser.parse_args()
    if args.attempts < 1:
        parser.error("--attempts 必须 >= 1")
    if args.version and len(args.extensions) != 1:
        parser.error("--version 必须配合 --extensions 指定一个扩展")
    if any(not re.fullmatch(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", e) for e in args.extensions):
        parser.error("扩展 ID 必须为 publisher.name")
    downloader = ExtensionDownloader(args.output, args.attempts, args.proxy)
    handler = logging.FileHandler(downloader.output / "download_error.log", encoding="utf-8")
    logging.basicConfig(level=logging.WARNING, handlers=[handler],
                        format="%(asctime)s %(levelname)s %(message)s")
    records = []
    try:
        for ext_id in dict.fromkeys(args.extensions):
            print(f"\n--- {ext_id} ---")
            try:
                info = downloader.get_extension_info(ext_id)
            except Exception as e:
                logging.exception("查询失败 %s", ext_id)
                records.append({"extension": ext_id, "status": "failed", "error": str(e)})
                print(f"  [失败] {e}")
                continue
            for target in dict.fromkeys(args.platforms):
                try:
                    build = select_build(info.get("versions", []), target,
                                         args.version, args.pre_release)
                    path, meta, status = downloader.download_build(ext_id, build, target)
                    records.append({"extension": ext_id, "target": target,
                                    "version": build["version"], "status": status,
                                    "path": str(path), "sha256": sha256(path), **meta})
                except Exception as e:
                    logging.exception("处理失败 %s %s", ext_id, target)
                    records.append({"extension": ext_id, "target": target,
                                    "status": "failed", "error": str(e)})
                    print(f"  [失败] {target}: {e}")
    finally:
        downloader.session.close()
    report = downloader.output / "download_manifest.json"
    temp = report.with_suffix(".json.part")
    temp.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, report)
    failures = sum(r["status"] == "failed" for r in records)
    print(f"\n完成：{len(records) - failures} 项成功，{failures} 项失败。清单：{report}")
    print("按目标平台分别选择最新可用稳定版；不同平台可能版本不同。")
    print("未校验本地 VS Code 版本兼容性；最低版本要求见清单 vscode_engine。")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
