# 中国象棋助手

读取 iPhone 的 USB 或投屏窗口画面，识别 9 列 10 行的象棋棋盘，由 [Pikafish](https://github.com/official-pikafish/Pikafish) 在本机计算走法。窗口显示中文棋谱、起终点箭头和参考续着。适合练习、复盘和允许使用辅助工具的对局，程序不会向手机发送点击。

## 安装与使用

从 [Releases](https://github.com/Anthony-Edward-Stark/xiangqi-assistant/releases/latest) 按设备下载：

| 平台 | 安装包 |
| --- | --- |
| Apple 芯片 Mac，macOS 14+ | `XiangqiAssistant-macOS-AppleSilicon.dmg` |
| Intel Mac，macOS 14+（AVX2） | `XiangqiAssistant-macOS-Intel.dmg` |
| Windows x64 | `XiangqiAssistant-Windows-x64.zip` |

**macOS：**把 DMG 里的 App 拖到“应用程序”。 USB 连接 iPhone，保持解锁并确认“信任此电脑”，然后显示棋盘。App 为 ad-hoc 签名，未经过 Apple 公证。

**Windows：**解压整个 ZIP，再双击 `XiangqiAssistant.exe`。先在电脑上打开 iPhone 投屏窗口（例如已有的 AirPlay 接收器或采集卡预览），然后用 Edge 或 Chrome 打开助手本地页面，点击“选择投屏窗口”，在浏览器中选该窗口。Windows 版不提供 iPhone USB 直连取屏。结束时可点击“停止程序”。Windows 可执行文件未进行商业签名。

中国象棋需要另配权重：下载 [Pikafish 2026-09-06 官方发布包](https://github.com/official-pikafish/Pikafish/releases/tag/Pikafish-2026-09-06)，解出 `pikafish.nnue`。首次打开助手后，把文件放到 macOS 的 `~/Library/Application Support/XiangqiAssistant/` 或 Windows 的 `%LOCALAPPDATA%\XiangqiAssistant\`，然后重启。请使用该版本权重；[权重采用独立许可](https://github.com/official-pikafish/Networks#nnue-license)。在 macOS 下载目录也可以执行 `tar -xf Pikafish.2026-09-06.7z pikafish.nnue`。

计算档位为 250 毫秒至 30 秒，默认 5 秒。点击“重置棋局”会清空本局记录并重新识别，保留定位和棋子模板。中局接入时可能需要手动确认走子方。支持校正棋盘及导入 FEN。

安装包内置 Python、OpenCV 和引擎。取屏与分析在本机运行。Windows 的共享画面只保留在内存。当前识别以清晰、正向棋盘为准，换皮肤或横屏需要重新校准。

## 从源码构建

使用对应架构的 Python 3.12。macOS 需要 Xcode Command Line Tools；Apple 芯片版的 Rapfi 需要 CMake。Windows 构建需要 7-Zip（象棋），或 CMake 和 Visual Studio 2022 的 ClangCL x64 工具链（五子棋）。

```sh
python -m pip install -r requirements.txt pyinstaller==6.22.3
python prepare_engine.py
python build_app.py
python verify_packaged.py
python pack_release.py
```

产物位于 `release/`。`prepare_engine.py` 校验并准备该平台引擎；象棋的官方权重仅用作本地验证，不会打入安装包。Mac Intel 源码入口也可直接用 `./run.sh`，默认地址为 `http://127.0.0.1:8767/`。真实手机截图不会随仓库发布。

## 许可

助手自有代码按 [GNU GPL v3.0](LICENSE) 发布。Pikafish 按 GPL-3.0 分发，完整对应源码和上游许可在 [`engine/`](engine/) 中，构建信息及 SHA-256 见 [`engine/manifest.json`](engine/manifest.json)。项目和公开安装包均不分发 Pikafish NNUE 权重。App 另附 Python、NumPy、OpenCV、PyInstaller 等依赖的许可。
