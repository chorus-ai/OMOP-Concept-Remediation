# Preview troubleshooting

Use a Terminal on the machine where the notebook kernel runs for file and Python setup. Use notebook cells to enter connection settings, run the scan, and save the report. No step below requires administrator rights, a write-capable database account, or a change to TLS verification.

## Git or virtual environment permission errors

- **Clone fails on `chmod` or file permissions.** The storage may allow ordinary file writes but not the permission changes Git needs. If GitHub access is approved, use **Code > Download ZIP** and extract a fresh copy of the whole project into a writable folder visible in Jupyter. Open the notebook beside the `remediation/` and `sql/` folders. ZIP extraction does not prove the folder can publish reports.
- **Creating `.venv` in the project fails.** On a Linux VM, if permitted, create an isolated environment on a writable local filesystem. The example uses a private directory in `/tmp` for the environment only, not for reports. It may be removed on restart, and some managed instances do not execute from `/tmp`. Use an approved alternative when needed.

```bash
# Run from the extracted or cloned project folder.
VENV_DIR=$(mktemp -d /tmp/concept-remediation-XXXXXX)
python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install -r requirements.txt
"$VENV_DIR/bin/python" -m ipykernel install --user --name concept-remediation-vm --display-name "Concept Remediation (VM)"
```

Use locally approved package sources. If a command fails, stop before the next line. If no approved environment or ready kernel is available, arrange one rather than modifying system Python or bypassing restrictions.

## Kernel registration reports a permissions error

If the error appeared in `ipykernel install`, the packages may already be installed and the kernel may already be visible. Run `jupyter kernelspec list` in the JupyterLab terminal. If the intended name is listed, reload JupyterLab, select that kernel from the notebook tab, and run only the setup cell. In a new cell test `import sys, ipykernel, psycopg, reportlab; print(sys.executable)` before connecting. A listed kernelspec may still refer to an interpreter that no longer exists. Confirm the interpreter with `import sys; print(sys.executable)` if needed.

If the kernel is not listed and your user Jupyter data directory is writable, register a minimal kernelspec under a **new** name. This writes only `kernel.json`, without copying optional logos and permissions. On Linux, with the `VENV_DIR` above set in the same Terminal:

```bash
JUPYTER_DATA_DIR_FOR_KERNEL=$(jupyter --data-dir)
"$VENV_DIR/bin/python" - "$JUPYTER_DATA_DIR_FOR_KERNEL" <<'PY'
import json
import sys
from pathlib import Path

folder = Path(sys.argv[1]) / "kernels" / "concept-remediation-private"
folder.mkdir(parents=True, exist_ok=True)
with (folder / "kernel.json").open("x", encoding="utf-8") as f:
    json.dump({
        "argv": [sys.executable, "-m", "ipykernel_launcher", "-f", "{connection_file}"],
        "display_name": "Concept Remediation (private)",
        "language": "python",
    }, f)
PY
jupyter kernelspec list
```

Reload and select **Concept Remediation (private)**. If an entry already exists, do not overwrite it. If the user data directory is not writable or the server does not load user kernels, use an approved preconfigured kernel.

## Certificate verification

Keep `sslmode="verify-full"`. Enter the exact database DNS name provided by the site and covered by the certificate. The address shown in a connection error can be a resolved IP even if you entered the DNS name.

- At the CA prompt, enter an **approved CA bundle** readable by the notebook kernel. For example, on Debian-based Linux systems the system bundle is commonly `/etc/ssl/certs/ca-certificates.crt`; use it only if it is available and approved for the server. Use the site's approved CA for private certificates. Do not download an unknown certificate or disable verification.
- Alternatively, enter `system` if your runtime uses libpq 16 or later and the system trust pool is approved. Leaving the prompt blank uses libpq's configured/default lookup, which may be `~/.postgresql/root.crt`; it is not the same as `system`.
- If terminal verification succeeds but the notebook still fails, confirm the kernel can read the same CA path and is using the intended interpreter. The libpq bundled with Psycopg may differ from the terminal client. In the notebook, `import psycopg; print(psycopg.pq.__impl__, psycopg.pq.version())` checks the runtime without a database call.

## Output and recovery

Choose an approved private output folder outside the repository. The notebooks test writes with a synthetic file before scanning or applying changes. If it fails, check the selected folder and permissions and choose an approved alternative. See [Reports and recovery](REPORTING.md).

- Preview: save again from the same in-memory snapshot without rescanning. If the kernel was lost, reconnect and run a new read-only Preview; it gets a new report ID.
- Commit: if the run committed but a report did not save, use the journal-only regeneration cell. If the commit outcome is unknown, reconcile the recorded run ID against the approved target and journal before any retry. Do not rerun Apply for a file error.
- Unfinished plan after kernel loss: review and rehearse a fresh plan unless the exact stored plan and independently recorded identity can be verified by the operator. Reconnecting is not approval to resume or repeat a write.

## Limit the primary-event scan

The connection discovers available supported event tables. If the review authorizes only part of that scope, add a cell after discovery and before scanning, for example:

```python
from dataclasses import replace

cfg = replace(cfg, tables=("condition_occurrence",))
```

The separate read-only audit still inventories other CDM fields. A site name does not filter rows. The vocabulary validity date `as_of` defaults to today; choose a fixed ISO date only when required for the review.
