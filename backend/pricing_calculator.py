"""
Printing price calculator — ported from the React app's calculation logic.

Supports 4 printing types, each with its own pricing model:

    roll     — roll-to-roll printing. Price = area × unit_price × margin × tax,
               with quantity-based discount tiers (m²-based).
    digital  — sheet-based printing. Picks best of normal vs rotated layout
               to minimise sheets. Adds waste sheets, addons, foil, spot UV.
    offset   — formula CEILING(W/A) × CEILING(H/B) × paper_price_per_1000,
               + cutting + folding + punching, scaled by quantity.
    uvdtf    — linear-meter UV DTF rolls with tiered pricing.

Each store keeps its own config in stores.tokens['pricing_config']. The AI
agent's `calculate_advanced_quote` tool resolves the active config for the
current store and passes the customer's inputs through `calculate_quote()`.

The calculation results are intentionally returned as plain dicts so the
agent can format them in Arabic for the customer without re-implementing
the math.
"""

from __future__ import annotations
import math
from typing import Any


# ── Default pricing config used when a store hasn't configured anything yet ─

DEFAULT_PRICING_CONFIG: dict[str, Any] = {
    # General
    "tax_rate":       15.0,   # %
    "profit_margin":  15.0,   # %

    # Minimum order floor (SAR, tax-inclusive). Applied as MAX(final, floor) to
    # every calculator's result. The bot must NOT tell the customer this is a
    # minimum — just show the number. Set to 0 to disable.
    "min_order_floor": 57.50,

    # ── Roll (m² based) ─────────────────────────────────────────────────
    "roll_enabled":     True,
    "roll_unit_price":  35.0,   # ريال per m²
    "default_roll_width": 100,  # cm
    "roll_discounts":   [],     # [{min: m², percent: %}]

    # ── Digital (sheet based) ───────────────────────────────────────────
    "digital_enabled":  True,
    "digital_paper_types": [    # [{name, price, active}]
        {"name": "كوشيه 200",  "price": 1.5, "active": True},
        {"name": "كوشيه 300",  "price": 2.0, "active": True},
        {"name": "ورق عادي 80","price": 0.8, "active": True},
    ],
    "digital_sheet_sizes": [    # [{name, width, height}] in cm
        {"name": "ربع ورق (33×48)",    "width": 33, "height": 48},
        {"name": "شيت طويل (33×100)",  "width": 33, "height": 100},
    ],
    "digital_addons":   [],     # [{name, price (per sheet)}]
    "digital_discounts":[],     # [{min: sheets, percent}]
    # Foil
    "foil_mold_price_per_cm2": 1.15,
    "foil_min_mold_price":     150.0,
    "foil_stamping_unit_price": 0.40,

    # ── Offset ──────────────────────────────────────────────────────────
    "offset_enabled":     True,
    "offset_fixed_width": 5,    # A
    "offset_fixed_height": 9,   # B
    "offset_paper_types": [     # [{name, price (per 1000), active}]
        {"name": "كوشيه 300 (70×100)", "price": 80.0, "active": True},
    ],
    "offset_discounts":   [],   # [{min: qty, percent}]
    "offset_cutting_normal":  120.0,  # per 1000
    "offset_cutting_diecut":  240.0,
    "offset_folding_per_1000": 50.0,
    "offset_punching_per_1000": 50.0,

    # ── UV DTF (linear meter) ───────────────────────────────────────────
    "uvdtf_enabled":     True,
    "uvdtf_unit_price":  150.0,  # ريال per linear meter (default)
    "uvdtf_roll_width":  55,     # cm
    "uvdtf_tiers": [             # [{min: meters, price}]
        {"min": 0,  "price": 150.0},
        {"min": 4,  "price": 120.0},
        {"min": 11, "price": 95.0},
    ],
}


# ── Helpers ──────────────────────────────────────────────────────────────────

def _get_discount_percent(value: float, discounts: list[dict]) -> float:
    """Pick the highest matching discount tier (value ≥ min)."""
    if not discounts:
        return 0.0
    applicable = None
    for rule in sorted(discounts, key=lambda r: r.get("min", 0)):
        if value >= rule.get("min", 0):
            applicable = rule
    return float(applicable.get("percent", 0)) if applicable else 0.0


def _get_tiered_price(value: float, tiers: list[dict], default_price: float) -> float:
    """Pick the highest matching tier price (value ≥ min)."""
    if not tiers:
        return default_price
    applicable = None
    for rule in sorted(tiers, key=lambda r: r.get("min", 0)):
        if value >= rule.get("min", 0):
            applicable = rule
    return float(applicable.get("price", default_price)) if applicable else default_price


def _merge_with_defaults(cfg: dict | None) -> dict:
    """Fill any missing keys with sensible defaults."""
    merged = {**DEFAULT_PRICING_CONFIG}
    if cfg:
        merged.update({k: v for k, v in cfg.items() if v is not None})
    return merged


def _apply_min_floor(cfg: dict, final_price: float) -> tuple[float, bool]:
    """
    Enforce the minimum-order floor (e.g. 57.50 SAR) on a final price.
    Returns (adjusted_price, was_floored). The agent uses `was_floored` to
    decide whether the calculation breakdown is meaningful to show — when
    the price is the floor, the bot should NOT expose internal numbers
    (margin, waste, etc.). It should just present the floor amount.
    """
    floor = float(cfg.get("min_order_floor", 0) or 0)
    if floor > 0 and final_price < floor:
        return round(floor, 2), True
    return round(final_price, 2), False


# ── Roll calculator ──────────────────────────────────────────────────────────

def _calculate_roll(cfg: dict, width: float, height: float, quantity: int,
                     roll_width: float | None = None) -> dict:
    """Roll-to-roll printing. Width/height in cm, quantity = number of stickers."""
    if width <= 0 or height <= 0 or quantity <= 0:
        return {"error": "العرض والارتفاع والكمية لازم تكون أكبر من صفر"}

    rw = float(roll_width or cfg["default_roll_width"])
    unit_price  = float(cfg["roll_unit_price"])
    tax_rate    = float(cfg["tax_rate"]) / 100
    margin_rate = 1 + (float(cfg["profit_margin"]) / 100)

    margin_cm = 0.2
    stickers_per_row = math.floor(rw / (width + margin_cm))
    if stickers_per_row <= 0:
        return {"error": f"الاستيكر أعرض من الرول ({rw} سم). جرب رول أوسع أو قلّل العرض."}

    rows_needed = math.ceil(quantity / stickers_per_row)
    base_length_m = (rows_needed * (height + margin_cm)) / 100
    safety_margins = math.floor(base_length_m / 0.5)
    final_length_m = base_length_m + (safety_margins * 0.05)
    area_m2 = final_length_m * (rw / 100)

    raw_price       = area_m2 * unit_price
    price_with_margin = raw_price * margin_rate
    tax_amount      = price_with_margin * tax_rate
    price_with_tax  = price_with_margin + tax_amount

    discount_percent = _get_discount_percent(area_m2, cfg.get("roll_discounts", []))
    discount_amount  = price_with_tax * (discount_percent / 100)
    final_price      = price_with_tax - discount_amount
    final_price, is_floored = _apply_min_floor(cfg, final_price)

    return {
        "type":              "roll",
        "stickers_per_row":  stickers_per_row,
        "rows_needed":       rows_needed,
        "length_meters":     round(final_length_m, 2),
        "area_m2":           round(area_m2, 3),
        "unit_price":        unit_price,
        "price_before_tax":  round(price_with_margin, 2),
        "tax_amount":        round(tax_amount, 2),
        "discount_percent":  discount_percent,
        "discount_amount":   round(discount_amount, 2),
        "final_price":       final_price,
        "is_floored":        is_floored,
        "currency":          "SAR",
        "details":           f"رول {width}×{height} سم، كمية {quantity}، مساحة {area_m2:.2f} م²",
    }


# ── Digital calculator ──────────────────────────────────────────────────────

def _calculate_digital(cfg: dict, width: float, height: float, quantity: int,
                        paper_type: str | None = None,
                        sheet_size: str | None = None,
                        addons: list[str] | None = None,
                        foil_width: float = 0, foil_height: float = 0,
                        spot_uv: bool = False) -> dict:
    """Sheet-based digital printing. Picks best layout (normal vs rotated)."""
    if width <= 0 or height <= 0 or quantity <= 0:
        return {"error": "العرض والارتفاع والكمية لازم تكون أكبر من صفر"}

    tax_rate = float(cfg["tax_rate"]) / 100

    # Resolve paper type
    active_papers = [p for p in cfg.get("digital_paper_types", []) if p.get("active", True)]
    selected_paper = None
    if paper_type:
        selected_paper = next((p for p in active_papers if p["name"] == paper_type), None)
    if not selected_paper and active_papers:
        selected_paper = active_papers[0]
    if not selected_paper:
        return {"error": "لا توجد أنواع ورق مفعّلة في الإعدادات"}

    sheet_unit_price = float(selected_paper["price"])
    paper_name = selected_paper["name"]

    # Resolve sheet size
    sheet_sizes = cfg.get("digital_sheet_sizes", [])
    selected_size = None
    if sheet_size:
        selected_size = next((s for s in sheet_sizes if s["name"] == sheet_size), None)
    if not selected_size and sheet_sizes:
        selected_size = sheet_sizes[0]
    if not selected_size:
        return {"error": "لا توجد مقاسات ورق مضبوطة في الإعدادات"}

    sheet_w = float(selected_size["width"])
    sheet_h = float(selected_size["height"])

    # Best layout (try rotated too)
    margin = 0.2
    count_normal = (math.floor(sheet_w / (width + margin))) * (math.floor(sheet_h / (height + margin)))
    count_rotated = (math.floor(sheet_w / (height + margin))) * (math.floor(sheet_h / (width + margin)))
    per_sheet = max(count_normal, count_rotated)
    is_rotated = count_rotated > count_normal

    if per_sheet <= 0:
        return {"error": f"مقاس التصميم ({width}×{height}) أكبر من مقاس الورق ({sheet_w}×{sheet_h})"}

    sheets_needed = math.ceil(quantity / per_sheet)

    # Waste sheets
    if sheets_needed <= 100:
        waste_sheets = 5
    elif sheets_needed <= 250:
        waste_sheets = 10
    elif sheets_needed <= 500:
        waste_sheets = 20
    else:
        waste_sheets = 30
    total_sheets = sheets_needed + waste_sheets

    # Addons cost per sheet
    addons_per_sheet = 0.0
    addon_names_used: list[str] = []
    if addons:
        all_addons = cfg.get("digital_addons", [])
        for addon_name in addons:
            addon = next((a for a in all_addons if a["name"] == addon_name), None)
            if addon:
                addons_per_sheet += float(addon.get("price", 0))
                addon_names_used.append(addon["name"])

    base_price       = total_sheets * sheet_unit_price
    addons_cost      = total_sheets * addons_per_sheet

    # Foil
    foil_cost = 0.0
    mold_price = 0.0
    stamping_cost = 0.0
    is_foil = (foil_width > 0 and foil_height > 0)
    if is_foil:
        foil_area = foil_width * foil_height
        mold_price = foil_area * float(cfg.get("foil_mold_price_per_cm2", 1.15))
        min_mold = float(cfg.get("foil_min_mold_price", 150))
        if mold_price < min_mold:
            mold_price = min_mold
        raw_stamping = quantity * float(cfg.get("foil_stamping_unit_price", 0.40))
        stamping_cost = max(200.0, raw_stamping)
        foil_cost = mold_price + stamping_cost

    # Spot UV (tiered flat cost)
    spot_uv_cost = 0.0
    if spot_uv and sheets_needed > 0:
        if sheets_needed <= 30:
            spot_uv_cost = 450.0
        elif sheets_needed <= 50:
            spot_uv_cost = 800.0
        else:
            spot_uv_cost = 1000.0

    price_before_tax = base_price + addons_cost + foil_cost + spot_uv_cost
    tax_amount       = price_before_tax * tax_rate
    price_with_tax   = price_before_tax + tax_amount

    discount_percent = _get_discount_percent(sheets_needed, cfg.get("digital_discounts", []))
    discount_amount  = price_with_tax * (discount_percent / 100)
    final_price      = price_with_tax - discount_amount
    final_price, is_floored = _apply_min_floor(cfg, final_price)

    extras = []
    if is_foil:    extras.append("بصمة")
    if spot_uv:    extras.append("سبوت يو في")
    if addon_names_used: extras.extend(addon_names_used)
    extras_text = " + ".join(extras) if extras else ""

    details = f"ديجيتال {width}×{height} سم على {paper_name}، كمية {quantity}، {sheets_needed} شيت + {waste_sheets} هالك"
    if extras_text:
        details += f" + {extras_text}"
    if is_rotated:
        details += " (تم تدوير التصميم)"

    return {
        "type":              "digital",
        "paper_name":        paper_name,
        "sheet_size":        f"{sheet_w}×{sheet_h}",
        "per_sheet":         per_sheet,
        "sheets_needed":     sheets_needed,
        "waste_sheets":      waste_sheets,
        "total_sheets":      total_sheets,
        "sheet_unit_price":  sheet_unit_price,
        "addons_cost":       round(addons_cost, 2),
        "foil_cost":         round(foil_cost, 2),
        "mold_price":        round(mold_price, 2),
        "stamping_cost":     round(stamping_cost, 2),
        "spot_uv_cost":      round(spot_uv_cost, 2),
        "price_before_tax":  round(price_before_tax, 2),
        "tax_amount":        round(tax_amount, 2),
        "discount_percent":  discount_percent,
        "discount_amount":   round(discount_amount, 2),
        "final_price":       final_price,
        "is_floored":        is_floored,
        "is_rotated":        is_rotated,
        "currency":          "SAR",
        "details":           details,
    }


# ── Offset calculator ───────────────────────────────────────────────────────

def _calculate_offset(cfg: dict, width: float, height: float, quantity: int,
                       paper_type: str | None = None,
                       cutting: str = "normal",  # "normal" or "diecut"
                       folding: bool = False, punching: bool = False) -> dict:
    """Offset printing. Tries both orientations, picks cheaper one."""
    if width <= 0 or height <= 0 or quantity <= 0:
        return {"error": "العرض والارتفاع والكمية لازم تكون أكبر من صفر"}

    tax_rate = float(cfg["tax_rate"]) / 100
    fixed_w = float(cfg.get("offset_fixed_width", 5))
    fixed_h = float(cfg.get("offset_fixed_height", 9))

    # Resolve paper
    active_papers = [p for p in cfg.get("offset_paper_types", []) if p.get("active", True)]
    selected_paper = None
    if paper_type:
        selected_paper = next((p for p in active_papers if p["name"] == paper_type), None)
    if not selected_paper and active_papers:
        selected_paper = active_papers[0]
    if not selected_paper:
        return {"error": "لا توجد أنواع ورق أوفست مفعّلة في الإعدادات"}

    paper_price_per_1000 = float(selected_paper["price"])
    paper_name = selected_paper["name"]

    # Cutting cost
    cutting_cost = float(cfg.get("offset_cutting_diecut" if cutting == "diecut" else "offset_cutting_normal", 120))
    cutting_label = "قص داي كت" if cutting == "diecut" else "قص عادي"

    folding_cost  = float(cfg.get("offset_folding_per_1000", 50))  if folding  else 0.0
    punching_cost = float(cfg.get("offset_punching_per_1000", 50)) if punching else 0.0

    # Try both orientations
    ceil_w1 = math.ceil(width / fixed_w)
    ceil_h1 = math.ceil(height / fixed_h)
    mult1 = ceil_w1 * ceil_h1

    ceil_w2 = math.ceil(height / fixed_w)
    ceil_h2 = math.ceil(width / fixed_h)
    mult2 = ceil_w2 * ceil_h2

    best_mult = min(mult1, mult2)
    is_rotated = mult2 < mult1

    price_per_1000_paper = best_mult * paper_price_per_1000
    total_per_1000 = price_per_1000_paper + cutting_cost + folding_cost + punching_cost
    price_per_unit = total_per_1000 / 1000

    raw_total = price_per_unit * quantity
    tax_amount = raw_total * tax_rate
    price_with_tax = raw_total + tax_amount

    discount_percent = _get_discount_percent(quantity, cfg.get("offset_discounts", []))
    discount_amount  = price_with_tax * (discount_percent / 100)
    final_price      = price_with_tax - discount_amount
    final_price, is_floored = _apply_min_floor(cfg, final_price)

    extras = [cutting_label]
    if folding:  extras.append("ثنية")
    if punching: extras.append("تخريم")
    if is_rotated: extras.append("تم التدوير")
    extras_text = " + ".join(extras)

    return {
        "type":              "offset",
        "paper_name":        paper_name,
        "paper_price_per_1000": paper_price_per_1000,
        "ceil_w":            ceil_w2 if is_rotated else ceil_w1,
        "ceil_h":            ceil_h2 if is_rotated else ceil_h1,
        "multiplier":        best_mult,
        "is_rotated":        is_rotated,
        "cutting_cost":      cutting_cost,
        "folding_cost":      folding_cost,
        "punching_cost":     punching_cost,
        "price_per_1000":    round(total_per_1000, 2),
        "price_per_unit":    round(price_per_unit, 4),
        "raw_total":         round(raw_total, 2),
        "tax_amount":        round(tax_amount, 2),
        "discount_percent":  discount_percent,
        "discount_amount":   round(discount_amount, 2),
        "final_price":       final_price,
        "is_floored":        is_floored,
        "currency":          "SAR",
        "details":           f"أوفست {width}×{height} سم على {paper_name}، كمية {quantity}، {extras_text}",
    }


# ── UV DTF calculator ───────────────────────────────────────────────────────

def _calculate_uvdtf(cfg: dict, width: float, height: float, quantity: int) -> dict:
    """UV DTF linear-meter printing. Picks orientation that uses fewer meters."""
    if width <= 0 or height <= 0 or quantity <= 0:
        return {"error": "العرض والارتفاع والكمية لازم تكون أكبر من صفر"}

    tax_rate = float(cfg["tax_rate"]) / 100
    roll_width = float(cfg.get("uvdtf_roll_width", 55))

    items_normal  = math.floor(roll_width / (height + 0.5))
    items_rotated = math.floor(roll_width / (width  + 0.5))

    if items_normal == 0 and items_rotated == 0:
        return {"error": f"الاستيكر أعرض من المسطح ({roll_width} سم)"}

    rows_normal  = math.ceil(quantity / items_normal)  if items_normal  > 0 else 0
    length_normal  = (rows_normal  * (width  + 0.5)) / 100 if items_normal  > 0 else float("inf")

    rows_rotated = math.ceil(quantity / items_rotated) if items_rotated > 0 else 0
    length_rotated = (rows_rotated * (height + 0.5)) / 100 if items_rotated > 0 else float("inf")

    if length_normal <= length_rotated:
        items_per_row = items_normal
        rows = rows_normal
        meters = round(length_normal, 2)
        is_rotated = False
    else:
        items_per_row = items_rotated
        rows = rows_rotated
        meters = round(length_rotated, 2)
        is_rotated = True

    unit_price = _get_tiered_price(meters, cfg.get("uvdtf_tiers", []), float(cfg["uvdtf_unit_price"]))
    price_before_tax = meters * unit_price
    tax_amount = price_before_tax * tax_rate
    final_price = price_before_tax + tax_amount
    final_price, is_floored = _apply_min_floor(cfg, final_price)

    return {
        "type":              "uvdtf",
        "items_per_row":     items_per_row,
        "total_rows":        rows,
        "meters_consumed":   meters,
        "unit_price":        unit_price,
        "price_before_tax":  round(price_before_tax, 2),
        "tax_amount":        round(tax_amount, 2),
        "final_price":       final_price,
        "is_floored":        is_floored,
        "is_rotated":        is_rotated,
        "currency":          "SAR",
        "details":           f"UV DTF {width}×{height} سم، كمية {quantity}، يستهلك {meters} م"
                             + (" (تم تدوير التصميم)" if is_rotated else ""),
    }


# ── Public API ─────────────────────────────────────────────────────────────

PRINTING_TYPES = ("roll", "digital", "offset", "uvdtf")


def calculate_quote(
    printing_type: str,
    config: dict | None,
    *,
    width: float,
    height: float,
    quantity: int,
    # Roll-specific
    roll_width: float | None = None,
    # Digital-specific
    paper_type: str | None = None,
    sheet_size: str | None = None,
    addons: list[str] | None = None,
    foil_width: float = 0, foil_height: float = 0,
    spot_uv: bool = False,
    # Offset-specific
    cutting: str = "normal",
    folding: bool = False, punching: bool = False,
) -> dict:
    """
    Calculate a quote for the given printing type using the store's pricing
    config (merged with defaults for any missing keys).
    """
    if printing_type not in PRINTING_TYPES:
        return {"error": f"نوع طباعة غير معروف: {printing_type!r}. الأنواع المتاحة: {', '.join(PRINTING_TYPES)}"}

    cfg = _merge_with_defaults(config)

    # Check if this printing type is enabled for this store
    enabled_key = f"{printing_type}_enabled"
    if not cfg.get(enabled_key, True):
        return {"error": f"نوع الطباعة '{printing_type}' معطّل في إعدادات المتجر"}

    try:
        if printing_type == "roll":
            return _calculate_roll(cfg, width, height, int(quantity), roll_width)
        if printing_type == "digital":
            return _calculate_digital(cfg, width, height, int(quantity),
                                       paper_type=paper_type, sheet_size=sheet_size,
                                       addons=addons or [],
                                       foil_width=foil_width, foil_height=foil_height,
                                       spot_uv=spot_uv)
        if printing_type == "offset":
            return _calculate_offset(cfg, width, height, int(quantity),
                                      paper_type=paper_type,
                                      cutting=cutting, folding=folding, punching=punching)
        if printing_type == "uvdtf":
            return _calculate_uvdtf(cfg, width, height, int(quantity))
    except Exception as e:
        return {"error": f"خطأ في الحساب: {type(e).__name__}: {e}"}

    return {"error": "نوع طباعة غير معروف"}


def list_available_options(config: dict | None) -> dict:
    """
    Return the active options the AI agent / customer can pick from:
    enabled printing types, paper types, sheet sizes, addons.
    Used so the agent can offer the right choices before calling
    calculate_quote with a wrong paper/sheet name.
    """
    cfg = _merge_with_defaults(config)
    return {
        "enabled_types": [t for t in PRINTING_TYPES if cfg.get(f"{t}_enabled", True)],
        "digital_papers":    [p["name"] for p in cfg.get("digital_paper_types",   []) if p.get("active", True)],
        "digital_sheets":    [s["name"] for s in cfg.get("digital_sheet_sizes",   [])],
        "digital_addons":    [a["name"] for a in cfg.get("digital_addons",        [])],
        "offset_papers":     [p["name"] for p in cfg.get("offset_paper_types",    []) if p.get("active", True)],
    }
