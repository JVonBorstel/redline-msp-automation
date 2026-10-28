"""B-85 Bicep core (Key Vault, identity, Log Analytics): static checks. Acceptance ids B85-1 to B85-4: specs/B-85.md.

No Azure CLI or Bicep compiler exists on the build machine, so nothing here compiles, lints, validates or deploys
a template. These tests read the .bicep and .bicepparam files as text and assert the security properties are
written down. Passing means "the properties are present in the source", not "the template builds".
Offline and deterministic. Run: uv run --frozen pytest -p no:cacheprovider tests/py/infra
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
CORE = REPO / "infra" / "bicep" / "core"
MODULES = CORE / "modules"
SECRETS_DOC = REPO / "docs" / "SECRETS.md"
PARAM_FILES = [CORE / "main.dev.bicepparam", CORE / "main.prod.bicepparam"]
MODULE_FILES = ["keyVault.bicep", "managedIdentity.bicep", "logAnalytics.bicep", "diagnosticSettings.bicep"]
REQUIRED_TAGS = ("environment", "owner", "dataClass", "project")
SECRET_NAME = re.compile(r"^client-[a-z0-9]+(?:-[a-z0-9]+)+$")
SECRET_KEY_NAMES = re.compile(
    r"(secret|password|passwd|pwd|token|apikey|api_key|accountkey|sas|connectionstring|credential)", re.I
)
SECRET_VALUE_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"AccountKey=", re.I),
    re.compile(r"[?&]sig=[A-Za-z0-9%+/=]{10,}"),
    re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\."),  # JWT
    re.compile(r"(?=[A-Za-z0-9+/]*[A-Z])(?=[A-Za-z0-9+/]*[a-z])(?=[A-Za-z0-9+/]*\d)[A-Za-z0-9+/]{40,}"),
    re.compile(r"(?i)\b(?:sk|pk|xox[abp])-[A-Za-z0-9-]{16,}"),
]
DEPLOY_PATTERNS = [
    re.compile(r"az\s+deployment\s+(?:group|sub|mg|tenant)\s+create", re.I),
    re.compile(r"az\s+deployment\s+create", re.I),
    re.compile(r"New-Az(?:ResourceGroup|Subscription|ManagementGroup|Tenant)?Deployment", re.I),
    re.compile(r"az\s+group\s+create", re.I),
    re.compile(r"az\s+keyvault\s+secret\s+set", re.I),
    re.compile(r"Set-AzKeyVaultSecret", re.I),
    re.compile(r"az\s+deployment\s+\w+\s+delete", re.I),
]


def strip_comments(text: str) -> str:
    """Remove // and /* */ comments (Bicep strings in this folder never contain those tokens)."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"(?m)//.*$", "", text)


def resource_blocks(text: str) -> list[tuple[str, str]]:
    """Return (type@version, body) for each top-level `resource sym 'type@ver' = {...}` block (brace matched)."""
    out: list[tuple[str, str]] = []
    code = strip_comments(text)
    pattern = r"(?m)^resource\s+\w+\s+'([^']+)'(?:\s+existing)?\s*=\s*(?:if\s*\([^)]*\)\s*)?\{"
    for m in re.finditer(pattern, code):
        if " existing" in m.group(0):
            continue  # a reference to a resource defined elsewhere, not a definition
        depth, i = 1, m.end()
        while i < len(code) and depth:
            depth += {"{": 1, "}": -1}.get(code[i], 0)
            i += 1
        out.append((m.group(1), code[m.end() : i - 1]))
    return out


def read_module(name: str) -> str:
    return (MODULES / name).read_text(encoding="utf-8")


def vault_body(text: str) -> str:
    bodies = [b for t, b in resource_blocks(text) if t.startswith("Microsoft.KeyVault/vaults@")]
    assert len(bodies) == 1, "exactly one Microsoft.KeyVault/vaults resource expected"
    return bodies[0]


def keyvault_findings(text: str) -> list[str]:
    """Missing security properties in a Key Vault module source; empty list means all present."""
    code = strip_comments(text)
    try:
        body = vault_body(text)
    except AssertionError as exc:
        return [str(exc)]
    checks = {
        "enableRbacAuthorization true": r"enableRbacAuthorization:\s*true\b",
        "enableSoftDelete true": r"enableSoftDelete:\s*true\b",
        "enablePurgeProtection true": r"enablePurgeProtection:\s*true\b",
        "publicNetworkAccess Disabled": r"publicNetworkAccess:\s*'Disabled'",
        "networkAcls defaultAction Deny": r"defaultAction:\s*'Deny'",
        "soft delete retention set": r"softDeleteRetentionInDays:\s*\w+",
        "tags applied": r"(?m)^\s*tags:\s*\w+",
    }
    found = [f"missing {label}" for label, pat in checks.items() if not re.search(pat, body)]
    if re.search(r"enableRbacAuthorization:\s*false|enableSoftDelete:\s*false|enablePurgeProtection:\s*false", body):
        found.append("a protection is explicitly false")
    if re.search(r"accessPolicies:\s*\[\s*\S", body):
        found.append("access policies used instead of RBAC")
    if "Microsoft.KeyVault/vaults/secrets" in code or "Microsoft.KeyVault/vaults/keys" in code:
        found.append("template declares a secret or key (values belong to people, not IaC)")
    return found


def secret_findings(text: str) -> list[str]:
    """Secret-looking literals in a parameter, template or doc file; empty list means clean."""
    found = []
    for lineno, line in enumerate(strip_comments(text).splitlines(), 1):
        for pat in SECRET_VALUE_PATTERNS:
            if pat.search(line):
                found.append(f"line {lineno}: value matches {pat.pattern[:30]}")
        param = re.match(r"\s*param\s+(\w+)\s*=\s*(.+)$", line)
        if param and SECRET_KEY_NAMES.search(param.group(1)):
            found.append(f"line {lineno}: parameter {param.group(1)} looks like a secret")
    return found


GOOD_VAULT = """
resource kv 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: name
  location: location
  tags: tags
  properties: {
    tenantId: subscription().tenantId
    sku: { family: 'A', name: 'standard' }
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 90
    enablePurgeProtection: true
    publicNetworkAccess: 'Disabled'
    networkAcls: { defaultAction: 'Deny', bypass: 'None' }
  }
}
"""


# ---- the checkers themselves must bite (mutation checks) ----


@pytest.mark.parametrize(
    ("old", "new", "expect"),
    [
        ("enableRbacAuthorization: true", "enableRbacAuthorization: false", "RBAC"),
        ("enableSoftDelete: true", "enableSoftDelete: false", "softdelete"),
        ("enablePurgeProtection: true", "", "purge"),
        ("publicNetworkAccess: 'Disabled'", "publicNetworkAccess: 'Enabled'", "publicNetworkAccess"),
        ("defaultAction: 'Deny'", "defaultAction: 'Allow'", "defaultAction"),
        ("  tags: tags\n", "", "tags"),
    ],
)
def test_b85_1_checker_flags_each_weakened_property(old: str, new: str, expect: str) -> None:
    assert keyvault_findings(GOOD_VAULT) == []
    findings = keyvault_findings(GOOD_VAULT.replace(old, new))
    assert any(expect.lower() in f.lower() for f in findings), findings


def test_b85_1_checker_flags_secret_resource_and_access_policies() -> None:
    bad = GOOD_VAULT + "\nresource s 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {\n  name: 'x'\n}\n"
    assert any("declares a secret" in f for f in keyvault_findings(bad))
    legacy = GOOD_VAULT.replace("tenantId:", "accessPolicies: [ { objectId: 'x' } ]\n    tenantId:")
    assert any("access policies" in f for f in keyvault_findings(legacy))


def test_b85_1_commented_out_property_does_not_count() -> None:
    assert keyvault_findings(GOOD_VAULT.replace("enablePurgeProtection: true", "// enablePurgeProtection: true"))


@pytest.mark.parametrize(
    "line",
    [
        "param sqlPassword = 'x'",
        "param x = 'AccountKey=abcd'",
        "param x = 'c?sv=1&sig=AbCdEfGhIjKlMnOp%2Bq'",
        "param x = '-----BEGIN RSA PRIVATE KEY-----'",
        "param x = '" + "Ab1" * 15 + "'",
        "param x = 'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abc'",
    ],
)
def test_b85_1_secret_scanner_flags_planted_values(line: str) -> None:
    assert secret_findings(line), line


def test_b85_3_deploy_patterns_match_what_they_should() -> None:
    samples = [
        "az deployment group create -g rg -f main.bicep",
        "az deployment sub create",
        "New-AzResourceGroupDeployment -Name x",
        "az group create -n rg",
        "az keyvault secret set --name n",
    ]
    for s in samples:
        assert any(p.search(s) for p in DEPLOY_PATTERNS), s
    assert not any(p.search("az deployment group what-if -g rg -f main.bicep") for p in DEPLOY_PATTERNS)
    assert not any(p.search("az deployment group validate -g rg -f main.bicep") for p in DEPLOY_PATTERNS)


# ---- B85-1: modules, security properties, no secrets ----


def test_b85_1_expected_files_exist() -> None:
    for name in MODULE_FILES:
        assert (MODULES / name).is_file(), name
    assert (CORE / "main.bicep").is_file()
    for p in PARAM_FILES:
        assert p.is_file(), p.name


def test_b85_1_key_vault_has_all_required_properties() -> None:
    assert keyvault_findings(read_module("keyVault.bicep")) == []


def test_b85_1_key_vault_retention_is_at_least_90_days_by_default() -> None:
    text = strip_comments(read_module("keyVault.bicep"))
    m = re.search(r"param\s+softDeleteRetentionInDays\s+int\s*=\s*(\d+)", text)
    assert m and int(m.group(1)) >= 90
    assert re.search(r"@minValue\(\s*(?:90|9\d|[1-9]\d{2})\s*\)", text)


def test_b85_1_vault_name_fits_the_24_character_limit() -> None:
    text = strip_comments(read_module("keyVault.bicep"))
    assert re.search(r"take\(.+,\s*24\)", text), "vault name must be truncated with take(..., 24)"


def test_b85_1_identity_is_user_assigned_and_logs_go_to_a_workspace() -> None:
    ident = [t for t, _ in resource_blocks(read_module("managedIdentity.bicep"))]
    assert any(t.startswith("Microsoft.ManagedIdentity/userAssignedIdentities@") for t in ident)
    la = resource_blocks(read_module("logAnalytics.bicep"))
    body = next(b for t, b in la if t.startswith("Microsoft.OperationalInsights/workspaces@"))
    assert re.search(r"retentionInDays:\s*\w+", body)
    assert re.search(r"disableLocalAuth:\s*true\b", body), "workspace shared-key auth must be disabled"


def test_b85_1_diagnostic_settings_send_audit_events_to_the_workspace() -> None:
    text = strip_comments(read_module("diagnosticSettings.bicep"))
    blocks = resource_blocks(text)
    assert any(t.startswith("Microsoft.Insights/diagnosticSettings@") for t, _ in blocks)
    assert "workspaceId" in text
    assert "AuditEvent" in text
    assert re.search(r"enabled:\s*true", text)
    assert "storageAccountId" not in text and "eventHubAuthorizationRuleId" not in text


def test_b85_1_vault_access_is_by_rbac_role_for_the_identity_not_an_access_policy() -> None:
    text = strip_comments(read_module("keyVault.bicep"))
    assert "Microsoft.Authorization/roleAssignments@" in text
    assert "principalType: 'ServicePrincipal'" in text
    assert "4633458b-17de-408a-b874-0445c86b69e6" in text, "Key Vault Secrets User role definition id"
    assert "00482a5a-887f-4fb3-b363-3b7fe8e74483" not in text, "no Key Vault Administrator role"


def test_b85_1_every_taggable_resource_gets_tags() -> None:
    untaggable = ("roleAssignments", "diagnosticSettings", "privateDnsZoneGroups")
    for name in MODULE_FILES:
        for rtype, body in resource_blocks(read_module(name)):
            if any(u in rtype for u in untaggable):
                continue
            assert re.search(r"(?m)^\s*tags:\s*\w+", body), f"{name}: {rtype} has no tags"


def test_b85_1_main_requires_the_tags_and_passes_them_to_every_module() -> None:
    text = strip_comments((CORE / "main.bicep").read_text(encoding="utf-8"))
    for tag in REQUIRED_TAGS:
        assert re.search(rf"\b{tag}\b", text), tag
    mods = re.findall(r"(?ms)^module\s+\w+\s+'[^']+'\s*=\s*\{(.*?)^\}", text)
    assert len(mods) >= 4
    for body in mods:
        assert re.search(r"tags:\s*\w+", body) or "diagnosticSettings" in body


def test_b85_1_main_environment_allows_dev_and_prod_only() -> None:
    text = strip_comments((CORE / "main.bicep").read_text(encoding="utf-8"))
    assert re.search(r"@allowed\(\s*\[\s*'dev'\s*,?\s*'prod'\s*\]\s*\)\s*param\s+environment\b", text)


@pytest.mark.parametrize("path", PARAM_FILES, ids=lambda p: p.name)
def test_b85_1_parameter_files_use_main_and_carry_required_tags(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert re.search(r"(?m)^using\s+'\./main\.bicep'", text)
    for tag in REQUIRED_TAGS:
        assert re.search(rf"(?m)^param {tag} = ", text), f"{path.name}: tag parameter {tag}"
    env = "dev" if "dev" in path.name else "prod"
    assert re.search(rf"param environment = '{env}'", text)


@pytest.mark.parametrize("path", PARAM_FILES, ids=lambda p: p.name)
def test_b85_1_no_secret_value_in_any_parameter_file(path: Path) -> None:
    assert secret_findings(path.read_text(encoding="utf-8")) == []


@pytest.mark.parametrize("path", sorted(CORE.rglob("*.bicep*")), ids=lambda p: p.name)
def test_b85_1_no_secret_literal_or_secure_default_in_any_bicep_file(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert secret_findings(text) == []
    assert not re.search(r"@secure\(\)\s*param\s+\w+\s+\w+\s*=", text), "a @secure parameter must have no default"
    assert "listKeys(" not in text and "listSecrets(" not in text and "listCredentials(" not in text


@pytest.mark.parametrize("path", PARAM_FILES, ids=lambda p: p.name)
def test_b85_1_parameter_values_are_placeholders_or_plain_names(path: Path) -> None:
    for line in strip_comments(path.read_text(encoding="utf-8")).splitlines():
        m = re.match(r"\s*param\s+(\w+)\s*=\s*'([^']*)'", line)
        if not m or m.group(1) in {"environment", "location"}:
            continue
        value = m.group(2)
        assert value == "" or value.startswith("<") or re.fullmatch(r"[a-z0-9-]{1,24}", value), line


def test_b85_1_prod_log_retention_is_at_least_dev_and_at_least_90() -> None:
    def val(path: Path) -> int:
        m = re.search(r"param logRetentionDays = (\d+)", path.read_text(encoding="utf-8"))
        assert m, f"{path.name} lacks logRetentionDays"
        return int(m.group(1))

    dev, prod = PARAM_FILES
    assert val(prod) >= val(dev)
    assert val(prod) >= 90


# ---- B85-2: secrets doc ----


def test_b85_2_secrets_doc_covers_the_pattern() -> None:
    low = SECRETS_DOC.read_text(encoding="utf-8").lower()
    for needle in (
        "managed identity",
        "key vault secrets user",
        "secret reference",
        "rotation",
        "purge protection",
        "soft delete",
        "client-<id>-<purpose>",
        "w-tool-08",
        "unverified",
    ):
        assert needle in low, needle


def test_b85_2_doc_states_rotation_stays_a_human_task_and_names_a_binding() -> None:
    text = SECRETS_DOC.read_text(encoding="utf-8")
    assert re.search(r"(?i)rotation[^.\n]*human", text)
    assert re.search(r"(?i)binding", text)
    assert re.search(r"kv://|secret_ref|secretRef|secret reference", text)


def test_b85_2_secrets_doc_contains_no_secret_values() -> None:
    assert secret_findings(SECRETS_DOC.read_text(encoding="utf-8")) == []


# ---- B85-3: nothing is deployed ----


def deploy_scan_files() -> list[Path]:
    roots = [REPO / "infra", REPO / "scripts", REPO / ".github" / "workflows", REPO / "levers"]
    exts = {".ps1", ".psm1", ".sh", ".bat", ".cmd", ".yml", ".yaml", ".bicep", ".bicepparam", ".md"}
    files = [p for r in roots if r.exists() for p in r.rglob("*") if p.is_file() and p.suffix in exts]
    files.append(SECRETS_DOC)
    return sorted(files)


def test_b85_3_no_script_or_infra_file_creates_or_deploys_anything() -> None:
    files = deploy_scan_files()
    assert any(f.suffix == ".bicep" for f in files)
    for f in files:
        text = f.read_text(encoding="utf-8", errors="replace")
        for pat in DEPLOY_PATTERNS:
            assert not pat.search(text), f"{f.relative_to(REPO)} matches {pat.pattern}"


def test_b85_3_whatif_instructions_exist_and_are_validate_or_whatif_only() -> None:
    text = (CORE / "README.md").read_text(encoding="utf-8")
    assert "az bicep build" in text and "az bicep lint" in text
    assert re.search(r"az deployment group validate", text)
    assert re.search(r"az deployment group what-if", text)
    assert "human" in text.lower()


# ---- B85-4: one vault per environment, secret naming ----


def test_b85_4_secret_name_pattern_accepts_and_rejects() -> None:
    for ok in ("client-contoso-graph-app", "client-c001-psa-api", "client-fabrikam-backup-key"):
        assert SECRET_NAME.match(ok), ok
    for bad in ("graph-app", "Client-contoso-graph", "client-contoso", "client_contoso_graph", "client--x-y"):
        assert not SECRET_NAME.match(bad), bad


def test_b85_4_doc_secret_names_follow_the_pattern() -> None:
    names = re.findall(r"`(client-[A-Za-z0-9-]+)`", SECRETS_DOC.read_text(encoding="utf-8"))
    assert len(names) >= 2
    for n in names:
        assert SECRET_NAME.match(n), n


def test_b85_4_doc_states_one_vault_per_environment_and_per_client_exception() -> None:
    low = SECRETS_DOC.read_text(encoding="utf-8").lower()
    assert "one key vault per environment" in low
    assert "dev" in low and "prod" in low
    assert "client contract" in low and "client record" in low and "d6-10" in low


def test_b85_4_main_creates_exactly_one_vault_and_names_it_for_its_environment() -> None:
    text = strip_comments((CORE / "main.bicep").read_text(encoding="utf-8"))
    assert len(re.findall(r"(?m)^module\s+\w+\s+'modules/keyVault\.bicep'", text)) == 1
    assert "environment" in strip_comments(read_module("keyVault.bicep"))
