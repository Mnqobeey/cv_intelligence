# Canonical CestaSoft Output Fix

## What changed
- Replaced active preview/export payload building with one canonical CestaSoft-shaped payload.
- Stopped active preview/export from rebuilding structured sections from builder strings when profile-structured data already exists.
- Removed the active export dependency on the George master template path and locked DOCX generation to `assets/Template Cestasoft Profile.docx`.
- Wired diagnostics to show canonical payload, render source, export source, and pipeline events.
- Updated frontend state sync so annotate, detected-block apply, review-complete, and direct template edits all refresh diagnostics from canonical JSON.

## Root cause fixed
- Preview and export contamination came from re-parsing builder text and legacy intermediates instead of rendering/exporting from one canonical structured payload.

## Integrity protections now in place
- Qualifications are parsed as strict one-row-per-entry records.
- Certifications are isolated from career history.
- Career history is derived from structured profile entries by default and only uses manual text override parsing when the builder content has actually changed.
- Export validation runs only against canonical structured JSON.
