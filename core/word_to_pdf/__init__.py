import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Tuple

logger = logging.getLogger("pdf_read_refresh.core.word_to_pdf")


def convert_word_bytes_to_pdf_bytes(content: bytes, suffix: str = ".docx") -> Tuple[bytes, str]:
    """
    Convert a Word-like document (doc/docx) into PDF bytes using LibreOffice.
    Returns (pdf_bytes, pdf_filename).
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_in = Path(tmpdir) / f"input{suffix}"
        tmp_in.write_bytes(content)

        cmd = [
            "soffice",
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            str(tmpdir),
            str(tmp_in),
        ]
        logger.info("LibreOffice convert start", extra={"cmd": " ".join(cmd), "tmpdir": tmpdir, "suffix": suffix})
        try:
            result = subprocess.run(cmd, capture_output=True, timeout=60)
        except Exception as exc:
            logger.error("LibreOffice spawn failed", extra={"error": str(exc)})
            raise RuntimeError(f"LibreOffice conversion failed: {exc}") from exc

        stderr_preview = result.stderr.decode("utf-8", errors="ignore")[:400] if result.stderr else ""
        stdout_preview = result.stdout.decode("utf-8", errors="ignore")[:200] if result.stdout else ""
        logger.info(
            "LibreOffice convert finished",
            extra={"rc": result.returncode, "stdout": stdout_preview, "stderr": stderr_preview},
        )
        if result.returncode != 0:
            raise RuntimeError(f"LibreOffice conversion failed rc={result.returncode} stderr={stderr_preview}")

        pdf_path = next(iter(Path(tmpdir).glob("*.pdf")), None)
        if not pdf_path or not pdf_path.exists():
            raise RuntimeError("LibreOffice conversion failed: no PDF output produced")

        size = pdf_path.stat().st_size
        logger.info("LibreOffice convert success", extra={"output_pdf": str(pdf_path), "size": size})
        return pdf_path.read_bytes(), pdf_path.name

