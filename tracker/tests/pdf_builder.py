"""A tiny PDF writer for tests: text in Helvetica (or Helvetica-Bold) at given
positions, so the resume importer can be tested on real PDFs without a PDF
library. Not collected as tests itself."""

from dataclasses import dataclass

PAGE_WIDTH = 612  # US Letter, in points
PAGE_HEIGHT = 792


@dataclass(frozen=True)
class Text:
    x: float
    y: float  # from the top of the page, like pdfplumber's "top"
    text: str
    size: float = 10
    bold: bool = False


def escape(text: str) -> bytes:
    """Text in a PDF string literal, in the WinAnsi encoding the fonts use."""
    raw = text.encode("cp1252")
    return raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def build_pdf(pages: list[list[Text]]) -> bytes:
    """A PDF with one page per list of texts."""
    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"",  # the page tree, filled in once the pages are numbered
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>",
    ]
    page_numbers: list[int] = []
    for texts in pages:
        stream = b"".join(
            b"BT /%s %g Tf %g %g Td (%s) Tj ET\n"
            % (
                b"F2" if item.bold else b"F1",
                item.size,
                item.x,
                PAGE_HEIGHT - item.y - item.size,
                escape(item.text),
            )
            for item in texts
        )
        objects.append(
            b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream)
        )
        content_number = len(objects)
        objects.append(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %d %d] "
            % (PAGE_WIDTH, PAGE_HEIGHT)
            + b"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> "
            + b"/Contents %d 0 R >>" % content_number
        )
        page_numbers.append(len(objects))
    kids = b" ".join(b"%d 0 R" % number for number in page_numbers)
    objects[1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (kids, len(page_numbers))

    output = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(output))
        output += b"%d 0 obj\n%s\nendobj\n" % (number, body)
    xref_at = len(output)
    output += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        output += b"%010d 00000 n \n" % offset
    output += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref_at,
    )
    return bytes(output)


def column(
    x: float, top: float, items: list[tuple[str, float, bool]], gap: float = 16
) -> list[Text]:
    """Texts stacked down the page from `top`: (text, size, bold) each."""
    texts: list[Text] = []
    y = top
    for text, size, bold in items:
        texts.append(Text(x, y, text, size, bold))
        y += gap
    return texts
