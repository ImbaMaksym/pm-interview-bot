# report.py
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

def make_pdf_report(pdf_path: str, title: str, lines: list[str], font_path: str = "DejaVuSans.ttf"):
    # Font
    pdfmetrics.registerFont(TTFont("DejaVu", font_path))

    c = canvas.Canvas(pdf_path, pagesize=A4)
    w, h = A4

    c.setFont("DejaVu", 18)
    c.drawString(40, h - 60, title)

    c.setFont("DejaVu", 11)
    y = h - 95
    for line in lines:
        if y < 60:
            c.showPage()
            c.setFont("DejaVu", 11)
            y = h - 60
        c.drawString(40, y, line[:1400])  # простий захист від дуже довгих рядків
        y -= 16

    c.save()
