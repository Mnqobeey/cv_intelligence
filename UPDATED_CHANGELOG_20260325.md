# Targeted Fix Changelog — 2026-03-25

## Fixed
- Pasted-text analysis now strips obvious UI chrome before section parsing.
- Review-complete no longer crashes the app when schema validation fails.
- Qualification extraction now preserves one row per qualification and restores structured rows from pasted-text CVs.
- Qualification end-date/status values such as `Completed` and `Ongoing` now survive through template state and canonical payload generation.
- Certification parsing now ignores experience-role headers and responsibility sentences.
- Career-history parsing strips leaked `Experience` / `Career History` prefixes before canonical mapping.
- Invalid portfolio/linkedin values inferred from stray text are cleared so they do not block review completion.

## Template
- Replaced the active output template with the attached `Template Cestasoft Profile.docx`.
- Removed the old `George Master Template.docx` asset from the packaged project.

## Verified
- Pasted-text flow reaches `review-complete` successfully.
- DOCX download works after review completion.
- CestaSoft template renders successfully from the updated pipeline.
- Route tests for upload and pasted-text flows pass.
