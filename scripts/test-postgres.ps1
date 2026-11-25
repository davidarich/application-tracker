<#
.SYNOPSIS
Runs the test suite against PostgreSQL in a throwaway Docker container.

.DESCRIPTION
Starts postgres:17 on localhost (port 55432 by default, so it doesn't clash
with a PostgreSQL you already run), waits until it accepts connections, runs
`python manage.py test` with DJANGO_DATABASE_URL pointing at it, then removes
the container, whether the tests pass or not. Needs Docker, and the project's
virtual environment activated (or python on the PATH).

.EXAMPLE
./scripts/test-postgres.ps1
./scripts/test-postgres.ps1 -Port 55433 tracker.tests.test_jobs
#>
param(
    [int]$Port = 55432,
    # Passed on to `manage.py test`, e.g. a test module.
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$TestArgs = @()
)

$ErrorActionPreference = "Stop"
$name = "app-tracker-test-pg-$Port"
$password = "app_tracker_test"

docker run --detach --rm --name $name `
    --env POSTGRES_USER=app_tracker `
    --env POSTGRES_PASSWORD=$password `
    --env POSTGRES_DB=app_tracker `
    --publish "127.0.0.1:${Port}:5432" `
    postgres:17 | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Couldn't start the PostgreSQL container." }

$previousUrl = $env:DJANGO_DATABASE_URL
try {
    Write-Host "Waiting for PostgreSQL on port $Port..."
    $ready = $false
    foreach ($attempt in 1..60) {
        docker exec $name pg_isready --username=app_tracker --dbname=app_tracker 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) { $ready = $true; break }
        Start-Sleep -Seconds 1
    }
    if (-not $ready) { throw "PostgreSQL didn't become ready within 60 seconds." }

    $env:DJANGO_DATABASE_URL = "postgres://app_tracker:${password}@127.0.0.1:${Port}/app_tracker"
    python manage.py test @TestArgs
    $testExitCode = $LASTEXITCODE
}
finally {
    $env:DJANGO_DATABASE_URL = $previousUrl
    docker stop $name | Out-Null
}
exit $testExitCode
