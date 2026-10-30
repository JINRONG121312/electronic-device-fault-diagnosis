from pathlib import Path
import json
import pdfplumber

source = Path(r"C:\Users\djr15\Desktop\自查报告模板.pdf")
out_dir = Path("tmp/pdf_template")
out_dir.mkdir(parents=True, exist_ok=True)

report = {"source": str(source), "pages": []}
all_text = []
with pdfplumber.open(source) as pdf:
    for number, page in enumerate(pdf.pages, 1):
        words = page.extract_words(x_tolerance=2, y_tolerance=2, keep_blank_chars=False)
        text = page.extract_text(x_tolerance=2, y_tolerance=2) or ""
        all_text.append(f"===== PAGE {number} =====\n{text}")
        report["pages"].append({
            "page": number,
            "width": page.width,
            "height": page.height,
            "rotation": page.rotation,
            "word_count": len(words),
            "words": words,
        })

(out_dir / "extracted_text.txt").write_text("\n\n".join(all_text), encoding="utf-8")
(out_dir / "layout.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({
    "page_count": len(report["pages"]),
    "pages": [
        {"page": p["page"], "size": [p["width"], p["height"]], "words": p["word_count"]}
        for p in report["pages"]
    ],
}, ensure_ascii=False, indent=2))
