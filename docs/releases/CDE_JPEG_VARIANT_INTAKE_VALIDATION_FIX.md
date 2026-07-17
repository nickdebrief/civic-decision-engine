# CDE JPEG Variant Intake Validation Fix

## Purpose

This maintenance fix corrects a false-positive `document_intake_file_type_mismatch`
for valid JPEG files produced by different image editors and redaction tools.

The immediate acceptance case is a redacted HR Walk-In Clinic receipt image saved
as `.jpg` or `.jpeg` after address redaction. The file is preserved exactly as
uploaded and enters the existing governed Document Intake lifecycle.

Follow-up diagnosis found that one remaining Redacted export used a `.jpeg`
filename but contained a JPEG 2000 Part 1 (JP2) container. JP2 is not baseline
or progressive JPEG and remains outside the governed supported-format list.

## Validation Boundary

Server-side byte detection remains authoritative. The filename extension and
browser-supplied content type are treated as supporting information only.

The validator continues to require:

- a supported extension;
- server-detected supported media bytes;
- agreement between extension and detected format;
- exact-byte SHA-256 calculation from the original upload.

JPEG validation now recognises legitimate first-marker variants after the JPEG
Start of Image marker, including JFIF, EXIF, ICC-profile, Adobe, comment,
quantisation-table, and start-of-scan variants. It no longer depends on one
encoder-specific prefix.

## Extension Handling

`.jpg` and `.jpeg` remain equivalent governed JPEG extensions, compared
case-insensitively.

Examples accepted when the bytes are valid JPEG:

- `receipt.jpg`
- `receipt.jpeg`
- `RECEIPT.JPG`

Extension spoofing remains rejected. PNG bytes renamed as `.jpg`, JPEG bytes
renamed as `.png`, arbitrary bytes, and truncated malformed JPEGs are not
accepted.

JPEG 2000 / JP2, TIFF, HEIC/HEIF, and WebP files renamed with `.jpg` or `.jpeg`
also remain rejected. Administrators should export those files explicitly as
JPEG through Preview or another trusted image editor before intake when JPEG is
the intended governed format.

## Diagnostics

Authenticated intake failures now emit safe diagnostic log fields:

- original filename;
- normalised extension;
- declared browser content type;
- expected and detected format where available;
- detected MIME type where available;
- a short leading byte signature in hexadecimal.

The logs do not include uploaded file contents, private storage paths, session
data, credentials, or secrets.

Authenticated upload failures now return a structured diagnostic for known
unsupported signatures. A `.jpeg` upload whose bytes are JP2 reports that the
server detected JPEG 2000 and recommends exporting explicitly as JPEG.

## Preserved Behaviour

This fix does not change:

- original uploaded bytes;
- SHA-256 semantics;
- storage naming;
- lifecycle transitions;
- publication rules;
- provenance;
- Keywords;
- correction behaviour;
- association behaviour;
- authentication;
- public/private visibility boundaries;
- audio validation;
- PDF validation;
- PNG validation.

## Validation

Focused regression coverage confirms acceptance of JFIF, EXIF, ICC-profile,
Adobe, and non-JFIF JPEG marker variants; `.jpg` and `.jpeg` extension
equivalence; uppercase extension handling; browser MIME non-authority; spoofed
extension rejection; malformed JPEG rejection; original-byte preservation; and
unchanged PDF, PNG, M4A, MP3, and WAV validation.
