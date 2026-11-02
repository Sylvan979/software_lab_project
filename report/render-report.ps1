# 由 report.md 渲染实验报告 PDF（pandoc + xeCJK/xelatex）
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$pandoc = Join-Path $env:LOCALAPPDATA 'Pandoc\pandoc.exe'
if (-not (Test-Path $pandoc)) { throw "未找到 pandoc：$pandoc" }

$pandocArgs = @(
  'report.md', '-o', 'report.pdf',
  '--pdf-engine=xelatex', '-N', '-H', 'report-header.tex',
  '-V', 'CJKmainfont=SimSun',
  '-V', 'CJKsansfont=Microsoft YaHei',
  '-V', 'mainfont=Times New Roman',
  '-V', 'sansfont=Microsoft YaHei',
  '-V', 'monofont=Consolas',
  '-V', 'fontsize=11pt',
  '-V', 'geometry:top=2.2cm,bottom=2.2cm,left=2.6cm,right=2.6cm',
  '--pdf-engine-opt=-interaction=nonstopmode'
)

& $pandoc @pandocArgs
if (-not (Test-Path 'report.pdf')) { throw 'PDF 渲染失败' }
'{0:N0} KB' -f ((Get-Item 'report.pdf').Length / 1KB)
