"""
Standalone prompt-caching verification.

Run:  python test_cache.py

Sends two IDENTICAL requests with a cached system prompt. The first writes
the cache; the second should READ it. If caching works you'll see
cache_read_input_tokens > 0 on the second request.

Uses the same ANTHROPIC_API_KEY and model your bot uses. Does NOT touch the DB.
"""
import os
import asyncio
from anthropic import AsyncAnthropic

# Use the same model the bot defaults to for Anthropic
MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")

# A system prompt big enough to clear the 1024-token minimum for Sonnet.
# (Real bot system prompt is ~5-6k tokens, well above the floor.)
SYSTEM = ("أنت مساعد مبيعات لمتجر طباعة. " * 200)  # ~1.2k+ tokens of Arabic


async def main():
    key = os.getenv("ANTHROPIC_API_KEY", "")
    if not key:
        print("❌ ANTHROPIC_API_KEY غير مضبوط في البيئة.")
        print("   شغّل:  $env:ANTHROPIC_API_KEY='sk-...'  ثم أعد التشغيل")
        return

    client = AsyncAnthropic(api_key=key)
    cached_system = [{
        "type":          "text",
        "text":          SYSTEM,
        "cache_control": {"type": "ephemeral"},
    }]

    for i in (1, 2):
        resp = await client.messages.create(
            model=MODEL,
            max_tokens=16,
            system=cached_system,
            messages=[{"role": "user", "content": "قل مرحبا فقط"}],
        )
        u = resp.usage
        write = getattr(u, "cache_creation_input_tokens", 0) or 0
        read  = getattr(u, "cache_read_input_tokens", 0) or 0
        print(f"الطلب {i}: input={u.input_tokens}  cache_write={write}  cache_read={read}")

    print()
    if read > 0:
        print("✅ الكاش شغّال — الطلب الثاني قرأ من الكاش.")
    else:
        print("⚠️ الكاش لم يقرأ. تحقق من: إصدار SDK، الموديل، أو طول الـ prompt (< 1024 توكن).")


if __name__ == "__main__":
    asyncio.run(main())
