<#
.SYNOPSIS
  一键刷新真实数据快照，然后用 Agent 1 跑一次回测（量化链路统一入口）。

.DESCRIPTION
  1) 用 SmartX 自带的 Python 跑 scripts\export_baostock_snapshot.py；
     给了 -Base 且没有 -Full 时走 --incremental（重叠校验，除权自动回退全量）。
  2) 读新快照的 manifest，算出 data_version。
  3) 复制示例指令、把 data_version 改成新值，再调用 scripts\run_agent1.py。

.EXAMPLE
  # 每天增量（基于上一份快照）
  .\scripts\refresh_and_run.ps1 -Base C:\AI_workspace\smartx_client\out\real40_pit `
      -Out C:\AI_workspace\smartx_client\out\real40_pit_20261111

.EXAMPLE
  # 全量
  .\scripts\refresh_and_run.ps1 -Out C:\AI_workspace\smartx_client\out\real40_pit_20261111 -Full
#>
[CmdletBinding()]
param(
    [string]$Out,
    [string]$Base = "",
    [string]$End = (Get-Date -Format "yyyy-MM-dd"),
    [string]$Start = "2019-01-01",
    [string]$Universe = "hs300_40_pit",
    [int]$Sample = 40,
    [string]$Instruction = "examples\research_instruction_hs300.json",
    [string]$BaoStockPython = "C:\Users\ADMIN\AppData\Local\Programs\xtp_rich_client\bin\cpython\python.exe",
    [string]$AgentPython = "python",
    [switch]$Full
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$env:PYTHONIOENCODING = "utf-8"

if (-not $Out) { throw "必须给 -Out（新快照目录，不能和 -Base 相同）" }
if (-not (Test-Path $BaoStockPython)) { throw "找不到带 baostock 的 Python：$BaoStockPython" }

$exporterArgs = @(
    "scripts\export_baostock_snapshot.py",
    "--out", $Out,
    "--universe", $Universe,
    "--index", "hs300",
    "--sample", "$Sample",
    "--start", $Start,
    "--end", $End,
    "--fundamentals",
    "--timeout", "20"
)
if ((-not $Full) -and $Base) {
    $exporterArgs += @("--incremental", "--base-dir", $Base)
    Write-Host "[1/3] 增量刷新：$Base -> $Out"
} else {
    Write-Host "[1/3] 全量刷新 -> $Out"
}

& $BaoStockPython @exporterArgs
if ($LASTEXITCODE -ne 0) { throw "导出失败，exit=$LASTEXITCODE" }

$manifestPath = Join-Path $Out "manifest.json"
$manifest = Get-Content -Raw -Encoding UTF8 $manifestPath | ConvertFrom-Json
$dv = "dv-" + $manifest.sha256.Substring(0, 12)
Write-Host "[2/3] 快照版本：$dv"

& $AgentPython -m quant.data_pointer --dir $Out
if ($LASTEXITCODE -ne 0) { throw "写最新快照指针失败，exit=$LASTEXITCODE" }

$instructionPath = Join-Path $root $Instruction
$instr = Get-Content -Raw -Encoding UTF8 $instructionPath | ConvertFrom-Json
$instr.data_version = $dv
$tmpInstruction = Join-Path $root "output\reports\instruction_$dv.json"
New-Item -ItemType Directory -Force -Path (Split-Path $tmpInstruction) | Out-Null
[IO.File]::WriteAllText($tmpInstruction, ($instr | ConvertTo-Json -Depth 6), (New-Object Text.UTF8Encoding($false)))

$agentOut = Join-Path $root "output\reports\agent1_$dv.json"
Write-Host "[3/3] Agent 1：$Instruction -> $agentOut"
& $AgentPython "scripts\run_agent1.py" --instruction $tmpInstruction --data-dir $Out --out $agentOut
if ($LASTEXITCODE -ne 0) { throw "Agent 1 失败，exit=$LASTEXITCODE" }

Write-Host ""
Write-Host "完成"
Write-Host "  快照   : $Out ($dv)"
Write-Host "  信封   : $agentOut"
Write-Host "  实验记录: experiments\exp-*.json（看信封里的 id）"
