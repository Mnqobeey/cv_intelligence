# CestaCV Intelligence Studio

CestaCV Intelligence Studio turns CV content into a clean professional profile and downloads it as a Word document. The primary processing path now uses OpenRouter to structure raw CVs into the app's canonical profile JSON.

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
2. OpenRouter structures the CV into the profile schema.
3. Review and edit the generated profile.
4. Download the DOCX profile.

## Run Locally

```bash
pip install -r requirements.txt
./run.sh
```

The application starts at `http://127.0.0.1:8000`.

Set OpenRouter credentials before processing raw CVs:

```bash
export OPENROUTER_API_KEY=your_key_here
export OPENROUTER_MODEL=deepseek/deepseek-chat-v3.1
```

Structured JSON test payloads can be pasted without an API call, but normal CV uploads and pasted CV text require `OPENROUTER_API_KEY`.

## Hosted Start Command

```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

## Free Deployment

The included `render.yaml` targets Render's free web service plan. It uses ephemeral `/tmp` storage, so uploaded files, generated exports, and the local SQLite session cache are temporary. Add `OPENROUTER_API_KEY` in the Render dashboard before deploying.

## Verification

```bash
pytest -q
```

## Privacy

Do not commit real CVs, generated exports, uploaded files, or local databases. The repository keeps only placeholder folders and sample-safe test data.
