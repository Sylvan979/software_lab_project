# 按实验三要求打包：实验报告.pdf + UML/ + code/，并压缩为 zip
$ErrorActionPreference = 'Stop'

$root = Resolve-Path (Join-Path $PSScriptRoot '..')
$student = '241220075'
$name = '赵力丹'
$folder = "实验3_${student}_${name}"
$dest = Join-Path $root $folder
$zip = Join-Path $root "$folder.zip"
$umlSource = Join-Path $root '..\lab2\实验2_241220075_赵力丹\UML'

if (-not (Test-Path (Join-Path $root 'report\report.pdf'))) {
  throw '缺少 report\report.pdf，请先运行 report\render-report.ps1'
}
if (-not (Test-Path $umlSource)) {
  throw "未找到 UML 源目录：$umlSource"
}

if (Test-Path $dest) { Remove-Item $dest -Recurse -Force }
New-Item -ItemType Directory -Path (Join-Path $dest 'UML') -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $dest 'code\docs') -Force | Out-Null

Copy-Item (Join-Path $root 'report\report.pdf') (Join-Path $dest '实验报告.pdf')
Copy-Item (Join-Path $umlSource '*') (Join-Path $dest 'UML')

foreach ($dir in 'app', 'tests', 'tools') {
  robocopy (Join-Path $root $dir) (Join-Path $dest "code\$dir") /E /XD __pycache__ /XF *.pyc *.pyo /NFL /NDL /NJH /NJS | Out-Null
  if ($LASTEXITCODE -ge 8) { throw "复制 $dir 失败（robocopy $LASTEXITCODE）" }
}
Copy-Item (Join-Path $root 'run.py') (Join-Path $dest 'code')
Copy-Item (Join-Path $root 'README.md') (Join-Path $dest 'code')
Copy-Item (Join-Path $root '.pylintrc') (Join-Path $dest 'code')
foreach ($doc in 'design-mapping.md', 'ai-usage.md', 'testing.md', 'ui-test-record.md') {
  Copy-Item (Join-Path $root "docs\$doc") (Join-Path $dest 'code\docs')
}

Get-ChildItem $dest -Recurse -Directory -Filter __pycache__ | Remove-Item -Recurse -Force
Get-ChildItem $dest -Recurse -File -Include *.pyc, *.pyo | Remove-Item -Force

if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path $dest -DestinationPath $zip -CompressionLevel Optimal
'{0}（{1:N0} KB）' -f $zip, ((Get-Item $zip).Length / 1KB)
