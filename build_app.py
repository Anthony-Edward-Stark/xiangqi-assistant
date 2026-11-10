"""Build the Intel macOS App with an embedded Python runtime and native window."""
import argparse
import hashlib
import importlib.metadata
import json
import plistlib
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def run(*arguments):
    subprocess.run([str(arg) for arg in arguments], check=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-dir", type=Path, default=ROOT / ".build/app")
    parser.add_argument("--output", type=Path, default=ROOT / "dist/中国象棋助手.app")
    parser.add_argument("--settings", type=Path)
    args = parser.parse_args()
    build = args.build_dir.resolve()
    build.mkdir(parents=True, exist_ok=True)
    capture = build / "phone-capture"
    run("/usr/bin/swiftc", "-O", "-target", "x86_64-apple-macosx14.0", ROOT / "capture.swift", "-o", capture)
    engine = ROOT / "engine"
    manifest = json.loads((engine / "manifest.json").read_text())
    # The network has separate terms and must never be bundled in public builds.
    engine_files = (*manifest["sha256"], "manifest.json", "AUTHORS", "NETWORKS.txt")
    engine_data = [arg for name in engine_files for arg in ("--add-data", f"{engine / name}:engine")]
    run(sys.executable, "-m", "PyInstaller", "--noconfirm", "--onedir", "--noupx",
        "--name", "xiangqi-backend", "--distpath", build / "dist", "--workpath", build / "pyi",
        "--specpath", build, "--paths", ROOT, "--add-data", f"{ROOT / 'index.html'}:.",
        *engine_data, "--add-binary", f"{capture}:bin",
        "--copy-metadata", "numpy", "--copy-metadata", "opencv-python-headless", ROOT / "app.py")
    app = args.output.resolve()
    if app.exists():
        info = app / "Contents/Info.plist"
        if not info.exists() or plistlib.loads(info.read_bytes()).get("CFBundleIdentifier") != "local.xiangqi.assistant":
            raise RuntimeError(f"Refusing to replace an unrelated App: {app}")
        shutil.rmtree(app)
    contents = app / "Contents"
    resources = contents / "Resources"
    executable = contents / "MacOS/XiangqiAssistant"
    executable.parent.mkdir(parents=True)
    resources.mkdir(parents=True)
    shutil.copytree(build / "dist/xiangqi-backend", resources / "backend", symlinks=True)
    run("/usr/bin/swiftc", "-O", "-target", "x86_64-apple-macosx14.0", "-framework", "AppKit",
        "-framework", "WebKit", ROOT / "macos/Launcher.swift", "-o", executable)
    run("/usr/bin/swiftc", "-O", ROOT / "macos/Icon.swift", "-o", build / "make-icon")
    run(build / "make-icon", build / "Xiangqi.iconset")
    run("/usr/bin/iconutil", "-c", "icns", build / "Xiangqi.iconset", "-o", resources / "Xiangqi.icns")
    settings = {"budget_ms": 5000, "my_color": "red", "orientation": "auto", "paused": False}
    if args.settings:
        saved = json.loads(args.settings.read_text())
        for key in ("orientation", "budget_ms", "my_color"):
            if key in saved:
                settings[key] = saved[key]
    (resources / "default-settings.json").write_text(json.dumps(settings, indent=2) + "\n")
    licenses = resources / "licenses"
    licenses.mkdir()
    shutil.copy2(Path(sysconfig.get_path("stdlib")) / "LICENSE.txt", licenses / "Python.txt")
    installer = importlib.metadata.distribution("pyinstaller")
    installer_license = next(item for item in installer.files if str(item).endswith("licenses/COPYING.txt"))
    shutil.copy2(installer.locate_file(installer_license), licenses / "PyInstaller.txt")
    (licenses / "说明.txt").write_text(
        "Python 及 PyInstaller 许可见本目录，PyInstaller 包含分发生成程序的例外条款。\n"
        "NumPy、OpenCV 及相关第三方许可见 ../backend/_internal/ 内的 dist-info 目录。\n"
        "Pikafish GPL-3.0 许可、对应完整源码及网络说明见 ../backend/_internal/engine/。\n")
    shutil.copy2(ROOT / "README.md", resources / "说明.md")
    shutil.copytree(ROOT / "macos", resources / "source/macos")
    for name in ("LICENSE", "README.md", "app.py", "vision.py", "rules.py", "engine.py", "index.html", "requirements.txt", "capture.swift", "build_app.py", "build_dmg.py", "run.sh", "verify.py"):
        shutil.copy2(ROOT / name, resources / "source" / name)
    (contents / "Info.plist").write_bytes(plistlib.dumps({
        "CFBundleExecutable": "XiangqiAssistant", "CFBundleIdentifier": "local.xiangqi.assistant",
        "CFBundleName": "中国象棋助手", "CFBundleDisplayName": "中国象棋助手", "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": "1.1", "CFBundleVersion": "2", "CFBundleIconFile": "Xiangqi.icns",
        "LSMinimumSystemVersion": "14.0", "NSHighResolutionCapable": True,
        "NSCameraUsageDescription": "读取通过 USB 连接的 iPhone 屏幕，用于识别中国象棋棋盘并计算下一手。",
        "NSAppTransportSecurity": {"NSAllowsLocalNetworking": True},
    }))
    (contents / "PkgInfo").write_bytes(b"APPL????")
    run("/usr/bin/codesign", "--force", "--deep", "--sign", "-", "--timestamp=none", app)
    # Signing changes executable bytes. Preserve provenance and hash the shipped files.
    engine_directory = resources / "backend/_internal/engine"
    manifest_file = engine_directory / "manifest.json"
    manifest = json.loads(manifest_file.read_text())
    manifest["pre_packaging_sha256"] = dict(manifest["sha256"])
    manifest["sha256"] = {name: hashlib.sha256((engine_directory / name).read_bytes()).hexdigest()
                          for name in manifest["sha256"]}
    manifest["packaging"] = {"target": "Intel macOS App", "signature": "local ad-hoc"}
    manifest_file.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    run("/usr/bin/codesign", "--force", "--sign", "-", "--timestamp=none", app)
    run("/usr/bin/codesign", "--verify", "--deep", "--strict", "--verbose=2", app)
    print(json.dumps({"app": str(app)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
