# 分发与便携运行说明

本文说明如何将 **evb-comm-tool** 打包发给他人，以及在任意 Windows 电脑上解压后直接运行。

## 打包方（你）

### 方式一：一键打包（推荐）

在项目根目录双击或运行：

```cmd
pack.bat
```

会在**上一级目录**生成 `evb-comm-tool_YYYYMMDD_HHMMSS.zip`。

### 方式二：手动 zip

将整个 `evb-comm-tool` 文件夹压缩为 zip，**务必排除**以下内容：

| 排除项 | 原因 |
|--------|------|
| `.venv/` | 虚拟环境绑定本机 Python 路径，换电脑必坏 |
| `.git/` | 版本历史，非运行所需 |
| `__pycache__/`、`*.pyc` | Python 缓存 |
| `.pytest_cache/`、`build/`、`dist/` | 构建/测试缓存 |
| `data/*_result_*.csv`（可选） | 本地测试结果，体积大且与对方无关 |
| `*.zip` | 避免嵌套旧包 |

**应包含：** 源码、`requirements.txt`、`setup.bat`、`run.bat`、`run.ps1`、`pack.bat`、`data/*.csv`（测试用例）、`docs/`、`reports/.gitkeep` 等。

## 接收方（同事）

### 前置要求

- Windows 10/11
- 已安装 **Python 3.10+**（[python.org](https://www.python.org/downloads/)，安装时勾选 **Add python.exe to PATH**）

### 三步运行

1. **解压** zip 到任意目录（路径可含中文，建议不要放在需要管理员权限的目录）
2. **进入**解压后的 `evb-comm-tool` 文件夹
3. **双击 `run.bat`**

首次运行会自动调用 `setup.bat`：创建本机 `.venv`、安装依赖（约 1–3 分钟）。之后再次启动只需双击 `run.bat`。

**弱机 / 换机卡顿：** 请改用 **`run_lite.bat`**（启用 `EVB_UI_LITE=1`）。说明见 [docs/软件使用手册.md](docs/软件使用手册.md) §7。

也可先手动配置再启动：

```cmd
setup.bat
run.bat
```

### 串口

- 程序**不会**写死 COM 口；插入 USB 串口后在下拉框选择对应端口（如 `COM3 - USB-SERIAL CH340`），再点「连接」。
- 若无 COM 口，安装 CH340 / CP2102 / FTDI 驱动后点「刷新端口」。

## 常见问题

| 现象 | 处理 |
|------|------|
| 提示未找到 Python | 安装 Python 3.10+ 并加入 PATH，或确认 `py --version` 可用 |
| `.venv` 来自旧电脑无法运行 | 删除 `.venv` 文件夹后重新运行 `run.bat` 或 `setup.bat` |
| 依赖安装慢或失败 | `setup.bat` 会先尝试清华镜像，失败则自动改用官方 PyPI |
| PowerShell 禁止运行 `.ps1` | 直接使用 **`run.bat`**，无需改执行策略 |
| 换机后界面卡、启动慢 | 用 **`run_lite.bat`**；确认未拷贝旧 `.venv`；见使用手册 §7 |

## 技术说明

- 所有启动脚本使用 `%~dp0` / `$PSScriptRoot`，**无**硬编码 `C:\Users\...` 路径。
- `main.py` 若检测到项目内 `.venv`，会用相对路径 relaunch 到虚拟环境 Python。
- `.venv` 已在 `.gitignore` 中，不应提交到 git，也不应打进 zip。

---

## 多机同步（GitHub 私密仓库）— 2026-07-17

目标：多台 Windows 电脑保持**同一最新源码**；每台各自 `setup.bat` 建本地 `.venv`，**不要**拷贝虚拟环境。

### 可移植性结论（现码审计）

| 项 | 状态 | 说明 |
|----|------|------|
| 路径可移植 | ✅ | `run.bat` / `setup.bat` / `pack.bat` 均相对 `%~dp0` |
| 他机自建环境 | ✅ | 无 `.venv` 时 `run.bat` 自动跑 `setup.bat`；坏 `.venv` 会重建 |
| 依赖清单 | ✅ | `requirements.txt`（PyQt6 / pyserial / numpy / matplotlib / openpyxl） |
| 镜像回退 | ✅ | 先清华 PyPI，失败再官方源 |
| 串口不写死 | ✅ | 运行时选 COM |
| `.venv` 不入库 | ✅ | `.gitignore` |
| 测后大数据不入库 | ✅ | `data/测后数据集/`、`*_result_*` 已忽略 |
| zip 分发 | ✅ | `pack.bat` 排除 `.venv` / `.git` / 缓存 |

**前置（每台电脑）：** Windows 10/11 + **Python 3.10+**（安装勾选 Add to PATH）。

### 与「zip 发给同事」的区别

| 方式 | 适合 | 同步手段 |
|------|------|----------|
| **GitHub 私密仓** | 你自己多台电脑、持续开发 | `git pull` / `git push` |
| **pack.bat zip** | 给无 git 的同事临时试用 | 发 zip → 解压 → `run.bat` |

### 当前仓库注意（推送前必看）

1. 远程已配置：`origin` → `https://github.com/AllenXu-weihao/evb-comm-tool.git`
2. 本地相对 `origin/main` 有**大量未提交改动**（源码 + docs + UI）。**不提交就 push，另一台电脑拿不到这些功能。**
3. `data/` 根目录测试 CSV 体积可达数百 MB；建议入库以 **`data/测试集/`** 为主，避免根目录与测试集重复大文件。测后结果**不要**提交。
4. 请在 GitHub 网页确认仓库为 **Private**。公开仓会暴露测试集与内部文档。

### 电脑 A（有最新代码）— 首次推满

```cmd
cd <项目目录>
git status
git add -A
git status
REM 确认没有 .venv、测后数据集、巨大无关 zip
git commit -m "Sync: portable host app, docs, and testset layout"
git push -u origin main
```

若 GitHub 网页仍是 Public：Settings → Change visibility → **Make private**。

### 电脑 B（新电脑）— 拉取并自建环境

```cmd
git clone https://github.com/AllenXu-weihao/evb-comm-tool.git
cd evb-comm-tool
run.bat
```

首次会建 `.venv` 并装依赖（需联网，约 1–3 分钟）。

### 日常多机同步

**下班前（改过代码的电脑）：**

```cmd
git add -A
git commit -m "简述今天改了什么"
git push
```

**上班后（另一台电脑）：**

```cmd
git pull
run.bat
```

若 `pull` 后依赖有变（`requirements.txt` 更新）：

```cmd
setup.bat
run.bat
```

### 冲突与坏环境

| 现象 | 处理 |
|------|------|
| `git pull` 冲突 | 先 `git status`；源码冲突需手工合并；勿把本机测后 CSV 强行推进仓 |
| 换机后 `.venv` 报错 | 删掉 `.venv` 再 `run.bat` / `setup.bat` |
| 推送要登录 | GitHub Desktop，或 Personal Access Token；勿把 token 写进仓库 |
| 弱机卡顿 | 用 `run_lite.bat` |

### 建议提交 / 不要提交

| 建议提交 | 不要提交 |
|----------|----------|
| `*.py`、`ui/`、`analysis/`、`comm/`、`protocol/` | `.venv/` |
| `requirements.txt`、`setup.bat`、`run.bat`、`pack.bat` | `data/测后数据集/`、`*_result_*` |
| `docs/`、`DISTRIBUTE.md`、`README.md` | `reports/*.xlsx`（本地报告） |
| `data/测试集/` 下需要的源 CSV | 整仓重复的超大 CSV 副本（能删则删） |
| `scripts/test_*.py` | `*.zip`、`.cursor/` |

### 自检清单（换机后 5 分钟）

1. `py --version` 或 `python --version` ≥ 3.10  
2. `run.bat` 能启动窗口  
3. 「刷新端口」能看到串口（驱动另装）  
4. `git pull` 后功能与文档与另一台一致  

---

*本节更新：2026-07-17。*