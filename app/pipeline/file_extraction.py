"""
Real document extraction -- pure deterministic parsing, zero AI calls
involved. The extracted text is then fed into the EXACT SAME text
extraction pipeline already built and tested tonight for pasted text. No
new AI pathway, no new evidence-extraction logic -- just more ways to get
real text in front of the classifier that's already proven to work on
messy input.

Honesty note on scope: .xlsx, .pdf (text-based only, not scanned images),
and .eml are supported here. Scanned/image PDFs needing OCR are explicitly
NOT included -- that's a genuinely different technical undertaking (a paid
cloud OCR service or a heavy system-level dependency), not a safe addition
to make unilaterally without a real infrastructure decision first.
"""
import io
import email
import zipfile
from email import policy
from openpyxl import load_workbook
from pypdf import PdfReader


class FileExtractionError(Exception):
    """Raised for any real, expected failure -- corrupted file, wrong
    format, empty content -- so the caller can show a clear, honest
    message instead of a raw stack trace."""
    pass


def extract_text_from_xlsx(file_bytes: bytes, max_chars: int = 8000) -> str:
    """
    Reads every cell of every sheet, row by row, and returns readable text.
    Deliberately simple -- no attempt to infer headers, merge cells, or
    guess structure. The downstream classifier is already proven to
    extract structured evidence from messy real-world text; this just gets
    the spreadsheet's actual content in front of it as plain text.

    max_chars caps the output to keep the eventual reasoning prompt a
    reasonable size -- a genuinely huge spreadsheet gets truncated with an
    honest note, not silently cut off without saying so.
    """
    try:
        workbook = load_workbook(io.BytesIO(file_bytes), data_only=True, read_only=True)
    except Exception as e:
        raise FileExtractionError(
            f"Could not read this file as a valid .xlsx spreadsheet: {type(e).__name__}"
        )

    lines = []
    for sheet in workbook.worksheets:
        lines.append(f"--- Sheet: {sheet.title} ---")
        row_count = 0
        for row in sheet.iter_rows(values_only=True):
            # Skip fully empty rows -- common in real spreadsheets, and
            # including them just adds noise without any real content.
            if all(cell is None for cell in row):
                continue
            row_text = " | ".join(str(cell) if cell is not None else "" for cell in row)
            lines.append(row_text)
            row_count += 1
            if row_count > 500:
                lines.append("[... additional rows truncated ...]")
                break

    if len(lines) <= 1:
        raise FileExtractionError("This spreadsheet appears to be empty.")

    full_text = "\n".join(lines)
    return _truncate(full_text, max_chars)


def extract_text_from_pdf(file_bytes: bytes, max_chars: int = 8000) -> str:
    """
    Extracts real, selectable text from a text-based PDF -- e.g. a
    digitally-created quote or contract, not a scanned photo of one. A
    scanned/image PDF will correctly extract as empty or near-empty text,
    since there's no OCR step here; that failure is surfaced honestly
    (FileExtractionError) rather than silently returning nothing.
    """
    try:
        reader = PdfReader(io.BytesIO(file_bytes))
    except Exception as e:
        raise FileExtractionError(
            f"Could not read this file as a valid PDF: {type(e).__name__}"
        )

    if reader.is_encrypted:
        raise FileExtractionError(
            "This PDF is password-protected. Please remove the password and try again."
        )

    pages_text = []
    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        if text.strip():
            pages_text.append(f"--- Page {i + 1} ---\n{text.strip()}")

    if not pages_text:
        raise FileExtractionError(
            "No selectable text found in this PDF -- it may be a scanned image rather "
            "than a text-based document. Scanned PDFs aren't supported yet; please copy "
            "and paste the relevant details directly instead."
        )

    full_text = "\n\n".join(pages_text)
    return _truncate(full_text, max_chars)


def extract_text_from_eml(file_bytes: bytes, max_chars: int = 8000) -> str:
    """
    Extracts the subject, sender, and body from a real .eml email file
    (the standard format when someone exports/saves an email from most
    mail clients). Uses Python's built-in email library -- no new
    dependency required for this one.
    """
    try:
        msg = email.message_from_bytes(file_bytes, policy=policy.default)
    except Exception as e:
        raise FileExtractionError(f"Could not read this file as a valid email: {type(e).__name__}")

    subject = msg.get("subject", "(no subject)")
    sender = msg.get("from", "(unknown sender)")
    date = msg.get("date", "(unknown date)")

    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                body = part.get_content()
                break
    else:
        body = msg.get_content()

    if not body or not body.strip():
        raise FileExtractionError("This email appears to have no readable text content.")

    full_text = f"From: {sender}\nDate: {date}\nSubject: {subject}\n\n{body.strip()}"
    return _truncate(full_text, max_chars)


def extract_text_from_zip(file_bytes: bytes, max_chars: int = 8000) -> str:
    """
    Extracts every supported file found inside a .zip archive, reusing the
    exact same extractors already built and tested for standalone files --
    no new parsing logic, just one more container layer. This is the
    natural fit for "just attach everything" -- a zip is often exactly how
    someone bundles a case's documents together (an email download, a
    shared folder export).

    Genuinely honest about partial failures: if some files inside extract
    fine and others don't (e.g. a scanned PDF alongside a real quote), both
    outcomes are reported clearly rather than silently dropping or failing
    the whole upload over one bad file.
    """
    try:
        archive = zipfile.ZipFile(io.BytesIO(file_bytes))
    except zipfile.BadZipFile:
        raise FileExtractionError("Could not read this file as a valid .zip archive.")

    extractors_by_ext = {
        ".xlsx": extract_text_from_xlsx,
        ".pdf": extract_text_from_pdf,
        ".eml": extract_text_from_eml,
    }

    sections, skipped = [], []
    for name in archive.namelist():
        # Skip directory entries and common zip artifacts (macOS metadata,
        # hidden system files) -- these aren't real content, and including
        # them would just add noise.
        if name.endswith("/") or "__MACOSX" in name or name.split("/")[-1].startswith("."):
            continue

        lower_name = name.lower()
        try:
            inner_bytes = archive.read(name)
        except Exception:
            skipped.append(f"{name} (could not read from archive)")
            continue

        if lower_name.endswith((".txt", ".csv")):
            try:
                text = inner_bytes.decode("utf-8", errors="replace")
                sections.append(f"--- File: {name} ---\n{text.strip()}")
            except Exception:
                skipped.append(f"{name} (could not decode as text)")
            continue

        matched_ext = next((ext for ext in extractors_by_ext if lower_name.endswith(ext)), None)
        if not matched_ext:
            skipped.append(f"{name} (unsupported format)")
            continue

        try:
            extracted = extractors_by_ext[matched_ext](inner_bytes, max_chars=max_chars)
            sections.append(f"--- File: {name} ---\n{extracted}")
        except FileExtractionError as e:
            skipped.append(f"{name} ({e})")

    if not sections:
        detail = "; ".join(skipped) if skipped else "the archive appears to be empty"
        raise FileExtractionError(f"No readable content found in this zip file ({detail}).")

    full_text = "\n\n".join(sections)
    if skipped:
        full_text += "\n\n[Note: could not read the following from this zip: " + "; ".join(skipped) + "]"

    return _truncate(full_text, max_chars)


def _truncate(text: str, max_chars: int) -> str:
    if len(text) > max_chars:
        return text[:max_chars] + "\n[... content truncated, file was larger than expected ...]"
    return text
