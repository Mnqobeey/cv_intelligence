# CestaCV Intelligence Studio

CestaCV Intelligence Studio helps turn CV content into a clean professional profile and download it as a Word document.

## Overview

The app gives recruiters or profile writers a browser workspace for reviewing CV content, organizing it into a consistent structure, and exporting a polished `.docx` profile.

## What It Produces

The generated DOCX is organized around:

1. Header and candidate details
2. Professional summary
3. Skills
4. Qualifications
5. Certifications
6. Career summary
7. Career history

The browser preview is the review surface. The Word document is the final output.

## Basic Flow

1. Upload or paste CV content.
2. Review and edit the structured profile.
3. Open the preview.
4. Download the DOCX profile.

## Run Locally

```bash
pip install -r requirements.txt
./run.sh
```

The application starts at `http://127.0.0.1:8000`.

## Hosted Start Command

```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

## Verification

```bash
pytest -q
```

## Privacy

Do not commit real CVs, generated exports, uploaded files, or local databases. The repository keeps only placeholder folders and sample-safe test data.
