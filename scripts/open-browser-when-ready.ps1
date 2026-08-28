# Polls a URL until it responds, then opens it in the default browser.
#
# Launched detached (start /b) from start.bat while uvicorn runs in the
# foreground of the same console. Prints nothing and exits with a non-zero
# code on timeout, since the foreground uvicorn output already shows
# startup errors.

param(
    [Parameter(Mandatory = $true)]
    [string]$Url,
    [int]$TimeoutSeconds = 30
)

for ($i = 0; $i -lt $TimeoutSeconds; $i++) {
    try {
        Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2 | Out-Null
        Write-Output "[start.bat] Server is up. Opening browser ..."
        Start-Process $Url
        exit 0
    } catch {
        Start-Sleep -Seconds 1
    }
}
exit 1
