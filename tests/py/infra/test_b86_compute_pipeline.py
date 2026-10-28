"""B-86 Bicep compute, Azure DevOps pipeline, branching and release doc: static checks. Acceptance ids B86-1 to B86-3.

No Azure CLI, Bicep compiler or Azure DevOps exists on the build machine, so nothing here compiles, lints, validates,
runs a pipeline or deploys. These tests read the .bicep, .bicepparam, .yml and .md files as text and assert the
properties are written down. Passing means "present in the source", not "the template builds / the pipeline runs".
Offline and deterministic. Run: uv run --frozen pytest -p no:cacheprovider tests/py/infra
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
COMPUTE = REPO / "infra" / "bicep" / "compute"
MODULES = COMPUTE / "modules"
PIPELINE = REPO / "infra" / "azure-pipelines.yml"
CI_YML = REPO / ".github" / "workflows" / "ci.yml"
RELEASE_DOC = REPO / "docs" / "BRANCHING_RELEASE.md"
PARAM_FILES = [COMPUTE / "main.dev.bicepparam", COMPUTE / "main.prod.bicepparam"]
MODULE_FILES = ["storageAccount.bicep", "functionApp.bicep", "logicApp.bicep", "automationAccount.bicep"]
REQUIRED_TAGS = ("environment", "owner", "dataClass", "project")

SECRET_KEY_NAMES = re.compile(
    r"(secret|password|passwd|pwd|token|apikey|api_key|accountkey|sas|connectionstring|credential)", re.I
)
SECRET_VALUE_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"AccountKey=", re.I),
    re.compile(r"[?&]sig=[A-Za-z0-9%+/=]{10,}"),
    re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\."),
    re.compile(r"(?=[A-Za-z0-9+/]*[A-Z])(?=[A-Za-z0-9+/]*[a-z])(?=[A-Za-z0-9+/]*\d)[A-Za-z0-9+/]{40,}"),
    re.compile(r"(?i)\b(?:sk|pk|xox[abp])-[A-Za-z0-9-]{16,}"),
    re.compile(r"DefaultEndpointsProtocol=", re.I),
]
DEPLOY_PATTERNS = [
    re.compile(r"az\s+deployment\s+(?:group|sub|mg|tenant)\s+create", re.I),
    re.compile(r"az\s+deployment\s+create", re.I),
    re.compile(r"New-Az(?:ResourceGroup|Subscription|ManagementGroup|Tenant)?Deployment", re.I),
    re.compile(r"az\s+group\s+create", re.I),
    re.compile(r"az\s+functionapp\s+(?:deploy|deployment)", re.I),
    re.compile(r"az\s+keyvault\s+secret\s+set", re.I),
    re.compile(r"AzureResourceManagerTemplateDeployment", re.I),
    re.compile(r"deploymentMode", re.I),
]
# Settings that carry a credential. Identity-based storage settings (AzureWebJobsStorage__accountName) are fine.
KEY_BASED_SETTINGS = re.compile(
    r"AzureWebJobsStorage'|AzureWebJobsStorage\"|WEBSITE_CONTENTAZUREFILECONNECTIONSTRING|APPINSIGHTS_INSTRUMENTATIONKEY"
    r"|_CONNECTION_STRING|AccountKey|listKeys\(|listSecrets\(|listCredentials\(|listKeys|primaryKey|secondaryKey"
)


def strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"(?m)//.*$", "", text)


def strip_yaml_comments(text: str) -> str:
    return re.sub(r"(?m)(^|\s)#.*$", "", text)


def resource_blocks(text: str) -> list[tuple[str, str]]:
    """(type@version, body) for each top-level `resource sym 'type@ver' = {...}` definition (brace matched)."""
    out: list[tuple[str, str]] = []
    code = strip_comments(text)
    for m in re.finditer(r"(?m)^resource\s+\w+\s+'([^']+)'(\s+existing)?\s*=\s*(?:if\s*\([^)]*\)\s*)?\{", code):
        if m.group(2):
            continue
        depth, i = 1, m.end()
        while i < len(code) and depth:
            depth += {"{": 1, "}": -1}.get(code[i], 0)
            i += 1
        out.append((m.group(1), code[m.end() : i - 1]))
    return out


def read_module(name: str) -> str:
    return (MODULES / name).read_text(encoding="utf-8")


def block(text: str, type_prefix: str) -> str:
    bodies = [b for t, b in resource_blocks(text) if t.startswith(type_prefix)]
    assert len(bodies) == 1, f"exactly one {type_prefix} resource expected, found {len(bodies)}"
    return bodies[0]


def secret_findings(text: str) -> list[str]:
    found = []
    for lineno, line in enumerate(strip_comments(text).splitlines(), 1):
        for pat in SECRET_VALUE_PATTERNS:
            if pat.search(line):
                found.append(f"line {lineno}: value matches {pat.pattern[:30]}")
        param = re.match(r"\s*param\s+(\w+)\s*=\s*(.+)$", line)
        if param and SECRET_KEY_NAMES.search(param.group(1)):
            found.append(f"line {lineno}: parameter {param.group(1)} looks like a secret")
    return found


def identity_findings(body: str) -> list[str]:
    """A compute resource must run as a user-assigned managed identity; system-assigned or none is a finding."""
    found = []
    if not re.search(r"identity:\s*\{[^{}]*type:\s*'UserAssigned'", body):
        found.append("identity type is not UserAssigned")
    if re.search(r"SystemAssigned", body):
        found.append("system-assigned identity used")
    if not re.search(r"userAssignedIdentities:\s*\{", body):
        found.append("no userAssignedIdentities binding")
    return found


def function_findings(text: str) -> list[str]:
    code = strip_comments(text)
    try:
        site = block(text, "Microsoft.Web/sites@")
    except AssertionError as exc:
        return [str(exc)]
    found = identity_findings(site)
    checks = {
        "httpsOnly true": r"httpsOnly:\s*true\b",
        "ftpsState Disabled": r"ftpsState:\s*'Disabled'",
        "minTlsVersion 1.2": r"minTlsVersion:\s*'1\.2'",
        "identity-based storage account setting": r"AzureWebJobsStorage__accountName",
        "storage credential managedidentity": r"AzureWebJobsStorage__credential'?\s*,?\s*value:\s*'managedidentity'",
        "storage client id setting": r"AzureWebJobsStorage__clientId",
        "keyVaultReferenceIdentity": r"keyVaultReferenceIdentity:\s*\w+",
        "tags applied": r"(?m)^\s*tags:\s*\w+",
    }
    found += [f"missing {label}" for label, pat in checks.items() if not re.search(pat, site)]
    if re.search(r"httpsOnly:\s*false|publicNetworkAccess:\s*'Enabled'", site):
        found.append("a protection is explicitly weakened")
    if KEY_BASED_SETTINGS.search(code):
        found.append("key or connection-string based setting")
    return found


GOOD_SITE = """
resource app 'Microsoft.Web/sites@2023-12-01' = {
  name: name
  location: location
  kind: 'functionapp,linux'
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${identityId}': {}
    }
  }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    keyVaultReferenceIdentity: identityId
    siteConfig: {
      ftpsState: 'Disabled'
      minTlsVersion: '1.2'
      appSettings: [
        { name: 'AzureWebJobsStorage__accountName', value: storageAccountName }
        { name: 'AzureWebJobsStorage__credential', value: 'managedidentity' }
        { name: 'AzureWebJobsStorage__clientId', value: identityClientId }
      ]
    }
  }
}
"""


# ---- the checkers themselves must bite (mutation checks) ----


@pytest.mark.parametrize(
    ("old", "new", "expect"),
    [
        ("type: 'UserAssigned'", "type: 'SystemAssigned'", "UserAssigned"),
        ("httpsOnly: true", "httpsOnly: false", "httpsOnly"),
        ("ftpsState: 'Disabled'", "ftpsState: 'AllAllowed'", "ftpsState"),
        ("minTlsVersion: '1.2'", "minTlsVersion: '1.0'", "minTlsVersion"),
        ("AzureWebJobsStorage__accountName", "AzureWebJobsStorage", "storage"),
        ("  tags: tags\n", "", "tags"),
    ],
)
def test_b86_1_checker_flags_each_weakened_function_property(old: str, new: str, expect: str) -> None:
    assert function_findings(GOOD_SITE) == []
    findings = function_findings(GOOD_SITE.replace(old, new))
    assert any(expect.lower() in f.lower() for f in findings), findings


def test_b86_1_checker_flags_connection_strings_and_keys() -> None:
    leaky = GOOD_SITE.replace("'AzureWebJobsStorage__clientId'", "'WEBSITE_CONTENTAZUREFILECONNECTIONSTRING'")
    assert any("key or connection" in f for f in function_findings(leaky))
    assert any("key or connection" in f for f in function_findings(GOOD_SITE + "\nvar k = listKeys(sa.id, '1')\n"))


def test_b86_1_commented_out_property_does_not_count() -> None:
    assert function_findings(GOOD_SITE.replace("httpsOnly: true", "// httpsOnly: true"))


@pytest.mark.parametrize(
    "line",
    [
        "param sqlPassword = 'x'",
        "param x = 'AccountKey=abcd'",
        "param x = 'DefaultEndpointsProtocol=https;AccountName=a'",
        "param x = '-----BEGIN RSA PRIVATE KEY-----'",
        "param x = '" + "Ab1" * 15 + "'",
    ],
)
def test_b86_1_secret_scanner_flags_planted_values(line: str) -> None:
    assert secret_findings(line), line


def test_b86_2_deploy_patterns_match_what_they_should() -> None:
    for s in (
        "az deployment group create -g rg -f main.bicep",
        "az group create -n rg",
        "az functionapp deployment source config-zip",
        "deploymentMode: Incremental",
        "task: AzureResourceManagerTemplateDeployment@3",
    ):
        assert any(p.search(s) for p in DEPLOY_PATTERNS), s
    for s in ("az deployment group what-if -g rg", "az deployment group validate -g rg", "az bicep lint --file x"):
        assert not any(p.search(s) for p in DEPLOY_PATTERNS), s


# ---- B86-1: compute modules ----


def test_b86_1_expected_files_exist() -> None:
    for name in MODULE_FILES:
        assert (MODULES / name).is_file(), name
    assert (COMPUTE / "main.bicep").is_file()
    assert (COMPUTE / "README.md").is_file()
    for p in PARAM_FILES:
        assert p.is_file(), p.name


def test_b86_1_function_app_has_all_required_properties() -> None:
    assert function_findings(read_module("functionApp.bicep")) == []


def test_b86_1_function_app_runs_on_an_app_service_plan_resource() -> None:
    types = [t for t, _ in resource_blocks(read_module("functionApp.bicep"))]
    assert any(t.startswith("Microsoft.Web/serverfarms@") for t in types)
    assert any(t.startswith("Microsoft.Web/sites@") for t in types)


def test_b86_1_function_app_publishing_credentials_are_off() -> None:
    blocks = resource_blocks(read_module("functionApp.bicep"))
    policies = [(t, b) for t, b in blocks if "basicPublishingCredentialsPolicies" in t]
    assert len(policies) == 2, "ftp and scm policies expected"
    for t, b in policies:
        assert re.search(r"allow:\s*false\b", b), t


def test_b86_1_storage_has_no_shared_key_access_and_no_public_blobs() -> None:
    body = block(read_module("storageAccount.bicep"), "Microsoft.Storage/storageAccounts@")
    for label, pat in {
        "allowSharedKeyAccess false": r"allowSharedKeyAccess:\s*false\b",
        "allowBlobPublicAccess false": r"allowBlobPublicAccess:\s*false\b",
        "supportsHttpsTrafficOnly true": r"supportsHttpsTrafficOnly:\s*true\b",
        "minimumTlsVersion TLS1_2": r"minimumTlsVersion:\s*'TLS1_2'",
        "defaultToOAuthAuthentication true": r"defaultToOAuthAuthentication:\s*true\b",
        "tags applied": r"(?m)^\s*tags:\s*\w+",
    }.items():
        assert re.search(pat, body), f"missing {label}"
    assert not re.search(r"allowSharedKeyAccess:\s*true|allowBlobPublicAccess:\s*true", body)


def test_b86_1_storage_role_for_the_function_identity_is_blob_data_owner_only() -> None:
    text = strip_comments(read_module("storageAccount.bicep"))
    assert "Microsoft.Authorization/roleAssignments@" in text
    assert "principalType: 'ServicePrincipal'" in text
    assert "b7e6dc6d-f1e8-4753-8033-0f276bb0955b" in text, "Storage Blob Data Owner role definition id"
    # Owner / Contributor / User Access Administrator must never be granted by this template.
    for forbidden in (
        "8e3af657-a8ff-443c-a75c-2fe8c4bcb635",
        "b24988ac-6180-42a0-ab88-20f7382dd24c",
        "18d7d88d-d35e-4fb5-a5c3-7773c20a72d9",
    ):
        assert forbidden not in text


def test_b86_1_logic_app_is_user_assigned_identity_and_starts_disabled() -> None:
    body = block(read_module("logicApp.bicep"), "Microsoft.Logic/workflows@")
    assert identity_findings(body) == []
    assert re.search(r"state:\s*'Disabled'", body), "the workflow ships disabled until a human enables it"
    assert re.search(r"(?m)^\s*tags:\s*\w+", body)
    assert not re.search(r"\bapiKey\b|\bBasic\b|\bpassword\b|\bsecret\b", body, re.I), (
        "no stored credential in the definition"
    )


def test_b86_1_automation_account_is_identity_only() -> None:
    body = block(read_module("automationAccount.bicep"), "Microsoft.Automation/automationAccounts@")
    assert identity_findings(body) == []
    assert re.search(r"disableLocalAuth:\s*true\b", body)
    assert re.search(r"publicNetworkAccess:\s*false\b", body)
    assert re.search(r"(?m)^\s*tags:\s*\w+", body)
    assert not re.search(
        r"Microsoft\.Automation/automationAccounts/(credentials|connections|certificates|variables)", body
    )
    code = strip_comments(read_module("automationAccount.bicep"))
    assert not re.search(r"automationAccounts/(credentials|connections|certificates)@", code), (
        "no stored credential resources"
    )


@pytest.mark.parametrize("name", MODULE_FILES)
def test_b86_1_every_module_is_free_of_keys_and_secret_literals(name: str) -> None:
    text = read_module(name)
    code = strip_comments(text)
    assert secret_findings(text) == []
    assert not KEY_BASED_SETTINGS.search(code), name
    assert not re.search(r"@secure\(\)\s*param\s+\w+\s+\w+\s*=", text)
    assert "SystemAssigned" not in code, "compute runs as the user-assigned identity from core, never a system one"
    assert "Microsoft.KeyVault/vaults/secrets" not in code


def test_b86_1_every_taggable_resource_gets_tags() -> None:
    untaggable = ("roleAssignments", "basicPublishingCredentialsPolicies", "diagnosticSettings")
    for name in MODULE_FILES:
        for rtype, body in resource_blocks(read_module(name)):
            if any(u in rtype for u in untaggable):
                continue
            assert re.search(r"(?m)^\s*tags:\s*\w+", body), f"{name}: {rtype} has no tags"


def test_b86_1_main_takes_the_core_identity_and_never_creates_one() -> None:
    text = strip_comments((COMPUTE / "main.bicep").read_text(encoding="utf-8"))
    for param in ("identityId", "identityPrincipalId", "identityClientId"):
        assert re.search(rf"(?m)^param\s+{param}\s+string\b", text), param
    assert "Microsoft.ManagedIdentity/userAssignedIdentities" not in text
    mods = re.findall(r"(?ms)^module\s+\w+\s+'([^']+)'\s*=\s*\{(.*?)^\}", text)
    used = {path.split("/")[-1] for path, _ in mods}
    assert set(MODULE_FILES) <= used
    for path, body in mods:
        assert re.search(r"tags:\s*\w+", body), path
    for path, body in mods:
        if path.endswith(("functionApp.bicep", "logicApp.bicep", "automationAccount.bicep")):
            assert "identityId" in body, path


def test_b86_1_main_environment_allows_dev_and_prod_only() -> None:
    text = strip_comments((COMPUTE / "main.bicep").read_text(encoding="utf-8"))
    assert re.search(r"@allowed\(\s*\[\s*'dev'\s*,?\s*'prod'\s*\]\s*\)\s*param\s+environment\b", text)
    for tag in REQUIRED_TAGS:
        assert re.search(rf"\b{tag}\b", text), tag


@pytest.mark.parametrize("path", PARAM_FILES, ids=lambda p: p.name)
def test_b86_1_parameter_files_are_placeholders_and_plain_names(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert re.search(r"(?m)^using\s+'\./main\.bicep'", text)
    assert secret_findings(text) == []
    for tag in REQUIRED_TAGS:
        assert re.search(rf"(?m)^param {tag} = ", text), f"{path.name}: {tag}"
    env = "dev" if "dev" in path.name else "prod"
    assert re.search(rf"param environment = '{env}'", text)
    for p in ("identityId", "identityPrincipalId", "identityClientId", "workspaceId"):
        assert re.search(rf"param {p} = '<[a-z-]+>'", text), (
            f"{path.name}: {p} must be a <placeholder>, never a real id"
        )
    assert not re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", text, re.I), "no GUIDs"
    assert "/subscriptions/" not in text


@pytest.mark.parametrize("path", sorted(COMPUTE.rglob("*.bicep*")), ids=lambda p: p.name)
def test_b86_1_no_secret_literal_in_any_compute_file(path: Path) -> None:
    assert secret_findings(path.read_text(encoding="utf-8")) == []


def test_b86_1_readme_gives_human_only_validate_and_whatif_steps() -> None:
    text = (COMPUTE / "README.md").read_text(encoding="utf-8")
    assert "az bicep build" in text and "az bicep lint" in text
    assert "az deployment group validate" in text and "az deployment group what-if" in text
    assert "human" in text.lower() and "nothing here has been compiled" in text.lower()


# ---- B86-2: pipeline ----


def pipeline_text() -> str:
    return PIPELINE.read_text(encoding="utf-8")


def stages(text: str) -> dict[str, str]:
    """Stage name -> its text (comments stripped). Stages sit at `  - stage: Name` under a top-level `stages:`."""
    code = strip_yaml_comments(text)
    m = re.search(r"(?m)^stages:\s*$", code)
    assert m, "top-level stages: missing"
    body = code[m.end() :]
    parts = re.split(r"(?m)^  - stage:\s*(\S+)\s*$", body)
    return {parts[i]: parts[i + 1] for i in range(1, len(parts) - 1, 2)}


def stage_order(text: str) -> list[str]:
    return list(stages(text))


def depends_on(stage_body: str) -> list[str]:
    m = re.search(r"(?m)^    dependsOn:[ \t]*(.*)$", stage_body)
    if not m:
        return []
    inline = m.group(1).strip()
    if inline.startswith("["):
        return [s.strip() for s in inline.strip("[]").split(",") if s.strip()]
    if inline:
        return [inline]
    block_m = re.search(r"(?m)^    dependsOn:\s*\n((?:      - .*\n)+)", stage_body)
    return re.findall(r"(?m)^      - (\S+)\s*$", block_m.group(1)) if block_m else []


def pipeline_findings(text: str) -> list[str]:
    """Structural problems with the gate: empty means what-if, then approval, then a disabled deploy, in that order."""
    found: list[str] = []
    try:
        st = stages(text)
    except AssertionError as exc:
        return [str(exc)]
    order = list(st)
    for name in ("Test", "Lint", "WhatIf", "Approval", "Deploy"):
        if name not in st:
            found.append(f"stage {name} missing")
    if found:
        return found
    if not (order.index("Test") < order.index("WhatIf") < order.index("Approval") < order.index("Deploy")):
        found.append("stage order must be Test, WhatIf, Approval, Deploy")
    if "WhatIf" not in depends_on(st["Approval"]):
        found.append("Approval does not depend on WhatIf")
    if "Approval" not in depends_on(st["Deploy"]):
        found.append("Deploy does not depend on Approval")
    if not {"Test", "Lint"} <= set(depends_on(st["WhatIf"])):
        found.append("WhatIf must depend on Test and Lint")
    approval = st["Approval"]
    if "ManualValidation@" not in approval:
        found.append("Approval has no ManualValidation task")
    if "pool: server" not in approval and "pool:\n      name: server" not in approval:
        found.append("ManualValidation must run in a server job")
    if not re.search(r"onTimeout:\s*reject\b", approval):
        found.append("approval must reject on timeout")
    if re.search(r"onTimeout:\s*resume", approval):
        found.append("approval resumes on timeout")
    if re.search(r"continueOnError:\s*true|condition:\s*(always|succeededOrFailed)\(\)|condition:\s*true", approval):
        found.append("approval can be skipped or ignored")
    if not re.search(r"(?m)^    condition:\s*false\s*$", st["Deploy"]):
        found.append("Deploy stage is not disabled with condition: false")
    if re.search(r"(?m)^    condition:\s*(always|succeededOrFailed|true)", st["Deploy"]):
        found.append("Deploy stage condition overrides the gate")
    if re.search(r"(?i)\bwhat-if\b|\bwhatif\b", st["Deploy"]) and "echo" not in st["Deploy"]:
        found.append("unexpected content in Deploy")
    for name, body in st.items():
        for pat in DEPLOY_PATTERNS:
            if pat.search(body):
                found.append(f"{name}: deploy command matches {pat.pattern[:30]}")
    return found


GOOD_PIPELINE = """
stages:
  - stage: Test
    jobs: []
  - stage: Lint
    jobs: []
  - stage: WhatIf
    dependsOn:
      - Test
      - Lint
    jobs: []
  - stage: Approval
    dependsOn:
      - WhatIf
    jobs:
      - job: Gate
        pool: server
        steps:
          - task: ManualValidation@1
            inputs:
              onTimeout: reject
  - stage: Deploy
    dependsOn:
      - Approval
    condition: false
    jobs:
      - job: Disabled
        steps:
          - script: echo disabled
"""


@pytest.mark.parametrize(
    ("old", "new", "expect"),
    [
        ("ManualValidation@1", "Bash@3", "ManualValidation"),
        ("onTimeout: reject", "onTimeout: resume", "timeout"),
        ("    condition: false\n", "", "disabled"),
        ("    dependsOn:\n      - Approval\n", "", "Deploy does not depend"),
        ("    dependsOn:\n      - WhatIf\n", "", "Approval does not depend"),
        ("pool: server", "pool: ubuntu", "server job"),
        ("echo disabled", "az deployment group create -g rg", "deploy command"),
        ("echo disabled", "az functionapp deployment source config-zip", "deploy command"),
    ],
)
def test_b86_2_gate_checker_flags_each_weakening(old: str, new: str, expect: str) -> None:
    assert pipeline_findings(GOOD_PIPELINE) == []
    findings = pipeline_findings(GOOD_PIPELINE.replace(old, new))
    assert any(expect.lower() in f.lower() for f in findings), findings


def test_b86_2_gate_checker_flags_wrong_stage_order() -> None:
    swapped = GOOD_PIPELINE.replace("- stage: Approval", "- stage: Tmp").replace("- stage: WhatIf", "- stage: Approval")
    assert pipeline_findings(swapped)


def test_b86_2_gate_checker_flags_always_condition_on_approval() -> None:
    bad = GOOD_PIPELINE.replace("        pool: server", "        pool: server\n        continueOnError: true")
    assert any("skipped" in f for f in pipeline_findings(bad))


def test_b86_2_pipeline_gate_structure_is_sound() -> None:
    assert pipeline_findings(pipeline_text()) == []


def test_b86_2_stage_order_is_the_documented_one() -> None:
    assert stage_order(pipeline_text()) == ["Test", "Lint", "WhatIf", "Approval", "Deploy"]


def test_b86_2_deploy_stage_is_disabled_and_runs_nothing_that_deploys() -> None:
    deploy = stages(pipeline_text())["Deploy"]
    assert re.search(r"(?m)^    condition:\s*false\s*$", deploy)
    steps = re.findall(r"(?m)^\s*-\s+(script|bash|pwsh|powershell|task):", deploy)
    assert all(s == "script" for s in steps), "the disabled stage may only echo"
    for line in re.findall(r"(?m)^\s*-\s+script:\s*(.*)$", deploy):
        assert line.strip().startswith("echo"), line


def test_b86_2_no_deploy_command_or_arm_deployment_task_anywhere_in_the_file() -> None:
    raw = pipeline_text()  # comments included: a command in a comment is one paste away from live
    for pat in DEPLOY_PATTERNS:
        assert not pat.search(raw), pat.pattern


def test_b86_2_whatif_stage_runs_validate_and_what_if() -> None:
    body = stages(pipeline_text())["WhatIf"]
    assert "az deployment group validate" in body
    assert "az deployment group what-if" in body
    assert "AzureCLI@2" in body
    assert "--no-pretty-print" in body or "--result-format" in body
    assert re.search(r"PublishPipelineArtifact@1|publish:", body), "what-if output is kept for the approver"


def test_b86_2_lint_stage_builds_and_lints_both_bicep_folders_with_no_cloud_access() -> None:
    body = stages(pipeline_text())["Lint"]
    for folder in ("infra/bicep/core", "infra/bicep/compute"):
        assert folder in body, folder
    assert "az bicep build" in body and "az bicep lint" in body
    assert "AzureCLI@2" not in body and "azureSubscription" not in body, "lint needs no cloud sign-in"


def test_b86_2_service_connection_and_resource_group_are_placeholders() -> None:
    text = strip_yaml_comments(pipeline_text())
    for name in ("azureServiceConnection", "resourceGroupName"):
        m = re.search(rf"(?ms)- name: {name}\s*\n\s*type: string\s*\n\s*default: '([^']*)'", text)
        assert m, name
        assert m.group(1).startswith("<") and m.group(1).endswith(">"), f"{name} default must be a <placeholder>"


def test_b86_2_pipeline_has_no_secret_literals_or_secret_variables() -> None:
    raw = pipeline_text()
    code = strip_yaml_comments(raw)
    for lineno, line in enumerate(code.splitlines(), 1):
        for pat in SECRET_VALUE_PATTERNS:
            assert not pat.search(line), f"line {lineno}"
    assert not re.search(r"(?i)\$\(System\.AccessToken\)|SYSTEM_ACCESSTOKEN", code)
    assert not re.search(r"(?im)^\s*(?:-\s*)?(?:name|key):\s*\w*(?:secret|password|token|key)\w*\s*$", code)
    assert not re.search(r"(?i)isSecret|persistCredentials:\s*true", code)
    assert not re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", raw, re.I), "no GUIDs"


def test_b86_2_pipeline_does_not_trigger_on_branches_other_than_main_and_prs() -> None:
    code = strip_yaml_comments(pipeline_text())
    trig = re.search(r"(?ms)^trigger:\s*\n(.*?)^(?=\S)", code)
    assert trig and re.search(r"-\s+main\b", trig.group(1))
    assert re.search(r"(?m)^pr:", code)
    assert "schedules:" in code, "nightly run mirrors ci.yml"


def ci_commands() -> list[str]:
    """Suite commands from ci.yml that the pipeline must also run: pwsh suite files and the pytest line."""
    text = CI_YML.read_text(encoding="utf-8")
    cmds = sorted(set(re.findall(r"pwsh -NoProfile -File (tests/[\w./-]+\.ps1)", text)))
    assert len(cmds) >= 3, cmds
    return cmds


@pytest.mark.parametrize("script", ci_commands())
def test_b86_2_pipeline_mirrors_every_ci_yml_suite(script: str) -> None:
    assert script in strip_yaml_comments(pipeline_text()), script


def test_b86_2_pipeline_mirrors_the_ci_yml_pytest_line_and_deselect() -> None:
    ci = CI_YML.read_text(encoding="utf-8")
    m = re.search(r"uv run --frozen pytest -p no:cacheprovider tests/py --deselect (\S+)", ci)
    assert m, "ci.yml pytest line changed; update the pipeline and this test together"
    code = strip_yaml_comments(pipeline_text())
    assert f"uv run --frozen pytest -p no:cacheprovider tests/py --deselect {m.group(1)}" in code
    assert "UV_PYTHON_PREFERENCE" in code and "only-managed" in code


def test_b86_2_pipeline_runs_secret_scan_suite_and_eval_gate() -> None:
    body = stages(pipeline_text())["Test"]
    assert "tests/ps/Test-Modules.ps1" in body, "the PowerShell lever suites run in the pipeline"
    assert "tests/py/infra" in body, "the static IaC checks run in the pipeline too"
    assert "tools/eval_gate.py" in body, "eval gate"


def test_b86_2_pipeline_pins_uv_and_never_leaves_it_floating() -> None:
    code = strip_yaml_comments(pipeline_text())
    assert re.search(r"uv==\d+\.\d+\.\d+", code)


def test_b86_2_ci_yml_and_workflows_are_untouched_by_this_item() -> None:
    # B-86 may not edit .github/**: a pipeline proposal lives under infra/ for a human to review.
    assert PIPELINE.parent.name == "infra"
    assert not (REPO / ".github" / "workflows" / "azure-pipelines.yml").exists()


# ---- B86-3: release doc ----


def release_text() -> str:
    return RELEASE_DOC.read_text(encoding="utf-8")


def test_b86_3_release_doc_covers_the_required_topics() -> None:
    low = release_text().lower()
    for needle in (
        "branches",
        "pull request",
        "semver",
        "std-vr",
        "changelog",
        "ring",
        "cm-5",
        "rollback",
        "cm-6",
        "approval",
        "what-if",
        "freeze",
        "unverified",
    ):
        assert needle in low, needle


def test_b86_3_release_doc_defines_four_rings_in_order() -> None:
    text = release_text()
    positions = [text.find(r) for r in ("R0", "R1", "R2", "R3")]
    assert all(p >= 0 for p in positions), positions
    assert positions == sorted(positions)
    low = text.lower()
    assert "test tenant" in low and "pilot" in low and "10%" in text and "all tenants" in low


def test_b86_3_release_doc_states_agents_never_approve_or_merge_and_no_agent_deploys() -> None:
    text = release_text()
    assert re.search(r"(?i)agents? never (?:approve|merge)", text)
    assert re.search(r"(?i)no (?:agent|pipeline stage in this repo)[^.\n]*deploy", text)
    assert re.search(r"(?i)human", text)


def test_b86_3_release_doc_rollback_keeps_previous_lever_version_registered_and_pins_per_tenant() -> None:
    text = release_text()
    assert re.search(r"(?i)previous (?:lever )?version", text)
    assert re.search(r"(?i)pin(?:ned)? per tenant", text)


def test_b86_3_release_doc_names_the_branch_and_tag_patterns() -> None:
    text = release_text()
    assert "<kind>/b<nn>-<slug>" in text
    assert re.search(r"v0\.<wave>\.0", text)
    assert "main" in text and "enterprise" in text


def test_b86_3_release_doc_says_which_rules_are_enforced_and_which_are_convention() -> None:
    low = release_text().lower()
    assert "convention" in low
    assert "branch protection" in low


def test_b86_3_release_doc_has_no_secret_values_or_deploy_commands() -> None:
    text = release_text()
    assert secret_findings(text) == []
    for pat in DEPLOY_PATTERNS:
        assert not pat.search(text), pat.pattern


# ---- nothing is deployed anywhere in what this item adds ----


def test_b86_no_new_file_creates_or_deploys_anything() -> None:
    files = [p for p in COMPUTE.rglob("*") if p.is_file()] + [PIPELINE, RELEASE_DOC]
    assert len(files) >= 9
    for f in files:
        text = f.read_text(encoding="utf-8", errors="replace")
        for pat in DEPLOY_PATTERNS:
            assert not pat.search(text), f"{f.relative_to(REPO)} matches {pat.pattern}"
