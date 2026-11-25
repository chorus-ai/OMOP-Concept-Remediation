# Quickstart: run a read-only Preview

Use Preview to see proposed concept replacements, findings that need manual review, and what the scan covered. It does not update the database. You need Python 3.10 or later, the project files, an approved PostgreSQL database, its CDM and vocabulary schema names, a read-only account, and a private report folder outside the repository.

## 1. Get the project on the machine that runs Jupyter

Use **Terminal** to get the files, install the Python packages, and register the notebook kernel. Do not enter database credentials there. If JupyterLab runs on a VM or JupyterHub and you access it in your browser, open **File > New > Terminal** in JupyterLab. Your laptop's terminal prepares only your laptop. For a local run, use PowerShell on Windows or Terminal on macOS/Linux.

Clone the repository in a writable location, or choose **Code > Download ZIP** on GitHub and extract it into a new folder on the machine that runs Jupyter. Use a fresh folder rather than overwriting a working copy. If Git is unavailable or the filesystem rejects Git's permission changes, use the ZIP route. If JupyterLab has no Terminal, use an approved preconfigured kernel with the dependencies already installed. See [troubleshooting](TROUBLESHOOTING.md) for managed environments.

## 2. Prepare an isolated Python kernel

Run one block from the project folder (the folder that contains `requirements.txt`). Use the approved package index or locally supplied wheels. You do not need to activate the environment or change the server's Python.

**macOS, Linux or a Linux VM:**

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m ipykernel install --user --name concept-remediation --display-name "Concept Remediation"
```

**Windows (PowerShell):**

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m ipykernel install --user --name concept-remediation --display-name "Concept Remediation"
```

If JupyterLab is already open, reload it after registering the kernel. If you are running Jupyter locally and it is not yet open, run `.venv/bin/python -m jupyter lab` (macOS/Linux) or `.\.venv\Scripts\python.exe -m jupyter lab` (Windows) from the project folder. If installation or kernel registration hits a permissions error, stop and check [troubleshooting](TROUBLESHOOTING.md) before reinstalling anything.

## 3. Connect and run Preview

1. Open `Preview_concept_remediation.ipynb` from the project folder and choose **Kernel > Change Kernel > Concept Remediation**. Run the first code cell with the default disconnected setup; it should say **Preview only; no connection made.**
2. In the connection cell, set the approved CDM and vocabulary schemas, CDM version (5.4 or 5.5), and private output folder outside the repository. Use the version from CDM_SOURCE.cdm_version.
3. Run the connection cell and type CONNECT when prompted. Enter the database DNS name, port, database name and read-only credentials. Keep verify-full and use the site-approved CA. For certificate and kernel details, see [troubleshooting](TROUBLESHOOTING.md).
4. Confirm the selected event tables, then run the scan cell. Run **Save the Preview outputs** to create the PDF, XLSX and JSON. Check that the PDF says **PREVIEW - NO CHANGES**. Run the last cell to close the connection.

## Read the result

| What you see | How to interpret it |
| --- | --- |
| Proposed replacements | Candidates for domain review; Preview does not apply them. |
| Blocked or review findings | Check the stated reason and any listed mapping candidates. Rows marked `same group` repeat a finding, not its count. |
| No proposed replacements | Review blocked findings and scan coverage before concluding that no issues were found. |
| Missing, inaccessible or unscanned fields | Coverage is incomplete; these are not zero counts. |

Counts refer to field occurrences, not unique people. Treat the PDF as private, even though it excludes patient and event IDs. Do not commit site outputs, credentials, or saved notebook outputs to Git.

For field coverage, see [CDM scope](CDM_COVERAGE.md). An authorized maintainer follows the separate [operator and DBA guide](SAFETY.md) for changes.
