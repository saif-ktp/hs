"""Export endpoints: turns an uploaded issues CSV into a branded PDF report.

Owns the /api/export/pdf route. All the layout work lives in report.py —
this module only decides what goes in. Stateless: the same CSV the
dashboard already parsed is simply re-parsed here rather than cached
server-side.
"""

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response

from core import parse_issues_csv
from report import generate_report_pdf

router = APIRouter()


@router.post("/api/export/pdf")
async def export_pdf(file: UploadFile = File(...)):
    raw = await file.read()
    try:
        data = parse_issues_csv(raw)
    except ValueError as e:
        raise HTTPException(400, str(e))

    pdf_bytes = generate_report_pdf(data)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="Listers-HS-Issues-Report.pdf"'},
    )
