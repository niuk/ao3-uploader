# AO3 Uploader

Automate uploading chapters from a **NovelCrafter** HTML export to **Archive of Our Own**.

## Setup

1. Create the virtual environment once:
   ```powershell
   python -m venv .venv
   ```
2. Activate it in PowerShell:
   ```powershell
   .\.venv\Scripts\Activate.ps1
   ```
3. Install the requirements:
   ```powershell
   pip install -r requirements.txt
   ```
4. Copy `.env.example` to `.env` and fill in your AO3 credentials:
   ```powershell
   cp .env.example .env
   ```

## Usage

```powershell
# List chapters parsed from your HTML export (no upload)
python upload.py export.html --work-id 12345678 --list-chapters

# Dry-run: fill forms but don't submit
python upload.py export.html --work-id 12345678 --dry-run

# Actually upload all chapters
python upload.py export.html --work-id 12345678

# Resume from chapter 5 (0-indexed, so --start 4)
python upload.py export.html --work-id 12345678 --start 4
```

### Options

| Flag              | Description                                      |
|-------------------|--------------------------------------------------|
| `--work-id`       | **(required)** The numeric AO3 work ID           |
| `--start N`       | Skip the first N chapters (0-based index)        |
| `--dry-run`       | Parse & fill forms, but don't click Post         |
| `--headless`      | Run Chrome without a visible window              |
| `--list-chapters` | Print parsed chapter titles and exit             |

## Notes

- The script expects your HTML to have `<h1>` or `<h2>` tags as chapter delimiters.
- A 3-second delay is added between chapter posts to be polite to AO3's servers.
- The browser is left open after the script finishes (unless `--headless`) so you can inspect results.

If you add or update dependencies in the future, run `pip freeze > requirements.txt` while the environment is active to keep the file in sync.
