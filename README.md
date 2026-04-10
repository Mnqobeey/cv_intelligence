# CestaCV Intelligence Studio

A FastAPI application for converting uploaded CVs into structured professional profiles and downloading the final result as a DOCX document.

## Overview

CestaCV Intelligence Studio provides a practical workspace for reviewing CV content, organizing it into a consistent professional profile format, and producing a Word document aligned to the CestaSoft presentation standard.

The application is designed to support a guided review process while still allowing the browser preview state to be downloaded immediately as the final `.docx` profile when needed.

## Recent updates

- Refactored the original `app/main.py` into smaller modules with clearer responsibilities.
- Replaced in-memory document handling with SQLite-backed persistence.
- Added safer upload validation and JSON request handling.
- Added cleanup routines for temporary upload and export artifacts.
- Improved the DOCX export workflow to follow the CestaSoft profile structure more consistently.
- Removed the forced preview-review step before DOCX download so users can download directly from the current profile state.
- Added a structured export contract for identity, summary, skills, qualifications, certifications, career summary, and career history.
- Removed bundled sample CVs, cached exports, validation output, and other non-essential repository files.
- Improved docstrings and comments to support maintainability.

## Output structure

The generated DOCX is organized around:

1. CestaSoft header
2. Candidate details
3. Professional summary
4. Skills
5. Qualifications
6. Certifications
7. Career summary
8. Career history

The in-app HTML preview is intended as a working surface for review. The primary final output is the downloadable `.docx` profile.

## Download flow

1. Upload or paste CV content.
2. Let the profile builder populate or make any edits you want.
3. Open the recruiter-ready preview.
4. Use `Download DOCX Profile` immediately when the preview is available.

Manual review is optional for workflow quality, but it is not required to trigger the DOCX download.

## Project structure

- `app/main.py` - FastAPI application bootstrap
- `app/routes.py` - API routes and request handling
- `app/storage.py` - SQLite persistence and artifact cleanup
- `app/constants.py` - shared configuration and paths
- `app/models.py` - models and helper builders
- `app/utils_text.py` - text extraction and cleanup helpers
- `app/parsers.py` - CV parsing and section detection
- `app/normalizers.py` - profile normalization and state preparation
- `app/source_views.py` - source preview helpers for uploaded files
- `app/renderers.py` - HTML preview rendering
- `app/docx_exporter.py` - DOCX payload mapping and document generation
- `Dockerfile` - container build for Docker-based hosting platforms
- `.dockerignore` - excludes local artifacts from container builds

## Run locally

```bash
pip install -r requirements.txt
./run.sh
```

The application starts at `http://127.0.0.1:8000`.

## Deploy on Koyeb

This repository can be deployed to Koyeb using the included `Dockerfile`. This is the simplest free-hosting path for demo or test environments.

Recommended Koyeb flow:

1. Push the repository to GitHub.
2. In Koyeb, create a new App from GitHub.
3. Select this repository and the branch you want to deploy.
4. Let Koyeb build from the `Dockerfile`.
5. Deploy the service and open the generated URL.

Runtime notes for Koyeb:

- The application uses ephemeral storage by default in hosted environments.
- SQLite data, uploads, and generated DOCX files may be lost on restart or redeploy.
- This setup is suitable for demos and testing, not long-term durable storage.

## Deploy on Render

This repository includes a ready-to-use `render.yaml` blueprint for deploying the application as a Render web service with persistent storage for SQLite data and generated artifacts.

Production start command:

```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

Recommended Render flow:

1. Push the repository to GitHub.
2. In Render, create a new Blueprint.
3. Connect the repository and select this project.
4. Render will detect `render.yaml` and provision the web service and persistent disk.
5. Open the deployed URL after the first successful deploy.

Notes:

- The persistent disk is mounted at `/var/data`.
- SQLite data, uploads, and generated DOCX files are stored on that disk.
- The application does not depend on the Render service name.
- A persistent disk requires a paid Render plan such as `starter`.

## Verification

Basic automated tests are included for the DOCX export flow and the upload-to-download flow, including direct download from the current preview state.

```bash
pytest -q
```

Expected result: tests pass in a correctly configured environment.

## Active export template

The active runtime export template is:

- `assets/Template Cestasoft Profile.docx`

Legacy template assets are not part of the active export path.
