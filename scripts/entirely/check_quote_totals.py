#!/usr/bin/env python3
"""Compare a placed quote with the workbook's expected prices. Read-only.

The companion to ``build_test_quote.py``: that script places a workbook example
quote, this one checks it. It reports every line, not a single pass/fail, so a
wrong band, a missed volume tier or a support line below its minimum names
itself.

    python scripts/entirely/check_quote_totals.py --target-org Entirely --expect DEMO-CS-01
    python scripts/entirely/check_quote_totals.py --target-org Entirely --expect DEMO-CS-02 \\
        --exclude-sku DEMO-CS-22 --exclude-sku DEMO-CS-24

A line is compared on its per-period amount — net unit price times quantity —
which is what the workbook's ``lineTotal`` states: a month for a monthly line, a
year for an annual one, the whole charge for a one-time one. The totals follow
the workbook's own arithmetic: first 12 months = monthly x 12 + annual +
one-time. The quote's own line totals are summed as well, which checks the
engine's term arithmetic rather than just its unit prices.

``--exclude-sku`` leaves a line out of the line check and out of both sides of
every total, so the rest of a quote can be verified while one line is known to
be wrong.

Exit status is 0 when everything matches and 1 otherwise.
"""

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_test_quote import EXPECTED, StepError, resolve_ids, sf_query  # noqa: E402

PERIODS = ("Monthly", "Annual", "One-time")


def money(value):
    return Decimal(str(value or 0)).quantize(Decimal("0.01"))


def find_quote(org, opp_id, key, quote_id):
    if quote_id:
        return quote_id
    rows = sf_query(org, "SELECT Id FROM Quote "
                         f"WHERE OpportunityId = '{opp_id}' "
                         f"AND Name = 'Verification {key}' "
                         "ORDER BY CreatedDate DESC LIMIT 1")
    if not rows:
        raise StepError(f"no 'Verification {key}' quote; run build_test_quote.py first")
    return rows[0]["Id"]


def check(org, key, quote_id, excluded, tolerance):
    quote = json.loads(EXPECTED.read_text())["quotes"][key]
    rows = sf_query(org,
                    "SELECT Product2.StockKeepingUnit, Quantity, NetUnitPrice, "
                    "TotalPrice FROM QuoteLineItem "
                    f"WHERE QuoteId = '{quote_id}'")
    actual = {}
    for row in rows:
        actual.setdefault(row["Product2"]["StockKeepingUnit"], []).append(row)

    print(f"{key} on quote {quote_id}  ({quote['shows']})")
    print(f"{'SKU':<12} {'period':<9} {'expected':>11} {'actual':>11} {'delta':>9}")

    failures = 0
    expected_by_period = dict.fromkeys(PERIODS, money(0))
    actual_by_period = dict.fromkeys(PERIODS, money(0))
    quote_total = money(0)
    seen = set()

    for line in quote["lines"]:
        sku, period = line["sku"], line["billingPeriod"]
        seen.add(sku)
        want = money(line["lineTotal"])
        matches = actual.get(sku, [])
        if sku in excluded:
            print(f"{sku:<12} {period:<9} {want:>11} {'excluded':>11}")
            continue
        if len(matches) != 1:
            print(f"{sku:<12} {period:<9} {want:>11} "
                  f"{'missing' if not matches else f'{len(matches)} lines':>11}  FAIL")
            failures += 1
            continue
        row = matches[0]
        got = money(Decimal(str(row["NetUnitPrice"])) * Decimal(str(row["Quantity"])))
        delta = got - want
        ok = abs(delta) <= tolerance
        failures += not ok
        print(f"{sku:<12} {period:<9} {want:>11} {got:>11} {delta:>9}"
              f"{'' if ok else '  FAIL'}")
        expected_by_period[period] += want
        actual_by_period[period] += got
        quote_total += money(row["TotalPrice"])

    # A bundle root and the EUR 0 usage line its model adds are not workbook
    # lines; they cannot move a total, so only a priced stranger fails.
    for sku in sorted(set(actual) - seen):
        priced = any(money(row["TotalPrice"]) for row in actual[sku])
        print(f"{sku:<12} {'':<9} {'':>11} {'unexpected':>11}"
              f"{'  FAIL' if priced else '  (EUR 0)'}")
        failures += priced

    def first12(by_period):
        return by_period["Monthly"] * 12 + by_period["Annual"] + by_period["One-time"]

    print()
    note = f" (excluding {', '.join(sorted(excluded))})" if excluded else ""
    print(f"Totals{note}")
    totals = [(name, expected_by_period[p], actual_by_period[p])
              for name, p in (("monthly", "Monthly"), ("annual", "Annual"),
                              ("one-time", "One-time"))]
    totals.append(("first 12 months", first12(expected_by_period),
                   first12(actual_by_period)))
    for name, want, got in totals:
        ok = abs(got - want) <= tolerance
        failures += not ok
        print(f"  {name:<16} {want:>11} {got:>11} {got - want:>9}"
              f"{'' if ok else '  FAIL'}")

    # A 12-month term bills twelve months, one year and the one-time charges,
    # so the engine's own line totals must add up to the same figure.
    want = first12(expected_by_period)
    ok = int(quote["termMonths"]) != 12 or abs(quote_total - want) <= tolerance
    failures += not ok
    print(f"  {'quote line sum':<16} {want:>11} {quote_total:>11} "
          f"{quote_total - want:>9}{'' if ok else '  FAIL'}")

    if not excluded:
        stated = money(quote["totals"]["first12Months"])
        ok = abs(first12(expected_by_period) - stated) <= tolerance
        failures += not ok
        print(f"  {'workbook states':<16} {stated:>11}"
              f"{'' if ok else '  FAIL (expected lines do not add up)'}")

    print()
    print("PASS" if not failures else f"FAIL: {failures} mismatch(es)")
    return failures


def main():
    parser = argparse.ArgumentParser(
        description="Compare a placed quote with expected_quotes.json. Read-only.")
    parser.add_argument("--target-org", required=True,
                        help="SF CLI alias or username; not a CCI org alias.")
    parser.add_argument("--expect", required=True,
                        help="Quote key in expected_quotes.json, e.g. DEMO-CS-01.")
    parser.add_argument("--quote-id",
                        help="Quote to check. Default: the latest one "
                             "build_test_quote.py placed for --expect.")
    parser.add_argument("--account", default="Kestrel Home & Living GmbH")
    parser.add_argument("--opportunity",
                        default="Kestrel Home & Living GmbH - Censhare Cloud")
    parser.add_argument("--exclude-sku", action="append", default=[],
                        help="Leave a line out of the comparison. Repeatable.")
    parser.add_argument("--tolerance", type=Decimal, default=Decimal("0.01"))
    args = parser.parse_args()

    quotes = json.loads(EXPECTED.read_text())["quotes"]
    if args.expect not in quotes:
        raise SystemExit(f"unknown quote {args.expect!r}; "
                         f"expected one of {', '.join(sorted(quotes))}")
    _account, _currency, opp_id, _pricebook = resolve_ids(
        args.target_org, args.account, args.opportunity)
    quote_id = find_quote(args.target_org, opp_id, args.expect, args.quote_id)
    failures = check(args.target_org, args.expect, quote_id,
                     set(args.exclude_sku), args.tolerance)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    try:
        main()
    except StepError as exc:
        raise SystemExit(f"FAILED: {exc}")
