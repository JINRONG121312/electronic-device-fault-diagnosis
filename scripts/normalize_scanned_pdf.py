from pathlib import Path

from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen import canvas

source_dir = Path("tmp/pdf_template/source_pages")
output = Path("tmp/pdf_template/normalized_a4.pdf")

c = canvas.Canvas(str(output))
for page_no in range(1, 9):
    image = source_dir / f"page-{page_no}.png"
    size = landscape(A4) if page_no in (5, 6, 7) else A4
    c.setPageSize(size)
    c.drawImage(str(image), 0, 0, width=size[0], height=size[1], preserveAspectRatio=False)
    c.showPage()
c.save()
print(output.resolve())
