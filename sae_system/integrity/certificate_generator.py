"""Completion certificate generator using ReportLab (A4 landscape PDF)."""

import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas as rl_canvas

CERTS_DIR = Path(__file__).resolve().parent.parent / "certificates"

# Gold colour: RGB(212, 175, 55)
_GOLD = colors.Color(212 / 255, 175 / 255, 55 / 255)
_DARK = colors.Color(0.08, 0.08, 0.12)
_WHITE = colors.white
_LIGHT_GRAY = colors.Color(0.85, 0.85, 0.85)


class CertificateGenerator:
    """Generates A4 landscape completion certificates as PDF files."""

    def __init__(self) -> None:
        """Ensure the certificates output directory exists."""
        CERTS_DIR.mkdir(parents=True, exist_ok=True)

    def generate_certificate(
        self,
        student_name: str,
        domain: str,
        completion_date: str,
        modules_completed: int,
        final_score: float,
        proof_hash: str,
        student_id: Optional[str] = None,
    ) -> str:
        """Generate a completion certificate PDF.

        Args:
            student_name: Full name of the learner.
            domain: Subject domain of the completed programme.
            completion_date: ISO date string (YYYY-MM-DD).
            modules_completed: Number of modules completed out of 10.
            final_score: Final aggregate score as a percentage (0–100).
            proof_hash: SHA-256 proof hash for verification.
            student_id: Optional learner ID used in the filename.

        Returns:
            Absolute path to the generated PDF file.
        """
        safe_domain = domain.replace(" ", "_").lower()
        safe_date = completion_date.replace("-", "")
        sid = (student_id or student_name).replace(" ", "_").lower()
        filename = f"{sid}_{safe_domain}_{safe_date}.pdf"
        out_path = CERTS_DIR / filename

        page_w, page_h = landscape(A4)  # 841.89 x 595.28 pt
        c = rl_canvas.Canvas(str(out_path), pagesize=landscape(A4))

        self._draw_background(c, page_w, page_h)
        self._draw_border(c, page_w, page_h)
        self._draw_content(
            c, page_w, page_h,
            student_name=student_name,
            domain=domain,
            completion_date=completion_date,
            modules_completed=modules_completed,
            final_score=final_score,
            proof_hash=proof_hash,
        )

        c.save()
        return str(out_path)

    # ------------------------------------------------------------------
    # Drawing helpers
    # ------------------------------------------------------------------

    def _draw_background(self, c: rl_canvas.Canvas, w: float, h: float) -> None:
        """Fill the page with a dark background."""
        c.setFillColor(_DARK)
        c.rect(0, 0, w, h, fill=True, stroke=False)

    def _draw_border(self, c: rl_canvas.Canvas, w: float, h: float) -> None:
        """Draw a double gold decorative border."""
        margin_outer = 0.8 * cm
        margin_inner = 1.3 * cm

        c.setStrokeColor(_GOLD)
        c.setLineWidth(3)
        c.rect(margin_outer, margin_outer,
               w - 2 * margin_outer, h - 2 * margin_outer,
               fill=False, stroke=True)

        c.setLineWidth(1)
        c.rect(margin_inner, margin_inner,
               w - 2 * margin_inner, h - 2 * margin_inner,
               fill=False, stroke=True)

    def _gold_divider(self, c: rl_canvas.Canvas, y: float, w: float) -> None:
        """Draw a horizontal gold divider line."""
        margin = 3 * cm
        c.setStrokeColor(_GOLD)
        c.setLineWidth(1.2)
        c.line(margin, y, w - margin, y)

    def _draw_content(
        self,
        c: rl_canvas.Canvas,
        w: float,
        h: float,
        student_name: str,
        domain: str,
        completion_date: str,
        modules_completed: int,
        final_score: float,
        proof_hash: str,
    ) -> None:
        """Lay out all text and graphic elements on the certificate."""
        cx = w / 2  # horizontal centre

        # ── Header ───────────────────────────────────────────────────────
        c.setFillColor(_GOLD)
        c.setFont("Times-Bold", 34)
        c.drawCentredString(cx, h - 2.8 * cm, "CERTIFICATE OF COMPLETION")

        c.setFillColor(_LIGHT_GRAY)
        c.setFont("Times-Italic", 17)
        c.drawCentredString(cx, h - 4.0 * cm, "Sovereign Autonomous Education System")

        # ── Top divider ───────────────────────────────────────────────────
        self._gold_divider(c, h - 4.8 * cm, w)

        # ── Body ──────────────────────────────────────────────────────────
        c.setFillColor(_LIGHT_GRAY)
        c.setFont("Times-Roman", 14)
        c.drawCentredString(cx, h - 6.2 * cm, "This certifies that")

        c.setFillColor(_WHITE)
        c.setFont("Times-Bold", 30)
        c.drawCentredString(cx, h - 7.8 * cm, student_name)

        c.setFillColor(_LIGHT_GRAY)
        c.setFont("Times-Roman", 14)
        c.drawCentredString(cx, h - 9.1 * cm, "has successfully completed the")

        c.setFillColor(_GOLD)
        c.setFont("Times-BoldItalic", 22)
        c.drawCentredString(cx, h - 10.4 * cm, domain)

        c.setFillColor(_LIGHT_GRAY)
        c.setFont("Times-Roman", 14)
        c.drawCentredString(cx, h - 11.5 * cm, "Learning Program")

        # ── Details row ───────────────────────────────────────────────────
        details = (
            f"Modules Completed: {modules_completed}/10  |  "
            f"Final Score: {final_score:.1f}%  |  "
            f"Date: {completion_date}"
        )
        c.setFillColor(_LIGHT_GRAY)
        c.setFont("Helvetica", 11)
        c.drawCentredString(cx, h - 12.8 * cm, details)

        # ── Bottom divider ────────────────────────────────────────────────
        self._gold_divider(c, 3.2 * cm, w)

        # ── Footer ────────────────────────────────────────────────────────
        # Bottom-left: verified by + truncated hash
        truncated_hash = proof_hash[:32] if len(proof_hash) > 32 else proof_hash
        c.setFillColor(_LIGHT_GRAY)
        c.setFont("Helvetica", 8)
        c.drawString(1.8 * cm, 2.4 * cm, "Verified by SAE System")
        c.setFont("Courier", 7)
        c.setFillColor(_GOLD)
        c.drawString(1.8 * cm, 1.8 * cm, truncated_hash)

        # Bottom-right: SAE logo text
        c.setFont("Times-Bold", 28)
        c.setFillColor(_GOLD)
        c.drawRightString(w - 1.8 * cm, 1.8 * cm, "SAE")

        # Bottom-centre: full proof hash
        c.setFont("Courier", 6)
        c.setFillColor(_LIGHT_GRAY)
        c.drawCentredString(
            cx, 1.2 * cm,
            f"Cryptographic verification hash: {proof_hash}",
        )
