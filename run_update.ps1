param([switch]$SetupOnly)

$ErrorActionPreference = 'Stop'
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvPython = Join-Path $Here '.venv\Scripts\python.exe'
$InstallMarker = Join-Path $Here '.venv\.install_complete'
$Requirements = Join-Path $Here 'requirements.txt'
$CredentialFile = Join-Path $Here '.gta_api_key.xml'
$StateFile = Join-Path $Here 'cache\state.json'

# 잠수함 패치 점검을 며칠 안 하면 경고하고 기본값을 [2]로 바꿀지.
# 2026-08-13에 28 -> 7로 줄였다. 이 값이 곧 "삭제나 유형 이름 변경을 모르고
# 지나갈 수 있는 최대 기간"이다. 매일 [1]로 돌리는 지금은 28일이 너무 길다.
$FullCheckDays = 7

# 아래 안내 문구의 '2008-01-01'은 auto_update.py의 START_DATE와 같아야 한다.
# START_DATE를 바꾸면 이 파일의 문구도 같이 고칠 것.

function Write-Rule { param([string]$Color = 'Gray') Write-Host ('-' * 66) -ForegroundColor $Color }

function Write-Title {
    param([string]$Text)
    Write-Host ''
    Write-Host ('=' * 66) -ForegroundColor Cyan
    Write-Host "  $Text" -ForegroundColor Cyan
    Write-Host ('=' * 66) -ForegroundColor Cyan
}

function Find-Python {
    $candidates = @(
        (Get-Command py -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -ErrorAction SilentlyContinue),
        (Get-Command python -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -ErrorAction SilentlyContinue),
        (Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe')
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }
    if (-not $candidates) { throw 'Python을 찾지 못했습니다. Codex 앱을 열고 다시 시도해 주세요.' }
    return $candidates[0]
}

Write-Title 'SKL Economic Security Tracker 업데이트'

# --- 설치 -------------------------------------------------------------------
# 표시 파일에 requirements.txt의 해시를 적어 둔다. 예전에는 파일이 "있는지"만
# 봤는데, 그러면 requirements.txt에 패키지를 추가해도 재설치가 일어나지 않아
# 없는 패키지를 부르며 죽었다. 내용이 바뀌면 다시 설치한다.
$RequirementsHash = (Get-FileHash -LiteralPath $Requirements -Algorithm SHA256).Hash
$InstalledHash = $null
if (Test-Path -LiteralPath $InstallMarker) {
    $InstalledHash = (Get-Content -LiteralPath $InstallMarker -Raw -Encoding UTF8).Trim()
}

$PipReady = $false
if (Test-Path -LiteralPath $VenvPython) {
    & $VenvPython -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('pip') else 1)"
    $PipReady = ($LASTEXITCODE -eq 0)
}

if ($InstalledHash -ne $RequirementsHash -or -not $PipReady) {
    if ($InstalledHash) {
        Write-Host '  [설정] 필요한 패키지가 바뀌었습니다. 추가로 설치합니다.' -ForegroundColor Yellow
    } else {
        Write-Host '  [최초 설정] 실행 환경을 준비합니다. 몇 분 걸립니다.' -ForegroundColor Yellow
    }
    if (-not (Test-Path -LiteralPath $VenvPython)) {
        $BasePython = Find-Python
        if ((Split-Path -Leaf $BasePython) -eq 'py.exe') { & $BasePython -3 -m venv (Join-Path $Here '.venv') }
        else { & $BasePython -m venv (Join-Path $Here '.venv') }
        if ($LASTEXITCODE -ne 0) { throw '실행 환경 생성에 실패했습니다.' }
    }
    if (-not $PipReady) {
        Write-Host '  pip 설치 상태를 복구합니다.' -ForegroundColor Yellow
        & $VenvPython -m ensurepip --upgrade
        if ($LASTEXITCODE -ne 0) { throw 'pip 복구에 실패했습니다. Python 설치 상태를 확인해 주세요.' }
    }
    & $VenvPython -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) { throw 'pip 준비에 실패했습니다.' }
    & $VenvPython -m pip install -r $Requirements
    if ($LASTEXITCODE -ne 0) { throw '필수 패키지 설치에 실패했습니다.' }
    Set-Content -LiteralPath $InstallMarker -Value $RequirementsHash -Encoding utf8
    Write-Host '  설치 완료' -ForegroundColor Green
}

if ($SetupOnly) {
    Write-Host '  실행 환경 확인 완료' -ForegroundColor Green
    exit 0
}

if (-not (Test-Path -LiteralPath $CredentialFile)) {
    Write-Host ''
    Write-Host '  [최초 설정] GTA Full Access API key를 입력해 주세요.' -ForegroundColor Yellow
    Write-Host '  현재 Windows 사용자만 복호화할 수 있게 암호화되어 저장됩니다.'
    $SecureKey = Read-Host '  GTA API key' -AsSecureString
    $SecureKey | Export-Clixml -LiteralPath $CredentialFile
}

# --- 현재 상태 --------------------------------------------------------------
$LastDate = $null
$LastRows = $null
$LastFull = $null
if (Test-Path -LiteralPath $StateFile) {
    $State = Get-Content -LiteralPath $StateFile -Raw -Encoding UTF8 | ConvertFrom-Json
    $LastDate = $State.data_end_date
    $LastRows = $State.rows
    $LastFull = $State.last_full_rebuild
}

Write-Host ''
$Mode = 'full'
if ($LastDate) {
    $DaysSinceFull = $null
    if ($LastFull) {
        $DaysSinceFull = ((Get-Date).Date - [datetime]::ParseExact($LastFull, 'yyyy-MM-dd', $null).Date).Days
    }

    Write-Host '  지금 갖고 있는 자료' -ForegroundColor White
    Write-Rule
    Write-Host ("    기간                2008-01-01 ~ {0}" -f $LastDate)
    Write-Host ("    건수                {0:N0}건" -f $LastRows)
    if ($LastFull) {
        if ($DaysSinceFull -eq 0) { $Ago = '오늘' } else { $Ago = "{0}일 전" -f $DaysSinceFull }
        $FullNote = "    마지막 잠수함 점검  {0} ({1})" -f $LastFull, $Ago
        if ($DaysSinceFull -ne $null -and $DaysSinceFull -ge $FullCheckDays) {
            Write-Host $FullNote -ForegroundColor Yellow
        } else {
            Write-Host $FullNote -ForegroundColor Green
        }
    }
    Write-Rule

    Write-Host ''
    Write-Host '  무엇을 할까요?   번호를 누르고 Enter' -ForegroundColor White
    Write-Rule
    Write-Host ''
    Write-Host '   [1]  빠른 업데이트' -NoNewline -ForegroundColor Cyan
    Write-Host '                              약 10분'
    Write-Host '        GTA에 "마지막 점검일 이후 손댄 것만" 물어서 그것만 받습니다.'
    Write-Host '        받아온 것 안에서는 새 건·수정을 정확히 잡습니다.'
    Write-Host '        단, GTA가 내용을 고치고도 손댄 티(last_updated)를 안 낸 건은'
    Write-Host '        애초에 받아오지도 못해 통째로 놓칩니다. 삭제도 확인 못 합니다.'
    Write-Host ''
    Write-Host '   [2]  잠수함 패치 점검' -NoNewline -ForegroundColor Cyan
    Write-Host '                           약 25분'
    Write-Host '        필터 없이 전부 다시 받아 [1]이 놓친 것까지 하나씩 대조합니다.'
    Write-Host '          - GTA가 손댄 티 없이 조용히 고친 것 (평가등급 재분류 등)'
    Write-Host '          - 조용히 지워버린 건'
    Write-Host '          - 조치 유형 이름을 통째로 갈아치운 것'
    Write-Host '        [1] 로는 이런 것이 보이지 않습니다. 대신할 방법이 없습니다.'
    Write-Host ''
    Write-Host '  BERT 분류는 두 경우 모두 새로 생긴 것만 돌립니다.'
    Write-Host ''
    if ($DaysSinceFull -ne $null -and $DaysSinceFull -ge $FullCheckDays) {
        Write-Host ("  잠수함 패치 점검을 한 지 {0}일 됐습니다. 이번엔 [2] 를 권합니다." -f $DaysSinceFull) -ForegroundColor Yellow
        $DefaultMode = '2'
    } else {
        $DefaultMode = '1'
    }
    Write-Host ("  그냥 Enter 를 누르면 [{0}] 로 진행합니다." -f $DefaultMode)
    Write-Host ''

    while ($true) {
        $Picked = (Read-Host '  선택 ').Trim()
        if ([string]::IsNullOrWhiteSpace($Picked)) { $Picked = $DefaultMode }
        if ($Picked -eq '1') { $Mode = 'incremental'; break }
        if ($Picked -eq '2') { $Mode = 'full'; break }
        Write-Host '  1 또는 2를 누르고 Enter 를 눌러 주세요.' -ForegroundColor Red
    }

} else {
    Write-Host '  현재 상태' -ForegroundColor White
    Write-Rule
    Write-Host '    최초 구축 (보유 자료 없음)' -ForegroundColor Yellow
    Write-Rule
    Write-Host ''
    Write-Host '  2008-01-01부터 전량을 받아 BERT로 새로 분류합니다.'
    Write-Host '  GPU 없이 약 6건/초라 여러 시간 걸립니다. 밤에 돌리시길 권합니다.'
}

# --- 종료일 입력 ------------------------------------------------------------
$Today = (Get-Date).ToString('yyyy-MM-dd')
Write-Host ''
Write-Host '  언제까지 받을까요?' -ForegroundColor White
Write-Host ("    그냥 Enter 를 누르면 오늘({0})까지 받습니다." -f $Today)

while ($true) {
    $Input = (Read-Host '    종료일 (YYYY-MM-DD)').Trim()
    if ([string]::IsNullOrWhiteSpace($Input)) { $EndDate = $Today; break }
    $Parsed = [datetime]::MinValue
    $Ok = [datetime]::TryParseExact($Input, 'yyyy-MM-dd', [Globalization.CultureInfo]::InvariantCulture, [Globalization.DateTimeStyles]::None, [ref]$Parsed)
    if (-not $Ok) { Write-Host '    형식이 맞지 않습니다. 예: 2026-08-17' -ForegroundColor Red; continue }
    if ($Parsed.Date -gt (Get-Date).Date) { Write-Host '    미래 날짜는 받을 수 없습니다.' -ForegroundColor Red; continue }
    if ($LastDate -and $Parsed.Date -lt [datetime]::ParseExact($LastDate, 'yyyy-MM-dd', $null).Date) {
        Write-Host ("    마지막 업데이트({0})보다 앞선 날짜입니다." -f $LastDate) -ForegroundColor Red
        continue
    }
    $EndDate = $Input; break
}

Write-Host ''
if ($Mode -eq 'incremental') {
    Write-Host ("  받는 범위    수정일 {0} ~ {1} (양끝 포함)" -f $LastDate, $EndDate) -ForegroundColor Cyan
} else {
    Write-Host ("  받는 범위    발표일 2008-01-01 ~ {0} 전량 (양끝 포함)" -f $EndDate) -ForegroundColor Cyan
}
if ($LastDate) {
    Write-Host ''
    Write-Host '  받은 뒤 직전 자료와 대조해 이렇게 나눕니다' -ForegroundColor White
    Write-Host '    새로 들어온 것   직전 자료에 없던 건'
    Write-Host '                     발표 후 며칠 만에 들어왔는지 따로 보여줍니다'
    Write-Host '    수정             내용이 바뀐 것'
    if ($Mode -eq 'incremental') {
        Write-Host '    삭제             확인하지 않음 ([2] 잠수함 패치 점검에서만 확인)'
    } else {
        Write-Host '    삭제             GTA에서 사라진 것'
    }
}

# --- 실행 -------------------------------------------------------------------
$SecureKey = Import-Clixml -LiteralPath $CredentialFile
$Ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecureKey)
try { $env:GTA_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($Ptr) }
finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($Ptr) }

try {
    & $VenvPython (Join-Path $Here 'auto_update.py') --end-date $EndDate --mode $Mode
    $ExitCode = $LASTEXITCODE
}
finally {
    Remove-Item -LiteralPath Env:GTA_API_KEY -ErrorAction SilentlyContinue
}

# 종료 코드 3 = 정상 종료했으나 새로 만든 파일이 없음 (변화 없음 또는 사용자 취소)
if ($ExitCode -eq 3) {
    Write-Host '  새로 만든 파일이 없어 폴더를 열지 않습니다.'
    exit 0
}
if ($ExitCode -ne 0) { exit $ExitCode }

# --- 사이트 갱신 -------------------------------------------------------------
# 여기서 실패해도 업데이트 자체는 이미 끝났다. 엑셀은 멀쩡하므로 경고만 하고
# output 폴더는 연다. 사이트만 옛 내용으로 남는다.
if (Test-Path -LiteralPath (Join-Path $Here 'site_config.json')) {
    Write-Host ''
    Write-Host '  변경 내역 사이트를 갱신합니다.' -ForegroundColor White
    Write-Rule

    # 이 블록에서 무슨 일이 나든 업데이트 결과(엑셀)는 이미 안전하다.
    # 예외로 전체가 죽지 않게 통째로 감싼다.
    try {
        & $VenvPython (Join-Path $Here 'publish_site.py')
        if ($LASTEXITCODE -ne 0) {
            Write-Host '    사이트 생성에 실패했습니다. 엑셀은 정상입니다.' -ForegroundColor Yellow
        } else {
            & (Join-Path $Here 'deploy_site.ps1')
            if ($LASTEXITCODE -ne 0) {
                Write-Host '    사이트 업로드에 실패했습니다. 엑셀은 정상입니다.' -ForegroundColor Yellow
            } else {
                $SiteUrl = (Get-Content -LiteralPath (Join-Path $Here 'site_config.json') -Raw -Encoding UTF8 | ConvertFrom-Json).url
                Write-Host ("    $SiteUrl") -ForegroundColor Cyan
            }
        }
    } catch {
        Write-Host ("    사이트 갱신 중 오류: " + $_.Exception.Message) -ForegroundColor Yellow
        Write-Host '    엑셀은 정상입니다.' -ForegroundColor Yellow
    }
    Write-Rule
}

Write-Host '  output 폴더를 엽니다.' -ForegroundColor Green
Start-Process explorer.exe -ArgumentList (Join-Path $Here 'output')
