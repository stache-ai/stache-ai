"""
Script to create test PDFs for OCR regression testing.
Generates various PDF types for comprehensive test coverage.

Uses reportlab to generate PDFs with embedded text layers for text-based PDFs,
and PIL/Pillow for image-only (scanned) PDFs.
"""

from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
import io
import os


def create_text_based_pdf():
    """Create a text-based PDF with embedded text layer (reportlab)."""
    output_path = Path(__file__).parent / "pdfs" / "01-text-based.pdf"

    c = canvas.Canvas(str(output_path), pagesize=letter)
    width, height = letter

    # Title
    c.setFont("Helvetica-Bold", 18)
    c.drawString(0.5 * inch, height - 0.5 * inch, "Text-Based PDF Test Document")

    # Content with embedded text layer
    c.setFont("Helvetica", 12)
    y = height - 1.2 * inch

    text_lines = [
        "This is a standard text-based PDF document with an embedded text layer.",
        "It contains regular text that can be extracted without OCR.",
        "The content is rendered with proper font encoding.",
        "",
        "Multiple paragraphs help test text processing capabilities.",
        "Each paragraph is positioned with proper spacing and formatting.",
        "",
        "Testing different content: numbers 12345, symbols @#$%^&*().",
        "This document simulates a typical born-digital text page.",
        "",
        "The text layer is embedded in the PDF structure, not as an image overlay.",
        "This is the standard format for documents created digitally.",
        "",
        "Additional content to reach adequate text length for testing.",
        "Lorem ipsum dolor sit amet, consectetur adipiscing elit.",
        "Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua.",
        "Ut enim ad minim veniam, quis nostrud exercitation ullamco.",
        "This approach ensures reliable text extraction.",
    ]

    for line in text_lines:
        c.drawString(0.5 * inch, y, line)
        y -= 0.25 * inch

    # Footer
    c.setFont("Helvetica-Oblique", 10)
    c.drawString(0.5 * inch, 0.5 * inch, "Generated for OCR regression testing")
    c.drawRightString(width - 0.5 * inch, 0.5 * inch, "Page 1")

    c.save()
    print(f"Created: {output_path}")


def create_empty_pdf():
    """Create an empty PDF (just blank page)."""
    output_path = Path(__file__).parent / "pdfs" / "02-empty.pdf"

    c = canvas.Canvas(str(output_path), pagesize=letter)
    c.setFont("Helvetica", 12)
    # Completely empty, just a blank page
    c.save()
    print(f"Created: {output_path}")


def create_single_page_pdf():
    """Create a minimal single-page PDF with embedded text."""
    output_path = Path(__file__).parent / "pdfs" / "03-single-page.pdf"

    c = canvas.Canvas(str(output_path), pagesize=letter)
    width, height = letter

    c.setFont("Helvetica-Bold", 16)
    c.drawString(0.5 * inch, height - 0.5 * inch, "Single Page Document")

    c.setFont("Helvetica", 12)
    y = height - 1.2 * inch

    text_lines = [
        "This is a minimal one-page PDF for testing purposes.",
        "It serves as a basic regression test case.",
        "Contains essential text for validation.",
    ]

    for line in text_lines:
        c.drawString(0.5 * inch, y, line)
        y -= 0.25 * inch

    c.save()
    print(f"Created: {output_path}")


def create_image_only_pdf_from_pil():
    """Helper: Create an image-only PDF using PIL (no text layer)."""
    img = Image.new('RGB', (612, 792), color='#f5f5f5')
    draw = ImageDraw.Draw(img)

    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 20)
        small_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)
    except (OSError, IOError):
        font = ImageFont.load_default()
        small_font = font

    return img, draw, font, small_font


def create_scanned_pdf():
    """
    Create a scanned PDF (image-based, no text layer, requires OCR).
    Uses PIL to ensure no text extraction capability.
    """
    output_path = Path(__file__).parent / "pdfs" / "04-scanned.pdf"

    img, draw, font, small_font = create_image_only_pdf_from_pil()

    text_lines = [
        "This is a simulated scanned PDF.",
        "It contains text rendered as pixels only.",
        "OCR is required to extract text from this.",
        "",
        "The text is not embedded in a text layer,",
        "only as pixels in the image.",
        "",
        "This represents real scanned documents from",
        "old books, fax machines, or photocopies.",
    ]

    y_pos = 80
    for line in text_lines:
        if line:
            draw.text((50, y_pos), line, fill='black', font=font)
        y_pos += 50

    # Add footer as image
    draw.text((50, 700), "Scanned document simulation", fill='gray', font=small_font)

    img.save(str(output_path), "PDF")
    print(f"Created: {output_path}")


def create_multi_page_pdf():
    """Create a multi-page PDF (11 pages) with embedded text layer."""
    output_path = Path(__file__).parent / "pdfs" / "05-large-multipage.pdf"

    c = canvas.Canvas(str(output_path), pagesize=letter)
    width, height = letter

    for page_num in range(1, 12):  # 11 pages
        c.setFont("Helvetica-Bold", 16)
        c.drawString(0.5 * inch, height - 0.5 * inch, f"Document Page {page_num}")

        c.setFont("Helvetica", 12)
        y = height - 1.2 * inch

        text_lines = [
            f"This is page {page_num} of a multi-page document.",
            "It's designed to test performance with larger PDFs.",
            "Each page contains similar content for consistency.",
            "",
            "Lorem ipsum dolor sit amet, consectetur adipiscing elit.",
            "Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua.",
            "Ut enim ad minim veniam, quis nostrud exercitation ullamco.",
            "",
            "Page number helps verify all pages are processed correctly.",
            f"This particular instance is iteration number {page_num}.",
            "Multi-page handling is essential for document processing.",
            "Each page should be processed independently.",
        ]

        for line in text_lines:
            c.drawString(0.5 * inch, y, line)
            y -= 0.25 * inch

        # Footer
        c.setFont("Helvetica-Oblique", 10)
        c.drawString(0.5 * inch, 0.5 * inch, f"Page {page_num} of 11")

        # New page for next iteration (except last)
        if page_num < 11:
            c.showPage()

    c.save()
    print(f"Created: {output_path}")


def create_hybrid_pdf():
    """
    Create a hybrid PDF with multiple pages of different types.
    Page 1: Text content (embedded text layer), Page 2: Simulated scanned content (image).
    """
    output_path = Path(__file__).parent / "pdfs" / "06-hybrid.pdf"

    # Create in-memory buffer for hybrid PDF
    from reportlab.pdfgen import canvas as pdf_canvas
    from reportlab.lib.pagesizes import letter as pdf_letter
    from reportlab.lib.units import inch as pdf_inch
    import io

    # Create temporary PDF with text layer (page 1)
    temp_buffer = io.BytesIO()
    c = pdf_canvas.Canvas(temp_buffer, pagesize=pdf_letter)
    width, height = pdf_letter

    # Page 1: Text-based content
    c.setFont("Helvetica-Bold", 16)
    c.drawString(0.5 * pdf_inch, height - 0.5 * pdf_inch, "Page 1: Text-Based Content")

    c.setFont("Helvetica", 12)
    y = height - 1.2 * pdf_inch

    text_lines_1 = [
        "This page contains regular text content with embedded text layer.",
        "It demonstrates a proper text layer in the document.",
        "",
        "Born-digital content like this doesn't require OCR.",
        "Page 2 will contain scanned/image content that requires OCR.",
        "This hybrid approach is common in document management.",
        "",
        "The text on this page is fully extractable and searchable.",
    ]

    for line in text_lines_1:
        c.drawString(0.5 * pdf_inch, y, line)
        y -= 0.25 * pdf_inch

    c.save()
    temp_buffer.seek(0)

    # Read the generated PDF
    temp_path = Path(__file__).parent / "pdfs" / "_temp_page1.pdf"
    temp_path.write_bytes(temp_buffer.getvalue())

    # Now create page 2 as image-only
    img, draw, font, small_font = create_image_only_pdf_from_pil()

    text_lines_2 = [
        "Page 2: Scanned Content",
        "",
        "This page is rendered as image pixels.",
        "No text layer exists - OCR is required.",
        "",
        "This hybrid approach is common for documents",
        "that mix born-digital and scanned pages.",
    ]

    y_pos = 50
    for line in text_lines_2:
        if line:
            draw.text((50, y_pos), line, fill='black', font=font)
        y_pos += 50

    # Save page 2 as temporary image-based PDF
    temp_img_path = Path(__file__).parent / "pdfs" / "_temp_page2.pdf"
    img.save(str(temp_img_path), "PDF")

    # Merge the two PDFs
    try:
        from PyPDF2 import PdfMerger
        merger = PdfMerger()
        merger.append(str(temp_path))
        merger.append(str(temp_img_path))
        merger.write(str(output_path))
        merger.close()
    except ImportError:
        # If PyPDF2 not available, just use the text-based version
        print("  Warning: PyPDF2 not available, creating single-page version")
        temp_path.rename(output_path)
        temp_img_path.unlink(missing_ok=True)
        print(f"Created: {output_path}")
        return
    finally:
        # Cleanup temp files
        temp_path.unlink(missing_ok=True)
        temp_img_path.unlink(missing_ok=True)

    print(f"Created: {output_path}")


def main():
    """Create all test PDFs."""
    print("Creating test PDF corpus...")
    print()

    create_text_based_pdf()
    create_empty_pdf()
    create_single_page_pdf()
    create_scanned_pdf()
    create_multi_page_pdf()
    create_hybrid_pdf()

    print()
    print("All test PDFs created successfully!")

    # List created files with sizes
    pdf_dir = Path(__file__).parent / "pdfs"
    print("\nCreated files:")
    total_size = 0
    for pdf_file in sorted(pdf_dir.glob("*.pdf")):
        size = pdf_file.stat().st_size
        total_size += size
        print(f"  {pdf_file.name}: {size:,} bytes")

    print(f"\nTotal size: {total_size:,} bytes ({total_size / 1024 / 1024:.2f} MB)")


if __name__ == "__main__":
    main()
