"""Package the signed App in a macOS drag-to-Applications disk image."""
import argparse
import hashlib
import json
import plistlib
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent
APP_NAME = "中国象棋助手.app"
INSTALL_TEXT = """中国象棋助手 {version}

安装：
1. 将“中国象棋助手.app”拖到旁边的“Applications”文件夹。
2. 在 Mac 的“应用程序”中双击“中国象棋助手”。
3. 安装完成后，可推出此磁盘映像。

首次分析前需配置 Pikafish 权重：
从 https://github.com/official-pikafish/Pikafish/releases/tag/Pikafish-2026-09-06
下载 Pikafish.2026-09-06.7z，解出 pikafish.nnue。首次启动 App 后，将权重
放到 ~/Library/Application Support/XiangqiAssistant/，然后重启助手。
在下载目录中可用 tar -xf Pikafish.2026-09-06.7z pikafish.nnue 提取文件。
权重适用 https://github.com/official-pikafish/Networks#nnue-license 的独立条款。

使用：
iPhone 通过 USB 连接 Mac，保持解锁并显示完整象棋开局。
首次连接时，在 iPhone 上确认“信任此电脑”。
助手只读取画面，显示中文走法和蓝色箭头；请在手机上自行走子。
点击“重置棋局”可清空本局记录并重新读取，原有自动识别继续保留。
计算时间可选 250 毫秒至 30 秒，计算中持续更新建议，完成后显示最终建议。

兼容：{platform}，macOS 14 或更新版本。
Python、OpenCV 和 Pikafish 引擎已内置。
本版使用本机 ad-hoc 签名，未进行 Apple 公证。
完整说明、第三方许可及对应源码随 App 资源附带。
"""


def run(*arguments):
    subprocess.run([str(item) for item in arguments], check=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", type=Path, default=ROOT / "dist" / APP_NAME)
    parser.add_argument("--output", type=Path, default=ROOT / "dist/XiangqiAssistant-macOS-Intel.dmg")
    parser.add_argument("--work-dir", type=Path, default=ROOT / ".build/dmg")
    args = parser.parse_args()
    app = args.app.resolve()
    output = args.output.resolve()
    info = plistlib.loads((app / "Contents/Info.plist").read_bytes())
    if info.get("CFBundleIdentifier") != "local.xiangqi.assistant":
        raise RuntimeError(f"Unexpected App bundle: {app}")
    if output.exists():
        raise FileExistsError(f"Output already exists: {output}")
    run("/usr/bin/codesign", "--verify", "--deep", "--strict", app)
    args.work_dir.mkdir(parents=True, exist_ok=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="xiangqi-", dir=args.work_dir) as temporary:
        folder = Path(temporary)
        stage = folder / "image-root"
        stage.mkdir()
        run("/usr/bin/ditto", app, stage / APP_NAME)
        (stage / "Applications").symlink_to("/Applications", target_is_directory=True)
        platform = "Apple 芯片 Mac" if info.get("AssistantArchitecture") == "arm64" else "Intel Mac（AVX2）"
        (stage / "安装说明.txt").write_text(INSTALL_TEXT.format(version=info["CFBundleShortVersionString"], platform=platform), encoding="utf-8")
        run("/usr/bin/codesign", "--verify", "--deep", "--strict", stage / APP_NAME)
        image = folder / "installer.dmg"
        run("/usr/bin/hdiutil", "create", "-srcfolder", stage, "-fs", "HFS+",
            "-volname", "中国象棋助手", "-format", "UDZO", "-imagekey", "zlib-level=9",
            "-nospotlight", image)
        run("/usr/bin/hdiutil", "verify", image)
        image.rename(output)
    print(json.dumps({"dmg": str(output), "bytes": output.stat().st_size,
                      "sha256": hashlib.sha256(output.read_bytes()).hexdigest()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
