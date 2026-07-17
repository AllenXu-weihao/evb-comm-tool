# testdata.csv 双行格式迁移流程图

**Author:** Xander  
**Date:** 2026-06-30  
**项目:** EVB-COM-TOOL  
**相关源码:** `scripts/migrate_testdata_dual_row.py` · `csv_loader.py`  
**入口命令:** `python scripts/migrate_testdata_dual_row.py`

本文档以 Mermaid 流程图描述旧版 7000 行仿真 CSV 迁移为 14000 行交错双行格式（仿真行 + 实测行）的逻辑。  
**仅文档，不修改 Python 实现。**

---

## 目录

1. [迁移总览（CLI 入口）](#1-迁移总览cli-入口)
2. [核心迁移逻辑（migrate_to_interleaved）](#2-核心迁移逻辑migrate_to_interleaved)
3. [单行 → 双行展开（build_interleaved_rows_from_legacy）](#3-单行--双行展开build_interleaved_rows_from_legacy)
4. [格式对比](#4-格式对比)

---

## 1. 迁移总览（CLI 入口）

对应 `scripts/migrate_testdata_dual_row.py` 的 `main()`。

```mermaid
flowchart TD
    START(["开始：python migrate_testdata_dual_row.py"]) --> PARSE["解析 CLI 参数<br/>--input / --output / --no-backup"]
    PARSE --> EXISTS{"源文件 src 存在?"}
    EXISTS -->|否| ERR1["stderr: 找不到文件<br/>exit(1)"]
    EXISTS -->|是| LOAD["before = load_test_csv(src)<br/>统计迁移前用例组数"]

    LOAD --> INTER{"before.interleaved<br/>已是交错格式?"}
    INTER -->|是| SKIP["打印「已是交错格式」<br/>N 对（2N 行）<br/>正常退出"]
    INTER -->|否| MIG["out = migrate_to_interleaved<br/>(src, dst, backup=not --no-backup)"]

    MIG --> RELOAD["after = load_test_csv(out)"]
    RELOAD --> PRINT["打印迁移摘要<br/>仿真行数 → 双行对数<br/>输出路径 / .bak 路径<br/>RowKind 标签"]
    PRINT --> DONE(["完成"])

    MIG -->|异常| ERR2["stderr: 迁移失败<br/>exit(1)"]

    style SKIP fill:#fff3cd
    style DONE fill:#d4edda
    style ERR1 fill:#f8d7da
    style ERR2 fill:#f8d7da
```

### CLI 参数说明

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--input` / `-i` | `data/testdata.csv` | 待迁移的源 CSV |
| `--output` / `-o` | 与 `--input` 相同 | 输出路径；默认可就地覆盖 |
| `--no-backup` | 关闭 | 就地更新时不生成 `.bak` 备份 |

---

## 2. 核心迁移逻辑（migrate_to_interleaved）

对应 `csv_loader.migrate_to_interleaved()`。

```mermaid
flowchart TD
    START(["migrate_to_interleaved(src, dst, backup)"]) --> LOAD["loaded = load_test_csv(src)"]

    LOAD --> CHECK1{"loaded.interleaved?"}
    CHECK1 -->|是| ERR1["ValueError<br/>已是交错双行格式，无需迁移"]
    CHECK1 -->|否| CHECK2{"loaded.cases 非空?"}
    CHECK2 -->|否| ERR2["ValueError<br/>无数据行"]
    CHECK2 -->|是| CHECK3{"loaded.dataset 可构建?"}
    CHECK3 -->|否| ERR3["ValueError<br/>无法构建交错数据集"]

    CHECK3 -->|是| ROWS["fieldnames = dataset.fieldnames<br/>out_rows = dataset.rows<br/>（14000 行，见 §3）"]

    ROWS --> INPLACE{"backup=True<br/>且 out == src?"}
    INPLACE -->|是| BAK["shutil.copy2(src → src.bak)<br/>例：testdata.csv.bak"]
    INPLACE -->|否| WRITE
    BAK --> WRITE["DictWriter 写 UTF-8-SIG CSV<br/>表头 STANDARD_FIELDNAMES<br/>写入全部 out_rows"]

    WRITE --> OUT(["返回 out 路径"])

    style BAK fill:#e8f4fd
    style OUT fill:#d4edda
    style ERR1 fill:#f8d7da
    style ERR2 fill:#f8d7da
    style ERR3 fill:#f8d7da
```

> **备份规则：** 仅当输出路径与源路径相同（就地更新）且 `backup=True` 时，才复制 `src.suffix + ".bak"`。  
> 若指定不同 `--output`，不创建备份。

---

## 3. 单行 → 双行展开（build_interleaved_rows_from_legacy）

在 `load_test_csv()` 加载旧版单行 CSV 时，于内存中调用；迁移写盘时复用同一 `dataset.rows`。

```mermaid
flowchart TD
    START(["旧版单行 CSV<br/>约 7000 行，无 RowKind"]) --> LOOP["遍历每一行 sim_row"]

    LOOP --> SIM["构造仿真行 sim_out<br/>RowKind = 仿真行<br/>Attempt = 空<br/>复制 EbNo_dB / In[] / Out[] / InfoBit[] / IterNum 等"]
    SIM --> MEAS["追加空白实测行<br/>RowKind = 实测行<br/>Attempt = 空<br/>RecvHex / InfoBit 等待回填"]
    MEAS --> MORE{"还有下一组?"}
    MORE -->|是| LOOP
    MORE -->|否| OUT(["输出 14000 行<br/>表头 STANDARD_FIELDNAMES"])

    style SIM fill:#e8f4fd
    style MEAS fill:#fff3cd
    style OUT fill:#d4edda
```

### 交错行序示例

```mermaid
flowchart LR
    subgraph PAIR0["用例 0"]
        R0["行 0：仿真行<br/>In[] / Out[] / EbNo_dB …"]
        R1["行 1：实测行<br/>RecvHex / InfoBit 空白"]
    end
    subgraph PAIR1["用例 1"]
        R2["行 2：仿真行"]
        R3["行 3：实测行"]
    end
    DOTS["… × 7000 组 …"]
    R0 --> R1 --> R2 --> R3 --> DOTS
```

---

## 4. 格式对比

| 项目 | 旧版单行 | 新版交错双行 |
|------|----------|--------------|
| 行数 | ~7000 | ~14000（7000 对） |
| `RowKind` 列 | 无 | 仿真行 / 实测行 交替 |
| `Attempt` 列 | 无 | 实测行可记录多次重试 |
| 实测字段 | 无 | `RecvHex`、`InfoBit[0..3]` 等 |
| 加载行为 | 内存展开为双行 | 直接按对解析 |
| 备份 | — | 就地迁移时生成 `.bak` |

### RowKind 常量

| 常量 | 值 | 含义 |
|------|-----|------|
| `ROW_KIND_SIM` | `仿真行` | 含仿真输入/输出，来自原 CSV |
| `ROW_KIND_MEASURED` | `实测行` | 初始空白，UART 测试后回填 |

---

*文档版本与源码同步至 2026-06-30。渲染环境：GitHub / Cursor Mermaid 预览。*
