# Host-native safety tests. All Exchange commands below are in-memory fakes.
# No module import, connection, tenant changes or HTTP requests are performed.
$ErrorActionPreference = 'Stop'
$target = Join-Path $PSScriptRoot 'microsoft-mail-rbac.ps1'
$global:DynaMailArgs = @{
    TenantId = [Guid]'11111111-1111-1111-1111-111111111111'
    AppId = [Guid]'22222222-2222-2222-2222-222222222222'
    EnterpriseObjectId = [Guid]'33333333-3333-3333-3333-333333333333'
    MailboxObjectId = [Guid]'44444444-4444-4444-4444-444444444444'
    ControlMailboxObjectId = [Guid]'55555555-5555-5555-5555-555555555555'
    Sender = 'registry@example.org'; ConfirmedNoUnscopedEntraGrant = $true
}
$global:DynaScopeName = 'Dyna-Mail-' + $global:DynaMailArgs.AppId.ToString('N')
function Reset-Fixture {
    $global:DynaFixture = @{
        Tenant = $global:DynaMailArgs.TenantId; MailboxId = $global:DynaMailArgs.MailboxObjectId
        Disabled = $true; Shared = $true; Principal = $false; ScopeFilter = ''; Exclusive = $false
        PrincipalApp = $global:DynaMailArgs.AppId; Grant = $false; Role = 'Application Mail.Send'
        Recipients = 1; ControlAllowed = $false; Calls = [Collections.Generic.List[string]]::new()
    }
}
function Get-ConnectionInformation {
    [PSCustomObject]@{ TenantID = $global:DynaFixture.Tenant; ConnectionUsedForInbuiltCmdlets = $true }
}
function Get-EXOMailbox($Identity, $Properties) {
    $mailboxId = if ($Identity -eq $global:DynaMailArgs.MailboxObjectId) {
        $global:DynaFixture.MailboxId
    } else { $global:DynaMailArgs.ControlMailboxObjectId }
    [PSCustomObject]@{ ExternalDirectoryObjectId = $mailboxId; PrimarySmtpAddress = $global:DynaMailArgs.Sender;
        RecipientTypeDetails = $(if ($global:DynaFixture.Shared) { 'SharedMailbox' } else { 'UserMailbox' }) }
}
function Get-User($Identity) { [PSCustomObject]@{ AccountDisabled = $global:DynaFixture.Disabled } }
function Get-ServicePrincipal {
    if ($global:DynaFixture.Principal) {
        [PSCustomObject]@{ AppId = $global:DynaFixture.PrincipalApp; ObjectId = $global:DynaMailArgs.EnterpriseObjectId }
    }
}
function Get-ManagementScope {
    if ($global:DynaFixture.ScopeFilter) {
        [PSCustomObject]@{ Name = $global:DynaScopeName; RecipientFilter = $global:DynaFixture.ScopeFilter;
            Exclusive = $global:DynaFixture.Exclusive }
    }
}
function Get-Recipient($Filter) {
    for ($n = 0; $n -lt $global:DynaFixture.Recipients; $n++) {
        [PSCustomObject]@{ ExternalDirectoryObjectId = $global:DynaMailArgs.MailboxObjectId }
    }
}
function Test-ServicePrincipalAuthorization($Identity, $Resource) {
    if ($global:DynaFixture.Grant) {
        $inScope = if (-not $Resource) { 'Not Run' }
            elseif ($Resource -eq $global:DynaMailArgs.MailboxObjectId) { $true }
            else { $global:DynaFixture.ControlAllowed }
        [PSCustomObject]@{ RoleName = $global:DynaFixture.Role; AllowedResourceScope = $global:DynaScopeName;
            ScopeType = 'CustomRecipientScope'; InScope = $inScope }
    }
}
function New-ServicePrincipal($AppId, $ObjectId, $DisplayName) {
    if ($AppId -ne $global:DynaMailArgs.AppId -or $ObjectId -ne $global:DynaMailArgs.EnterpriseObjectId) {
        throw 'Wrong principal mutation'
    }
    $global:DynaFixture.Calls.Add('principal'); $global:DynaFixture.Principal = $true
}
function New-ManagementScope($Name, $RecipientRestrictionFilter) {
    if ($RecipientRestrictionFilter -ne "ExternalDirectoryObjectId -eq '$($global:DynaMailArgs.MailboxObjectId)'") {
        throw 'Resource mutation is not limited to the immutable mailbox ID'
    }
    $global:DynaFixture.Calls.Add('scope'); $global:DynaFixture.ScopeFilter = $RecipientRestrictionFilter
}
function New-ManagementRoleAssignment($Name, $Role, $App, $CustomResourceScope) {
    if ($Role -ne 'Application Mail.Send' -or $App -ne $global:DynaMailArgs.EnterpriseObjectId -or
        $CustomResourceScope -ne $global:DynaScopeName) { throw 'Wrong role or scope mutation' }
    $global:DynaFixture.Calls.Add('grant'); $global:DynaFixture.Grant = $true
}
function Assert-Condition($condition, $message) { if (-not $condition) { throw $message } }
function Assert-Blocked($setup, $pattern) {
    Reset-Fixture
    & $setup
    $rejected = $false
    try { & $target @global:DynaMailArgs -Confirm:$false | Out-Null }
    catch {
        $rejected = $true
        Assert-Condition ($_.Exception.Message -match $pattern) "Unexpected rejection: $($_.Exception.Message)"
    }
    Assert-Condition $rejected 'Unsafe input was accepted'
    Assert-Condition ($global:DynaFixture.Calls.Count -eq 0) 'Unsafe input caused a tenant mutation'
}
Reset-Fixture
$preview = & $target @global:DynaMailArgs -WhatIf
Assert-Condition ($preview.Preview -eq $true -and $global:DynaFixture.Calls.Count -eq 0) 'WhatIf mutated state'
Reset-Fixture
$result = & $target @global:DynaMailArgs -Confirm:$false
Assert-Condition ($result.PositiveInScope -and -not $result.ControlInScope -and
    -not $result.ActualGraphDeliveryVerified -and $global:DynaFixture.Calls.Count -eq 3) 'Scoped setup failed'
& $target @global:DynaMailArgs -Confirm:$false | Out-Null
Assert-Condition ($global:DynaFixture.Calls.Count -eq 3) 'Repeated setup duplicated permissions'
Assert-Blocked { $global:DynaFixture.Tenant = [Guid]::NewGuid() } 'expected tenant'
Assert-Blocked { $global:DynaFixture.MailboxId = [Guid]::NewGuid() } 'mailbox IDs'
Assert-Blocked { $global:DynaFixture.Shared = $false } 'shared mailbox type'
Assert-Blocked { $global:DynaFixture.Disabled = $false } 'sign-in blocked'
Assert-Blocked { $global:DynaFixture.Principal = $true; $global:DynaFixture.PrincipalApp = [Guid]::NewGuid() } 'conflicts'
Assert-Blocked {
    $global:DynaFixture.Principal = $true; $global:DynaFixture.Grant = $true; $global:DynaFixture.Role = 'Application Mail.Read'
} 'Existing Exchange grants'
Assert-Blocked { $global:DynaFixture.ScopeFilter = "RecipientTypeDetails -eq 'SharedMailbox'" } 'management scope differs'
Assert-Blocked {
    $global:DynaFixture.ScopeFilter = "ExternalDirectoryObjectId -eq '$($global:DynaMailArgs.MailboxObjectId)'"
    $global:DynaFixture.Exclusive = $true
} 'management scope differs'
Assert-Blocked { $global:DynaFixture.Recipients = 2 } 'exactly the approved mailbox'
Reset-Fixture
$missingAttestation = $global:DynaMailArgs.Clone(); $missingAttestation.ConfirmedNoUnscopedEntraGrant = $false
$rejected = $false
try { & $target @missingAttestation -Confirm:$false | Out-Null }
catch { $rejected = $_.Exception.Message -match 'no unscoped Entra' }
Assert-Condition ($rejected -and $global:DynaFixture.Calls.Count -eq 0) 'Missing Entra verification caused writes'
Reset-Fixture
$global:DynaFixture.ControlAllowed = $true
$rejected = $false
try { & $target @global:DynaMailArgs -Confirm:$false | Out-Null }
catch { $rejected = $_.Exception.Message -match 'Authorization checks failed' }
Assert-Condition ($rejected -and $global:DynaFixture.Calls.Count -eq 3) 'Failed negative control was not reported'
Write-Output 'PASS: 14 mailbox configuration scenarios; Exchange commands simulated; no live API or grant.'
