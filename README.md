# EVB 通信质量监测上位机

基于 PyQt6 的 EVB 通信芯片测试上位机，支持串口通信、批量 CSV Sim-to-Real 测试与 BER/迭代曲线分析。

**EVB** = **E**valuation **B**oard（评估板）：本项目所测 Turbo 通信译码芯片的评估硬件平台；`evb-comm-tool` 为 PC 端与之 UART/AA 协议通信的上位机。

### 文档入口

| 读者 | 文档 |
|------|------|
| **操作人员** | [docs/软件使用手册.md](docs/软件使用手册.md) — 四标签页/串口/批量/三份 Excel/监测/`run_lite.bat` |
| **入门故事（师傅带徒弟）** | [docs/师傅带徒弟_代码故事.md](docs/师傅带徒弟_代码故事.md) — 每个模块对应什么需求、什么技术，通俗漫画风 |
| **学架构 / SE** | [docs/软件工程视角与VibeCoding重建实验.md](docs/软件工程视角与VibeCoding重建实验.md) — 分层、重发、result→ok→ber 流程图、课程切片 |
| **协议 / 公式 / 二次开发** | [PROTOCOL_UART.md](docs/PROTOCOL_UART.md) · [SIM_TO_REAL.md](docs/SIM_TO_REAL.md) · [CODE_GUIDE.md](docs/CODE_GUIDE.md) |
| **从零搭建清单** | [docs/EVB通信工具_代码需求书.md](docs/EVB通信工具_代码需求书.md)（精简规格索引；细节以上述文档与现码为准） |

**硬件 / PCB（与上位机软件解耦）**： [PCB大阵列拼接评估需求说明.md](docs/PCB大阵列拼接评估需求说明.md) · [44x76阵列物理评估.md](docs/44x76阵列物理评估.md) · [RRAM阵列_PCB_IO信号说明.md](docs/RRAM阵列_PCB_IO信号说明.md) · [嘉立创_原理图与PCB设计指导书.md](docs/嘉立创_原理图与PCB设计指导书.md) · [AD_原理图与PCB设计指导书.md](docs/AD_原理图与PCB设计指导书.md)

**打包分发**见 [DISTRIBUTE.md](DISTRIBUTE.md)（zip 不含 `.venv`，对方解压后双击 `run.bat` 即可）。  
**多机私密 GitHub 同步**（2026-07-17 审计）：见 [DISTRIBUTE.md §多机同步](DISTRIBUTE.md#多机同步github-私密仓库--2026-07-17)。

## 环境配置

本项目推荐使用 **Python 虚拟环境**，避免依赖装到全局 Python 或 PATH 未配置导致无法运行。

### 前置要求

- **Python 3.10+**（推荐 3.12 / 3.13；当前已在 Python 3.14 验证）
- Windows 10/11

### 检查 Python 是否可用

在 PowerShell 或 cmd 中依次尝试：

```powershell
py --version
python --version
python3 --version
```

**说明：** 很多 Windows 机器只有 `py` 启动器可用，`python` 可能不在 PATH 中。后续命令统一使用 `.venv\Scripts\python.exe`，不依赖全局 `python` 命令。

### 方式一：一键脚本（推荐，Windows）

**首选 `run.bat`** — 不依赖 PowerShell 执行策略，在 **cmd 和 PowerShell 中均可直接运行：

```cmd
cd <项目目录>
run.bat
```

首次运行若缺少 `.venv`，`run.bat` 会自动调用 `setup.bat` 完成环境配置（优先 `py -3`，其次 `py` / `python` / `python3`）。

**首次仅配置环境（可选）：**

```cmd
cd <项目目录>
setup.bat
```

> **PowerShell 执行策略提示：** 若运行 `.\run.ps1` 报错  
> *「无法加载文件 … 因为在此系统上禁止运行脚本」*  
> 这是 Windows 默认安全策略，**无需修改系统设置**。请改用上面的 **`run.bat`**，或使用下方「直接命令」。

**可选 — 临时绕过执行策略运行 ps1：**

```powershell
powershell -ExecutionPolicy Bypass -File .\run.ps1
```

### 方式二：手动配置

```powershell
cd <项目目录>

# 1. 创建虚拟环境
py -3 -m venv .venv

# 2. 升级 pip
.\.venv\Scripts\python.exe -m pip install --upgrade pip

# 3. 安装依赖
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 4. 验证（可选）
.\.venv\Scripts\python.exe -c "import protocol.codec; import ui.main_window; print('OK')"
```

### 启动应用

**推荐（Windows）：**

```cmd
cd <项目目录>
run.bat
```

**直接命令（不依赖任何脚本）：**

```cmd
cd <项目目录>
.\.venv\Scripts\python.exe main.py
```

在 PowerShell 中同样可用上述两条命令（`run.bat` 不受执行策略限制）。

### 依赖列表

| 包 | 版本 |
|----|------|
| PyQt6 | 6.7.1 |
| matplotlib | >= 3.8.0 |
| pyserial | 3.5 |
| numpy | >= 2.2.0 |
| pandas / openpyxl | 可选，Excel 报告导出 |

### 常见问题

| 问题 | 解决方法 |
|------|----------|
| `'python' 不是内部或外部命令` | 使用 `py` 创建 venv，或安装 Python 时勾选 **Add to PATH** |
| `'pip' 不是内部或外部命令` | 使用 `py -m pip` 或 `.venv\Scripts\python.exe -m pip` |
| numpy 安装失败 / 编译错误 | 确保 pip 已升级；Python 3.14 需 numpy >= 2.2（已提供预编译 wheel） |
| PowerShell 禁止运行 `.ps1` 脚本 | **无需改策略**，直接运行 `run.bat`；或 `powershell -ExecutionPolicy Bypass -File .\run.ps1` |

### 串口没反应 / 无法连接

| 现象 | 排查步骤 |
|------|----------|
| 下拉框显示「未检测到 COM 口」 | 1. 确认 USB 线已插好<br>2. 打开 **设备管理器 → 端口 (COM 和 LPT)** 查看是否出现 COM 口<br>3. 若无 COM 口，安装对应 USB 转串口驱动（**CH340** / **CP2102** / **FTDI**）<br>4. 点击工具栏 **「刷新端口」**（未连接时每 1.5 秒也会自动刷新） |
| 有 COM 口但连接失败 | 1. 关闭占用串口的其他程序（Arduino IDE、串口助手、PuTTY 等）<br>2. 重新拔插 USB<br>3. 在设备管理器中确认 COM 口号，在下拉框选择 **COM3 - 描述** 这类带描述的项 |
| 已连接但发送无回复 | 1. 确认波特率 **9600**、8N1（界面固定显示）<br>2. 确认 TX/RX 接线正确<br>3. 查看日志是否有 `接收超时` 或 `未收敛` |
| 状态栏一直显示「未连接」 | 必须手动选择 COM 口后点击 **「连接」**；插入 USB 不会自动连接 |

**连接步骤（必做）：**

1. 插入 USB 串口，等待下拉框出现 COM 口（如 `COM3 - USB-SERIAL CH340`）
2. 选择正确的 COM 口
3. 点击 **「连接」** — 串口配置区应显示绿色 **「● 已连接」**
4. 点击 **「▶ 运行当前」** 测试通信（可先编辑发送区 12 通道 DAC 值）

**命令行检查 COM 口（可选）：**

```cmd
.\.venv\Scripts\python.exe -c "from comm.port_utils import list_com_ports; print(list_com_ports())"
```

## 快速开始

```cmd
cd <项目目录>
run.bat
```

若 `.venv` 尚未创建，`run.bat` 会自动运行 `setup.bat`；也可手动先执行 `setup.bat`。


## 协议说明

### 发送帧 (主机 → EVB)，34 字节

| 字节 | 说明 |
|------|------|
| 0 | 帧头 `0xAA` |
| 1 | 命令字节 |
| 2-25 | 12 通道，每通道 2 字节大端序 12-bit 原始值 |
| 26-33 | 固定尾部 `09 C4 09 C4 09 C4 0F A0` |

通道电压换算: `(raw / 4096) × 4.096 V`

**示例 TX:**
```
AA 0D AC 0D AC 07 72 06 B6 09 C4 05 DC 0D AC 0C 54 09 C4 09 C4 09 C4 0F A0
```

### 接收帧 (EVB → 主机)，17 字节

| 字节 | 说明 |
|------|------|
| 0 | 迭代计数 |
| 1-16 | 8 路输出，每路 2 字节大端序 12-bit 原始值 |

输出列电流换算: `I_col = ((raw / 4096) × 5 − 2.5) × (−1)`（XXX=12-bit ADC raw；见 docs/SIM_TO_REAL.md）

**示例 RX:**
```
02 09 30 0B 6F 05 27 05 7E 05 1F 03 F0 00 00 0B 20
```

### 错误重传

- 若回传 **CH1–8 任一路** 原始值 `< 0x2FF` (767)，自动重发当前帧
- 最大重试次数可配置（默认 5 次重发）
- 接收超时可配置（默认 500 ms）

## 串口默认参数（8N1）

| 参数 | 默认值 |
|------|--------|
| 波特率 | 9600 |
| 数据位 | 8 |
| 校验位 | 无 (N) |
| 停止位 | 1 |

波特率、超时与重试次数可在界面修改；数据位/校验/停止位固定为 **8N1**。

## CSV 测试文件格式

```csv
group_id,cmd,ch1,ch2,ch3,ch4,ch5,ch6,ch7,ch8,ch9,ch10,ch11,ch12,exp_sign1,exp_sign2,exp_sign3,exp_sign4,exp_sign5,exp_sign6,exp_sign7,exp_sign8
```

| 列名 | 说明 |
|------|------|
| `group_id` | 测试组编号 |
| `cmd` | 命令字节，支持十进制或 `0x` 十六进制 |
| `ch1` ~ `ch12` | 12 通道原始值，范围 0-4095 |
| `exp_sign1` ~ `exp_sign8` | 可选，期望输出符号: `+1`、`-1` 或 `0` |

### 期望符号与比特误码率 (BER)

- **比特 BER**：对 RX 12-bit ADC 做硬判决（`raw > 2048 → 0`，否则 `1`），与 CSV `exp_sign` 反推的 ground truth 比特比较
- 期望比特：`u = (1 - exp_sign) / 2`（BPSK：`+1→0`，`-1→1`）
- 若 CSV 含 `exp_sign` 列，直接使用；`exp_sign=0` 的通道不参与 BER 分母
- 若无 `exp_sign` 列，按优先级使用界面「默认期望符号」或从 ch1–ch8 输入 raw 推断（精度较低）

### 示例文件

- `data/测试集/` — 源测试 CSV（加载用）
- `data/测后数据集/YYYY-MM-DD/` — 按日期存放的测后 CSV + 三份 Excel

测试向量格式见 [docs/SIM_TO_REAL.md](docs/SIM_TO_REAL.md)。

界面按 `DAC测试GUI_编程规范.md` 实现，采用 **双标签页** 布局：

- **测试执行** — 串口配置、用例列表、12 通道发送 / 8 通道接收、控制按钮、日志
- **可视化分析** — BER-SNR 曲线、平均迭代次数-SNR 曲线、电压解码表（口径见 [docs/SIM_TO_REAL.md](docs/SIM_TO_REAL.md)）

```
┌──────────────────────────────────────────────────────────────────┐
│  [串口配置] 端口 | 波特率 | 连接/断开/刷新 | 状态                │
├────────────┬───────────────────────┬──────────────────────────────┤
│ 单帧测试区 │  发送 (12通道)         │  接收 (8通道)                 │
│ 批量测试区 │  ΔV / DAC / hex       │  ΔV / DAC / 正负对 / hex     │
│ (CSV 后显) │                       │                              │
├────────────┴───────────────────────┴──────────────────────────────┤
│  hex 收发 | 协议解析 | 日志                                        │
│  批量区: [▶▶ 运行全部] [■ 停止] [📊 导出报告]                       │
└──────────────────────────────────────────────────────────────────┘
```

## 批量测试流程

测试向量格式见 [docs/SIM_TO_REAL.md](docs/SIM_TO_REAL.md)。默认数据集在 `data/测试集/`（如 `mode1.csv`）。

1. （可选）单帧 A1 黄金抓包联调确认收发正常
2. 连接串口
3. 点击 **「加载 CSV」** → 选择 `data/测试集/` 下的源文件
4. 点击 **「▶▶ 运行全部」**（批量期间 UI 节流，结束后刷新图表）
5. 每组: 构建 TX 帧 → 发送 → 等待 RX (17 字节) → CH1–8 raw≥0x2FF 收敛重试（最多 5 次重发）→ 符号比对；每次尝试写入 CSV `Attempt` 列（1, 2, …）；**BER 仅统计最终收敛帧**（raw < 0x2FF 不计入）。
6. 批量结束后导出测后 CSV 到 `data/测后数据集/YYYY-MM-DD/`，并**固定生成三份 Excel**（后台写入，日志提示写完）：
   - ① `{stem}_result_{时间}.xlsx`：完整记录（含通信错误帧与全部 Attempt）
   - ② `{stem}_result_{时间}_ok.xlsx`：最终失败 → 仿真行+Attempt1..N **整套删除**；最终成功 → 只留收敛 Attempt（无 Out≈2.5）
   - ③ `{stem}_result_{时间}_ber.xlsx`：在②上只留 CodeBit≠仿真 的行，误码通道 CodeBit+Out 粉红高亮
7. **仿真 CodeBit 自动监测**：加载时快照；测后导出比对。详见 [docs/软件使用手册.md](docs/软件使用手册.md)。
8. 切换到 **「可视化分析」** 查看 BER-SNR / 迭代次数曲线
9. 点击 **「📊 导出报告」** 导出 Excel 或 CSV（含 Attempt 列与行背景色）

## 项目结构

```
evb-comm-tool/
├── main.py
├── csv_loader.py
├── protocol/               # 编解码、0x2FF
├── comm/serial_worker.py   # 串口 QThread、多 Attempt
├── analysis/               # 比对、聚合、三份 Excel、CodeBit 监测
├── ui/                     # 主界面、图表、perf_settings
├── data/
│   ├── 测试集/             # 源测试 CSV
│   └── 测后数据集/YYYY-MM-DD/  # 按日期存放测后结果
├── docs/                   # 使用手册 / SE 视角 / PROTOCOL / SIM_TO_REAL / CODE_GUIDE
└── scripts/                # 冒烟与验收脚本
```

## 日志格式

单帧测试输出详细 TX/RX 解析；**批量测试仅输出起止摘要**（避免 7000 帧刷屏阻塞 UI）。
