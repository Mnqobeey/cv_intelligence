$ErrorActionPreference = 'Stop'

$projectRoot = 'C:\Users\ThandokuhleM_7dgopdd\Downloads\cv_parser_latest'
$pythonExe = 'C:\Users\ThandokuhleM_7dgopdd\AppData\Local\Programs\Python\Python313\python.exe'
$outputDir = Join-Path $projectRoot 'storage\outputs'

if (!(Test-Path $outputDir)) {
    New-Item -ItemType Directory -Path $outputDir | Out-Null
}

$cmd = 'cd /d "{0}" && "{1}" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 1>"{2}" 2>"{3}"' -f `
    $projectRoot, `
    $pythonExe, `
    (Join-Path $outputDir 'api_stdout.log'), `
    (Join-Path $outputDir 'api_stderr.log')

& cmd.exe /c "start \"cv-parser-api\" /b $cmd"
