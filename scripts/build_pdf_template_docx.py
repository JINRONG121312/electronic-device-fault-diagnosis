from pathlib import Path

from docx import Document
from docx.enum.section import WD_ORIENT, WD_SECTION
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Mm, Pt


SOURCE_DIR = Path("tmp/pdf_template/source_pages")
OUTPUT = Path("output/word/自查报告模板_版式保真版.docx")


def configure_section(section, landscape: bool) -> tuple:
    if landscape:
        width, height = Mm(297), Mm(210)
        section.orientation = WD_ORIENT.LANDSCAPE
    else:
        width, height = Mm(210), Mm(297)
        section.orientation = WD_ORIENT.PORTRAIT
    section.page_width = width
    section.page_height = height
    section.top_margin = Mm(0)
    section.bottom_margin = Mm(0)
    section.left_margin = Mm(0)
    section.right_margin = Mm(0)
    section.header_distance = Mm(0)
    section.footer_distance = Mm(0)
    return width, height


def prepare_paragraph(paragraph):
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    paragraph.paragraph_format.space_before = Pt(0)
    paragraph.paragraph_format.space_after = Pt(0)
    paragraph.paragraph_format.line_spacing = 1
    paragraph.paragraph_format.keep_together = True
    p_pr = paragraph._p.get_or_add_pPr()
    spacing = p_pr.get_or_add_spacing()
    spacing.set(qn("w:before"), "0")
    spacing.set(qn("w:after"), "0")


def main():
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    images = [SOURCE_DIR / f"page-{i}.png" for i in range(1, 9)]
    missing = [str(p) for p in images if not p.exists()]
    if missing:
        raise FileNotFoundError(f"Missing rendered PDF pages: {missing}")

    doc = Document()
    # Remove the default empty paragraph after reusing it for page 1.
    paragraph = doc.paragraphs[0]

    for index, image_path in enumerate(images):
        landscape = index in (4, 5, 6)
        if index == 0:
            section = doc.sections[0]
        else:
            section = doc.add_section(WD_SECTION.NEW_PAGE)
            paragraph = doc.add_paragraph()
        page_width, page_height = configure_section(section, landscape)
        prepare_paragraph(paragraph)

        # Leave a fraction of a millimetre for the paragraph mark so Word and
        # LibreOffice both keep each source image on exactly one page.
        run = paragraph.add_run()
        run.add_picture(
            str(image_path.resolve()),
            width=page_width,
            height=page_height - Mm(0.4),
        )

    doc.core_properties.title = "自查报告模板（PDF版式保真转换）"
    doc.core_properties.subject = "由扫描型PDF逐页转换，保留原页面方向与内容"
    doc.core_properties.comments = "源PDF无可提取文本，本文件采用逐页图像保真转换。"
    doc.save(OUTPUT)
    print(OUTPUT.resolve())


if __name__ == "__main__":
    main()
