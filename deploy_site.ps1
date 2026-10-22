# SKL Economic Security Tracker — site/ 를 Cloudflare Pages 로 올린다.
#
# 토큰은 .cf_api_token.xml (이 PC 의 이 Windows 계정만 복호화 가능) 에서 읽어
# 환경변수로 wrangler 에 넘기고, 끝나면 지운다. 화면에도 로그에도 찍지 않는다.
# 계정 ID·프로젝트 이름은 비밀이 아니라 site_config.json 에 평문으로 둔다.

param(
    # 올릴 폴더. 기본은 publish_site.py 가 만드는 site/.
    [string]$Path
)

$ErrorActionPreference = 'Stop'
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$TokenFile = Join-Path $Here '.cf_api_token.xml'
$ConfigFile = Join-Path $Here 'site_config.json'
if ([string]::IsNullOrWhiteSpace($Path)) { $SiteDir = Join-Path $Here 'site' }
else { $SiteDir = (Resolve-Path -LiteralPath $Path).Path }

function Fail { param([string]$Text) Write-Host "    $Text" -ForegroundColor Red; exit 1 }

if (-not (Test-Path -LiteralPath $SiteDir)) {
    Fail 'site 폴더가 없습니다. publish_site.py 를 먼저 실행해야 합니다.'
}
if (-not (Test-Path -LiteralPath $TokenFile)) {
    Fail 'Cloudflare 토큰이 없습니다. 사이트_설정.cmd 를 실행해 [1] 을 먼저 해 주세요.'
}
if (-not (Test-Path -LiteralPath $ConfigFile)) {
    Fail 'site_config.json 이 없습니다.'
}

$Config = Get-Content -LiteralPath $ConfigFile -Raw -Encoding UTF8 | ConvertFrom-Json
$AccountId = $Config.account_id
$ProjectName = $Config.project_name

if ([string]::IsNullOrWhiteSpace($AccountId) -or $AccountId -notmatch '^[0-9a-f]{32}$') {
    Fail 'site_config.json 의 account_id 가 비었거나 형식이 맞지 않습니다.'
}
if ([string]::IsNullOrWhiteSpace($ProjectName)) {
    Fail 'site_config.json 의 project_name 이 비어 있습니다.'
}

if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    Fail 'Node.js 를 찾지 못했습니다. https://nodejs.org 에서 설치해 주세요.'
}

# wrangler 는 이 폴더에 직접 설치해 쓴다. `npx wrangler@4 ...` 로 매번
# 받아오는 방식은 Windows 에서 "could not determine executable to run" 으로
# 죽었다. 없으면 여기서 한 번 설치한다.
$Wrangler = Join-Path $Here 'node_modules\.bin\wrangler.cmd'
if (-not (Test-Path -LiteralPath $Wrangler)) {
    Write-Host '    [최초 설정] 업로드 도구를 설치합니다. 1분쯤 걸립니다.' -ForegroundColor Yellow
    Push-Location $Here
    try { & npm install --no-fund --no-audit } finally { Pop-Location }
    if (-not (Test-Path -LiteralPath $Wrangler)) { Fail '업로드 도구 설치에 실패했습니다.' }
}

# 토큰 꺼내기
$Secure = Import-Clixml -LiteralPath $TokenFile
$Ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secure)
try { $Token = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($Ptr) }
finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($Ptr) }

$env:CLOUDFLARE_API_TOKEN = $Token
$env:CLOUDFLARE_ACCOUNT_ID = $AccountId

# functions/ 가 없으면 인증이 통째로 빠진다. 올리기 전에 막는다.
$MiddlewarePath = Join-Path $Here 'functions\_middleware.js'
if (-not (Test-Path -LiteralPath $MiddlewarePath)) {
    Remove-Item -LiteralPath Env:CLOUDFLARE_API_TOKEN -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath Env:CLOUDFLARE_ACCOUNT_ID -ErrorAction SilentlyContinue
    Fail 'functions\_middleware.js 가 없습니다. 인증 없이 올라가므로 중단합니다.'
}

Write-Host "    Cloudflare Pages 로 올립니다 ($ProjectName)" -ForegroundColor Cyan

$Output = ''
try {
    # --cwd 가 중요하다. wrangler 는 "올리는 폴더" 가 아니라 실행 위치의
    # functions/ 를 찾는다. 이걸 빼면 인증 미들웨어가 조용히 빠진 채로
    # 올라가 사이트가 열린다. 2026-08-13에 실제로 그렇게 새어나갔다.
    # --commit-dirty 는 git 저장소가 아니어도 경고 없이 진행하게 한다.
    & $Wrangler pages deploy $SiteDir `
        --cwd $Here `
        --project-name $ProjectName `
        --branch main `
        --commit-dirty=true 2>&1 | Tee-Object -Variable Lines
    $Code = $LASTEXITCODE
    $Output = ($Lines | Out-String)
}
finally {
    Remove-Item -LiteralPath Env:CLOUDFLARE_API_TOKEN -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath Env:CLOUDFLARE_ACCOUNT_ID -ErrorAction SilentlyContinue
}

if ($Code -ne 0) {
    Write-Host ''
    Write-Host '    업로드에 실패했습니다.' -ForegroundColor Red
    Write-Host '    토큰이 만료됐거나 프로젝트 이름이 다를 수 있습니다.'
    exit $Code
}

# --- 정말 잠겼는지 직접 확인한다 -------------------------------------------
# wrangler 가 성공했다고 잠긴 것은 아니다. 인증 없이 실제로 받아본다.
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

function Get-Status {
    param([string]$Url)
    try {
        $r = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 20 -ErrorAction Stop
        return [int]$r.StatusCode
    } catch {
        if ($_.Exception.Response) { return [int]$_.Exception.Response.StatusCode }
        return -1
    }
}

$Targets = @("$($Config.url)/?cb=$([DateTime]::Now.Ticks)")
if ($Output -match 'https://([0-9a-f]{8})\.[^\s]*pages\.dev') {
    $DeployHash = $Matches[1]
    $Targets += "https://$DeployHash.$ProjectName.pages.dev/?cb=$([DateTime]::Now.Ticks)"
}

Start-Sleep -Seconds 4
Write-Host ''
Write-Host '    잠김 확인 중...' -ForegroundColor Cyan

# 판정 기준
#   200번대           내용이 실제로 나갔다 = 노출. 실패 처리한다.
#   401 / 403 / 503   막혔다. 정상.
#   그 밖(404·5xx·응답없음)  아직 안 열렸거나 닿지 못했다. 내용이 나간 것은
#                     아니므로 실패로 보지 않고 알리기만 한다. 갓 만든 배포
#                     주소는 몇 초간 404 가 뜬다.
$Leaked = @()
$Unknown = @()
foreach ($Target in $Targets) {
    $Shown = ($Target -split '\?')[0]
    $Status = -1
    # 갓 만든 주소가 준비될 시간을 준다. 판정이 서면 곧바로 멈춘다.
    foreach ($Attempt in 1..5) {
        $Status = Get-Status $Target
        if ($Status -ge 200 -and $Status -lt 300) { break }
        if ($Status -eq 401 -or $Status -eq 403 -or $Status -eq 503) { break }
        if ($Attempt -lt 5) { Start-Sleep -Seconds 3 }
    }

    if ($Status -ge 200 -and $Status -lt 300) {
        Write-Host ("      {0}  열림  {1}" -f $Status, $Shown) -ForegroundColor Red
        $Leaked += $Shown
    } elseif ($Status -eq 401 -or $Status -eq 403 -or $Status -eq 503) {
        Write-Host ("      {0}  잠김  {1}" -f $Status, $Shown) -ForegroundColor Green
    } else {
        Write-Host ("      {0}  확인 못 함 (내용은 안 나감)  {1}" -f $Status, $Shown) -ForegroundColor DarkGray
        $Unknown += $Shown
    }
}

if ($Leaked.Count -gt 0) {
    Write-Host ''
    Write-Host '  ############################################################' -ForegroundColor Red
    Write-Host '  인증이 걸리지 않았습니다. 내용이 공개 상태입니다.' -ForegroundColor Red
    Write-Host '  Cloudflare 대시보드에서 이 배포를 즉시 지우세요.' -ForegroundColor Red
    Write-Host '  ############################################################' -ForegroundColor Red
    exit 1
}

Write-Host '    업로드 완료' -ForegroundColor Green
exit 0
