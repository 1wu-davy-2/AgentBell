#requires -version 5.1
[CmdletBinding()]
param(
    [ValidateSet('auto', 'claude', 'gemini', 'grok', 'codex')]
    [string]$Agent = 'auto',
    [string]$ConfigPath = '',
    [switch]$DryRun,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$RemainingArgs = @()
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

try {
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    [Console]::OutputEncoding = $utf8
    $OutputEncoding = $utf8
} catch {
}

function Get-Field {
    param($Object, [string[]]$Names)
    if ($null -eq $Object) { return '' }
    foreach ($name in $Names) {
        $prop = $Object.PSObject.Properties[$name]
        if ($null -eq $prop -or $null -eq $prop.Value) { continue }
        $value = $prop.Value
        if ($value -is [string] -or $value -is [int] -or $value -is [long] -or $value -is [double] -or $value -is [bool]) {
            $text = [string]$value
            if (-not [string]::IsNullOrWhiteSpace($text)) { return $text.Trim() }
        }
    }
    return ''
}

function Limit-Text {
    param([string]$Text, [int]$Max)
    if ([string]::IsNullOrWhiteSpace($Text)) { return '' }
    $clean = ($Text -replace '\s+', ' ').Trim()
    if ($clean.Length -le $Max) { return $clean }
    return $clean.Substring(0, $Max - 1) + '…'
}

function New-Turn {
    return [guid]::NewGuid().ToString('N').Substring(0, 12)
}

function Get-StatePath {
    param([string]$SessionId)
    $key = $SessionId
    if ([string]::IsNullOrWhiteSpace($key)) { $key = 'default' }
    $safe = [regex]::Replace($key, '[^A-Za-z0-9._-]', '_')
    if ($safe.Length -gt 100) { $safe = $safe.Substring(0, 100) }
    return Join-Path $script:StateDir ($script:Agent + '-' + $safe + '.json')
}

function Read-State {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return $null }
    try {
        $text = [System.IO.File]::ReadAllText($Path, [System.Text.Encoding]::UTF8)
        if ([string]::IsNullOrWhiteSpace($text)) { return $null }
        return $text | ConvertFrom-Json
    } catch {
        return $null
    }
}

function Save-State {
    param([string]$Path, [string]$Turn, [bool]$Waiting)
    $tmp = "$Path.$PID.tmp"
    try {
        $dir = Split-Path -Parent $Path
        if (-not (Test-Path -LiteralPath $dir)) {
            New-Item -ItemType Directory -Path $dir -Force | Out-Null
        }
        $json = [ordered]@{
            turn    = $Turn
            waiting = $Waiting
            updated = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
        } | ConvertTo-Json -Compress
        [System.IO.File]::WriteAllText($tmp, $json, (New-Object System.Text.UTF8Encoding($false)))
        Move-Item -LiteralPath $tmp -Destination $Path -Force
    } catch {
    } finally {
        try {
            if (Test-Path -LiteralPath $tmp) {
                Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
            }
        } catch {
        }
    }
}

function Remove-State {
    param([string]$Path)
    try {
        if (Test-Path -LiteralPath $Path) {
            Remove-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
        }
    } catch {
    }
}

function Get-WaitReason {
    param([string]$Type, [string]$Message)
    $typeText = $Type.ToLowerInvariant()
    if ($typeText -match 'permission|approval|confirm') { return 'permission' }
    if ($typeText -match 'idle|question|input') { return 'question' }
    $text = ($Type + ' ' + $Message).ToLowerInvariant()
    if ($text -match 'rate.?limit|quota|too many requests|429|限流|配额|速率|频率') { return 'rate_limit' }
    if ($text -match 'context|token limit|max.*(token|length)|上下文|超出.*长度|token.*超') { return 'context_limit' }
    if ($text -match 'permission|approval|approve|allow|authorize|confirm|权限|允许|批准|确认|授权') { return 'permission' }
    if ($text -match 'idle|question|input|answer|ask|是否|要不要|回答|提问|输入') { return 'question' }
    return 'other'
}

function Send-AgentBell {
    param(
        [string]$Title,
        [string]$Status,
        [string]$Summary,
        [string]$Phase = '',
        [bool]$NeedsInput = $false,
        [string]$WaitReason = '',
        [string]$Priority = 'normal',
        [bool]$Silent = $false,
        [string]$Turn = '',
        [string]$SessionId = '',
        [bool]$WithActions = $true
    )

    if ([string]::IsNullOrWhiteSpace($Turn)) { $Turn = New-Turn }
    $runId = 'hook:' + $script:Agent
    $dedupe = 'agentbell-hook:' + $script:Agent
    if (-not [string]::IsNullOrWhiteSpace($SessionId)) {
        $runId += ':' + $SessionId
        $dedupe += ':' + $SessionId
    }
    $runId += ':' + $Turn
    $dedupe += ':' + $Turn
    if ($runId.Length -gt 120) { $runId = $runId.Substring(0, 120) }
    if ($dedupe.Length -gt 200) { $dedupe = $dedupe.Substring(0, 200) }

    $payload = [ordered]@{
        title       = Limit-Text $Title 100
        status      = $Status
        summary     = Limit-Text $Summary 200
        source      = $script:Label
        priority    = $Priority
        silent      = [bool]$Silent
        needs_input = [bool]$NeedsInput
        dedupe_key  = $dedupe
        run_id      = $runId
    }
    if ($NeedsInput) {
        $payload['wait_reason'] = $WaitReason
        $payload['wait_source'] = 'explicit'
    }
    if (-not [string]::IsNullOrWhiteSpace($Phase)) { $payload['phase'] = $Phase }
    if (-not [string]::IsNullOrWhiteSpace($SessionId)) { $payload['session_id'] = $SessionId }

    if ($WithActions) {
        $actions = @()
        if (-not [string]::IsNullOrWhiteSpace($SessionId)) {
            $actions += @{ kind = 'session'; label = '查看记录' }
        }
        $actions += @{ kind = 'timeline'; label = '时间线' }
        $payload['actions'] = $actions
    }

    $origin = [ordered]@{ pid = $PID }
    if (-not [string]::IsNullOrWhiteSpace($script:Cwd)) { $origin['working_dir'] = $script:Cwd }
    $payload['origin'] = $origin

    if ($DryRun) {
        $result = [ordered]@{
            target = $script:Target
            body   = $payload
        }
        $result | ConvertTo-Json -Depth 8 -Compress
        return
    }

    try {
        $json = $payload | ConvertTo-Json -Depth 8 -Compress
        $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
        $headers = @{}
        if (-not [string]::IsNullOrWhiteSpace($script:Token)) {
            $headers['X-Token'] = $script:Token
        }
        Invoke-RestMethod -Uri $script:Target -Method Post `
            -ContentType 'application/json; charset=utf-8' `
            -Headers $headers -Body $bytes -TimeoutSec 3 | Out-Null
    } catch {
    }
}

# ---------- read hook input ----------

$raw = ''
if ($RemainingArgs.Count -gt 0) {
    $candidate = ($RemainingArgs | ForEach-Object { [string]$_ }) -join ' '
    if ($candidate.TrimStart().StartsWith('{')) { $raw = $candidate }
}
if ([string]::IsNullOrWhiteSpace($raw) -and [Console]::IsInputRedirected) {
    try {
        $raw = [Console]::In.ReadToEnd()
    } catch {
        $raw = ''
    }
}
if ([string]::IsNullOrWhiteSpace($raw)) { exit 0 }

try {
    $payloadInput = $raw | ConvertFrom-Json
} catch {
    exit 0
}
if ($null -eq $payloadInput) { exit 0 }

if ($Agent -eq 'auto') {
    if ($env:GROK_EVENT -or $env:GROK_SESSION_ID) {
        $Agent = 'grok'
    } elseif ($env:CLAUDE_SESSION_ID -or $env:CLAUDE_PROJECT_DIR) {
        $Agent = 'claude'
    } elseif ($env:GEMINI_SESSION_ID) {
        $Agent = 'gemini'
    } else {
        $Agent = 'claude'
    }
}
$Agent = $Agent.ToLowerInvariant()
$labels = @{
    claude = 'Claude Code'
    gemini = 'Gemini CLI'
    grok   = 'Grok'
    codex  = 'Codex'
}
$script:Agent = $Agent
$script:Label = $labels[$Agent]
if ([string]::IsNullOrWhiteSpace($script:Label)) { $script:Label = 'Agent' }

if ([string]::IsNullOrWhiteSpace($ConfigPath)) {
    $script:AppDir = Split-Path -Parent $PSScriptRoot
    if ([string]::IsNullOrWhiteSpace($script:AppDir)) {
        $script:AppDir = (Get-Location).Path
    }
    $ConfigPath = Join-Path $script:AppDir 'config.json'
} else {
    $script:AppDir = Split-Path -Parent $ConfigPath
}
$script:StateDir = Join-Path $script:AppDir 'hooks\state'

$script:Port = ''
$script:Token = ''
if (Test-Path -LiteralPath $ConfigPath) {
    try {
        $configText = [System.IO.File]::ReadAllText($ConfigPath, [System.Text.Encoding]::UTF8)
        $config = $configText | ConvertFrom-Json
        if ($null -ne $config.port) { $script:Port = $config.port }
        if ($null -ne $config.token) { $script:Token = [string]$config.token }
    } catch {
    }
}
if ($env:AGENTBELL_PORT) {
    $envPort = 0
    if ([int]::TryParse([string]$env:AGENTBELL_PORT, [ref]$envPort) -and $envPort -ge 1 -and $envPort -le 65535) {
        $script:Port = $envPort
    }
}
if ($env:AGENTBELL_TOKEN) { $script:Token = $env:AGENTBELL_TOKEN }
$parsedPort = 0
if (-not [int]::TryParse([string]$script:Port, [ref]$parsedPort) -or $parsedPort -lt 1 -or $parsedPort -gt 65535) {
    exit 0
}
$script:Port = $parsedPort
$script:Target = 'http://127.0.0.1:' + $script:Port + '/notify'
$script:Token = [string]$script:Token

$eventName = Get-Field $payloadInput @('hook_event_name', 'hookEventName', 'event_name', 'eventName', 'event')
if ([string]::IsNullOrWhiteSpace($eventName)) {
    $eventName = Get-Field $payloadInput @('type')
}
if ([string]::IsNullOrWhiteSpace($eventName) -and $env:GROK_EVENT) {
    $eventName = $env:GROK_EVENT
}
$eventKey = $eventName.ToLowerInvariant() -replace '[_\-]', ''

$sessionId = Get-Field $payloadInput @(
    'session_id', 'sessionId', 'conversation_id', 'conversationId',
    'thread_id', 'threadId', 'thread-id', 'chat_id', 'chatId'
)
if ([string]::IsNullOrWhiteSpace($sessionId)) {
    if ($env:GROK_SESSION_ID) { $sessionId = $env:GROK_SESSION_ID }
    elseif ($env:CLAUDE_SESSION_ID) { $sessionId = $env:CLAUDE_SESSION_ID }
    elseif ($env:GEMINI_SESSION_ID) { $sessionId = $env:GEMINI_SESSION_ID }
}
if ($sessionId.Length -gt 120) { $sessionId = $sessionId.Substring(0, 120) }

$cwd = Get-Field $payloadInput @(
    'cwd', 'working_dir', 'workingDirectory', 'project_dir', 'projectDir',
    'project_path', 'projectPath'
)
if ([string]::IsNullOrWhiteSpace($cwd)) { $cwd = (Get-Location).Path }
$script:Cwd = $cwd
$project = ''
if (-not [string]::IsNullOrWhiteSpace($cwd)) {
    try {
        $trimmed = ([string]$cwd).TrimEnd('\', '/')
        if (-not [string]::IsNullOrWhiteSpace($trimmed)) {
            $project = Split-Path -Leaf $trimmed
        }
    } catch {
    }
}
if ($project.Length -gt 60) { $project = $project.Substring(0, 60) }

$message = Get-Field $payloadInput @(
    'message', 'last_assistant_message', 'lastAssistantMessage',
    'last-assistant-message', 'errorDetails', 'error_details', 'error', 'details'
)
$notificationType = Get-Field $payloadInput @(
    'notification_type', 'notificationType', 'notification', 'matcher'
)

# ---------- Codex: completion only ----------

if ($Agent -eq 'codex') {
    $turn = Get-Field $payloadInput @('turn-id', 'turn_id', 'turnId')
    if ([string]::IsNullOrWhiteSpace($turn)) { $turn = New-Turn }
    $failed = $false
    if ($eventKey -match 'fail|error|cancel') { $failed = $true }
    if (-not [string]::IsNullOrWhiteSpace((Get-Field $payloadInput @('error')))) { $failed = $true }
    if ($failed) {
        $status = 'failed'
        $title = $script:Label + ' 执行失败'
        $priority = 'high'
        if ([string]::IsNullOrWhiteSpace($message)) { $message = '本轮任务执行失败' }
    } else {
        $status = 'succeeded'
        $title = $script:Label + ' 已完成'
        $priority = 'normal'
        if ([string]::IsNullOrWhiteSpace($message)) { $message = '本轮任务已完成' }
    }
    Send-AgentBell -Title $title -Status $status -Summary $message -Phase 'finished' `
        -Priority $priority -Turn $turn -SessionId $sessionId -WithActions $true
    exit 0
}

# ---------- turn state ----------

$statePath = Get-StatePath $sessionId
$state = Read-State $statePath

if ($eventKey -eq 'sessionend') {
    Remove-State $statePath
    exit 0
}

if ($eventKey -eq 'userpromptsubmit' -or $eventKey -eq 'beforeagent') {
    $turn = New-Turn
    Save-State $statePath $turn $false
    $summary = '新一轮任务已开始'
    if (-not [string]::IsNullOrWhiteSpace($project)) {
        $summary = '项目 ' + $project + ' · 新一轮任务已开始'
    }
    Send-AgentBell -Title ($script:Label + ' 开始处理') -Status 'running' -Summary $summary `
        -Phase 'started' -Priority 'normal' -Silent $true -Turn $turn `
        -SessionId $sessionId -WithActions $false
    exit 0
}

if ($eventKey -eq 'notification') {
    $typeText = ($notificationType + ' ' + $eventName).ToLowerInvariant()
    if ($typeText -match 'task_complete|turn_complete|session_ready') { exit 0 }

    $turn = ''
    if ($null -ne $state -and -not [string]::IsNullOrWhiteSpace([string]$state.turn)) {
        $turn = [string]$state.turn
    } else {
        $turn = New-Turn
    }
    Save-State $statePath $turn $true

    $reason = Get-WaitReason $notificationType $message
    switch ($reason) {
        'permission' {
            $title = $script:Label + ' 等待权限确认'
            $priority = 'high'
        }
        'rate_limit' {
            $title = $script:Label + ' 触发限流'
            $priority = 'high'
        }
        'context_limit' {
            $title = $script:Label + ' 上下文接近上限'
            $priority = 'high'
        }
        'question' {
            $title = $script:Label + ' 等待你的回答'
            $priority = 'normal'
        }
        default {
            $title = $script:Label + ' 需要你处理'
            $priority = 'normal'
        }
    }
    if ([string]::IsNullOrWhiteSpace($message)) {
        $message = '会话已暂停，等待你回到终端处理'
    }
    Send-AgentBell -Title $title -Status 'running' -Summary $message -Phase 'waiting_input' `
        -NeedsInput $true -WaitReason $reason -Priority $priority -Turn $turn `
        -SessionId $sessionId -WithActions $true
    exit 0
}

if ($eventKey -eq 'stop' -or $eventKey -eq 'afteragent') {
    $stopActive = Get-Field $payloadInput @('stop_hook_active', 'stopHookActive')
    if ($stopActive -eq 'True' -or $stopActive -eq 'true') { exit 0 }
    $turn = ''
    if ($null -ne $state -and -not [string]::IsNullOrWhiteSpace([string]$state.turn)) {
        $turn = [string]$state.turn
    } else {
        $turn = New-Turn
    }
    if ([string]::IsNullOrWhiteSpace($message)) { $message = '本轮任务已完成' }
    Send-AgentBell -Title ($script:Label + ' 已完成') -Status 'succeeded' -Summary $message `
        -Phase 'finished' -Priority 'normal' -Turn $turn -SessionId $sessionId `
        -WithActions $true
    Remove-State $statePath
    exit 0
}

if ($eventKey -eq 'stopfailure') {
    $turn = ''
    if ($null -ne $state -and -not [string]::IsNullOrWhiteSpace([string]$state.turn)) {
        $turn = [string]$state.turn
    } else {
        $turn = New-Turn
    }
    if ([string]::IsNullOrWhiteSpace($message)) { $message = '本轮任务执行失败' }
    Send-AgentBell -Title ($script:Label + ' 执行失败') -Status 'failed' -Summary $message `
        -Phase 'finished' -Priority 'high' -Turn $turn -SessionId $sessionId `
        -WithActions $true
    Remove-State $statePath
    exit 0
}

if ($eventKey -eq 'stopcancelled') {
    $turn = ''
    if ($null -ne $state -and -not [string]::IsNullOrWhiteSpace([string]$state.turn)) {
        $turn = [string]$state.turn
    } else {
        $turn = New-Turn
    }
    if ([string]::IsNullOrWhiteSpace($message)) { $message = '本轮任务已取消' }
    Send-AgentBell -Title ($script:Label + ' 已取消') -Status 'canceled' -Summary $message `
        -Phase 'finished' -Priority 'normal' -Turn $turn -SessionId $sessionId `
        -WithActions $true
    Remove-State $statePath
    exit 0
}

exit 0
