from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from assistant.dates import parse_date
from assistant.forms import PolicyStatus, Product, is_unknown
from assistant.sources import CsvPolicySource, PolicyDataError, PolicySource

HEADER = "policy_id,customer_id,customer_name,product,start_date,monthly_premium,status,last_payment_date,open_claims,notes"
REAL_CSV = Path(__file__).resolve().parents[2] / "data" / "policies.csv"


def write_csv(tmp_path: Path, *rows: str, header: str = HEADER, bom: bool = True) -> Path:
    path = tmp_path / "policies.csv"
    text = "\n".join((header, *rows)) + "\n"
    path.write_text(("﻿" if bom else "") + text, encoding="utf-8")
    return path


GOOD = "4401,C-1051,דנה עמר,בריאות,2020-09-09,160,פעילה,2026-10-01,0,"


# --- parse_date --------------------------------------------------------------


def test_parse_date_iso_and_israeli_order():
    assert parse_date("2026-10-25") == date(2026, 10, 25)
    assert parse_date(" 15/03/2023 ") == date(2023, 3, 15)
    # Israeli order, never American: 02/07 is 2 July.
    assert parse_date("02/07/2024") == date(2024, 7, 2)


@pytest.mark.parametrize("text", ["", "2026/10/25", "03/15/2023", "31/02/2024", "yesterday"])
def test_parse_date_rejects_anything_else(text):
    with pytest.raises(ValueError):
        parse_date(text)


# --- Reading rows ------------------------------------------------------------


def test_reads_a_row_into_a_policy(tmp_path):
    source = CsvPolicySource(write_csv(tmp_path, GOOD))
    p = source.get_policy("4401")
    assert p.policy_id == "4401"
    assert p.customer_id == "C-1051"
    assert p.customer_name == "דנה עמר"
    assert p.product is Product.HEALTH
    assert p.status is PolicyStatus.ACTIVE
    assert p.start_date == date(2020, 9, 9)
    assert p.monthly_premium == Decimal("160")
    assert p.last_payment_date == date(2026, 10, 1)
    assert p.open_claims == 0
    assert p.notes == ""


def test_fields_missing_from_csv_stay_unknown(tmp_path):
    p = CsvPolicySource(write_csv(tmp_path, GOOD)).get_policy("4401")
    assert is_unknown(p.paid_through)
    assert is_unknown(p.claim_stage)


def test_works_without_bom(tmp_path):
    assert CsvPolicySource(write_csv(tmp_path, GOOD, bom=False)).get_policy("4401") is not None


def test_mixed_date_formats(tmp_path):
    row = "4421,C-1074,מאיה ברק,רכב,02/07/2024,480,פעילה,01/10/2026,0,"
    p = CsvPolicySource(write_csv(tmp_path, row)).get_policy("4421")
    assert p.start_date == date(2024, 7, 2)
    assert p.last_payment_date == date(2026, 10, 1)


def test_quoted_notes_with_comma_are_kept_whole(tmp_path):
    row = '4455,C-1096,ליאור כהן,דירה,2023-08-10,160,מוקפאת,2026-08-01,0,"לקוח ביקש הקפאה 09/2026, לבדוק מול גבייה"'
    p = CsvPolicySource(write_csv(tmp_path, row)).get_policy("4455")
    assert p.status is PolicyStatus.FROZEN
    assert p.notes == "לקוח ביקש הקפאה 09/2026, לבדוק מול גבייה"


def test_whitespace_is_trimmed(tmp_path):
    row = " 4401 , C-1051 , דנה עמר , בריאות , 2020-09-09 , 160 , פעילה , 2026-10-01 , 0 , הערה "
    source = CsvPolicySource(write_csv(tmp_path, row))
    p = source.get_policy(" 4401 ")
    assert (p.policy_id, p.customer_id, p.product, p.notes) == ("4401", "C-1051", Product.HEALTH, "הערה")


# --- Lookups -----------------------------------------------------------------


def test_unknown_policy_is_none(tmp_path):
    assert CsvPolicySource(write_csv(tmp_path, GOOD)).get_policy("9999") is None


def test_customer_policies_sorted_and_complete(tmp_path):
    source = CsvPolicySource(write_csv(
        tmp_path,
        "4433,C-1072,אורן גבאי,דירה,2022-11-15,180,פעילה,2026-10-01,0,",
        GOOD,
        "4418,C-1072,אורן גבאי,רכב,2022-11-15,520,מבוטלת,2026-10-01,0,",
    ))
    assert [p.policy_id for p in source.get_customer_policies("C-1072")] == ["4418", "4433"]
    assert source.get_customer_policies("C-0000") == []


def test_same_name_different_customers_are_separate(tmp_path):
    source = CsvPolicySource(write_csv(
        tmp_path,
        "4419,C-1067,הילה אברהם,נסיעות,2026-12-22,110,פעילה,2026-10-08,0,",
        "4441,C-1093,הילה אברהם,רכב,2026-09-15,460,פעילה,2026-10-09,0,",
    ))
    assert [p.policy_id for p in source.get_customer_policies("C-1067")] == ["4419"]


# --- Bad data: never guess, never hide ---------------------------------------


@pytest.mark.parametrize(
    "bad_row",
    [
        "4402,C-1052,שירה לוי,אופנוע,2025-07-15,160,פעילה,2026-05-01,0,",  # unknown product
        "4402,C-1052,שירה לוי,בריאות,2025-07-15,160,בתוקף,2026-05-01,0,",  # unknown status
        "4402,C-1052,שירה לוי,בריאות,07/15/2025,160,פעילה,2026-05-01,0,",  # American date
        "4402,C-1052,שירה לוי,בריאות,2025-07-15,₪160,פעילה,2026-05-01,0,",  # not a number
        "4402,C-1052,שירה לוי,בריאות,2025-07-15,-160,פעילה,2026-05-01,0,",  # negative premium
        "4402,C-1052,שירה לוי,בריאות,2025-07-15,NaN,פעילה,2026-05-01,0,",  # not a real amount
        "4402,C-1052,שירה לוי,בריאות,2025-07-15,160,פעילה,2026-05-01,-1,",  # negative claims
        "4402,C-1052,שירה לוי,בריאות,2025-07-15,160,פעילה,2026-05-01,1.5,",  # not a count
        "4402,C-1052,שירה לוי,בריאות,2025-07-15,160,פעילה,,0,",  # empty date
        "4402,C-1052,שירה לוי,בריאות,2025-07-15,160",  # short row
        "4402,C-1052,שירה לוי,בריאות,2025-07-15,160,פעילה,2026-05-01,0,הוקפא 09/2026, לבדוק",  # unquoted comma
    ],
)
def test_bad_row_raises_on_lookup_but_others_still_load(tmp_path, bad_row):
    source = CsvPolicySource(write_csv(tmp_path, GOOD, bad_row))
    assert source.get_policy("4401") is not None
    with pytest.raises(PolicyDataError, match="4402"):
        source.get_policy("4402")
    with pytest.raises(PolicyDataError, match="4402"):
        source.get_customer_policies("C-1052")
    assert len(source.load_errors) == 1


def test_bad_row_blocks_the_whole_customer(tmp_path):
    # A partial list would hide a policy from the multi-policy rules (04-ג).
    source = CsvPolicySource(write_csv(
        tmp_path,
        "4418,C-1072,אורן גבאי,רכב,2022-11-15,520,פעילה,2026-10-01,0,",
        "4433,C-1072,אורן גבאי,דירה,2022-11-15,180,פעילה,not-a-date,0,",
    ))
    assert source.get_policy("4418") is not None
    with pytest.raises(PolicyDataError, match="4433"):
        source.get_customer_policies("C-1072")


def test_duplicate_policy_id_uses_neither_copy(tmp_path):
    source = CsvPolicySource(write_csv(
        tmp_path,
        GOOD,
        "4401,C-1051,דנה עמר,בריאות,2020-09-09,999,פעילה,2026-10-01,0,",
    ))
    with pytest.raises(PolicyDataError, match="appears 2 times"):
        source.get_policy("4401")
    with pytest.raises(PolicyDataError):
        source.get_customer_policies("C-1051")


def test_row_without_policy_id_is_logged(tmp_path):
    source = CsvPolicySource(write_csv(tmp_path, GOOD, ",C-1052,שירה לוי,בריאות,2025-07-15,160,פעילה,2026-05-01,0,"))
    assert source.get_policy("4401") is not None
    assert len(source.load_errors) == 1
    assert "no policy ID" in str(source.load_errors[0])


def test_missing_column_fails_the_whole_file(tmp_path):
    header = HEADER.replace(",open_claims", "")
    with pytest.raises(PolicyDataError, match="open_claims"):
        CsvPolicySource(write_csv(tmp_path, header=header))


# --- Against the real export (skipped when data/ isn't present) --------------

needs_real_data = pytest.mark.skipif(not REAL_CSV.exists(), reason="data/policies.csv not present")


@pytest.fixture(scope="module")
def real() -> PolicySource:
    return CsvPolicySource(REAL_CSV)


@needs_real_data
def test_real_export_loads_cleanly(real):
    assert real.load_errors == []
    assert real.get_policy("4471").customer_id == "C-1088"


@needs_real_data
def test_real_export_every_date_is_a_date(real):
    # The export mixes ISO and DD/MM/YYYY text; the engine must only ever see dates.
    policies = list(real._by_id.values())
    assert len(policies) == 61
    for p in policies:
        assert type(p.start_date) is date, p.policy_id
        assert type(p.last_payment_date) is date, p.policy_id


@needs_real_data
def test_real_export_known_quirks(real):
    assert real.get_policy("4408").start_date == date(2023, 3, 15)
    assert real.get_policy("4449").start_date == date(2025, 1, 20)
    assert real.get_policy("4455").status is PolicyStatus.FROZEN
    assert "03/2026" in real.get_policy("4440").notes
    assert [p.policy_id for p in real.get_customer_policies("C-1072")] == ["4418", "4433"]
