# PASS-59-169 self-updater — cold-eyes loop log

## Cold-eyes loop log

| Loop | Date | Lanes | Q1 | Q2 | Q3 | Q4 | Outcome |
|------|------|-------|----|----|----|----|---------|
| impl | 2026-11-20 | 0 (amendment; no reviewer dispatched) | - | - | - | - | PASS-59-280: step 3 passes `system_ok=True` to `pip_install` where it takes it, so an install already in a protected system Python keeps updating there; new installs on such a system go into RetroDB's own `.venv`. Test in tests/test_pass59_280_installer.py. |
