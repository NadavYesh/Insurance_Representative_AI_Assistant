"""The company rulebook: data/policies/01–04 written as rules the RuleEngine runs.

Every rule cites its source as "<doc>-<section>": 01 cancellation, 02 refunds,
03 claims, 04 exceptions. 04 overrides the others, so its rows sit above the
rules they change.

"Today" is the date the rep asks; a cancellation request is taken as received
today (01-§1 requires it in writing, see the 01-§1 note).
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta
from decimal import Decimal

from assistant.formatting import show
from assistant.forms import Intent, PolicyStatus, Product, Question, Unknown, is_unknown
from assistant.rules.base import BlockingRule, Case, DecisionTable, NoteRule, Row

CANCELLATION = frozenset({Intent.CANCEL, Intent.REFUND}) # *********************************
CLAIMS = frozenset({Intent.CLAIM}) 

SHIFT_MANAGER = "מנהל משמרת"
COLLECTIONS = "מחלקת גבייה"

CLAIM_PAID = Question(
    "claim_paid_last_12_months",
    "האם שולמה ללקוח תביעה ב-12 החודשים האחרונים? (כן / לא / לא יודע)",
    "02-§3",
)


# --- Helpers -----------------------------------------------------------------


def months_between(start: date, end: date) -> int:
    """Whole months from start to end; 0 if end is before start."""
    months = (end.year - start.year) * 12 + (end.month - start.month) - (end.day < start.day)
    return max(months, 0)


def month_end(d: date) -> date:
    return d.replace(day=calendar.monthrange(d.year, d.month)[1])


def in_cooling_off(c: Case) -> bool:
    # 01-§2: within 14 days of the start. A policy that hasn't started yet counts too.
    return (c.today - c.known_policy.start_date).days <= 14


def bonus_rate(months: int) -> Decimal:
    """Seniority bonus as a percent of the annual premium (02-§2ג).

    The table's brackets share their edges ("1 to 3", "3 to 5"); an edge goes to
    the higher bracket, so exactly 3 years earns 10%.
    """
    if months < 12:
        return Decimal(0)
    if months < 36:
        return Decimal(5)
    if months <= 60:
        return Decimal(10)
    return Decimal(15)


def paid_through(c: Case) -> date:
    """The end of the period the customer has paid for.

    The CSV doesn't have it. Premiums are monthly, so the last payment is taken to
    cover the rest of its month (02-§2א note says so to the rep).
    """
    policy = c.known_policy
    if not is_unknown(policy.paid_through):
        return policy.paid_through
    return month_end(policy.last_payment_date)


def _month_index(d: date) -> int:
    return d.year * 12 + d.month


def first_unpaid_month(c: Case) -> date:
    """The first billing month not paid for: the month after paid_through, but not
    before the policy started."""
    after_paid = paid_through(c) + timedelta(days=1)
    return max(after_paid.replace(day=1), c.known_policy.start_date.replace(day=1))


def unpaid_months(c: Case) -> int:
    """Billing months owed up to and including this one; 0 if none.

    The current month counts in full: the customer is charged for the month the
    cancellation request comes in (01-§1). A policy that hasn't started owes nothing.
    """
    return max(_month_index(c.today) - _month_index(first_unpaid_month(c)) + 1, 0)


def _refund_below_zero(c: Case) -> bool:
    """What the customer owes (fee, debt) is more than the refund it is offset against.

    01-§5 sends a debt larger than the refund to collections; a fee larger than the
    refund goes there too, as the same kind of balance owed. An unknown refund can't
    be compared, so it doesn't escalate.
    """
    balance = _refund_balance(c)
    return not is_unknown(balance) and balance < 0


def _refund_balance(c: Case):
    """02-§2: prorated part − cancellation fee + seniority bonus, less any debt (01-§5).
    Unknown if any part is."""
    return (
        c.value("prorated_premium")
        - c.value("cancellation_fee")
        + c.value("seniority_bonus")
        - c.value("arrears_debt")
    )


# --- Explanations: how each value was worked out, shown to the rep ------------------


def _n(value: object) -> str:
    """A number inside a formula; "?" when unknown (its reason is shown elsewhere)."""
    return "?" if is_unknown(value) else show(value)


def _bracket(months: int) -> str:
    if months < 12:
        return "פחות משנה"
    if months < 36:
        return "שנה עד 3 שנים"
    if months <= 60:
        return "3 עד 5 שנים"
    return "מעל 5 שנים"


def _explain_cooling_off(c: Case, result: bool) -> str:
    start = c.known_policy.start_date
    days = (c.today - start).days
    when = f"{days} ימים מתחילת הפוליסה ({show(start)})" if days >= 0 else f"הפוליסה מתחילה בעוד {-days} ימים ({show(start)})"
    return f"{when}; עד 14 ימים = תקופת התחרטות → {show(result)}"


def _explain_rate(c: Case, result: Decimal) -> str:
    months = c.value("seniority_months")
    return f"ותק {months} חודשים ({_bracket(months)}) → {show(result)}%"


def _explain_health_rate(c: Case, result: Decimal) -> str:
    if c.request.claim_paid_last_12_months:  # Unknown here means no explanation; the reason is shown
        return "שולמה ללקוח תביעה ב-12 החודשים האחרונים → 0%"
    return _explain_rate(c, result) + ", לא שולמה תביעה ב-12 החודשים האחרונים"


def _explain_bonus(c: Case, result: object) -> str:
    rate = c.value("seniority_bonus_rate_percent")
    return f"{_n(rate)}% × {show(c.known_policy.monthly_premium)} ₪ × 12 = {_n(result)} ₪"


def _explain_days_since_payment(c: Case, result: int) -> str:
    arrears = "מעל 60 = פיגור" if result > 60 else "עד 60 = אין פיגור"
    return f"{show(c.today)} − {show(c.known_policy.last_payment_date)} = {result} ימים; {arrears}"


def _explain_debt(c: Case, result: Decimal) -> str:
    months = unpaid_months(c)
    first = first_unpaid_month(c)
    if months == 0:
        return f"שולם עד {show(paid_through(c))}, כולל החודש הנוכחי → 0 ₪"
    span = f"{first:%m/%Y}" if months == 1 else f"{first:%m/%Y}–{c.today:%m/%Y}"
    return (
        f"שולם עד {show(paid_through(c))}; {months} חודשים שלא שולמו ({span}, כולל החודש הנוכחי)"
        f" × {show(c.known_policy.monthly_premium)} ₪ = {show(result)} ₪"
    )


def _explain_refund(c: Case, result: object) -> str:
    parts = (
        f"{_n(c.value('prorated_premium'))} (חלק יחסי) − {_n(c.value('cancellation_fee'))} (דמי ביטול)"
        f" + {_n(c.value('seniority_bonus'))} (מענק ותק) − {_n(c.value('arrears_debt'))} (חוב)"
    )
    balance = _refund_balance(c)
    if is_unknown(balance):
        return f"{parts} = לא ידוע"
    if balance < 0:
        return f"{parts}: הניכויים גבוהים מההחזר (הפרש {show(-balance)} ₪) → אין החזר, 0 ₪"
    return f"{parts} = {show(balance)} ₪"


# --- Blocking rules, most important first -------------------------------------

BLOCKING_RULES = (
    BlockingRule(
        "04-ה",
        "הלקוח הזכיר תלונה לרשות שוק ההון, ביטוח וחיסכון",
        lambda c: c.request.mentions_regulator,
        route_to=SHIFT_MANAGER,
        needs_policy=False,
    ),
    BlockingRule(
        "01-§6",
        "לפוליסה יש תביעה פתוחה. ביטול דורש אישור מנהל משמרת, והנציג אינו מוסמך לאשר, לדחות או להעריך סכומים",
        lambda c: c.known_policy.open_claims > 0,
        route_to=SHIFT_MANAGER,
        response_time="2 ימי עסקים",
        intents=CANCELLATION,
    ),
    BlockingRule(
        "04-ד",
        "פוליסה מוקפאת אינה ניתנת לביטול. על הלקוח לבקש הפשרה דרך מחלקת גבייה, ורק אחר כך להגיש בקשת ביטול",
        lambda c: c.known_policy.status is PolicyStatus.FROZEN,
        intents=CANCELLATION,
    ),
    BlockingRule(
        "סטטוס פוליסה",
        "הפוליסה כבר מבוטלת. אין בנתונים מידע על החזר שבוצע; יש לבדוק מול מחלקת הכספים",
        lambda c: c.known_policy.status is PolicyStatus.CANCELLED,
        intents=CANCELLATION,
    ),
    BlockingRule(
        "01-§4",
        "הנסיעה כבר החלה. פוליסת נסיעות ניתנת לביטול רק עד יום לפני תחילת הנסיעה, ולא יינתן החזר",
        lambda c: c.known_policy.product is Product.TRAVEL and c.today >= c.known_policy.start_date,
        intents=CANCELLATION,
    ),
    # Needs the calculated refund, so the engine checks it after the tables. No amounts
    # are given: the balance rests on estimates, and settling it is collections' job.
    BlockingRule(
        "01-§5",
        "דמי הביטול והחוב (אם יש) גבוהים מההחזר המגיע ללקוח, ולכן אין החזר. הסדר היתרה נעשה במחלקת גבייה",
        _refund_below_zero,
        route_to=COLLECTIONS,
        say="אין החזר. יש לפנות למחלקת גבייה.",
        intents=CANCELLATION,
        needs_values=True,
    ),
)


# --- Decision tables, in dependency order --------------------------------------


def _table(name: str, *rows: Row, intents=CANCELLATION, is_estimate: bool = False) -> DecisionTable:
    return DecisionTable(name, rows, intents, is_estimate)


CANCELLATION_TABLES = (
    _table("cooling_off", Row("01-§2", True, in_cooling_off, explain=_explain_cooling_off)),
    _table(
        "seniority_months",
        Row(
            "02-§2ג",
            True,
            lambda c: months_between(c.known_policy.start_date, c.today),
            explain=lambda c, r: f"מ-{show(c.known_policy.start_date)} עד {show(c.today)} = {r} חודשים מלאים",
        ),
    ),
    _table(
        "effective_date",
        Row(
            "01-§2",
            lambda c: c.value("cooling_off"),
            lambda c: c.today,
            explain=lambda c, r: f"בתקופת התחרטות הביטול מיידי = {show(r)}",
        ),
        Row(
            "04-ב",
            lambda c: c.known_policy.product is Product.HEALTH and c.known_policy.start_date < date(2024, 1, 1),
            lambda c: c.today + timedelta(days=30),
            explain=lambda c, r: (
                f"בריאות שנפתחה לפני 01/01/2024 ({show(c.known_policy.start_date)}): "
                f"{show(c.today)} + 30 ימים = {show(r)}"
            ),
        ),
        Row("01-§1", True, lambda c: month_end(c.today), explain=lambda c, r: f"סוף החודש של {show(c.today)} = {show(r)}"),
    ),
    _table(
        "cancellation_fee",
        Row("01-§2", lambda c: c.value("cooling_off"), Decimal(0), explain="בתקופת התחרטות → 0 ₪"),
        Row("04-א", lambda c: c.known_policy.product is Product.CAR, Decimal(150), explain="פוליסת רכב → 150 ₪ בכל ותק"),
        Row(
            "01-§3",
            lambda c: c.value("seniority_months") >= 12,
            Decimal(0),
            explain=lambda c, r: f"ותק {c.value('seniority_months')} חודשים (12 ומעלה) → 0 ₪",
        ),
        Row("01-§3", True, Decimal(50), explain=lambda c, r: f"ותק {c.value('seniority_months')} חודשים (פחות מ-12) → 50 ₪"),
    ),
    _table(
        "seniority_bonus_rate_percent",
        Row("02-§2ג", lambda c: c.value("seniority_months") < 12, Decimal(0), explain=_explain_rate),
        Row(
            "02-§3",
            lambda c: c.known_policy.product is Product.HEALTH,
            # "I don't know" is Unknown; branching on it leaves this rate (and the bonus) Unknown.
            lambda c: Decimal(0) if c.request.claim_paid_last_12_months else bonus_rate(c.value("seniority_months")),
            asks=(CLAIM_PAID,),
            explain=_explain_health_rate,
        ),
        Row("02-§2ג", True, lambda c: bonus_rate(c.value("seniority_months")), explain=_explain_rate),
    ),
    _table(
        "seniority_bonus",
        Row(
            "02-§2ג",
            True,
            lambda c: c.value("seniority_bonus_rate_percent") / 100 * c.known_policy.monthly_premium * 12,
            explain=_explain_bonus,
        ),
        is_estimate=True,
    ),
    _table(
        "prorated_premium",
        Row(
            "01-§2",
            lambda c: c.value("cooling_off"),
            Unknown("בתקופת ההתחרטות הלקוח זכאי להחזר מלא של כל הפרמיה ששולמה, אך סכום הפרמיה ששולם אינו בנתונים"),
        ),
        Row(
            "02-§2א",
            lambda c: paid_through(c) <= c.value("effective_date"),
            Decimal(0),
            explain=lambda c, r: (
                f"שולם עד {show(paid_through(c))}, לא אחרי מועד הביטול ({show(c.value('effective_date'))}) → 0 ₪"
            ),
        ),
        Row("02-§2א", True, Unknown("הלקוח שילם מראש מעבר למועד הביטול; החלק היחסי ייקבע במחלקת הכספים")),
        is_estimate=True,
    ),
    _table(
        "days_since_last_payment",
        Row("01-§5", True, lambda c: (c.today - c.known_policy.last_payment_date).days, explain=_explain_days_since_payment),
    ),
    _table(
        "arrears_debt",
        Row(
            "01-§5",
            lambda c: c.value("days_since_last_payment") > 60,
            lambda c: unpaid_months(c) * c.known_policy.monthly_premium,
            explain=_explain_debt,
        ),
        Row("01-§5", True, Decimal(0), explain="אין פיגור → 0 ₪"),
        is_estimate=True,
    ),
    _table(
        "refund_estimate",
        # Fees and debt are offset against the refund (01-§3, 01-§5); it never goes below 0.
        # Below 0 escalates to collections (blocking rule 01-§5).
        Row("02-§2", lambda c: _refund_balance(c) < 0, Decimal(0), explain=_explain_refund),
        Row("02-§2", True, _refund_balance, explain=_explain_refund),
        is_estimate=True,
    ),
    _table("refund_transfer_business_days", Row("02-§4", True, 14)),
)


CLAIM_TABLES = (
    _table("open_claims", Row("03-§3", True, lambda c: c.known_policy.open_claims), intents=CLAIMS),
    _table("claim_stage", Row("03-§3", True, lambda c: c.known_policy.claim_stage), intents=CLAIMS),
    _table("acknowledgement_business_days", Row("03-§2", True, 3), intents=CLAIMS),
    _table("assessor_appointment_business_days", Row("03-§2", True, 10), intents=CLAIMS),
    _table("claim_payment_date", Row("03-§2", True, Unknown("הנוהל אינו קובע מועד לתשלום תביעה מאושרת")), intents=CLAIMS),
)

TABLES = CANCELLATION_TABLES + CLAIM_TABLES


# --- Notes --------------------------------------------------------------------


def _row_used(c: Case, table: str, rule_id: str) -> bool:
    return table in c.values and c.values[table].rule_id == rule_id


def _documents(product: Product, text: str) -> NoteRule:
    return NoteRule("03-§4", text, lambda c: c.known_policy.product is product, CLAIMS)


NOTE_RULES = (
    NoteRule(
        "01-§1",
        "ביטול מחייב בקשה בכתב (מייל, טופס באתר או מכתב); בקשה טלפונית אינה מספיקה. יש לשלוח ללקוח קישור לטופס. "
        "המועדים חושבו בהנחה שהבקשה בכתב מתקבלת היום.",
        True,
        frozenset({Intent.CANCEL}),
    ),
    NoteRule(
        "04-ג",
        "ללקוח פוליסות נוספות. ביטול פוליסה זו מבטל את הנחת ריבוי הפוליסות (5%) על הפוליסות הנותרות החל מחודש "
        "החיוב הבא. יש ליידע את הלקוח לפני הביטול.",
        lambda c: any(
            p.policy_id != c.known_policy.policy_id and p.status is not PolicyStatus.CANCELLED
            for p in c.customer_policies
        ),
        CANCELLATION,
    ),
    NoteRule(
        "04-ב",
        "פוליסת בריאות מהדור הקודם: הביטול נכנס לתוקף 30 יום מקבלת הבקשה, והלקוח מחויב על 30 הימים הללו.",
        lambda c: _row_used(c, "effective_date", "04-ב"),
        CANCELLATION,
    ),
    NoteRule(
        "01-§4",
        "פוליסת נסיעות ניתנת לביטול רק עד יום לפני מועד תחילת הנסיעה.",
        lambda c: c.known_policy.product is Product.TRAVEL,
        CANCELLATION,
    ),
    NoteRule(
        "02-§2א",
        "החלק היחסי חושב בהנחה שהפרמיה משולמת חודשית והתשלום האחרון מכסה את החודש שבו שולם.",
        lambda c: _row_used(c, "prorated_premium", "02-§2א") and is_unknown(c.known_policy.paid_through),
        CANCELLATION,
    ),
    NoteRule(
        "01-§5",
        "הלקוח בפיגור תשלומים: החוב מקוזז מכל החזר. אם החוב גדול מההחזר, הלקוח מופנה למחלקת גבייה להסדר.",
        lambda c: c.value("days_since_last_payment") > 60,
        CANCELLATION,
    ),
    NoteRule(
        "01-§5",
        "חוב הפיגורים חושב בהנחה שהפרמיה משולמת חודשית, שהתשלום האחרון מכסה את החודש שבו שולם, "
        "ושהחודש הנוכחי מחויב במלואו. הסכום המדויק נקבע במחלקת גבייה.",
        lambda c: c.value("days_since_last_payment") > 60 and is_unknown(c.known_policy.paid_through),
        CANCELLATION,
    ),
    NoteRule(
        "02-§5",
        "כל סכום הוא הערכה בלבד; הסכום הסופי נקבע ומאושר על ידי מחלקת הכספים. אין להתחייב ללקוח על סכום מדויק.",
        True,
        CANCELLATION,
    ),
    NoteRule(
        "03-§6",
        "אין להעריך סיכויי אישור או לנקוב בסכומים, ואין למסור את המלצת המעריך לפני שההחלטה נשלחה בכתב.",
        True,
        CLAIMS,
    ),
    _documents(Product.CAR, "מסמכים לתביעת רכב: דוח משטרה (אם רלוונטי), הצעת מחיר ממוסך, צילומי הנזק."),
    _documents(Product.HOME, "מסמכים לתביעת דירה: צילומי הנזק, קבלות על רכוש שניזוק, ודוח שמאי אם הנזק מעל 10,000 ₪."),
    _documents(Product.HEALTH, "מסמכים לתביעת בריאות: מסמכים רפואיים, קבלות, הפניית רופא."),
    _documents(Product.TRAVEL, 'מסמכים לתביעת נסיעות: כרטיסי טיסה, אישורים רפואיים מחו"ל, קבלות.'),
)
