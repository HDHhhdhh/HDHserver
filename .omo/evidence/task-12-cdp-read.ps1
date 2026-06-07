param(
  [Parameter(Mandatory = $true)][int]$Port,
  [Parameter(Mandatory = $true)][string]$OutPath
)

$ErrorActionPreference = 'Stop'

function Receive-CdpMessage {
  param([System.Net.WebSockets.ClientWebSocket]$Socket)

  $buffer = New-Object byte[] 65536
  $stream = New-Object System.IO.MemoryStream
  do {
    $segment = [ArraySegment[byte]]::new($buffer)
    $result = $Socket.ReceiveAsync($segment, [Threading.CancellationToken]::None).GetAwaiter().GetResult()
    if ($result.Count -gt 0) {
      $stream.Write($buffer, 0, $result.Count)
    }
  } until ($result.EndOfMessage)

  return [Text.Encoding]::UTF8.GetString($stream.ToArray())
}

for ($i = 0; $i -lt 40; $i++) {
  try {
    $tabs = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/json/list"
    if ($tabs) { break }
  } catch {
    Start-Sleep -Milliseconds 250
  }
}

if (-not $tabs) {
  throw "CDP endpoint on port $Port did not become available"
}

$tab = @($tabs | Where-Object { $_.type -eq 'page' })[0]
if (-not $tab -or -not $tab.webSocketDebuggerUrl) {
  throw "No page websocket found on port $Port"
}

$socket = [System.Net.WebSockets.ClientWebSocket]::new()
$socket.ConnectAsync([Uri]$tab.webSocketDebuggerUrl, [Threading.CancellationToken]::None).GetAwaiter().GetResult()

try {
  $status = ''
  for ($i = 0; $i -lt 40; $i++) {
    $payload = @{
      id = $i + 1
      method = 'Runtime.evaluate'
      params = @{
        expression = "document.body && document.body.getAttribute('data-qa-status') || ''"
        returnByValue = $true
      }
    } | ConvertTo-Json -Compress -Depth 5

    $bytes = [Text.Encoding]::UTF8.GetBytes($payload)
    $socket.SendAsync(
      [ArraySegment[byte]]::new($bytes),
      [System.Net.WebSockets.WebSocketMessageType]::Text,
      $true,
      [Threading.CancellationToken]::None
    ).GetAwaiter().GetResult()

    do {
      $raw = Receive-CdpMessage -Socket $socket
      $message = $raw | ConvertFrom-Json
    } while ($message.id -ne ($i + 1))

    $status = [string]($message.result.result.value)
    if ($status) { break }
    Start-Sleep -Milliseconds 250
  }

  if (-not $status) {
    throw "Timed out waiting for data-qa-status"
  }

  Set-Content -Path $OutPath -Value $status -Encoding UTF8
  Write-Output $status
} finally {
  if ($socket.State -eq [System.Net.WebSockets.WebSocketState]::Open) {
    $socket.CloseAsync(
      [System.Net.WebSockets.WebSocketCloseStatus]::NormalClosure,
      'done',
      [Threading.CancellationToken]::None
    ).GetAwaiter().GetResult()
  }
  $socket.Dispose()
}
