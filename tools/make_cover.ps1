# 生成公众号封面（2.35:1 头图 + 1:1 方图），GDI+ 渲染中文。
# 用法： powershell -ExecutionPolicy Bypass -File tools\make_cover.ps1
# 配色与文章一致：近黑底、宣纸米色强调线、克制的两行标题。

Add-Type -AssemblyName System.Drawing

$OutDir = Join-Path $PSScriptRoot '..\output\articles'
$OutDir = [System.IO.Path]::GetFullPath($OutDir)
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$Bg      = [System.Drawing.Color]::FromArgb(24, 23, 21)
$Frame   = [System.Drawing.Color]::FromArgb(52, 48, 43)
$Accent  = [System.Drawing.Color]::FromArgb(192, 174, 140)
$Ink     = [System.Drawing.Color]::FromArgb(237, 231, 219)
$Muted   = [System.Drawing.Color]::FromArgb(150, 142, 128)
$Faint   = [System.Drawing.Color]::FromArgb(108, 101, 90)

function New-Canvas([int]$w, [int]$h) {
    $bmp = New-Object System.Drawing.Bitmap($w, $h)
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $g.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::AntiAliasGridFit
    $g.Clear($Bg)
    return @($bmp, $g)
}

function Get-Font([single]$size, [bool]$bold, [string]$family) {
    $style = if ($bold) { [System.Drawing.FontStyle]::Bold } else { [System.Drawing.FontStyle]::Regular }
    return New-Object System.Drawing.Font($family, $size, $style, [System.Drawing.GraphicsUnit]::Pixel)
}

$family = 'Microsoft YaHei'
$installed = (New-Object System.Drawing.Text.InstalledFontCollection).Families | ForEach-Object { $_.Name }
if ($installed -notcontains $family) {
    foreach ($cand in @('Microsoft YaHei UI', 'SimHei', 'SimSun')) {
        if ($installed -contains $cand) { $family = $cand; break }
    }
}

# ---------- 2.35:1 头图 ----------
$w = 900; $h = 383
$c = New-Canvas $w $h
$bmp = $c[0]; $g = $c[1]

$pen = New-Object System.Drawing.Pen($Frame, 1)
$g.DrawRectangle($pen, 24, 24, $w - 48, $h - 48)

$fLabel = Get-Font 19 $false $family
$brushMuted = New-Object System.Drawing.SolidBrush($Muted)
$g.DrawString('杂灵根散修录 · 开篇', $fLabel, $brushMuted, 62, 78)

$penAccent = New-Object System.Drawing.Pen($Accent, 3)
$g.DrawLine($penAccent, 62, 112, 118, 112)

$fTitle = Get-Font 54 $true $family
$brushInk = New-Object System.Drawing.SolidBrush($Ink)
$g.DrawString('先苟住', $fTitle, $brushInk, 58, 134)
$g.DrawString('再谈筑基', $fTitle, $brushInk, 58, 210)

$fSmall = Get-Font 17 $false $family
$brushFaint = New-Object System.Drawing.SolidBrush($Faint)
$g.DrawString('一个散户的公开笔记本', $fSmall, $brushFaint, 560, 318)

$g.Dispose()
$wide = Join-Path $OutDir 'cover-opening-2.35x1.png'
$bmp.Save($wide, [System.Drawing.Imaging.ImageFormat]::Png)
$bmp.Dispose()

# ---------- 1:1 方图 ----------
$w = 383; $h = 383
$c = New-Canvas $w $h
$bmp = $c[0]; $g = $c[1]

$pen = New-Object System.Drawing.Pen($Frame, 1)
$g.DrawRectangle($pen, 20, 20, $w - 40, $h - 40)

$fLabel = Get-Font 15 $false $family
$brushMuted = New-Object System.Drawing.SolidBrush($Muted)
$g.DrawString('杂灵根散修录', $fLabel, $brushMuted, 48, 92)

$penAccent = New-Object System.Drawing.Pen($Accent, 3)
$g.DrawLine($penAccent, 48, 124, 96, 124)

$fTitle = Get-Font 44 $true $family
$brushInk = New-Object System.Drawing.SolidBrush($Ink)
$g.DrawString('先苟住', $fTitle, $brushInk, 44, 148)
$g.DrawString('再谈筑基', $fTitle, $brushInk, 44, 206)

$g.Dispose()
$square = Join-Path $OutDir 'cover-opening-1x1.png'
$bmp.Save($square, [System.Drawing.Imaging.ImageFormat]::Png)
$bmp.Dispose()

Write-Output "font=$family"
Write-Output "wide=$wide"
Write-Output "square=$square"
