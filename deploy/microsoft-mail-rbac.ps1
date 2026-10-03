<#
Configure only Mail.Send for one immutable mailbox ID after approval.
Requires an existing dedicated Entra app and an authenticated Exchange session.
Entra grants are additive: confirm their absence separately before applying.
Use -WhatIf for a read-only preview. No credentials, deletion or mail sending.
https://learn.microsoft.com/en-us/exchange/permissions-exo/application-rbac
#>
[CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'High')]
param(
    [Parameter(Mandatory)][Guid]$TenantId,
    [Parameter(Mandatory)][Guid]$AppId,
    [Parameter(Mandatory)][Guid]$EnterpriseObjectId,
    [Parameter(Mandatory)][Guid]$MailboxObjectId,
    [Parameter(Mandatory)][Guid]$ControlMailboxObjectId,
    [Parameter(Mandatory)][ValidatePattern('^[A-Za-z0-9._+-]+@[A-Za-z0-9.-]+$')][string]$Sender,
    [switch]$ConfirmedNoUnscopedEntraGrant
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if (-not $ConfirmedNoUnscopedEntraGrant) {
    throw 'Verify that the dedicated app has no unscoped Entra mail grant before proceeding.'
}
foreach ($id in @($TenantId, $AppId, $EnterpriseObjectId, $MailboxObjectId, $ControlMailboxObjectId)) {
    if ($id -eq [Guid]::Empty) { throw 'Identifiers must not be empty.' }
}
if ($AppId -eq $EnterpriseObjectId -or $MailboxObjectId -eq $ControlMailboxObjectId) {
    throw 'App registration, enterprise principal and control mailbox require distinct IDs.'
}
$connections = @(Get-ConnectionInformation | Where-Object { $_.ConnectionUsedForInbuiltCmdlets })
if ($connections.Count -ne 1 -or [Guid]$connections[0].TenantID -ne $TenantId) {
    throw 'The active Exchange connection does not match the expected tenant.'
}
$mailbox = Get-EXOMailbox -Identity $MailboxObjectId -Properties ExternalDirectoryObjectId
$control = Get-EXOMailbox -Identity $ControlMailboxObjectId -Properties ExternalDirectoryObjectId
if ([Guid]$mailbox.ExternalDirectoryObjectId -ne $MailboxObjectId -or
    $mailbox.PrimarySmtpAddress.ToString() -ine $Sender -or
    $mailbox.RecipientTypeDetails.ToString() -ne 'SharedMailbox' -or
    [Guid]$control.ExternalDirectoryObjectId -ne $ControlMailboxObjectId) {
    throw 'The mailbox IDs, primary sender or shared mailbox type do not match.'
}
if ((Get-User -Identity $Sender).AccountDisabled -ne $true) {
    throw 'The shared mailbox must have user sign-in blocked.'
}
$suffix = $AppId.ToString('N')
$scopeName = "Dyna-Mail-$suffix"
$assignmentName = "Dyna-MailSend-$suffix"
$filter = "ExternalDirectoryObjectId -eq '$MailboxObjectId'"
$principals = @(Get-ServicePrincipal | Where-Object {
    [Guid]$_.AppId -eq $AppId -or [Guid]$_.ObjectId -eq $EnterpriseObjectId
})
if ($principals.Count -gt 1 -or ($principals.Count -eq 1 -and (
    [Guid]$principals[0].AppId -ne $AppId -or [Guid]$principals[0].ObjectId -ne $EnterpriseObjectId))) {
    throw 'An existing Exchange principal conflicts with the supplied enterprise app IDs.'
}
$grants = @()
if ($principals.Count) {
    $grants = @(Test-ServicePrincipalAuthorization -Identity $EnterpriseObjectId)
    if (@($grants | Where-Object {
        $_.RoleName -ne 'Application Mail.Send' -or $_.AllowedResourceScope -ne $scopeName -or
        $_.ScopeType -ne 'CustomRecipientScope'
    }).Count -or $grants.Count -gt 1) {
        throw 'Existing Exchange grants differ from the dedicated one-mailbox Mail.Send scope.'
    }
}
$scopes = @(Get-ManagementScope | Where-Object { $_.Name -eq $scopeName })
if ($scopes.Count -gt 1 -or ($scopes.Count -eq 1 -and (
    $scopes[0].Exclusive -or
    ($scopes[0].RecipientFilter -replace '[\s()]', '') -ine ($filter -replace '[\s()]', '')))) {
    throw 'The existing management scope differs from the immutable mailbox filter.'
}
$preview = @(Get-Recipient -Filter $filter)
if ($preview.Count -ne 1 -or [Guid]$preview[0].ExternalDirectoryObjectId -ne $MailboxObjectId) {
    throw 'The resource filter must resolve to exactly the approved mailbox.'
}
if ($WhatIfPreference) {
    [PSCustomObject]@{ Preview = $true; TenantId = $TenantId; AppId = $AppId;
        MailboxId = $MailboxObjectId; Sender = $Sender; Role = 'Application Mail.Send';
        RecipientFilter = $filter; ScopeName = $scopeName; ExistingGrant = [bool]$grants.Count }
    return
}
if (-not $PSCmdlet.ShouldProcess("$AppId / $MailboxObjectId", 'Configure one-mailbox Application Mail.Send')) {
    return
}
if (-not $principals.Count) {
    New-ServicePrincipal -AppId $AppId -ObjectId $EnterpriseObjectId -DisplayName 'Dyna Rejestr Tablic Mail' | Out-Null
}
if (-not $scopes.Count) {
    New-ManagementScope -Name $scopeName -RecipientRestrictionFilter $filter | Out-Null
}
if (-not $grants.Count) {
    New-ManagementRoleAssignment -Name $assignmentName -Role 'Application Mail.Send' `
        -App $EnterpriseObjectId -CustomResourceScope $scopeName | Out-Null
}
$positive = @(Test-ServicePrincipalAuthorization -Identity $EnterpriseObjectId -Resource $MailboxObjectId)
$negative = @(Test-ServicePrincipalAuthorization -Identity $EnterpriseObjectId -Resource $ControlMailboxObjectId)
if ($positive.Count -ne 1 -or $positive[0].RoleName -ne 'Application Mail.Send' -or
    $positive[0].AllowedResourceScope -ne $scopeName -or $positive[0].ScopeType -ne 'CustomRecipientScope' -or
    $positive[0].InScope -ne $true -or $negative.Count -ne 1 -or
    $negative[0].RoleName -ne 'Application Mail.Send' -or $negative[0].InScope -ne $false) {
    throw 'Authorization checks failed. Stop and inspect grants; no automatic deletion or retry.'
}
[PSCustomObject]@{ Role = 'Application Mail.Send'; Sender = $Sender;
    MailboxId = $MailboxObjectId; PositiveInScope = $true; ControlInScope = $false;
    EntraPermissionsIncludedInTest = $false; ActualGraphDeliveryVerified = $false }
