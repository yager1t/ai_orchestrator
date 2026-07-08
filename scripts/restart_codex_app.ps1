$ErrorActionPreference = "Stop"

$logPath = Join-Path $env:TEMP "codex-restart.log"
$helperPath = Join-Path $env:TEMP "codex-restart-helper.ps1"

$helper = @'
$ErrorActionPreference = "Continue"
$logPath = Join-Path $env:TEMP "codex-restart.log"
"[$(Get-Date -Format o)] restart helper started" | Add-Content -Path $logPath
Start-Sleep -Seconds 3

$targets = @("Codex", "codex", "OpenAI.Codex")
foreach ($name in $targets) {
  Get-Process -Name $name -ErrorAction SilentlyContinue |
    ForEach-Object {
      "[$(Get-Date -Format o)] stopping $($_.ProcessName) pid=$($_.Id)" | Add-Content -Path $logPath
      Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue
    }
}

Start-Sleep -Seconds 3

$started = $false
$codexApps = Get-StartApps | Where-Object {
  $_.Name -like "*Codex*" -or $_.AppID -like "*OpenAI.Codex*"
}
foreach ($app in $codexApps) {
  try {
    "[$(Get-Date -Format o)] starting appid=$($app.AppID) name=$($app.Name)" | Add-Content -Path $logPath
    Start-Process "shell:AppsFolder\$($app.AppID)"
    $started = $true
    break
  } catch {
    "[$(Get-Date -Format o)] failed appid=$($app.AppID): $($_.Exception.Message)" | Add-Content -Path $logPath
  }
}

if (-not $started) {
  $fallback = Join-Path $env:LOCALAPPDATA "OpenAI\Codex\bin\codex.exe"
  if (Test-Path $fallback) {
    "[$(Get-Date -Format o)] starting fallback=$fallback" | Add-Content -Path $logPath
    Start-Process -FilePath $fallback -ArgumentList "app"
    $started = $true
  }
}

"[$(Get-Date -Format o)] restart helper finished started=$started" | Add-Content -Path $logPath
'@

Set-Content -Path $helperPath -Value $helper -Encoding UTF8
"[$(Get-Date -Format o)] scheduling Codex restart via $helperPath" | Set-Content -Path $logPath -Encoding UTF8

Start-Process powershell.exe `
  -WindowStyle Hidden `
  -ArgumentList @(
    "-NoProfile",
    "-ExecutionPolicy",
    "Bypass",
    "-File",
    $helperPath
  )

Write-Output "Codex restart scheduled. Log: $logPath"
Write-Output "Helper: $helperPath"
