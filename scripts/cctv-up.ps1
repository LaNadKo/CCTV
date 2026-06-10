[CmdletBinding()]
param(
    [ValidateSet(
        "core",
        "server",
        "server-cpu",
        "server-gpu",
        "public",
        "with-processor",
        "with-gpu",
        "processor-nvidia",
        "with-nginx"
    )]
    [string]$Profile = "server",

    [int]$BackendPort = 8001,
    [string]$Domain = "",
    [string]$Email = "",
    [string]$AdminLogin = "",
    [string]$AdminPassword = "",
    [string]$PostgresPassword = "",

    [switch]$Interactive,
    [switch]$Production,
    [switch]$LocalOnly,
    [switch]$ExposeBackend,
    [switch]$InstallDocker,
    [switch]$IssueCertificate,
    [switch]$LetsEncryptStaging,
    [switch]$Pull,
    [switch]$NoBuild,
    [switch]$NoStart,
    [switch]$SkipHealth,
    [switch]$RotateWeakSecrets,
    [switch]$AllowEnvRecreate,
    [switch]$GenerateAdminPassword,
    [switch]$GeneratePostgresPassword,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$EnvPath = Join-Path $Root ".env"
$EnvExamplePath = Join-Path $Root ".env.example"
$InteractiveMode = $Interactive -or $PSBoundParameters.Count -eq 0

function Write-Step {
    param([string]$Message)
    Write-Host "[..] $Message"
}

function Write-Ok {
    param([string]$Message)
    Write-Host "[OK] $Message" -ForegroundColor Green
}

function Write-Warn {
    param([string]$Message)
    Write-Host "[!!] $Message" -ForegroundColor Yellow
}

function Write-Fail {
    param([string]$Message)
    Write-Host "[ER] $Message" -ForegroundColor Red
}

function New-RandomBytes {
    param([int]$Count)
    $bytes = New-Object byte[] $Count
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $rng.GetBytes($bytes)
    }
    finally {
        $rng.Dispose()
    }
    return ,$bytes
}

function New-HexSecret {
    param([int]$Bytes = 32)
    return ([BitConverter]::ToString((New-RandomBytes $Bytes))).Replace("-", "").ToLowerInvariant()
}

function New-UrlSafeSecret {
    param([int]$Bytes = 24)
    $raw = [Convert]::ToBase64String((New-RandomBytes $Bytes))
    return $raw.TrimEnd("=").Replace("+", "-").Replace("/", "_")
}

function New-FernetKey {
    $raw = [Convert]::ToBase64String((New-RandomBytes 32))
    return $raw.Replace("+", "-").Replace("/", "_")
}

function Test-WeakValue {
    param(
        [string]$Value,
        [int]$MinimumLength,
        [string[]]$BlockedValues
    )
    if ([string]::IsNullOrWhiteSpace($Value)) {
        return $true
    }
    if ($Value.Length -lt $MinimumLength) {
        return $true
    }
    $lower = $Value.ToLowerInvariant()
    foreach ($blocked in $BlockedValues) {
        if ($lower -eq $blocked.ToLowerInvariant()) {
            return $true
        }
    }
    return $false
}

function ConvertTo-JsonStringArray {
    param([string[]]$Values)
    $items = @()
    foreach ($value in $Values) {
        $escaped = $value.Replace("\", "\\").Replace('"', '\"')
        $items += '"' + $escaped + '"'
    }
    return "[" + ($items -join ",") + "]"
}

function Read-EnvLines {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        return @()
    }
    return @(Get-Content -LiteralPath $Path -Encoding UTF8)
}

function Read-EnvValues {
    param([string[]]$Lines)
    $values = @{}
    foreach ($line in $Lines) {
        if ($line -match '^\s*([^#=\s]+)\s*=(.*)$') {
            $key = $Matches[1].Trim()
            $value = $Matches[2].Trim()
            if (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'"))) {
                $value = $value.Substring(1, $value.Length - 2)
            }
            $values[$key] = $value
        }
    }
    return $values
}

function Set-EnvLines {
    param(
        [string[]]$Lines,
        [System.Collections.Specialized.OrderedDictionary]$Updates
    )
    $seen = @{}
    $out = New-Object System.Collections.Generic.List[string]
    foreach ($line in $Lines) {
        if ($line -match '^\s*([^#=\s]+)\s*=') {
            $key = $Matches[1].Trim()
            if ($Updates.Contains($key)) {
                $out.Add("$key=$($Updates[$key])")
                $seen[$key] = $true
            }
            else {
                $out.Add($line)
            }
        }
        else {
            $out.Add($line)
        }
    }
    foreach ($key in $Updates.Keys) {
        if (-not $seen.ContainsKey($key)) {
            if ($out.Count -gt 0 -and -not [string]::IsNullOrWhiteSpace($out[$out.Count - 1])) {
                $out.Add("")
            }
            $out.Add("$key=$($Updates[$key])")
        }
    }
    return @($out.ToArray())
}

function Get-LanIp {
    try {
        $ip = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop |
            Where-Object {
                $_.IPAddress -notlike "127.*" -and
                $_.IPAddress -notlike "169.254.*" -and
                $_.IPAddress -ne "0.0.0.0"
            } |
            Sort-Object `
                @{ Expression = {
                    $text = $_.IPAddress
                    if ($text -like "192.168.*" -or $text -like "10.*" -or $text -match "^172\.(1[6-9]|2[0-9]|3[0-1])\.") { 0 } else { 1 }
                } },
                InterfaceIndex |
            Select-Object -First 1 -ExpandProperty IPAddress
        if ($ip) {
            return $ip
        }
    }
    catch {
        # Fallback below works on hosts without Get-NetIPAddress.
    }

    try {
        $hostName = [System.Net.Dns]::GetHostName()
        $addresses = [System.Net.Dns]::GetHostAddresses($hostName)
        foreach ($address in $addresses) {
            if ($address.AddressFamily -eq [System.Net.Sockets.AddressFamily]::InterNetwork) {
                $text = $address.ToString()
                if ($text -notlike "127.*" -and $text -notlike "169.254.*") {
                    return $text
                }
            }
        }
    }
    catch {
        return ""
    }
    return ""
}

function Get-ComposeProjectName {
    $existing = [Environment]::GetEnvironmentVariable("COMPOSE_PROJECT_NAME")
    if (-not [string]::IsNullOrWhiteSpace($existing)) {
        return $existing
    }
    $name = Split-Path -Leaf $Root
    $name = $name.ToLowerInvariant() -replace '[^a-z0-9]+', '-'
    $name = $name.Trim("-")
    if ([string]::IsNullOrWhiteSpace($name)) {
        return "cctvlocal"
    }
    return $name
}

function Test-DockerReady {
    try {
        & docker version | Out-Null
        & docker compose version | Out-Null
        return $true
    }
    catch {
        return $false
    }
}

function Test-DockerCliAvailable {
    return [bool](Get-Command docker -ErrorAction SilentlyContinue)
}

function Test-DockerVolumeExists {
    param([string]$Name)
    if ([string]::IsNullOrWhiteSpace($Name)) {
        return $false
    }
    try {
        & docker volume inspect $Name 2>$null | Out-Null
        return $LASTEXITCODE -eq 0
    }
    catch {
        return $false
    }
}

function Read-YesNo {
    param(
        [string]$Prompt,
        [bool]$Default = $false
    )
    $suffix = if ($Default) { "Y/n" } else { "y/N" }
    while ($true) {
        $value = (Read-Host "$Prompt [$suffix]").Trim().ToLowerInvariant()
        if ([string]::IsNullOrWhiteSpace($value)) {
            return $Default
        }
        if ($value -in @("y", "yes", "д", "да")) {
            return $true
        }
        if ($value -in @("n", "no", "н", "нет")) {
            return $false
        }
        Write-Warn "Введите y/n или да/нет."
    }
}

function Read-IntValue {
    param(
        [string]$Prompt,
        [int]$Default
    )
    while ($true) {
        $value = (Read-Host "$Prompt [$Default]").Trim()
        if ([string]::IsNullOrWhiteSpace($value)) {
            return $Default
        }
        $parsed = 0
        if ([int]::TryParse($value, [ref]$parsed) -and $parsed -gt 0 -and $parsed -le 65535) {
            return $parsed
        }
        Write-Warn "Введите корректный TCP-порт от 1 до 65535."
    }
}

function Read-SecretText {
    param([string]$Prompt)
    $secure = Read-Host $Prompt -AsSecureString
    if ($secure.Length -eq 0) {
        return ""
    }
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr)
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr)
    }
}

function Read-MenuChoice {
    param(
        [string]$Title,
        [object[]]$Items,
        [int]$DefaultIndex = 1
    )
    Write-Host ""
    Write-Host $Title -ForegroundColor Cyan
    for ($i = 0; $i -lt $Items.Count; $i++) {
        $number = $i + 1
        Write-Host ("  {0}. {1}" -f $number, $Items[$i].Label)
        if (-not [string]::IsNullOrWhiteSpace($Items[$i].Description)) {
            Write-Host ("     {0}" -f $Items[$i].Description) -ForegroundColor DarkGray
        }
    }
    while ($true) {
        $value = (Read-Host "Выбор [$DefaultIndex]").Trim()
        if ([string]::IsNullOrWhiteSpace($value)) {
            return $Items[$DefaultIndex - 1]
        }
        $index = 0
        if ([int]::TryParse($value, [ref]$index) -and $index -ge 1 -and $index -le $Items.Count) {
            return $Items[$index - 1]
        }
        Write-Warn "Введите номер от 1 до $($Items.Count)."
    }
}

function Invoke-InteractiveWizard {
    $existing = Read-EnvValues -Lines (Read-EnvLines -Path $EnvPath)

    Write-Host ""
    Write-Host "CCTV Комплекс: мастер запуска" -ForegroundColor Cyan
    Write-Host "Безопасный режим: существующие пароли и БД не меняются, пока вы явно не выберете замену." -ForegroundColor DarkGray

    $profileChoice = Read-MenuChoice -Title "Профиль Docker" -DefaultIndex 1 -Items @(
        [pscustomobject]@{ Key = "server"; Label = "Сервер без nginx"; Description = "PostgreSQL, backend, MediaMTX. Подходит для LAN и Native Console." },
        [pscustomobject]@{ Key = "with-nginx"; Label = "Сервер с nginx"; Description = "Backend закрыт на localhost, вход через nginx HTTP/HTTPS." },
        [pscustomobject]@{ Key = "public"; Label = "Публичный сервер"; Description = "nginx + certbot/Let's Encrypt, нужен домен и email." },
        [pscustomobject]@{ Key = "core"; Label = "Core минимум"; Description = "Backend и MediaMTX с PostgreSQL, без дополнительных сервисов." },
        [pscustomobject]@{ Key = "server-cpu"; Label = "Сервер + Processor CPU"; Description = "Backend, MediaMTX и Docker Processor CPU/auto." },
        [pscustomobject]@{ Key = "server-gpu"; Label = "Сервер + Processor NVIDIA"; Description = "Backend, MediaMTX и Docker Processor с NVIDIA." }
    )
    Set-Variable -Name Profile -Scope Script -Value $profileChoice.Key

    Set-Variable -Name BackendPort -Scope Script -Value (Read-IntValue -Prompt "Порт backend снаружи" -Default $BackendPort)

    if ($Profile -in @("with-nginx", "public")) {
        $domainDefault = if (-not [string]::IsNullOrWhiteSpace($existing["DOMAIN"])) { $existing["DOMAIN"] } else { $Domain }
        $domainValue = (Read-Host "Домен nginx/публичного входа [$domainDefault]").Trim()
        if ([string]::IsNullOrWhiteSpace($domainValue)) {
            $domainValue = $domainDefault
        }
        Set-Variable -Name Domain -Scope Script -Value $domainValue

        $expose = Read-YesNo -Prompt "Оставить прямой LAN-доступ к backend кроме nginx" -Default $false
        Set-Variable -Name ExposeBackend -Scope Script -Value ([switch]$expose)
    }
    else {
        $localOnlyValue = Read-YesNo -Prompt "Ограничить backend только 127.0.0.1" -Default $false
        Set-Variable -Name LocalOnly -Scope Script -Value ([switch]$localOnlyValue)
    }

    if ($Profile -eq "public") {
        $emailDefault = if (-not [string]::IsNullOrWhiteSpace($Email)) { $Email } else { "" }
        $emailValue = (Read-Host "Email для Let's Encrypt [$emailDefault]").Trim()
        if ([string]::IsNullOrWhiteSpace($emailValue)) {
            $emailValue = $emailDefault
        }
        Set-Variable -Name Email -Scope Script -Value $emailValue
        Set-Variable -Name IssueCertificate -Scope Script -Value ([switch](Read-YesNo -Prompt "Выпустить/обновить сертификат Let's Encrypt сейчас" -Default $false))
        if ($IssueCertificate) {
            Set-Variable -Name LetsEncryptStaging -Scope Script -Value ([switch](Read-YesNo -Prompt "Использовать staging Let's Encrypt" -Default $false))
        }
    }

    $adminLoginDefault = if (-not [string]::IsNullOrWhiteSpace($existing["BOOTSTRAP_ADMIN_LOGIN"])) { $existing["BOOTSTRAP_ADMIN_LOGIN"] } else { "admin" }
    $adminLoginValue = (Read-Host "Логин первичного администратора [$adminLoginDefault]").Trim()
    if ([string]::IsNullOrWhiteSpace($adminLoginValue)) {
        $adminLoginValue = $adminLoginDefault
    }
    Set-Variable -Name AdminLogin -Scope Script -Value $adminLoginValue

    $adminOptions = @(
        [pscustomobject]@{ Key = "keep"; Label = "Оставить пароль из .env"; Description = "Ничего не менять, если пароль уже задан." },
        [pscustomobject]@{ Key = "manual"; Label = "Ввести пароль"; Description = "Записать указанный BOOTSTRAP_ADMIN_PASSWORD в .env." },
        [pscustomobject]@{ Key = "generate"; Label = "Сгенерировать пароль"; Description = "Скрипт создаст сильный пароль и покажет его один раз." }
    )
    $adminDefault = if ([string]::IsNullOrWhiteSpace($existing["BOOTSTRAP_ADMIN_PASSWORD"])) { 2 } else { 1 }
    $adminChoice = Read-MenuChoice -Title "Пароль первичного администратора" -Items $adminOptions -DefaultIndex $adminDefault
    if ($adminChoice.Key -eq "manual") {
        $value = Read-SecretText -Prompt "Введите BOOTSTRAP_ADMIN_PASSWORD"
        if ([string]::IsNullOrWhiteSpace($value)) {
            throw "Пароль администратора не может быть пустым."
        }
        Set-Variable -Name AdminPassword -Scope Script -Value $value
    }
    elseif ($adminChoice.Key -eq "generate") {
        Set-Variable -Name GenerateAdminPassword -Scope Script -Value ([switch]$true)
    }

    $pgOptions = @(
        [pscustomobject]@{ Key = "keep"; Label = "Оставить пароль PostgreSQL из .env"; Description = "Безопасно для существующей БД." },
        [pscustomobject]@{ Key = "manual"; Label = "Ввести пароль PostgreSQL"; Description = "Записать указанный POSTGRES_PASSWORD в .env." },
        [pscustomobject]@{ Key = "generate"; Label = "Сгенерировать PostgreSQL пароль"; Description = "Для новой БД или пересозданных volumes." }
    )
    $pgDefault = if ([string]::IsNullOrWhiteSpace($existing["POSTGRES_PASSWORD"]) -or $existing["POSTGRES_PASSWORD"] -eq "cctv") { 3 } else { 1 }
    $pgChoice = Read-MenuChoice -Title "Пароль PostgreSQL" -Items $pgOptions -DefaultIndex $pgDefault
    if ($pgChoice.Key -eq "manual") {
        $value = Read-SecretText -Prompt "Введите POSTGRES_PASSWORD"
        if ([string]::IsNullOrWhiteSpace($value)) {
            throw "Пароль PostgreSQL не может быть пустым."
        }
        Set-Variable -Name PostgresPassword -Scope Script -Value $value
    }
    elseif ($pgChoice.Key -eq "generate") {
        Set-Variable -Name GeneratePostgresPassword -Scope Script -Value ([switch]$true)
    }

    Set-Variable -Name Production -Scope Script -Value ([switch](Read-YesNo -Prompt "Production-режим" -Default ($Profile -in @("public", "with-nginx"))))
    Set-Variable -Name Pull -Scope Script -Value ([switch](Read-YesNo -Prompt "Сначала выполнить docker compose pull" -Default $false))
    Set-Variable -Name NoBuild -Scope Script -Value ([switch](-not (Read-YesNo -Prompt "Собирать Docker images перед запуском" -Default $true)))
    Set-Variable -Name NoStart -Scope Script -Value ([switch](-not (Read-YesNo -Prompt "Запустить контейнеры сейчас" -Default $true)))
    if (-not $NoStart) {
        Set-Variable -Name SkipHealth -Scope Script -Value ([switch](-not (Read-YesNo -Prompt "Проверить backend /health после запуска" -Default $true)))
    }
}

function Install-DockerDesktop {
    if ($DryRun) {
        Write-Host "+ winget install -e --id Docker.DockerDesktop --accept-package-agreements --accept-source-agreements"
        return
    }
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw "winget не найден. Установите Docker Desktop вручную и повторите запуск."
    }
    & winget install -e --id Docker.DockerDesktop --accept-package-agreements --accept-source-agreements
    Write-Warn "После установки запустите Docker Desktop, дождитесь готовности движка и повторите этот скрипт."
}

function Get-ProfileArgs {
    param([string]$SelectedProfile)
    switch ($SelectedProfile) {
        "core" {
            return @{
                Profiles = @("core")
                Services = @("backend", "mediamtx")
            }
        }
        "server" {
            return @{
                Profiles = @("server")
                Services = @()
            }
        }
        "server-cpu" {
            return @{
                Profiles = @("server-cpu")
                Services = @()
            }
        }
        "server-gpu" {
            return @{
                Profiles = @("server-gpu")
                Services = @()
            }
        }
        "public" {
            return @{
                Profiles = @("server", "public")
                Services = @()
            }
        }
        "with-processor" {
            return @{
                Profiles = @("core", "with-processor")
                Services = @()
            }
        }
        "with-gpu" {
            return @{
                Profiles = @("core", "with-gpu")
                Services = @()
            }
        }
        "processor-nvidia" {
            return @{
                Profiles = @("core", "processor-nvidia")
                Services = @()
            }
        }
        "with-nginx" {
            return @{
                Profiles = @("server", "with-nginx")
                Services = @()
            }
        }
    }
}

function Invoke-Compose {
    param(
        [string[]]$Profiles,
        [string[]]$Services,
        [string]$ProjectName
    )
    $args = @("compose", "-p", $ProjectName)
    foreach ($item in $Profiles) {
        $args += @("--profile", $item)
    }
    if ($Pull) {
        $pullArgs = $args + @("pull")
        Write-Host "+ docker $($pullArgs -join ' ')"
        if (-not $DryRun) {
            & docker @pullArgs
        }
    }
    $args += @("up", "-d")
    if (-not $NoBuild) {
        $args += "--build"
    }
    foreach ($service in $Services) {
        $args += $service
    }
    Write-Host "+ docker $($args -join ' ')"
    if (-not $DryRun) {
        & docker @args
    }
}

function Wait-BackendHealth {
    param([int]$Port)
    $url = "http://127.0.0.1:$Port/health"
    Write-Step "Проверяю backend: $url"
    for ($i = 1; $i -le 60; $i++) {
        try {
            $response = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 2
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 300) {
                Write-Ok "Backend отвечает"
                return $true
            }
        }
        catch {
            Start-Sleep -Seconds 2
        }
    }
    Write-Warn "Backend не ответил за 120 секунд. Проверьте docker compose ps и docker logs."
    return $false
}

if ($InteractiveMode) {
    Invoke-InteractiveWizard
}

if ($LocalOnly -and $ExposeBackend) {
    throw "Нельзя одновременно указать -LocalOnly и -ExposeBackend."
}
if ($IssueCertificate -and [string]::IsNullOrWhiteSpace($Domain)) {
    throw "Для -IssueCertificate нужен -Domain."
}
if ($IssueCertificate -and [string]::IsNullOrWhiteSpace($Email)) {
    throw "Для -IssueCertificate нужен -Email."
}

Set-Location -LiteralPath $Root
$projectName = Get-ComposeProjectName
$env:COMPOSE_PROJECT_NAME = $projectName
$lanIp = Get-LanIp
$envCreated = $false
$generatedAdminPassword = ""

Write-Step "Проект: $Root"
Write-Step "Docker Compose project: $projectName"

$dockerCliAvailable = Test-DockerCliAvailable
$dockerReady = $false
if ($dockerCliAvailable) {
    $dockerReady = Test-DockerReady
}

if (-not $dockerReady) {
    if ($DryRun) {
        Write-Warn "Docker не готов. Dry-run продолжится без выполнения docker compose."
    }
    elseif (-not $dockerCliAvailable -and $InstallDocker) {
        Write-Step "Docker не найден. Запускаю установку Docker Desktop."
        Install-DockerDesktop
        exit 0
    }
    elseif (-not $dockerCliAvailable) {
        Write-Fail "Docker не найден."
        Write-Host "Повторите с -InstallDocker или установите Docker Desktop вручную."
        exit 2
    }
    else {
        Write-Fail "Docker установлен, но движок не отвечает."
        Write-Host "Запустите Docker Desktop, дождитесь статуса Running и повторите команду."
        exit 2
    }
}

if (-not (Test-Path -LiteralPath $EnvPath)) {
    if (-not (Test-Path -LiteralPath $EnvExamplePath)) {
        throw ".env.example не найден."
    }
    $pgDataVolumeName = "${projectName}_pgdata"
    if ($dockerCliAvailable -and (Test-DockerVolumeExists -Name $pgDataVolumeName) -and -not $AllowEnvRecreate) {
        $message = ".env отсутствует, но Docker volume $pgDataVolumeName уже существует. Автогенерация нового .env может сломать доступ к существующей БД. Восстановите .env из бэкапа/контейнера или повторите с -AllowEnvRecreate, если точно нужен новый .env."
        if ($DryRun) {
            Write-Warn $message
        }
        else {
            Write-Fail $message
            exit 3
        }
    }
    Write-Step "Создаю .env из .env.example"
    if (-not $DryRun) {
        Copy-Item -LiteralPath $EnvExamplePath -Destination $EnvPath
    }
    $envCreated = $true
}

$lines = if ($DryRun -and -not (Test-Path -LiteralPath $EnvPath)) {
    Read-EnvLines -Path $EnvExamplePath
}
else {
    Read-EnvLines -Path $EnvPath
}
$current = Read-EnvValues -Lines $lines

$selectedDomain = $Domain
if ([string]::IsNullOrWhiteSpace($selectedDomain)) {
    if (-not [string]::IsNullOrWhiteSpace($current["DOMAIN"])) {
        $selectedDomain = $current["DOMAIN"]
    }
    else {
        $selectedDomain = "localhost"
    }
}
$selectedDomain = $selectedDomain.Trim().TrimEnd(".").ToLowerInvariant()

$backendBind = "0.0.0.0"
if ($LocalOnly) {
    $backendBind = "127.0.0.1"
}
elseif (($Profile -eq "public" -or $Profile -eq "with-nginx") -and -not $ExposeBackend) {
    $backendBind = "127.0.0.1"
}

$environment = "production"
if (-not $envCreated -and -not $Production -and $Profile -ne "public" -and $Profile -ne "with-nginx" -and -not [string]::IsNullOrWhiteSpace($current["ENVIRONMENT"])) {
    $environment = $current["ENVIRONMENT"]
}

$allowedHosts = @("127.0.0.1", "localhost")
if (-not [string]::IsNullOrWhiteSpace($lanIp)) {
    $allowedHosts += $lanIp
}
if ($selectedDomain -ne "localhost" -and $selectedDomain -ne "127.0.0.1") {
    $allowedHosts += $selectedDomain
}

$corsOrigins = @(
    "http://127.0.0.1:$BackendPort",
    "http://localhost:$BackendPort"
)
if (-not [string]::IsNullOrWhiteSpace($lanIp)) {
    $corsOrigins += "http://${lanIp}:$BackendPort"
}
if ($selectedDomain -ne "localhost" -and $selectedDomain -ne "127.0.0.1") {
    $corsOrigins += "http://$selectedDomain"
    $corsOrigins += "https://$selectedDomain"
}

$updates = [ordered]@{
    "DOMAIN" = $selectedDomain
    "BACKEND_BIND" = $backendBind
    "BACKEND_PORT" = "$BackendPort"
    "ENVIRONMENT" = $environment
    "CORS_ORIGINS" = ConvertTo-JsonStringArray -Values $corsOrigins
    "ALLOWED_HOSTS" = ConvertTo-JsonStringArray -Values $allowedHosts
    "ENABLE_DOCS" = "false"
    "ALLOW_LEGACY_QUERY_TOKENS" = "false"
}

if ($Profile -eq "public" -or $Profile -eq "with-nginx") {
    $updates["NGINX_HTTPS_ENABLED"] = if ($IssueCertificate) { "true" } else { $current["NGINX_HTTPS_ENABLED"] }
    if ([string]::IsNullOrWhiteSpace($updates["NGINX_HTTPS_ENABLED"])) {
        $updates["NGINX_HTTPS_ENABLED"] = "false"
    }
}

$postgresPasswordUpdated = $false
if (-not [string]::IsNullOrWhiteSpace($PostgresPassword)) {
    $updates["POSTGRES_PASSWORD"] = $PostgresPassword
    $postgresPasswordUpdated = $true
}
elseif ($GeneratePostgresPassword -or $envCreated -or [string]::IsNullOrWhiteSpace($current["POSTGRES_PASSWORD"]) -or ($RotateWeakSecrets -and (Test-WeakValue -Value $current["POSTGRES_PASSWORD"] -MinimumLength 16 -BlockedValues @("cctv", "postgres", "password", "changeme")))) {
    $updates["POSTGRES_PASSWORD"] = New-UrlSafeSecret -Bytes 24
    $postgresPasswordUpdated = $true
}
if ((Test-WeakValue -Value $current["JWT_SECRET"] -MinimumLength 32 -BlockedValues @("changeme", "change-me", "changeme-generate-with-openssl-rand-hex-32")) -and ($envCreated -or $RotateWeakSecrets -or [string]::IsNullOrWhiteSpace($current["JWT_SECRET"]) -or $current["JWT_SECRET"] -like "changeme*")) {
    $updates["JWT_SECRET"] = New-HexSecret -Bytes 32
}
if ((Test-WeakValue -Value $current["PROCESSOR_API_KEY"] -MinimumLength 24 -BlockedValues @("changeme", "processor-secret-key-2026", "changeme-generate-with-openssl-rand-hex-24")) -and ($envCreated -or $RotateWeakSecrets -or [string]::IsNullOrWhiteSpace($current["PROCESSOR_API_KEY"]) -or $current["PROCESSOR_API_KEY"] -like "changeme*")) {
    $updates["PROCESSOR_API_KEY"] = New-UrlSafeSecret -Bytes 32
}
if ([string]::IsNullOrWhiteSpace($current["TOTP_ENCRYPTION_KEY"]) -or ($RotateWeakSecrets -and (Test-WeakValue -Value $current["TOTP_ENCRYPTION_KEY"] -MinimumLength 32 -BlockedValues @("changeme")))) {
    $updates["TOTP_ENCRYPTION_KEY"] = New-FernetKey
}
if ([string]::IsNullOrWhiteSpace($current["PROCESSOR_MEDIA_TOKEN"])) {
    $updates["PROCESSOR_MEDIA_TOKEN"] = New-UrlSafeSecret -Bytes 24
}
$adminPasswordUpdated = $false
if (-not [string]::IsNullOrWhiteSpace($AdminLogin)) {
    $updates["BOOTSTRAP_ADMIN_LOGIN"] = $AdminLogin
}
elseif ([string]::IsNullOrWhiteSpace($current["BOOTSTRAP_ADMIN_LOGIN"])) {
    $updates["BOOTSTRAP_ADMIN_LOGIN"] = "admin"
}
if (-not [string]::IsNullOrWhiteSpace($AdminPassword)) {
    $updates["BOOTSTRAP_ADMIN_PASSWORD"] = $AdminPassword
    $adminPasswordUpdated = $true
}
elseif ($GenerateAdminPassword -or [string]::IsNullOrWhiteSpace($current["BOOTSTRAP_ADMIN_PASSWORD"]) -or ($envCreated -and $current["BOOTSTRAP_ADMIN_PASSWORD"] -eq "")) {
    $generatedAdminPassword = New-UrlSafeSecret -Bytes 24
    $updates["BOOTSTRAP_ADMIN_PASSWORD"] = $generatedAdminPassword
    $adminPasswordUpdated = $true
}
if ($envCreated -or $generatedAdminPassword -or $adminPasswordUpdated -or $Production -or $Profile -eq "public" -or $Profile -eq "with-nginx") {
    $updates["ALLOW_DEFAULT_ADMIN"] = "false"
}

$newLines = Set-EnvLines -Lines $lines -Updates $updates
if ($DryRun) {
    Write-Step "Dry run: .env был бы обновлен"
}
else {
    [System.IO.File]::WriteAllText($EnvPath, (($newLines -join [Environment]::NewLine) + [Environment]::NewLine), [System.Text.UTF8Encoding]::new($false))
    Write-Ok ".env готов"
}

if ($IssueCertificate) {
    $python = Get-Command py -ErrorAction SilentlyContinue
    $certArgs = @()
    if ($python) {
        $certExe = "py"
        $certArgs += "-3"
    }
    else {
        $python = Get-Command python -ErrorAction SilentlyContinue
        if (-not $python) {
            throw "Для выпуска сертификата нужен Python: py -3 или python."
        }
        $certExe = "python"
    }
    $certArgs += @("scripts\setup_public_https.py", "--domain", $selectedDomain, "--email", $Email)
    if ($LetsEncryptStaging) {
        $certArgs += "--staging"
    }
    if ($DryRun) {
        $certArgs += "--dry-run"
    }
    Write-Host "+ $certExe $($certArgs -join ' ')"
    if (-not $DryRun) {
        & $certExe @certArgs
    }
}

$profileArgs = Get-ProfileArgs -SelectedProfile $Profile
if ($NoStart) {
    Write-Step "Запуск контейнеров пропущен: -NoStart"
}
else {
    Invoke-Compose -Profiles $profileArgs.Profiles -Services $profileArgs.Services -ProjectName $projectName
}

if (-not $NoStart -and -not $SkipHealth -and -not $DryRun) {
    Wait-BackendHealth -Port $BackendPort | Out-Null
}

$finalLines = if ($DryRun) { $newLines } else { Read-EnvLines -Path $EnvPath }
$final = Read-EnvValues -Lines $finalLines
$adminLogin = if ([string]::IsNullOrWhiteSpace($final["BOOTSTRAP_ADMIN_LOGIN"])) { "admin" } else { $final["BOOTSTRAP_ADMIN_LOGIN"] }
$adminPassword = $final["BOOTSTRAP_ADMIN_PASSWORD"]
$localBackend = "http://127.0.0.1:$BackendPort"
$lanBackend = if (-not [string]::IsNullOrWhiteSpace($lanIp)) { "http://${lanIp}:$BackendPort" } else { "" }

Write-Host ""
Write-Host "CCTV запущен/подготовлен" -ForegroundColor Cyan
Write-Host "Профиль Docker: $Profile"
Write-Host "Файл настроек: $EnvPath"
Write-Host "Backend внутри Docker: http://backend:8000"
Write-Host "Backend на этом ПК: $localBackend"
if ($backendBind -eq "0.0.0.0" -and -not [string]::IsNullOrWhiteSpace($lanBackend)) {
    Write-Host "Backend в локальной сети: $lanBackend"
}
elseif (-not [string]::IsNullOrWhiteSpace($lanBackend)) {
    Write-Host "Backend в локальной сети: закрыт прямым bind, используйте nginx или -ExposeBackend"
}
if ($Profile -eq "public" -or $Profile -eq "with-nginx") {
    Write-Host "nginx HTTP: http://localhost"
    if ($selectedDomain -ne "localhost" -and $selectedDomain -ne "127.0.0.1") {
        Write-Host "Домен: https://$selectedDomain"
    }
}
Write-Host "Логин администратора для чистой БД: $adminLogin"
if ([string]::IsNullOrWhiteSpace($adminPassword)) {
    Write-Warn "Пароль администратора не задан в .env"
}
elseif (-not [string]::IsNullOrWhiteSpace($generatedAdminPassword)) {
    Write-Host "Пароль администратора для чистой БД: $generatedAdminPassword"
    Write-Warn "Сохраните этот пароль: он показан только при генерации."
}
elseif ($adminPasswordUpdated) {
    Write-Host "Пароль администратора для чистой БД: записан в .env"
}
else {
    Write-Host "Пароль администратора для чистой БД: задан в .env"
}
if ($postgresPasswordUpdated) {
    Write-Host "Пароль PostgreSQL: обновлен в .env"
}
else {
    Write-Host "Пароль PostgreSQL: взят из .env"
}
Write-Host "Health: $localBackend/health"
Write-Warn "BOOTSTRAP_ADMIN_* применяется только при первой инициализации пустой БД. Если БД уже создана, пароль существующего admin не меняется."
if ($RotateWeakSecrets) {
    Write-Warn "Если была пересоздана POSTGRES_PASSWORD при существующем volume БД, может потребоваться пересоздание БД или ручная смена пароля PostgreSQL."
}
