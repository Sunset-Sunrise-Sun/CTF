$ErrorActionPreference = 'Stop'
Push-Location "$PSScriptRoot/../backend"
python -m ruff check app tests
if ($LASTEXITCODE -ne 0) { throw 'Backend lint failed' }
python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw 'Backend tests failed' }
Pop-Location
Push-Location "$PSScriptRoot/../frontend"
npm run build
if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed' }
Pop-Location
