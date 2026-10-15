$jobs = @()
for ($i = 1; $i -le 8; $i++) {
    $jobs += Start-Job -ScriptBlock {
        param($u)
        $out = & curl.exe -s -o NUL -w "%{http_code} ttfb=%{time_starttransfer}" --max-time 20 $u 2>&1
        "code=$LASTEXITCODE $u -> $out"
    } -ArgumentList "http://122.51.97.86:5300/api/health"
}
$jobs | Wait-Job | Out-Null
$jobs | Receive-Job | Sort-Object
$jobs | Remove-Job
