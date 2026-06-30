# EVB 通信质量监测上位机

基于 PyQt6 的 EVB 通信芯片测试上位机，支持串口通信、批量 CSV 测试、符号 BER 分析和实时 SNR/质量监测。

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
cd %USERPROFILE%\Desktop\evb-comm-tool
run.bat
```

首次运行若缺少 `.venv`，`run.bat` 会自动调用 `setup.bat` 完成环境配置。

**首次仅配置环境（可选）：**

```cmd
cd %USERPROFILE%\Desktop\evb-comm-tool
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
cd %USERPROFILE%\Desktop\evb-comm-tool

# 1. 创建虚拟环境
py -m venv .venv

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
cd %USERPROFILE%\Desktop\evb-comm-tool
run.bat
```

**直接命令（不依赖任何脚本）：**

```cmd
cd %USERPROFILE%\Desktop\evb-comm-tool
.\.venv\Scripts\python.exe main.py
```

在 PowerShell 中同样可用上述两条命令（`run.bat` 不受执行策略限制）。

### 依赖列表

| 包 | 版本 |
|----|------|
| PyQt6 | 6.7.1 |
| pyqtgraph | 0.13.7 |
| pyserial | 3.5 |
| numpy | >= 2.2.0 |

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
| 已连接但发送无回复 | 1. 确认波特率 **115200**、校验 **无(N)**、停止位 **1**（默认 8N1）<br>2. 确认 TX/RX 接线正确<br>3. 查看接收面板日志是否有 `[错误] 接收超时` |
| 状态栏一直显示「未连接」 | 必须手动选择 COM 口后点击 **「连接」**；插入 USB 不会自动连接 |

**连接步骤（必做）：**

1. 插入 USB 串口，等待下拉框出现 COM 口（如 `COM3 - USB-SERIAL CH340`）
2. 选择正确的 COM 口
3. 点击 **「连接」** — 状态栏应变为绿色 **「已连接 COMx @ 115200 bps」**
4. 点击 **「发送单帧」** 测试通信

**命令行检查 COM 口（可选）：**

```cmd
.\.venv\Scripts\python.exe -c "from comm.port_utils import list_com_ports; print(list_com_ports())"
```

## 快速开始

```cmd
cd %USERPROFILE%\Desktop\evb-comm-tool
run.bat
```

若 `.venv` 尚未创建，先运行 `setup.bat`，再运行 `run.bat`。

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

输出电压换算: `(raw / 4096) × 5.0 × (-1.25) V`

**示例 RX:**
```
02 09 30 0B 6F 05 27 05 7E 05 1F 03 F0 00 00 0B 20
```

### 错误重传

- 若任一路输出原始值 `< 0x1FF` (511)，自动重发当前帧
- 最大重试次数可配置（默认 3 次）
- 接收超时可配置（默认 500 ms）

## 串口默认参数

| 参数 | 默认值 |
|------|--------|
| 波特率 | 115200 |
| 数据位 | 8 |
| 校验位 | 无 (N) |
| 停止位 | 1 |

所有参数均可在界面工具栏修改。

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

### 期望符号 (BER) 逻辑

- **符号 BER**: 仅比较测量电压与期望值的**正负号**，符号一致即判定正确
- 若 CSV 含 `exp_sign` 列，直接使用
- 若无 `exp_sign` 列，按优先级使用:
  1. 界面「默认期望符号」配置（逗号分隔，如 `+1,-1,+1,-1,+1,-1,+1,-1`）
  2. 从输入通道 ch1-ch8 推断（raw > 2048 → +1，raw < 2048 → -1，= 2048 → 0）

### 示例文件

- `data/sample_test.csv` — 10 组示例（含用户协议样例）
- `data/sample_test_1000.csv` — 运行生成脚本获得 1000 组演示数据:

```powershell
.\.venv\Scripts\python.exe data/generate_sample.py
```
## 界面布局

```
┌─────────────────────────────────────────────────────────────────┐
│  工具栏: COM端口 | 波特率 | 校验 | 停止位 | 超时 | 重试 | 连接   │
├──────────────────────────────┬──────────────────────────────────┤
│ ① 发送面板                  │ ③ SNR / 质量                      │
│  - 12 通道输入表            │  - 实时 SNR 曲线                  │
│  - TX 帧 HEX 预览           │  - 通道质量柱状图                  │
│  - 加载 CSV / 发送单帧      │  - 重试次数、成功率                │
├──────────────────────────────┼──────────────────────────────────┤
│ ② 接收面板                  │ ④ BER / 统计                      │
│  - 带时间戳 HEX 日志        │  - 符号 BER / 帧错误率             │
│  - 8 路输出解析 + 电压      │  - 低值重试统计                    │
│  - 迭代计数高亮             │  - 导出 CSV 报告                   │
└──────────────────────────────┴──────────────────────────────────┘
```

## 批量测试流程

1. 连接串口
2. 加载 CSV 测试文件
3. 点击「开始测试」
4. 每组: 构建 TX 帧 → 发送 → 等待 RX (17 字节) → 校验/重试 → 更新统计
5. 完成后可导出报告至 `reports/` 目录

## 项目结构

```
evb-comm-tool/
├── main.py                 # 入口
├── requirements.txt
├── setup.ps1 / setup.bat   # 一键环境配置
├── run.ps1 / run.bat       # 一键启动
├── csv_loader.py           # CSV 加载├── protocol/
│   ├── codec.py            # 帧编解码
│   └── validator.py        # 重传校验
├── comm/
│   └── serial_worker.py    # 串口 QThread 工作线程
├── analysis/
│   ├── ber.py              # 符号 BER
│   └── snr.py              # SNR / 稳定性
├── ui/
│   └── main_window.py      # 主界面
├── data/
│   ├── sample_test.csv
│   └── generate_sample.py
└── reports/
```

## 日志格式

```
[HH:MM:SS.mmm]发送→AA 0D AC 0D ...
[HH:MM:SS.mmm]接收←02 09 30 0B ...
```

## 假设与说明

1. **串口参数**: 默认 115200 8N1，可在 UI 完全配置
2. **符号 BER**: 不要求电压精确值，仅判正负（死区 ±0.05V 内视为 0）
3. **SNR**: 有参考值时计算 SNR(dB)；无参考值时显示信号稳定性（均值/标准差）
4. **Windows COM**: 通过 `pyserial` 自动枚举 COM 端口，点击「刷新」更新列表
5. **无硬件测试**: 未连接 EVB 时仍可编辑通道、预览 TX 帧、加载 CSV
