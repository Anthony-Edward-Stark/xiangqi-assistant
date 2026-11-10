# 中国象棋助手

在 Mac 上读取 USB 连接的 iPhone 画面，识别 9 列 10 行的象棋棋盘，由 [Pikafish](https://github.com/official-pikafish/Pikafish) 在本机计算走法。窗口显示中文棋谱、起终点箭头和参考续着。适合练习、复盘和允许使用辅助工具的对局，程序不会向手机发送点击。

## 安装与使用

1. 从 [Releases](https://github.com/Anthony-Edward-Stark/xiangqi-assistant/releases/latest) 下载 `XiangqiAssistant-macOS-Intel.dmg`，把“中国象棋助手.app”拖到“应用程序”。支持有 AVX2 的 Intel Mac，最低 macOS 14。
2. 下载 [Pikafish 2026-09-06 官方发布包](https://github.com/official-pikafish/Pikafish/releases/tag/Pikafish-2026-09-06)，解出其中的 `pikafish.nnue`。首次打开 App 后，把文件放到 `~/Library/Application Support/XiangqiAssistant/`，再重启。请用该版本配套的权重；其他版本的权重可能不兼容。权重采用[独立许可](https://github.com/official-pikafish/Networks#nnue-license)，未经许可不得商用。
3. 用 USB 连接 iPhone，保持解锁。首次连接时在手机上确认“信任此电脑”。显示完整开局供助手学习棋子，再选择执子颜色。

1.1 版提供 250 毫秒至 30 秒的计算档位，默认 5 秒。计算时持续更新建议，同一局保留搜索缓存。点击“重置棋局”清空本局记录并重新识别，保留定位和棋子模板。中局接入时可能需要手动确认走子方。支持校正棋盘及导入 FEN。

安装包内置 Python、OpenCV、取屏程序和 Pikafish 引擎。App 为 ad-hoc 签名，未经过 Apple 公证。取屏、模板和分析均留在本机。其他皮肤、横屏及遮挡未验证。

在下载目录中，也可用系统自带的 `tar -xf Pikafish.2026-09-06.7z pikafish.nnue` 提取权重。

## 从源码运行或构建

在符合上述条件的 Intel Mac 上安装 Python 3.12 和 Xcode Command Line Tools。把上述官方发布包中的 `pikafish.nnue` 放入 `engine/`（Git 忽略该文件，构建也不会将它打入安装包）。运行 `./run.sh` 启动，默认窗口地址为 `http://127.0.0.1:8767/`，运行数据保存在仓库的 `.runtime/`。如需指定 Python，可用 `ASSISTANT_PYTHON=python3.12 ./run.sh`。

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt pyinstaller==6.22.3
.venv/bin/python verify.py
.venv/bin/python build_app.py
.venv/bin/python build_dmg.py
```

构建产物在 `dist/`。`./run.sh --image /path/to/board.jpg` 可回放截图。`verify.py` 检查规则、搜索、缓存和重置行为，可用 `--fixtures` 追加有标注的识别测试。个人采集画面未随仓库发布。

## 许可

助手自有代码按 [GNU GPL v3.0](LICENSE) 发布。Pikafish 按 GPL-3.0 分发，完整对应源码和上游许可在 [`engine/`](engine/) 中，构建信息及 SHA-256 见 [`engine/manifest.json`](engine/manifest.json)。项目和公开安装包均不分发 Pikafish NNUE 权重。App 另附 Python、NumPy、OpenCV、PyInstaller 等依赖的许可。
