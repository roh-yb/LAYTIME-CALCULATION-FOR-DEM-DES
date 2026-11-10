"""업로드 파일 → 모델 입력 (텍스트 또는 이미지 data URL)."""
import base64
import io

MAX_PDF_IMAGE_PAGES = 8


def _img_data_url(raw: bytes, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(raw).decode()}"


def file_to_payload(name: str, raw: bytes) -> tuple[str, list[str]]:
    """(text, images). 스캔 PDF/이미지는 images 로 반환."""
    lower = name.lower()
    if lower.endswith((".txt", ".md")):
        for enc in ("utf-8", "cp949", "latin-1"):
            try:
                return raw.decode(enc), []
            except UnicodeDecodeError:
                continue
    if lower.endswith((".csv", ".xlsx", ".xlsm")):
        import pandas as pd

        if lower.endswith(".csv"):
            sheets = {"csv": pd.read_csv(io.BytesIO(raw), header=None, dtype=str)}
        else:
            sheets = pd.read_excel(io.BytesIO(raw), sheet_name=None, header=None, dtype=str)
        parts = [f"### Sheet: {n}\n{df.dropna(how='all').fillna('').to_csv(index=False, header=False)}" for n, df in sheets.items()]
        return "\n\n".join(parts), []
    if lower.endswith(".pdf"):
        return _pdf_payload(raw)
    if lower.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif")):
        ext = lower.rsplit(".", 1)[-1]
        mime = "image/jpeg" if ext in ("jpg", "jpeg") else f"image/{ext}"
        return "", [_img_data_url(raw, mime)]
    raise ValueError(f"지원하지 않는 파일 형식입니다: {name}")


def _pdf_payload(raw: bytes) -> tuple[str, list[str]]:
    import pdfplumber

    texts = []
    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            texts.append(f"--- page {i} ---\n{page.extract_text() or ''}")
    text = "\n".join(texts)
    if len("".join(t.split("---", 2)[-1] for t in texts).strip()) >= 80:
        return text, []

    # 텍스트가 거의 없으면 스캔본으로 보고 이미지로 변환
    import pypdfium2 as pdfium

    images = []
    doc = pdfium.PdfDocument(raw)
    for i in range(min(len(doc), MAX_PDF_IMAGE_PAGES)):
        pil = doc[i].render(scale=2).to_pil()
        buf = io.BytesIO()
        pil.convert("RGB").save(buf, format="JPEG", quality=85)
        images.append(_img_data_url(buf.getvalue(), "image/jpeg"))
    return "", images
