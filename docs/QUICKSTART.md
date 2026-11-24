# VM Quickstart: create a read-only preview

Success means a new private PDF headed **PREVIEW - NO CHANGES**, with **0 committed changes**. Start on a disposable, approved PostgreSQL VM/database copy. Preview does not change the database, but large scans use database resources.

## 1. Set up Jupyter

You need Python 3.10+, the whole project folder, and access to an approved Python package index or approved local wheels. Paste the block into a terminal **on the VM that runs Jupyter**, replacing the example path with the folder that contains `requirements.txt`. Stop if any line fails.

```bash
cd /path/to/OMOP-Concept-Remediation
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m ipykernel install --user --name concept-remediation --display-name "Concept Remediation"
```

If JupyterLab is already running, use it. Otherwise, from the same folder run `.venv/bin/python -m jupyter lab`.

**Windows VM:** use PowerShell and the actual local project path. Run `py -3 -m venv .venv`, then replace each `.venv/bin/python` command above (including the optional launch) with `.\.venv\Scripts\python.exe`. No global installation, activation or change to execution policy is needed.

## 2. Open the notebook and enter your settings

1. Open `Preview_concept_remediation.ipynb` from the project folder. Click **Kernel > Change Kernel > Concept Remediation**. Run the first code cell without changing it: it should say **Preview only; no connection made.**
2. In the next code cell, enter `cdm_schema`, `vocabulary_schema` and `cdm_version` (`"5.4"` or `"5.5"`, matching `CDM_SOURCE.cdm_version`). Set `private_output` to a site-approved private folder **outside this project**.
3. In the first cell, set `RUN_DATABASE = True` and rerun it. Then run the second cell. Run the remaining cells individually after enabling the connection. Enter the DBA-provided hostname, port (blank means 5432), database name, **read-only username**, and password when prompted. Enter the CA certificate path if the DBA provides one; otherwise leave that prompt blank to use the PostgreSQL client's default CA lookup on the VM. Use the hostname on the certificate and keep `sslmode="verify-full"`. Never paste credentials into code cells or save them in config.
4. Read **Selected available event tables** and the coverage/exclusions. If they match your approved scope, run the scan cell and open the new `preview_<id>.pdf` in the private folder. Run the final cell to close the connection. Save or share notebook copies only after removing outputs and any site-specific private details.

## Check the result

| What you see | Meaning / action |
|---|---|
| Proposed replacements | Structurally eligible, not approved. Ask the domain owner to review the proposed meaning. |
| Blocked or review rows | Investigate the reason and listed candidates. Rows marked `same group` repeat the finding, not its count. |
| No proposed replacements | The report is still valid; check blocked findings and exclusions. |
| Missing or inaccessible fields | Coverage is incomplete. Confirm schemas and grants with the DBA; this does not mean zero occurrences. |
| Import, certificate, scope or PDF error | Stop, close the connection if open, and fix the kernel/project path, CA, scope or private output location. Do not weaken TLS or switch to apply. |

Counts are event/field occurrences, not distinct patients. Reports can contain exact small counts and local labels. Keep them private and seek site disclosure review before sharing.

## Advanced controls

`as_of` defaults to today. Set a fixed ISO date only when the review calls for it. The starting `tables` value in the connection cell is a bootstrap placeholder; discovery replaces it with visible supported event tables. If authorized to narrow primary-event scope **after discovery**, add a cell before the scan, for example:

```python
from dataclasses import replace
cfg = replace(cfg, tables=("condition_occurrence",))
```

The separate versioned audit still inventories other fields. A site name is not a row filter. Preview is never permission to apply; see the [operator and DBA guide](SAFETY.md) for that separate workflow.
