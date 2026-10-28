"""Use-case intake, ROI tracker, SOC 2 control mapping and risk register (B-95, specs/B-95.md; W-TOOL-13; C-37, C-45).

Everything here is plain files and pure functions: no network, no model, no tenant, no clock. The four governance pages
are generated from map/controls.json, the AIR table of docs/map/05-governance.md, the committed eval reports and four
small data files, so they cannot drift (``python -m workflows.assurance check``). Synthetic data only; nothing here is a
certification, an attestation or a measured saving.
"""
