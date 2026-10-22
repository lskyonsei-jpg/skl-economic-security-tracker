# SKL Economic Security Tracker — 사이트 설정 (Cloudflare 토큰 / 접속 비밀번호)
#
# 둘 다 최초 1회만 하면 되고, 값을 바꿀 때 다시 실행한다.
# 입력한 값은 화면에도 로그에도 남지 않는다.

$ErrorActionPreference = 'Stop'
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$TokenFile = Join-Path $Here '.cf_api_token.xml'
$ConfigFile = Join-Path $Here 'site_config.json'

function Write-Rule { Write-Host ('-' * 66) -ForegroundColor Gray }

function Fail {
    param([string]$Text)
    Write-Host ''
    Write-Host "  $Text" -ForegroundColor Red
    Write-Host ''
    exit 1
}

function Read-Secret {
    <#  Read-Host -AsSecureString 로 받아 평문으로 돌려준다.
        화면에는 아무것도 보이지 않는다.  #>
    param([string]$Prompt)
    $Secure = Read-Host $Prompt -AsSecureString
    $Ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secure)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($Ptr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($Ptr) }
}

function Get-Token {
    if (-not (Test-Path -LiteralPath $TokenFile)) { return $null }
    $Secure = Import-Clixml -LiteralPath $TokenFile
    $Ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secure)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($Ptr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($Ptr) }
}

# --- [1] Cloudflare 토큰 ----------------------------------------------------
function Set-CloudflareToken {
    Write-Host ''
    Write-Host '  [1] Cloudflare API 토큰' -ForegroundColor Cyan
    Write-Rule
    Write-Host ''
    if (Test-Path -LiteralPath $TokenFile) {
        Write-Host '  이미 저장된 토큰이 있습니다. 새 토큰으로 덮어씁니다.' -ForegroundColor Yellow
        Write-Host ''
    }
    Write-Host '  dash.cloudflare.com → My Profile → API Tokens 에서 만든 토큰입니다.'
    Write-Host '  권한은  Account / Cloudflare Pages / Edit  하나면 됩니다.'
    Write-Host ''
    Write-Host '    붙여넣기   Ctrl+V  또는  마우스 오른쪽 클릭'
    Write-Host '    화면에는 아무것도 나타나지 않습니다. 정상입니다.' -ForegroundColor DarkGray
    Write-Host ''

    $Plain = Read-Secret '  토큰'
    if ([string]::IsNullOrWhiteSpace($Plain)) { Fail '아무것도 입력되지 않았습니다. 저장하지 않았습니다.' }

    # 저장하기 전에 진짜 되는 토큰인지 확인한다.
    Write-Host ''
    Write-Host '  확인 중...' -ForegroundColor Cyan
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    try {
        $Check = Invoke-RestMethod -Uri 'https://api.cloudflare.com/client/v4/user/tokens/verify' `
            -Headers @{ Authorization = "Bearer $Plain" }
    } catch {
        Fail "Cloudflare 가 이 토큰을 거절했습니다. 저장하지 않았습니다. ($($_.Exception.Message))"
    }
    if (-not $Check.success) { Fail 'Cloudflare 가 이 토큰을 거절했습니다. 저장하지 않았습니다.' }

    ConvertTo-SecureString $Plain -AsPlainText -Force | Export-Clixml -LiteralPath $TokenFile
    $Plain = $null
    [GC]::Collect()

    Write-Host ''
    Write-Host '  저장 완료.  이 PC 의 현재 Windows 계정만 풀 수 있게 암호화했습니다.' -ForegroundColor Green
    Write-Host ''
}

# --- [2] 사이트 비밀번호 ----------------------------------------------------
function Set-SitePassword {
    Write-Host ''
    Write-Host '  [2] 사이트 접속 비밀번호' -ForegroundColor Cyan
    Write-Rule
    Write-Host ''

    if (-not (Test-Path -LiteralPath $TokenFile)) { Fail 'Cloudflare 토큰이 먼저 필요합니다. [1] 을 먼저 하세요.' }
    if (-not (Test-Path -LiteralPath $ConfigFile)) { Fail 'site_config.json 이 없습니다.' }
    $Config = Get-Content -LiteralPath $ConfigFile -Raw -Encoding UTF8 | ConvertFrom-Json

    Write-Host '  사이트에 들어갈 때 쓸 비밀번호를 정해 주세요.'
    Write-Host ''
    Write-Host '    아이디는  skl  로 고정입니다.' -ForegroundColor White
    Write-Host '    영문·숫자·기호만. 한글은 브라우저가 제대로 못 보냅니다.' -ForegroundColor DarkGray
    Write-Host '    8자 이상.' -ForegroundColor DarkGray
    Write-Host ''

    $Plain = Read-Secret '  비밀번호'
    if ($Plain.Length -lt 8) { Fail '8자 이상으로 정해 주세요. 저장하지 않았습니다.' }
    if ($Plain -notmatch '^[\x21-\x7E]+$') {
        Fail '영문·숫자·기호만 쓸 수 있습니다(공백·한글 불가). 저장하지 않았습니다.'
    }
    $Again = Read-Secret '  한 번 더'
    if ($Plain -cne $Again) { Fail '두 번 입력한 값이 다릅니다. 저장하지 않았습니다.' }
    $Again = $null

    Write-Host ''
    Write-Host '  Cloudflare 에 저장합니다...' -ForegroundColor Cyan

    # Cloudflare API 로 직접 넣는다. 예전에는
    #   $Plain | wrangler pages secret put ...
    # 처럼 파이프로 넘겼는데, PowerShell 이 값 끝에 줄바꿈을 붙여서 저장돼
    # 비밀번호가 영영 안 맞았다(2026-08-13). 파이프를 쓰지 않는다.
    #
    # production 과 preview 양쪽에 넣는다. 배포마다 생기는 <해시> 주소가
    # 어느 쪽으로 뜨든 비밀번호가 걸리게 하기 위해서다.
    $Entry = @{ type = 'secret_text'; value = $Plain }
    $Payload = @{
        deployment_configs = @{
            production = @{ env_vars = @{ SITE_PASSWORD = $Entry } }
            preview    = @{ env_vars = @{ SITE_PASSWORD = $Entry } }
        }
    } | ConvertTo-Json -Depth 8

    $Token = Get-Token
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $Uri = "https://api.cloudflare.com/client/v4/accounts/$($Config.account_id)/pages/projects/$($Config.project_name)"
    try {
        $Result = Invoke-RestMethod -Method PATCH -Uri $Uri -Body $Payload `
            -Headers @{ Authorization = "Bearer $Token"; 'Content-Type' = 'application/json' }
    } catch {
        Fail "저장에 실패했습니다. $($_.Exception.Message)"
    } finally {
        $Plain = $null; $Entry = $null; $Payload = $null; $Token = $null
        [GC]::Collect()
    }
    if (-not $Result.success) { Fail 'Cloudflare 가 거절했습니다.' }

    # Cloudflare Pages 는 배포 시점에 환경변수를 묶는다. 다시 올리지 않으면
    # 이미 올라가 있는 사이트에는 옛 비밀번호가 계속 걸려 있다.
    if (Test-Path -LiteralPath (Join-Path $Here 'site')) {
        Write-Host ''
        Write-Host '  새 비밀번호를 적용하려면 다시 올려야 합니다. 올립니다...' -ForegroundColor Cyan
        & (Join-Path $Here 'deploy_site.ps1')
        if ($LASTEXITCODE -ne 0) {
            Write-Host ''
            Write-Host '  비밀번호는 저장됐지만 재업로드에 실패했습니다.' -ForegroundColor Yellow
            Write-Host '  다음 업데이트 실행 때 반영됩니다.' -ForegroundColor Yellow
            Write-Host ''
            return
        }
    } else {
        Write-Host ''
        Write-Host '  다음 업데이트 실행 때 사이트에 반영됩니다.' -ForegroundColor DarkGray
    }

    Write-Host ''
    Write-Host '  저장 완료' -ForegroundColor Green
    Write-Host ''
    Write-Host ('    주소     {0}' -f $Config.url)
    Write-Host  '    아이디   skl'
    Write-Host ''
}

# --- [3] 사람별 계정 --------------------------------------------------------
#
# 계정 명단은 .site_users.json 에 남긴다. Cloudflare 는 한 번 넣은 secret 을
# 다시 읽려주지 않아서, 명단을 여기 두지 않으면 한 명 추가할 때마다 전원을
# 다시 만들어야 한다. 파일에 들어가는 것은 소금과 해시뿐이고 비밀번호 원문은
# 어디에도 저장되지 않는다.
$UsersFile = Join-Path $Here '.site_users.json'

function Get-SiteUsers {
    if (-not (Test-Path -LiteralPath $UsersFile)) { return @() }
    $Raw = Get-Content -LiteralPath $UsersFile -Raw -Encoding UTF8
    if ([string]::IsNullOrWhiteSpace($Raw)) { return @() }
    return @($Raw | ConvertFrom-Json)
}

function Get-PasswordHash {
    param([string]$Salt, [string]$Password)
    # 미들웨어의 hashPassword 와 같은 계산이어야 한다: SHA-256("소금:비밀번호")
    $Bytes = [Text.Encoding]::UTF8.GetBytes("${Salt}:${Password}")
    $Sha = [Security.Cryptography.SHA256]::Create()
    try { return -join ($Sha.ComputeHash($Bytes) | ForEach-Object { $_.ToString('x2') }) }
    finally { $Sha.Dispose() }
}

function Save-SiteUsers {
    <#  명단을 파일에 쓰고 Cloudflare 의 SITE_USERS 를 통째로 다시 넣는다.  #>
    param([array]$Users)

    $Config = Get-Content -LiteralPath $ConfigFile -Raw -Encoding UTF8 | ConvertFrom-Json
    $Json = if ($Users.Count -eq 0) { '[]' } else { ConvertTo-Json @($Users) -Depth 4 }
    Set-Content -LiteralPath $UsersFile -Value $Json -Encoding utf8

    $Lines = ($Users | ForEach-Object { '{0}:{1}:{2}' -f $_.name, $_.salt, $_.hash }) -join "`n"
    $Payload = @{
        deployment_configs = @{
            production = @{ env_vars = @{ SITE_USERS = @{ type = 'secret_text'; value = $Lines } } }
            preview    = @{ env_vars = @{ SITE_USERS = @{ type = 'secret_text'; value = $Lines } } }
        }
    } | ConvertTo-Json -Depth 8

    $Token = Get-Token
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $Uri = "https://api.cloudflare.com/client/v4/accounts/$($Config.account_id)/pages/projects/$($Config.project_name)"
    try {
        $Result = Invoke-RestMethod -Method PATCH -Uri $Uri -Body $Payload `
            -Headers @{ Authorization = "Bearer $Token"; 'Content-Type' = 'application/json' }
    } catch {
        Fail "Cloudflare 저장에 실패했습니다. $($_.Exception.Message)"
    } finally {
        $Token = $null; $Payload = $null
        [GC]::Collect()
    }
    if (-not $Result.success) { Fail 'Cloudflare 가 거절했습니다.' }

    # Pages 는 배포 시점에 환경변수를 묶는다. 다시 올리지 않으면 이미 올라가
    # 있는 사이트에는 옛 명단이 그대로 걸려 있다.
    if (Test-Path -LiteralPath (Join-Path $Here 'site')) {
        Write-Host ''
        Write-Host '  적용하려면 다시 올려야 합니다. 올립니다...' -ForegroundColor Cyan
        & (Join-Path $Here 'deploy_site.ps1')
        if ($LASTEXITCODE -ne 0) {
            Write-Host ''
            Write-Host '  명단은 저장됐지만 재업로드에 실패했습니다.' -ForegroundColor Yellow
            Write-Host '  다음 업데이트 실행 때 반영됩니다.' -ForegroundColor Yellow
        }
    } else {
        Write-Host ''
        Write-Host '  다음 업데이트 실행 때 사이트에 반영됩니다.' -ForegroundColor DarkGray
    }
}

function Set-SiteUsers {
    Write-Host ''
    Write-Host '  [3] 사람별 계정' -ForegroundColor Cyan
    Write-Rule
    Write-Host ''

    if (-not (Test-Path -LiteralPath $TokenFile)) { Fail 'Cloudflare 토큰이 먼저 필요합니다. [1] 을 먼저 하세요.' }
    if (-not (Test-Path -LiteralPath $ConfigFile)) { Fail 'site_config.json 이 없습니다.' }

    $Users = @(Get-SiteUsers)
    if ($Users.Count -eq 0) {
        Write-Host '  지금 발급된 계정이 없습니다. (아이디 skl 은 [2] 로 따로 관리합니다)'
    } else {
        Write-Host '  지금 발급된 계정'
        foreach ($u in $Users) {
            $Made = if ($u.created) { $u.created } else { '?' }
            Write-Host ("    {0,-16} {1}" -f $u.name, $Made)
        }
    }
    Write-Host ''
    Write-Host '   [a]  계정 만들기'
    Write-Host '   [d]  계정 지우기'
    Write-Host ''
    $Pick = (Read-Host '  선택 ').Trim().ToLower()

    if ($Pick -eq 'd') {
        if ($Users.Count -eq 0) { Fail '지울 계정이 없습니다.' }
        $Name = (Read-Host '  지울 아이디').Trim()
        $Left = @($Users | Where-Object { $_.name -cne $Name })
        if ($Left.Count -eq $Users.Count) { Fail "그런 아이디가 없습니다: $Name" }
        Save-SiteUsers $Left
        Write-Host ''
        Write-Host "  지웠습니다: $Name" -ForegroundColor Green
        Write-Host '  그 사람은 이제 들어올 수 없습니다.' -ForegroundColor DarkGray
        Write-Host ''
        return
    }
    if ($Pick -ne 'a') { Fail 'a 또는 d 를 골라 주세요.' }

    Write-Host ''
    Write-Host '  줄 사람의 아이디를 정해 주세요. 영문·숫자·밑줄만, 콜론(:) 불가.' -ForegroundColor DarkGray
    $Name = (Read-Host '  아이디').Trim()
    if ($Name -notmatch '^[A-Za-z0-9_]{2,32}$') { Fail '영문·숫자·밑줄 2~32자로 정해 주세요.' }
    if ($Name -ceq 'skl') { Fail 'skl 은 [2] 에서 관리합니다. 다른 이름을 쓰세요.' }
    if ($Users | Where-Object { $_.name -ceq $Name }) { Fail "이미 있는 아이디입니다: $Name" }

    Write-Host ''
    Write-Host '  비밀번호를 정해 주세요. 정한 값은 화면에 나오지 않으니 따로 적어 두세요.' -ForegroundColor Yellow
    Write-Host '    영문·숫자·기호만, 8자 이상. 한글은 브라우저가 제대로 못 보냅니다.' -ForegroundColor DarkGray
    Write-Host ''
    $Plain = Read-Secret '  비밀번호'
    if ($Plain.Length -lt 8) { Fail '8자 이상으로 정해 주세요. 저장하지 않았습니다.' }
    if ($Plain -notmatch '^[\x21-\x7E]+$') {
        Fail '영문·숫자·기호만 쓸 수 있습니다(공백·한글 불가). 저장하지 않았습니다.'
    }
    $Again = Read-Secret '  한 번 더'
    if ($Plain -cne $Again) { Fail '두 번 입력한 값이 다릅니다. 저장하지 않았습니다.' }
    $Again = $null

    # RandomNumberGenerator::Fill 은 .NET Core 3.0 부터다. 이 스크립트는
    # Windows PowerShell 5.1(.NET Framework)에서도 돌아야 하므로 Create() 로
    # 만들어 GetBytes 를 쓴다. 양쪽에서 다 된다.
    $SaltBytes = New-Object byte[] 16
    $Rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $Rng.GetBytes($SaltBytes) } finally { $Rng.Dispose() }
    $Salt = -join ($SaltBytes | ForEach-Object { $_.ToString('x2') })
    $Hash = Get-PasswordHash $Salt $Plain
    $Plain = $null
    [GC]::Collect()

    $Users += [pscustomobject]@{
        name    = $Name
        salt    = $Salt
        hash    = $Hash
        created = (Get-Date).ToString('yyyy-MM-dd')
    }

    Write-Host ''
    Write-Host '  Cloudflare 에 저장합니다...' -ForegroundColor Cyan
    Save-SiteUsers $Users

    $Config = Get-Content -LiteralPath $ConfigFile -Raw -Encoding UTF8 | ConvertFrom-Json
    Write-Host ''
    Write-Host '  만들었습니다. 아래 두 가지를 그 사람에게 전해 주세요.' -ForegroundColor Green
    Write-Host ''
    Write-Host ('    주소     {0}' -f $Config.url)
    Write-Host ('    아이디   {0}' -f $Name)
    Write-Host  '    비밀번호  방금 정한 값 (여기에는 표시하지 않습니다)'
    Write-Host ''
    Write-Host '  비밀번호는 저장해 두지 않으므로 잊으면 다시 만들어야 합니다.' -ForegroundColor DarkGray
    Write-Host ''
}

# --- 메뉴 -------------------------------------------------------------------
Write-Host ''
Write-Host ('=' * 66) -ForegroundColor Cyan
Write-Host '  SKL Economic Security Tracker — 사이트 설정' -ForegroundColor Cyan
Write-Host ('=' * 66) -ForegroundColor Cyan
Write-Host ''

$TokenState = if (Test-Path -LiteralPath $TokenFile) { '저장됨' } else { '없음' }
Write-Host '  지금 상태' -ForegroundColor White
Write-Rule
Write-Host ("    Cloudflare 토큰    {0}" -f $TokenState)
if (Test-Path -LiteralPath $ConfigFile) {
    $Url = (Get-Content -LiteralPath $ConfigFile -Raw -Encoding UTF8 | ConvertFrom-Json).url
    Write-Host ("    사이트 주소        {0}" -f $Url)
}
Write-Rule
Write-Host ''
Write-Host '  무엇을 할까요?   번호를 누르고 Enter' -ForegroundColor White
Write-Host ''
Write-Host '   [1]  Cloudflare 토큰 저장' -ForegroundColor Cyan
Write-Host '        토큰을 새로 발급했거나 만료됐을 때.'
Write-Host ''
Write-Host '   [2]  내 비밀번호 설정  (아이디 skl)' -ForegroundColor Cyan
Write-Host '        본인이 들어갈 때 쓰는 비밀번호를 정하거나 바꿉니다.'
Write-Host ''
Write-Host '   [3]  다른 사람 계정 만들기 / 지우기' -ForegroundColor Cyan
Write-Host '        사람마다 아이디와 비밀번호를 따로 발급합니다.'
Write-Host '        지우면 그 사람만 못 들어오고 나머지는 그대로입니다.'
Write-Host ''

while ($true) {
    $Picked = (Read-Host '  선택 ').Trim()
    if ($Picked -eq '1') { Set-CloudflareToken; break }
    if ($Picked -eq '2') { Set-SitePassword; break }
    if ($Picked -eq '3') { Set-SiteUsers; break }
    Write-Host '  1, 2, 3 중 하나를 누르고 Enter 를 눌러 주세요.' -ForegroundColor Red
}
