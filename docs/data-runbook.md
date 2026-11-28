# 数据 Runbook

> 主路径是 Agent 2；没有 Agent 2 会话时才用本文的命令行入口。规则相同：
> 不覆盖已有快照、每次新目录、全 ASCII 路径、成功后再更新指针。

## 1. 当前状态

| 项 | 值 |
|---|---|
| 最新快照 | `C:\AI_workspace\smartx_client\out\real40_pit_cont_pit_20261128` |
| data_version | `dv-c3c3aa85070f` |
| 区间 | 2019-01-02..2026-11-27 |
| 标的 | 40 |
| universe | `hs300_40_pit` |
| 源 | baostock continuous |
| 指针 | `output/data/latest.json` |

## 2. 刷新（增量）

```powershell
$py="C:\Users\ADMIN\AppData\Local\Programs\xtp_rich_client\bin\cpython\python.exe"
& $py -u scripts\export_baostock_snapshot.py `
  --out C:\AI_workspace\smartx_client\out\real40_pit_cont_pit_YYYYMMDD `
  --base-dir C:\AI_workspace\smartx_client\out\real40_pit_cont_pit_20261125 `
  --incremental --continuous --fundamentals --end YYYY-MM-DD
```

注意：

- 新目录不能已存在；
- 增量必须继承 base 的 `universe` 名；2026-11-28 已修
  （此前增量把 `hs300_40_pit` 写成 `hs300_40`，必须检查）；
- 财报增量通常为 0 行，属正常；
- 失败不落半份快照。

## 3. 体检

```powershell
python scripts\check_snapshot.py C:\AI_workspace\smartx_client\out\real40_pit_cont_pit_YYYYMMDD
```

退出码 0 才能用；重点看：

- calendar 覆盖；
- prices 缺失率；
- fundamentals 公告日；
- universe 时点覆盖；
- `adjust_mode`。

## 4. 重算全文件 dv

```powershell
python scripts\rehash_snapshot.py C:\AI_workspace\smartx_client\out\real40_pit_cont_pit_YYYYMMDD
```

只有改过 manifest/文件内容才需要；`dv` 会变。

## 5. 更新指针

```powershell
python -c "from quant.data_pointer import write_pointer; import json; print(json.dumps(write_pointer(r'C:\AI_workspace\smartx_client\out\real40_pit_cont_pit_YYYYMMDD', job_id='manual-YYYYMMDD'), ensure_ascii=False, indent=2))"
```

Agent 2 成功时会自动做；手动刷新才需要。

## 6. 双源交叉验证

```powershell
python scripts\compare_snapshots.py --left <baostock> --right <akshare> --out output\reports\crosscheck.json
```

已知：

- AkShare 38/40（000961/600068 拉取失败）；
- 002085 差异已定位并处理；
- `book` 中位数差 36.7%，财报不可互验；
- 价格连续价修复后最大收益差约 2.9%。

## 7. QMT bars 导入

```powershell
python scripts\import_qmt_bars.py `
  --bars output\qmt\qmt_bars.csv `
  --base-snapshot C:\AI_workspace\smartx_client\out\real40_pit_cont_pit_20261125 `
  --out C:\AI_workspace\smartx_client\out\real40_qmt_YYYYMMDD
```

限制：OHLC 全用 close 近似，只适合价格因子；QMT 缺 000961/600068，导入后 38 只。

## 8. 已知坑

- 增量丢 universe：已修 `scripts/export_baostock_snapshot.py`；
- 历史 PIT 免费源没有，别用当前成分冒充历史；
- AkShare 接口/字段会变，失败不落半份快照；
- 不要覆盖旧快照；实验绑定旧 `dv`；
- 改完 manifest 必须 rehash，否则 `dv` 与实际内容不符。
