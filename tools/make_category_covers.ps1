# 生成四个栏目的公众号封面（2.35:1 头图 + 1:1 方图），GDI+ 渲染中文。
# 用法： pwsh -File tools/make_category_covers.ps1
# 与 cover-opening 同一套视觉语言：近黑底、细边框、米色短横线；
# 每个栏目只换强调色与一处极淡的图形母题，保证放在一起是一组、分开也认得。

Add-Type -AssemblyName System.Drawing

$OutDir = Join-Path $PSScriptRoot '..\output\articles\covers'
$OutDir = [System.IO.Path]::GetFullPath($OutDir)
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$Bg    = [System.Drawing.Color]::FromArgb(24, 23, 21)
$Frame = [System.Drawing.Color]::FromArgb(52, 48, 43)
$Ink   = [System.Drawing.Color]::FromArgb(237, 231, 219)
$Muted = [System.Drawing.Color]::FromArgb(150, 142, 128)
$Faint = [System.Drawing.Color]::FromArgb(108, 101, 90)

function Get-Font([single]$size, [bool]$bold, [string]$family) {
    $style = if ($bold) { [System.Drawing.FontStyle]::Bold } else { [System.Drawing.FontStyle]::Regular }
    return New-Object System.Drawing.Font($family, $size, $style, [System.Drawing.GraphicsUnit]::Pixel)
}

function New-Canvas([int]$w, [int]$h) {
    $bmp = New-Object System.Drawing.Bitmap($w, $h)
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $g.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::AntiAliasGridFit
    $g.Clear($Bg)
    return @($bmp, $g)
}

function Pen-A([int]$alpha, $c, [int]$width = 1) {
    return New-Object System.Drawing.Pen([System.Drawing.Color]::FromArgb($alpha, $c[0], $c[1], $c[2]), $width)
}

function Brush-A([int]$alpha, $c) {
    return New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb($alpha, $c[0], $c[1], $c[2]))
}

# ---------- 图形母题：极淡，只做区分，不抢标题 ----------
function Draw-Motif($g, [string]$key, $accent, [double]$x, [double]$y, [double]$w, [double]$h, [double]$scale = 1) {
    switch ($key) {
        'quant' {
            # 坐标网格 + 一条不规则的折线（数据，不是净值承诺）
            $grid = Pen-A 28 $accent
            for ($i = 1; $i -lt 4; $i++) {
                $g.DrawLine($grid, [single]($x + $w * $i / 4), [single]$y, [single]($x + $w * $i / 4), [single]($y + $h))
            }
            for ($j = 1; $j -lt 3; $j++) {
                $g.DrawLine($grid, [single]$x, [single]($y + $h * $j / 3), [single]($x + $w), [single]($y + $h * $j / 3))
            }
            $rel = @(@(0, 0.62), @(0.18, 0.72), @(0.34, 0.44), @(0.5, 0.56), @(0.66, 0.30), @(0.82, 0.44), @(1, 0.38))
            $line = Pen-A 70 $accent
            for ($i = 1; $i -lt $rel.Count; $i++) {
                $g.DrawLine($line,
                    [single]($x + $w * $rel[$i - 1][0]), [single]($y + $h * $rel[$i - 1][1]),
                    [single]($x + $w * $rel[$i][0]), [single]($y + $h * $rel[$i][1]))
            }
            $dot = Brush-A 90 $accent
            foreach ($p in $rel) {
                $g.FillEllipse($dot, [single]($x + $w * $p[0] - 2), [single]($y + $h * $p[1] - 2), 4, 4)
            }
        }
        'ai' {
            # 中心节点 + 一圈节点：一处结构，不是电路板
            $nodes = @(@(0.10, 0.22), @(0.30, 0.08), @(0.62, 0.10), @(0.90, 0.30), @(0.86, 0.68), @(0.60, 0.88), @(0.26, 0.84), @(0.06, 0.56), @(0.46, 0.46))
            $hub = 8
            $edges = @(@(0, 1), @(1, 2), @(2, 3), @(3, 4), @(4, 5), @(5, 6), @(6, 7), @(7, 0))
            for ($i = 0; $i -lt $hub; $i++) { $edges += , @($i, $hub) }
            $line = Pen-A 60 $accent
            foreach ($e in $edges) {
                $g.DrawLine($line,
                    [single]($x + $w * $nodes[$e[0]][0]), [single]($y + $h * $nodes[$e[0]][1]),
                    [single]($x + $w * $nodes[$e[1]][0]), [single]($y + $h * $nodes[$e[1]][1]))
            }
            $dot = Brush-A 95 $accent
            for ($i = 0; $i -lt $hub; $i++) {
                $p = $nodes[$i]
                $g.FillEllipse($dot, [single]($x + $w * $p[0] - 2.5), [single]($y + $h * $p[1] - 2.5), 5, 5)
            }
            # 中心点画实心小方块，和外围圆点区分
            $g.FillRectangle($dot, [single]($x + $w * $nodes[$hub][0] - 3.5), [single]($y + $h * $nodes[$hub][1] - 3.5), 7, 7)
        }
        'market' {
            # 时间轴 + 高低不一的刻度：复盘是把点标出来，不是画趋势
            $axis = Pen-A 62 $accent
            $g.DrawLine($axis, [single]$x, [single]($y + $h * 0.6), [single]($x + $w), [single]($y + $h * 0.6))
            $lens = @(0.18, 0.34, 0.10, 0.42, 0.22, 0.48, 0.16, 0.30, 0.24)
            $tick = Pen-A 70 $accent
            for ($i = 0; $i -lt $lens.Count; $i++) {
                $tx = $x + $w * $i / ($lens.Count - 1)
                $g.DrawLine($tick, [single]$tx, [single]($y + $h * 0.6), [single]$tx, [single]($y + $h * (0.6 - $lens[$i])))
            }
            $mark = Brush-A 100 $accent
            $g.FillEllipse($mark, [single]($x + $w * 5 / 8 - 3), [single]($y + $h * 0.6 - 3), 6, 6)
        }
        'misc' {
            # 一枚极淡的印章：账号的落款
            $side = [double](84 * $scale)
            $mx = $x + $w - $side
            $my = $y + $h - $side
            $g.DrawRectangle((Pen-A 62 $accent 2), [single]$mx, [single]$my, [single]$side, [single]$side)
            $f = Get-Font ([single](46 * $scale)) $true 'Microsoft YaHei'
            $b = Brush-A 58 $accent
            $sz = $g.MeasureString('杂', $f)
            $g.DrawString('杂', $f, $b,
                [single]($mx + ($side - $sz.Width) / 2),
                [single]($my + ($side - $sz.Height) / 2))
        }
    }
}

function Draw-Text($g, [string]$label, [string]$hero, [string]$tag, $accent, [int]$w, [int]$h) {
    $family = 'Microsoft YaHei'
    $brushMuted = New-Object System.Drawing.SolidBrush($Muted)
    $brushInk = New-Object System.Drawing.SolidBrush($Ink)
    $brushFaint = New-Object System.Drawing.SolidBrush($Faint)
    $penAccent = New-Object System.Drawing.Pen([System.Drawing.Color]::FromArgb($accent[0], $accent[1], $accent[2]), 3)

    if ($w -gt $h) {
        # 2.35:1 头图
        $g.DrawString($label, (Get-Font 19 $false $family), $brushMuted, 62, 74)
        $g.DrawLine($penAccent, 62, 108, 118, 108)
        $g.DrawString($hero, (Get-Font 54 $true $family), $brushInk, 58, 140)
        if ($tag) {
            $fTag = Get-Font 17 $false $family
            $size = $g.MeasureString($tag, $fTag)
            $g.DrawString($tag, $fTag, $brushFaint, $w - 62 - $size.Width, 306)
        }
    } else {
        # 1:1 方图
        $g.DrawString($label, (Get-Font 15 $false $family), $brushMuted, 46, 84)
        $g.DrawLine($penAccent, 46, 116, 92, 116)
        $g.DrawString($hero, (Get-Font 42 $true $family), $brushInk, 42, 146)
    }
}

$Cats = @(
    @{ Key = 'quant';  Name = '量化研究'; Accent = @(127, 163, 168); Tag = '把判断写成可证伪的因子' },
    @{ Key = 'ai';     Name = 'AI 技术';  Accent = @(145, 135, 185); Tag = '工具、流程与执行' },
    @{ Key = 'market'; Name = '市场复盘'; Accent = @(178, 116, 92);  Tag = '记录判断，不展示输出' },
    @{ Key = 'misc';   Name = '杂项';     Accent = @(192, 174, 140); Tag = '发刊词、运营与杂记' }
)

foreach ($cat in $Cats) {
    # 2.35:1
    $w = 900; $h = 383
    $c = New-Canvas $w $h
    $bmp = $c[0]; $g = $c[1]
    $g.DrawRectangle((New-Object System.Drawing.Pen($Frame, 1)), 24, 24, $w - 48, $h - 48)
    Draw-Motif $g $cat.Key $cat.Accent 540 112 296 168 1
    Draw-Text $g '杂灵根散修录' $cat.Name $cat.Tag $cat.Accent $w $h
    $g.Dispose()
    $p = Join-Path $OutDir ("cover-{0}-2.35x1.png" -f $cat.Key)
    $bmp.Save($p, [System.Drawing.Imaging.ImageFormat]::Png)
    $bmp.Dispose()
    Write-Output "wide  $p"

    # 1:1
    $w = 383; $h = 383
    $c = New-Canvas $w $h
    $bmp = $c[0]; $g = $c[1]
    $g.DrawRectangle((New-Object System.Drawing.Pen($Frame, 1)), 20, 20, $w - 40, $h - 40)
    Draw-Motif $g $cat.Key $cat.Accent 214 232 122 96 0.78
    Draw-Text $g '杂灵根散修录' $cat.Name '' $cat.Accent $w $h
    $g.Dispose()
    $p = Join-Path $OutDir ("cover-{0}-1x1.png" -f $cat.Key)
    $bmp.Save($p, [System.Drawing.Imaging.ImageFormat]::Png)
    $bmp.Dispose()
    Write-Output "square $p"
}
