# 跨平台兼容性与 pip 发行检查

检查日期：2026-10-22。本文区分代码实现、自动化验证和真实音频设备验收。
0.2.1 补齐 macOS / Linux 桌面集成，可以从此前的 0.2.0 pip 安装升级。
0.2.2 增加首次启动的高性能 GPU 默认选择、CLI `auto` 和 macOS CoreML 入口。
0.2.3 将程序迁入 `src/openbroadcast/`，同步调整可编辑安装、文档资源和 Windows 构建路径。
0.2.4 增加麦克风音棚音效、跨显卡显存管理和持续实时性能不足提醒。
开发环境为 Windows x64 / CPython 3.12，另在 Ubuntu 24.04 WSL / Xvfb 中验证 Linux 桌面功能；
macOS 仍待原生验收，WSL 测试不代表 Linux 音频硬件已通过验收。

## 安装与构建

项目使用 `pyproject.toml` / setuptools 构建一个通用 `py3-none-any` wheel。
Python 源码本身没有平台绑定；NumPy、ONNX Runtime、sounddevice、soundfile 的原生库由 pip
按操作系统、处理器架构和 Python 版本选择。通用 wheel 不代表所有 CPU 架构都有可用依赖。

- 最低 CPython 3.11，建议使用 3.12；不宣称支持 32 位、PyPy、自由线程构建或任意 Linux 发行版。
- Windows AMD64 自动安装 `onnxruntime-directml==1.24.4`；其他平台安装 `onnxruntime>=1.20,<2`。
  DirectML 1.24.4 只发布了 CPython 3.11–3.14 的 Windows x64 wheel，
  之前文档中的 Python 3.10 与该依赖不兼容。
- Windows ARM64 使用普通 ONNX Runtime 的 CPU 路径，但尚未纳入验收范围。
- macOS Intel / Apple Silicon 和 Linux 的最低系统版本由实际选择的原生依赖决定。
  Intel Mac 建议先使用 Python 3.12；新版 Python 未必有对应的 ONNX Runtime wheel。
- 不同时依赖 `onnxruntime` 和 `onnxruntime-directml`，避免它们覆盖同一个 Python 模块。
  如果自行切换 CUDA 等发行包，请在独立环境中管理替代依赖；普通 pip 安装不自动提供这些后端。
- macOS / Linux 自动安装 `PySide6-Essentials`，托盘在独立进程的主线程中运行 Qt；
  Tk 界面和音频处理仍在原进程。这样避免在 Tk 中混用第二套 GUI 事件循环，
  也避免要求 Linux 虚拟环境从源码编译 PyGObject。Qt 自带库会增加安装体积。
- 当前源码构建的 wheel 内含三份 ONNX 模型、DSP NPZ、双语 README 和 Windows 源码启动脚本；
  模型仍按安装包目录定位，不依赖当前工作目录。没有首次运行联网下载模型的逻辑。
  wheel 同时携带可选的 Windows x64 DirectML 辅助模块；其他平台不会加载该 DLL。
- GUI 依赖 Tk 和桌面会话；Linux 另需系统 PortAudio，必要时安装 libsndfile。
  Python/pip 包不负责安装系统库或虚拟音频驱动。

Debian / Ubuntu 的音频、Tk 和 Qt 桌面依赖：

```sh
sudo apt install python3-venv python3-tk libportaudio2 libsndfile1 libegl1 libgl1 libxcb-cursor0 libxkbcommon-x11-0 libxcb-icccm4 libxcb-keysyms1 libxcb-shape0
```

Tk 必须与虚拟环境所用的 Python 对应，可运行 `python -m tkinter` 检查。

在项目目录构建：

```sh
git lfs install
git lfs pull
python -m pip install build twine
python -m build --outdir dist/pypi
python -m twine check --strict dist/pypi/*
```

默认构建先生成 sdist，再从 sdist 构建 wheel，因此可以发现源码发行包遗漏文件的问题。
从 Git 克隆后需安装 Git LFS 并拉取音棚模型；发行 wheel 和便携 ZIP 已包含完整模型，无需 Git LFS。
安装使用 `python -m pip install .` 或 `python -m pip install path/to/package.whl`；
开发使用 `python -m pip install -e .`。安装后有 `openbroadcast`、`openbroadcast-gui`
和 `python -m openbroadcast` 三个入口。Windows 自启仍使用环境中的绝对 `pythonw.exe`
和包内 `run_gui.pyw` 路径，不要求登录后的工作目录指向源码。

源码位于 `src/openbroadcast/`。开发时使用 `python -m pip install -e .`，
再从任意目录运行 `python -m openbroadcast`。根目录文档由 `setup.py` 的构建命令复制进 wheel，
可编辑安装直接读取仓库文档，不维护两份副本。测试不通过修改 `sys.path` 掩盖安装问题。

Windows 便携版使用 `packaging/windows/` 中的脚本和配置：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\packaging\windows\build_windows.ps1
```

macOS 的 pip 入口是 `openbroadcast-gui` 或 `python -m openbroadcast`。
当前不生成 `.app`、不向“应用程序”目录注册应用，因此不会自动在启动台 / 应用列表中出现。
启动命令与登录自启配置是独立机制；未来的 `.app` 发行需要额外封装和原生验证。

## 功能逐项检查

| 功能 / 模块 | Windows | macOS | Linux | 限制 |
| --- | --- | --- | --- | --- |
| GUI / CLI 启动 | 已实现 | 已实现 | 已实现 | GUI 必须安装 Tk 并有图形会话 |
| CPU 降噪、房间去混响 | 已实现 | 已实现 | 已实现 | NumPy + ONNX Runtime；模型延迟每级 70 ms |
| 麦克风、扬声器独立实时路由 | WASAPI | CoreAudio | PortAudio 提供的 ALSA / JACK 等接口 | 48 kHz，单声道 / 双声道；具体驱动待各平台验收 |
| 同时处理两路、效果强度、在线切换 | 已实现 | 已实现 | 已实现 | 需要两条独立虚拟音频路径和足够算力 |
| 设备刷新 / 掉线错误 / 保存设备身份 | 已实现 | 已实现 | 已实现 | 不擅自改接其他设备；刷新前停止音频流 |
| 录音、原始 / 处理后对比、试听 | 已实现 | 已实现 | 已实现 | 音频输出设备必须支持 48 kHz |
| WAV / FLAC / OGG 输入，WAV / FLAC 输出 | 已实现 | 已实现 | 已实现 | 文件重采样为线性插值，非高质量带限重采样 |
| 文件进度、取消、原子输出、多声道 | 已实现 | 已实现 | 已实现 | 独立模型状态，内存有界；由 libsndfile 解码 |
| GUI GPU 列表 / 持久化选择 | DirectML / 可选 CUDA | CoreML 系统调度，待实机验证 | 可选 CUDA | 运行库未提供支持时默认 CPU；没有自动 CUDA 依赖安装 |
| CLI `--provider` | 默认 auto | 默认 auto | 默认 auto | auto 无受支持的 GPU 时选择 CPU；显式 GPU 初始化失败会报错 |
| 托盘、关闭隐藏、登录启动 | 已实现 | Qt 菜单栏 / LaunchAgent | Qt 桌面托盘 / XDG Autostart | 托盘就绪后才隐藏；缺失 / 故障时恢复主窗口 |
| 单实例及唤醒已隐藏窗口 | Windows 内核 mutex / event | POSIX flock / 激活计数 | POSIX flock / 激活计数，按桌面会话隔离 | 二次启动只唤醒，不创建新音频路由；崩溃自动释放锁 |
| Windows COM / 原生标题栏 | 有平台保护 | 跳过 | 跳过 | 非 Windows 不加载 Windows API |
| 页面滚动 | MouseWheel / 120 | 原生小步长 | X11 Button-4 / Button-5 | 下拉框滚轮保护保留 |
| 设置保存、主题、中英文 | 已实现 | 已实现 | 已实现 | Windows 读取 UI 语言，其他系统读取 locale 环境 |
| 读取已装 NVIDIA Broadcast 的试听素材 | 可选 | 无 | 无 | 不打包素材，缺失时不影响录音 / 文件处理 |
| 音棚音效（当前源码） | CPU / DirectML 已验证 | 未验证 | 未验证 | 默认关闭，替代降噪与去混响；不提供强度调节，CPU 实测未达到实时速度 |
| 视频、内置虚拟声卡 | 无 | 无 | 无 | 现阶段不支持 |

设置路径：Windows `%APPDATA%/OpenBroadcast/settings.json`；
macOS `~/Library/Application Support/OpenBroadcast/settings.json`；
Linux `$XDG_CONFIG_HOME/OpenBroadcast/settings.json`，未设置时为 `~/.config/OpenBroadcast/settings.json`。

## 默认推理设备

- 新安装的 GUI 与 CLI `--provider auto` 优先选择运行库支持的 GPU，无可选 GPU 时使用 CPU。
  已保存的 GUI CPU / GPU 选择保持不变；显式选中的显卡缺失或初始化失败仍会报错。
- Windows 使用 `IDXGIFactory6::EnumAdapterByGpuPreference(HIGH_PERFORMANCE)` 的排序，
  按 LUID 匹配回 DirectML 原生编号；排序接口不可用时按专用显存选择。
  CUDA 根据多处理器数量 × 时钟频率、显存排序。这是硬件估计，不是模型基准测试。
- macOS 提供 CoreML 时，默认选择系统管理的 GPU 入口，设置 `MLComputeUnits=CPUAndGPU`。
  ARM Mac 使用 Apple 芯片的集成 GPU，不需要对多个显卡排序。
  CoreML 可将部分运算安排到 CPU；ORT 的 CoreML 接口没有逐块 Metal 显卡绑定参数。
  界面明确说明系统调度，不将 CoreML 提供程序已加载当作全部运算均由 GPU 执行的证据。
- 本机 RTX 5090 被选为默认设备，两份模型均已通过真实 DirectML 推理；
  CoreML 的发现、选择和会话参数通过模拟验证，新增 macOS 专属两模型测试供原生 CI 执行，
  尚未实测 Mac GPU 使用率或端到端性能。

依据：[Windows 高性能显卡排序](https://learn.microsoft.com/en-us/windows/win32/api/dxgi1_6/nf-dxgi1_6-idxgifactory6-enumadapterbygpupreference)、
[CoreML 提供程序选项](https://onnxruntime.ai/docs/execution-providers/CoreML-ExecutionProvider.html)、
[Apple CPU/GPU 策略](https://developer.apple.com/documentation/coreml/mlcomputeunits/cpuandgpu)。

## 托盘、自启和单实例实现

- 三系统关闭窗口均保留音频处理，通过托盘菜单“打开 / 退出”操作。
  `--background` 三系统通用，只有收到托盘已就绪事件才隐藏窗口。
  macOS 支持 Dock reopen 和 Cmd+Q 的正常退出处理。
- macOS / Linux 托盘辅助进程通过管道回传事件，只有 Tk 主线程操作主窗口。
  启动超时、进程崩溃、托盘服务消失会恢复窗口；父进程退出时管道 EOF 会终止辅助进程。
  macOS 辅助进程不创建额外 Dock 应用。主进程不加载 Qt。
- Linux 需要 StatusNotifier / AppIndicator 或 XEmbed 托盘。部分 GNOME 桌面需要扩展。
  X11 的 Qt 系统库安装命令见本文“安装与构建”；Wayland 下窗口能恢复显示，但前台焦点受合成器策略控制。
- 自启只写当前用户配置：Windows 的 Run 值、
  macOS `~/Library/LaunchAgents/io.openbroadcast.desktop.plist`、
  Linux `$XDG_CONFIG_HOME/autostart/openbroadcast.desktop`（默认 `~/.config/autostart/`）。
  不注册系统服务、不安装音频驱动、不创建 Linux 音频接线。
  配置在下次登录桌面时生效，系统登录项策略仍可禁用它；关闭选项不会结束当前运行。
- 启动参数保留虚拟环境解释器的符号链接路径，使用绝对程序路径；
  macOS 使用 plist 参数数组，Linux 遵循 Desktop Entry 的两层转义，不经过 shell。
  写入使用原子替换；移动目录 / 虚拟环境后需要重新开关自启，卸载前应关闭自启。
- POSIX 锁位于 macOS `~/Library/Caches/OpenBroadcast/instances/`、
  Linux `~/.cache/OpenBroadcast/instances/`，目录私有、文件禁止符号链接。
  主锁由内核持有，退出或崩溃后释放。激活计数由另一把锁保护，
  不丢失首次启动尚未创建 GUI 时收到的唤醒请求。
  不删除持锁文件，避免新进程通过另一个 inode 绕过原有锁。

## 音棚音效验证

音棚音效的当前源码验证（Windows，ONNX Runtime DirectML 1.24.4）：

- 音棚音效仅在麦克风侧提供，文件处理沿用麦克风所选效果；扬声器与其试听仅提供降噪和房间回声消除。
- 独立模型约 501 MB，使用标准 ONNX 算子，不加载 NVIDIA SDK 或 TensorRT。
- 与本机原版对照两段各 12 秒语音，连续独立状态输出 SNR 约 22–27 dB；
  生成式网络对累加精度差异敏感，不保证与原版逐位一致。
- 本轮相对上一版（已启用图融合和缓冲复用）：RTX 5090 两段各 12 秒语音、
  CPU 与 AMD 两段各 2 秒语音，各重复三轮，完整输出及重复重置均逐位一致。
  146 组浮点缓存的所有输入消费者原本就先转换到 FP16；把这一舍入移到缓存输出边界，
  以 FP16 保存缓存，权重与内部运算不变。包括计数器在内的 147 组有效状态已核对一致。
  双份缓存的张量数据由约 181.5 MB 减至 90.7 MB；这不是整个模型的显存用量，
  还存在权重、执行工作区及资源对齐开销。
- DirectML 保留主机侧最终 Tanh、半精度舍入和限幅，维持模型主体图融合。
  Windows x64 辅助模块在所选适配器上创建同一 D3D12 设备、DirectML 设备与命令队列，
  显式复用双份 GPU 状态、I/O 绑定和上传/回读缓冲；仅音频每块往返，循环状态留在显存。
  本机 NVIDIA 和 AMD 均已验证实际使用此路径，修复了 Python 独立 DML 分配器只能用
  adapter 0 的限制。Intel 尚未实机验证；CPU 和其他平台保留标准 ONNX Runtime 路径。
  辅助模块缺失、不受支持或首次预热失败时，会关闭资源并回退同一所选 GPU 的 Python ORT 路径；
  实时处理开始后的错误会正常上报。Python 回退路径仅在 adapter 0 使用独立绑定缓冲。
  48 kHz、480 样本接口的缓冲为 3360 样本（70 ms）；文件处理补齐尾部并去除该缓冲。
- 降噪和去混响复用输入、FFT 前后处理及重叠相加缓冲，不改变模型或运算精度；
  CPU、RTX 5090 与 AMD 核显的新旧输出均已验证逐位一致。
- RTX 5090 双声道独立缓存测试（4 秒）每个 80 ms 块中位约 19.0 ms，P95 约 21.8 ms。
  CPU 与本机 AMD 核显的音棚音效仍未达到实时速度；以上不是其他设备或多路并发性能保证。
- 重置、流式与整文件一致性、边界长度、双声道独立缓存，以及中英文两种布局已验证。
  真实设备长时间路由与其他平台仍需实机验收。

2026-10-22 本轮在 RTX 5090 上的性能对照（48 kHz 单声道，8 个推理线程）：下表单位为每 80 ms 音频的
平均处理毫秒数，由完整 12 秒流水线总耗时的中位数折算；越低越好，实时预算为 80 ms。
两段语音均使用独立连续状态，统一补齐 160 ms 尾部，计时包含音频前后处理和 GPU 同步，
不含模型加载。原生列调用本机 Broadcast 随附 SDK 和对应模型，不包含设备或虚拟声卡链路。

| 麦克风效果 | 本轮修改前 | 新版 | 本机原生 SDK |
| --- | ---: | ---: | ---: |
| 噪音消除 | 1.290 ms | 1.337 ms | 0.687 ms |
| 房间回声消除 | 1.321 ms | 1.325 ms | 0.693 ms |
| 回声消除 → 降噪 | 2.660 ms | 2.803 ms | 1.404 ms |
| 音棚音效 | 10.436 ms | 10.162 ms | 5.146 ms |

“本轮修改前”是上一轮已优化的实现。音棚新旧版使用同进程独立实例，交替 AB/BA，
每段语音各 3 轮；6 对中 4 对新版更快、2 对略慢，中位总耗时减少 2.63%，属于小幅收益。
音棚处理 12 秒的总耗时从 1.565 秒变为 1.524 秒，原生约 0.772 秒，
新版耗时仍约为原生的 1.97 倍。80 ms 窗口 P95 的跨轮中位数从 11.314 降至 10.828 ms。
前三种效果本轮未合入不稳定优化，表中前后差异来自不同测量批次的波动，不代表算法提速或回退。
原生每段也测 3 轮，每轮重建实例，避免测试中反复调用 SDK Reset 出现的状态异常；
重建与 reset 不计入处理时间，开启 CUDA Graph、读取输出前同步 GPU，并逐轮核对输出。
70 ms 缓冲延迟没有改变，以上耗时也不等于端到端通话延迟。

跨后端音棚补充验证（每段 2 秒语音、各 3 轮，同样补齐 160 ms 尾部）：

| 设备 | 修改前处理 2 秒音频 | 新版处理 2 秒音频 | 新版实时因子 |
| --- | ---: | ---: | ---: |
| Ryzen 7 9800X3D，8 线程 | 3.109 s | 2.938 s | 1.469 |
| AMD Radeon 核显 | 8.553 s | 7.729 s | 3.864 |

CPU 使用 AB/BA；AMD 使用独立进程、单会话常驻，两批相邻复测，耗时约减少 9.6%。
双模型同时驻留的压力测试会使 AMD 新版变慢至约 9.7 s / 2 s，因此不能拿共驻数据代表单路性能。
短样本的尾部补齐占比较高，不宜与 12 秒样本直接比较。CPU 和这块 AMD 核显仍不满足音棚实时速度。
其他三种效果在 CPU 和 AMD 上也完成复测，全部 24 项新旧完整波形比较逐位一致。
本轮通过 200 项现有回归测试中的 188 项，12 项按平台条件跳过；14 项性能提醒测试和
3 项启动回退测试全部通过。重置、流式/文件一致性、边界长度、双声道状态隔离及资源关闭通过验证；
项目外构建的 Windows 程序已实际验证 CPU、RTX 和 AMD 三模型推理及界面/托盘，
两块 GPU 均启用新模块且无初始化回退。

### 耗时拆分与辅助模块

可选 `NativeDmlSession(..., profile=True)` 通过 `last_timing` 返回每次调用的 CPU 分段及
D3D12 GPU 时间戳；默认关闭时间戳查询。下面为同一生产模型和 DLL、单会话、8 个推理线程、
20 块实音预热后连续 60 块的中位数，每块 80 ms 音频，单位 ms：

| 分段 | RTX 5090 | AMD Radeon 核显 |
| --- | ---: | ---: |
| CPU 准备并提交上传 | 0.0581 | 0.0809 |
| CPU 提交推理及回读 | 0.2924 | 0.6154 |
| CPU 等待完成 | 9.2227 | 284.9923 |
| CPU 回读复制 | 0.0007 | 0.0010 |
| 辅助模块调用总计 | 9.6545 | 285.6502 |
| GPU 上传 | 0.0011 | 0.0018 |
| GPU 推理队列区间 | 9.5243 | 285.3982 |
| GPU 下载 | 0.0020 | 0.0015 |

辅助模块调用总计 P95 分别为 10.5760 / 287.7103 ms，不包括 Python 音频队列与最终激活。
GPU 推理区间可能包含等待 CPU 提交的空隙，不代表活跃算子时长之和；CPU 与 GPU 区间重叠，
不能相加，各分段的中位数也不能相加得到总计。音频传输开销已经很小，剩余差距主要在模型执行。

其他效果也进行了前后处理与推理拆分：RTX 的降噪/去混响推理约占 68%，AMD 约占 97%。
高线程数串联场景关闭线程自旋或共用线程池可以提速，但会拖慢默认线程数及单效果，
因此未作为全局策略合入；预录制拷贝命令也未得到稳定收益。本轮保留模型权重、内部运算精度和效果强度。

辅助模块源代码与交付 DLL 位于 `src/openbroadcast/audio/native/`，仅使用标准 D3D12/DirectML
和安装包内同版本 ORT C API，不增加 CUDA、TensorRT 或厂商专有依赖。
Windows x64 构建需要 Visual Studio C++ 工具及含 DirectML.h 的 Windows SDK；可在项目根目录运行：

```powershell
.\packaging\windows\build_explicit_dml.ps1 `
  -Source .\src\openbroadcast\audio\native\explicit_dml.cpp `
  -Output .\src\openbroadcast\audio\native\explicit_dml.dll
```

脚本按 SHA-256 校验 ORT 1.24.4 头文件，默认将下载和编译中间文件放到系统临时目录，
项目内只更新指定 DLL。PyInstaller 同时收集该模块和 ORT 的 `onnxruntime.dll`、`DirectML.dll`；
`--check-runtime` 报告音棚实际是否启用此路径、所选适配器及初始化回退原因。

## 音频接线

Windows 和 macOS 使用用户自行安装的 [VB-CABLE](https://vb-audio.com/Cable/)。
官方提供 Windows、macOS Intel / Apple Silicon 安装包，以及两系统的 A+B / C+D 独立音频线。
Linux 由用户自行配置 PipeWire / PulseAudio 等路由，程序不自动创建或连接虚拟设备。

按设备用途选择：OpenBroadcast 麦克风输出连接虚拟线播放端，通话软件从同一条线录音端收音。
扬声器路由反向连接：通话软件向另一条线播放，OpenBroadcast 读取后输出到真实耳机。
Windows 名称通常为 `CABLE Input` / `CABLE Output`；macOS 名称可能相同，需按录音 / 播放方向选择。
两路同时运行不能复用同一条虚拟线，避免反馈。macOS 使用“音频 MIDI 设置”检查 48 kHz，
并授予启动应用麦克风权限。

## 自动化与实机验收

`.github/workflows/compatibility.yml` 构建同一份 wheel，分别在 Windows、macOS Apple Silicon、
macOS Intel、Ubuntu 上安装测试，Windows 额外测试最低 Python 3.11。
Linux 使用 Xvfb、隔离 D-Bus 和 trayer；CI 要求 Tk 能成功创建窗口，不将缺失显示环境默认为通过。
原生托盘测试覆盖 Qt 初始化、托盘服务消失、父进程管道关闭、无托盘环境的降级。
macOS 原生下拉菜单不暴露 Tcl listbox，因此四项针对 Windows / X11 popdown 内部结构的
GUI 测试在 Aqua 上跳过。真实菜单交互需要 macOS 手工验收。

`packaging/check_installed.py` 用 `python -I` 在源码目录之外执行，检查：

- 导入路径确实位于 site-packages，而非被源码目录掩盖；
- 控制台 / GUI 入口、版本、模型哈希及打包资源；
- 三个模型分别执行真实 CPU 推理；
- 双声道 FLAC 经过两级模型后写出 WAV，帧数、采样率和数值有效；
- Tk、PortAudio 和 libsndfile 可以加载。

本次本地验证结果：

| 检查 | 结果 |
| --- | --- |
| sdist 构建及从 sdist 构建 wheel | 通过 |
| Twine 严格元数据 / README 检查 | 通过 |
| 全新 Windows 虚拟环境 pip 安装及 `pip check` | 通过 |
| Windows 桌面完整测试（含 Windows 托盘回归） | 200 项：188 通过，12 项平台条件跳过 |
| Ubuntu 24.04 WSL / Xvfb / trayer 完整测试 | 200 项：198 通过，Windows / macOS 原生测试各跳过 1 项 |
| Linux 原生托盘：正常启动、托盘服务丢失、管道 EOF、无托盘降级 | 全部通过 |
| Linux 并发实例争用、唤醒计数、进程崩溃后重新取得锁 | 全部通过 |
| Linux 自启 Exec 特殊路径经真实 GIO 桌面启动器执行 | 通过 |
| macOS LaunchAgent 参数、原子写入、禁用、路径保留 | 自动化验证通过；待实际登录验收 |
| 已安装 wheel 的独立入口、模型和双声道文件处理检查 | 通过 |
| 已安装 wheel 的 Tk 界面、设置、设备枚举、原生托盘及退出检查 | 通过 |
| 两模型在 CPU、NVIDIA RTX 5090 DirectML、AMD Radeon DirectML 上推理 | 全部通过 |
| 默认 GPU 选择与 CLI 自动推理 | Windows 选中 RTX 5090；WSL 无受支持 GPU 时使用 CPU，均通过真实推理 |
| macOS CoreML 自动选择 / CPUAndGPU 参数 / 界面说明 | 模拟验证通过；原生两模型测试已加入，待 Mac 执行 |
| macOS Intel / Apple Silicon、Linux x64 / ARM64 的 CPython 3.12 二进制依赖解析 | 通过，仅安装条件检查 |

依赖解析使用目标平台 wheel 标签；Intel Mac 选择 ONNX Runtime 1.23.2，
Apple Silicon 和 Linux 选择 1.31.0。此结果是当日的安装候选，不是固定依赖锁定，
也不是在这些系统上成功启动的证据。Linux 按 glibc 2.35 及其兼容标签检查，不包含 Alpine / musl。

自动化音频路由测试使用模拟设备，不替代真实麦克风 / 耳机 / VB-CABLE 验收。
GitHub CI 配置尚需提交后执行；macOS 目前只有配置 / 控制流测试，仍需原生桌面验收。
发布前应分别验证：
设备枚举、48 kHz 接线、两路同时处理、录音试听、权限拒绝、热拔插、长时间运行的丢帧和延迟。
三个系统均需在实际登录会话验收自启、托盘打开 / 退出和重复启动唤醒；
macOS 另验菜单栏与 Dock，Linux 另验目标桌面及 Wayland / X11 差异。

## 发行状态

发行入口为 [GitHub Releases](https://github.com/divingclone/openBroadcast/releases)，
提供 Windows 便携 ZIP、Python wheel 和源码发行包。wheel 可下载后直接用 pip 安装，
也可用 `python -m pip install "git+https://github.com/divingclone/openBroadcast.git"` 从源码安装。
当前不通过 PyPI 分发。

仓库没有项目 LICENSE，也没有单独的模型再分发许可文件；
`src/openbroadcast/audio/denoiser.py` 明确记载模型权重提取自 NVIDIA Broadcast。
因此没有为整个发行包擅自声明 MIT 等许可证；公开发行前需要项目所有者确认源码及模型的再分发许可。
这与本地打包、安装和功能验证是不同的检查项。

参考：[DirectML 发行文件](https://pypi.org/project/onnxruntime-directml/1.24.4/)、
[sounddevice 系统依赖](https://python-sounddevice.readthedocs.io/en/latest/installation.html)、
[PyPI 文件限制](https://docs.pypi.org/project-management/storage-limits/)、
[GitHub 原生 runner](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)。
桌面集成依据：[Apple LaunchAgent](https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/CreatingLaunchdJobs.html)、
[XDG Autostart](https://specifications.freedesktop.org/autostart/latest/)、
[Desktop Entry Exec](https://specifications.freedesktop.org/desktop-entry/latest/exec-variables.html)、
[Qt 系统托盘](https://doc.qt.io/qtforpython-6/PySide6/QtWidgets/QSystemTrayIcon.html)。
