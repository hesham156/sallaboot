"""
Bot training material — admin-supplied instructions, FAQs, and reference
files that get injected into the AI system prompt so the bot learns
store-specific knowledge.

Three kinds of entries:

    instruction — short directive ("لا تخصم أكثر من 10%", "كن لطيفاً مع
                  العملاء الجدد"). Always included verbatim in the prompt.
    faq         — Q&A pair. Listed together under "أسئلة شائعة" so the bot
                  recognises common questions and uses the admin's wording.
    file        — uploaded reference file (PDF / TXT). We extract the text
                  at upload time and store it in bot_training.content; the
                  original binary stays in the uploads table.

The full collection is built into a prompt block by build_training_block()
and injected by store_brain.get_knowledge_for_prompt().
"""

from __future__ import annotations
import io
import database as db


# Per-file char cap when stuffing into the prompt. Long PDFs get truncated
# at this boundary so a single 100-page manual can't blow the whole budget.
PER_FILE_CHAR_CAP = 4000

# Total prompt budget reserved for training material across all entries.
TRAINING_CHAR_BUDGET = 8000


# ── File text extraction ────────────────────────────────────────────────────

def extract_text(filename: str, data: bytes) -> tuple[str, str | None]:
    """
    Extract plain text from an uploaded reference file.
    Returns (text, error).  Errors are non-fatal — we still keep the file.

    Supported formats:
      .pdf  → pypdf
      .txt  → utf-8 decode (latin-1 fallback)
      .md   → utf-8 decode
      others → empty text + note so the admin sees we couldn't read it
    """
    name_lower = (filename or "").lower()

    # Plain text
    if name_lower.endswith((".txt", ".md", ".csv", ".log")):
        for enc in ("utf-8", "utf-16", "latin-1"):
            try:
                return data.decode(enc, errors="strict"), None
            except UnicodeDecodeError:
                continue
        return data.decode("utf-8", errors="replace"), None

    # PDF
    if name_lower.endswith(".pdf"):
        try:
            from pypdf import PdfReader
        except ImportError:
            return "", "pypdf غير مثبت — استخدم .txt كحل بديل"
        try:
            reader = PdfReader(io.BytesIO(data))
            pages = []
            for page in reader.pages:
                try:
                    pages.append(page.extract_text() or "")
                except Exception:
                    continue
            text = "\n".join(p.strip() for p in pages if p and p.strip())
            if not text.strip():
                return "", "تعذّر استخراج نص من PDF (ربما صور ممسوحة ضوئياً)"
            return text, None
        except Exception as exc:
            return "", f"خطأ في قراءة PDF: {type(exc).__name__}: {exc}"

    # Unknown — keep file but no text
    return "", f"نوع الملف غير مدعوم لاستخراج النص ({name_lower or 'unknown'})"


# ── Prompt block builder ────────────────────────────────────────────────────

async def build_training_block(store_id: str) -> str:
    """
    Build the training prompt block for a store. Returns "" when there's
    nothing enabled. Groups by kind (instructions → FAQs → files) so the
    AI sees them in a coherent order, smallest-and-highest-signal first.
    """
    entries = await db.list_training(store_id)
    if not entries:
        return ""

    instructions: list[dict] = []
    faqs:         list[dict] = []
    files:        list[dict] = []
    for e in entries:
        if not e.get("enabled", True):
            continue
        kind = e.get("kind")
        if   kind == "instruction": instructions.append(e)
        elif kind == "faq":         faqs.append(e)
        elif kind == "file":        files.append(e)

    if not (instructions or faqs or files):
        return ""

    blocks: list[str] = []
    budget = TRAINING_CHAR_BUDGET

    # 1) Instructions — short and high priority. Include all even if over
    #    budget (admins explicitly wrote these).
    if instructions:
        lines = ["══ توجيهات الإدارة للبوت ══"]
        for e in instructions:
            title   = (e.get("title") or "").strip()
            content = (e.get("content") or "").strip()
            if title and content:
                lines.append(f"• {title}: {content}")
            elif content:
                lines.append(f"• {content}")
            elif title:
                lines.append(f"• {title}")
        section = "\n".join(lines)
        blocks.append(section)
        budget -= len(section) + 2

    # 2) FAQs — Q&A; trim if budget runs out
    if faqs and budget > 200:
        lines = ["══ أسئلة شائعة (أجب بنفس روح هذه الإجابات) ══"]
        used = 0
        for e in faqs:
            q = (e.get("title") or "").strip()
            a = (e.get("content") or "").strip()
            if not (q and a):
                continue
            chunk = f"س: {q}\nج: {a}\n"
            if used + len(chunk) > budget - 200:
                lines.append("… (المزيد من الأسئلة محفوظ)")
                break
            lines.append(chunk)
            used += len(chunk)
        section = "\n".join(lines)
        blocks.append(section)
        budget -= len(section) + 2

    # 3) File reference material — truncate each at PER_FILE_CHAR_CAP and
    #    skip files once budget is exhausted.
    if files and budget > 300:
        lines = ["══ مواد مرجعية (من ملفات الإدارة) ══"]
        for e in files:
            if budget < 200:
                lines.append(f"… (+{len(files)} ملف لم يُحمَّل في الـ prompt — متاح للبحث عند الحاجة)")
                break
            title   = (e.get("title") or e.get("file_name") or "ملف").strip()
            content = (e.get("content") or "").strip()
            if not content:
                continue
            snippet = content[:PER_FILE_CHAR_CAP]
            truncated = len(content) > PER_FILE_CHAR_CAP
            header = f"── {title} ──"
            chunk = header + "\n" + snippet + ("\n… (تم اقتطاع باقي الملف)" if truncated else "")
            if budget - len(chunk) < 0:
                # Fit what we can
                chunk = (header + "\n" + snippet)[:budget - 50] + "\n…"
            lines.append(chunk)
            budget -= len(chunk) + 2
        section = "\n\n".join(lines)
        blocks.append(section)

    return "\n\n".join(blocks)
