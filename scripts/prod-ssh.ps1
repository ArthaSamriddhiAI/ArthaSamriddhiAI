<#
.SYNOPSIS
    SSH wrapper for the ArthaSamriddhiAI prod EC2 instance.

.DESCRIPTION
    Reads the PEM path from $env:ARTHA_PROD_PEM, defaulting to
    D:\Desktop\ArthaSamriddhiAI.pem. Passes any extra arguments through
    to ssh after the host, so you can run one-shot remote commands.

.EXAMPLE
    .\scripts\prod-ssh.ps1
    # Interactive shell on prod.

.EXAMPLE
    .\scripts\prod-ssh.ps1 -- uptime
    # Runs `uptime` on prod and exits.

.EXAMPLE
    $env:ARTHA_PROD_PEM = "C:\keys\artha.pem"; .\scripts\prod-ssh.ps1
    # Use a PEM at a non-default path.

.NOTES
    Does not read the PEM itself; just passes its path to ssh -i.
    For Windows PEM permission setup, see docs/prod-access.md §1a.
#>

[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Remaining
)

$ErrorActionPreference = 'Stop'

$DefaultPem = 'D:\Desktop\ArthaSamriddhiAI.pem'
$Host_      = '13.204.187.25'
$User       = 'ubuntu'

$Pem = if ($env:ARTHA_PROD_PEM) { $env:ARTHA_PROD_PEM } else { $DefaultPem }

if (-not (Test-Path -LiteralPath $Pem)) {
    Write-Error "PEM not found at '$Pem'. Set `$env:ARTHA_PROD_PEM or place the key at '$DefaultPem'."
    exit 1
}

# Drop a leading literal '--' separator if present (PowerShell param parsing quirk).
$extra = @()
if ($Remaining) {
    $extra = $Remaining
    if ($extra.Count -gt 0 -and $extra[0] -eq '--') {
        $extra = $extra[1..($extra.Count - 1)]
    }
}

$sshArgs = @(
    '-i', $Pem,
    '-o', 'IdentitiesOnly=yes',
    "$User@$Host_"
) + $extra

Write-Verbose "ssh $($sshArgs -join ' ')"
& ssh @sshArgs
exit $LASTEXITCODE
