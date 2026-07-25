$ErrorActionPreference = "Stop"
Set-Location -LiteralPath "E:\test\danmu\experiments\live2d-screen-poc"
$logOut = "E:\test\danmu\experiments\live2d-screen-poc\artifacts\frieren_stdout.txt"
$logErr = "E:\test\danmu\experiments\live2d-screen-poc\artifacts\frieren_stderr.txt"
$p = Start-Process -FilePath "python" `
  -ArgumentList @(
    "-m", "src.main",
    "--model", "E:\news-test\live 2d\Frieren\Frieren\Frieren.model3.json"
  ) `
  -WorkingDirectory "E:\test\danmu\experiments\live2d-screen-poc" `
  -PassThru `
  -RedirectStandardOutput $logOut `
  -RedirectStandardError $logErr
"PID=$($p.Id)"
Start-Sleep -Seconds 6
"HasExited=$($p.HasExited)"
if ($p.HasExited) { "ExitCode=$($p.ExitCode)" }
Get-Content -LiteralPath $logOut -ErrorAction SilentlyContinue
Get-Content -LiteralPath $logErr -ErrorAction SilentlyContinue
Get-Content -LiteralPath "E:\test\danmu\experiments\live2d-screen-poc\artifacts\poc.log" -Tail 25 -ErrorAction SilentlyContinue
