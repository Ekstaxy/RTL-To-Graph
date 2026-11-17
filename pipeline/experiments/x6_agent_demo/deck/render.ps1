# Render a pptx to PNGs with PowerPoint COM: powershell -File render.ps1 deck.pptx outdir
param([string]$deck, [string]$outdir)
$before = @(Get-Process POWERPNT -ErrorAction SilentlyContinue | ForEach-Object { $_.Id })
$app = New-Object -ComObject PowerPoint.Application
try {
  $p = $app.Presentations.Open((Resolve-Path $deck).Path, $true, $false, $false)
  New-Item -ItemType Directory -Force $outdir | Out-Null
  $i = 1
  foreach ($s in $p.Slides) { $s.Export((Join-Path (Resolve-Path $outdir).Path ("slide{0:D2}.png" -f $i)), "PNG", 1600, 900); $i++ }
  $p.Close()
} finally {
  $app.Quit() | Out-Null
  [System.Runtime.InteropServices.Marshal]::ReleaseComObject($app) | Out-Null
  Start-Sleep -Milliseconds 800
  Get-Process POWERPNT -ErrorAction SilentlyContinue | Where-Object { $before -notcontains $_.Id } | ForEach-Object { Stop-Process -Id $_.Id -Force }
}
Write-Output ("rendered " + ($i - 1))
