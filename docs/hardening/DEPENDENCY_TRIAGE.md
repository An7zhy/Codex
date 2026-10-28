# Dependency remediation record — 2026-10-28

Baseline: [original scanner summary](../audit/dependency_summary.json) and
[raw original notices](../audit/pip_audit.json). These reported 90 records across
four packages, with duplicate/alias records; not 90 independently demonstrated
remote vulnerabilities. No malicious package/image/UNC exploitation was executed.

| Package | Original → installed | Applicability review | Remediation and evidence |
| --- | --- | --- | --- |
| Streamlit | 1.50.0 → 1.66.1 | Original notices include Windows component UNC/SSRF/NTLM exposure (fix ≥1.54) and a local hashing issue (≥1.53.1). Windows exploitability was not executed; retaining an affected Windows fallback was relevant to this project's users. | Upgraded above both reported fixes. AppTest and real Chromium V1/V2 parameter and V3 regressions passed. Fallback is absent from clean API runtime, loopback by default and stopped in pilot mode. |
| Pillow | 11.3.0 → 13.0.0 | Original notices concern image/font decoders and resource limits; source search found no `Image.open`, `st.image` or PIL import in app.py/src/backend. CSV/XLSX ingestion is not proof those decoder exploits are reachable. | Version13 covers the original reported fixes up to13. Initial Streamlit1.54+Pillow13 dependency resolution was rejected (`pillow<13`), so used compatible Streamlit1.66.1. No vulnerability suppression/ignored advisory IDs. Pillow not installed in clean API runtime. |
| pip | 25.0.1 → 26.2.2 | Installer/archive/index vulnerabilities, not business HTTP endpoints. One fallback-tar advisory has Python≥3.12 mitigation, but remaining installer notices still needed maintenance. | Upgraded installer above reported26.2 fixes; bootstrap docs/Windows launcher pin this version. Not treated as an API authorization fix. |
| pytest | 8.4.2 → 9.0.3 | UNIX temporary-directory local-user issue; development tool, not API runtime. | Upgraded to the reported fixed release. Full regression executed; pytest absent from clean API runtime. |

`requirements-core.txt` holds original calculation dependencies plus defusedxml.
`requirements-web.txt` includes that core and FastAPI/uvicorn/multipart;
`requirements.txt` keeps the patched local Streamlit/test stack;
`requirements-dev.txt` installs both and browser/API test tools. Production should
use a fresh web venv. Reused environments are not cleaned by excluding a package
from a requirements file; upgrade existing fallback requirements or create a new venv.

Actual isolated pip-audit2.10.1 scan of the updated development/application venv:
**exit0, 0 known advisory records**, [raw JSON](pip_audit.json).
Actual npm production audit: **exit0, 0 known notices**, [raw JSON](npm_audit.json).
[Clean web-only install/import/solver evidence](clean_web_runtime.json) separately
checks the runtime split. These are dated advisory database snapshots, not proof
of zero vulnerabilities or completed Windows/public-network security testing.

Streamlit's test APIs changed: relative AppTest paths now resolve from the calling
test file; unsubmitted form values are sent only when submitted and a forced
AppTest run rebuilds committed server values. Tests use absolute script paths and
re-stage identical client drafts after the unchanged "not applied" assertions.
All numerical/context assertions are retained. Real browser tests independently
verify draft/applied changes and retained shipment selection; see
[parameters](streamlit_parameters.json) and [V3](streamlit_transport.json).
