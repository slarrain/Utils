"""Unit tests for the pure split / settlement logic."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from calculations import compute_settlement  # noqa: E402


def test_worked_example():
    # A: 2 ppl/day x 2 days = 4 person-days, paid 100
    # B: 1 then 3 = 4 person-days, paid 0
    # cost/person-day = 100/8 = 12.5 -> each share 50 -> B pays A 50
    res = compute_settlement(person_days={1: 4, 2: 4}, paid={1: 100, 2: 0})
    assert res["total_cost"] == 100
    assert res["total_person_days"] == 8
    shares = {r["family_id"]: r["share"] for r in res["rows"]}
    assert shares == {1: 50, 2: 50}
    assert res["transactions"] == [{"from": 2, "to": 1, "amount": 50}]


def test_shares_sum_to_total_and_balances_net_to_zero():
    # Amounts/person-days chosen to force rounding.
    person_days = {1: 7, 2: 5, 3: 11, 4: 2}
    paid = {1: 30000, 2: 0, 3: 100000, 4: 12345}
    res = compute_settlement(person_days, paid)

    total_cost = sum(paid.values())
    assert sum(r["share"] for r in res["rows"]) == total_cost
    assert sum(r["balance"] for r in res["rows"]) == 0
    # every share is a non-negative integer
    for r in res["rows"]:
        assert isinstance(r["share"], int) and r["share"] >= 0


def test_transactions_reconcile_every_balance():
    person_days = {1: 3, 2: 4, 3: 5, 4: 6, 5: 1}
    paid = {1: 0, 2: 50000, 3: 0, 4: 90000, 5: 7000}
    res = compute_settlement(person_days, paid)

    # Net effect of suggested payments must exactly cancel each family's balance.
    net = {r["family_id"]: r["balance"] for r in res["rows"]}
    for t in res["transactions"]:
        net[t["from"]] += t["amount"]   # debtor pays out -> balance rises toward 0
        net[t["to"]] -= t["amount"]     # creditor receives -> balance falls toward 0
    assert all(v == 0 for v in net.values())
    # Greedy settle should never need more than n-1 transactions.
    assert len(res["transactions"]) <= len(net) - 1


def test_no_attendance_cannot_settle():
    res = compute_settlement(person_days={1: 0, 2: 0}, paid={1: 5000, 2: 0})
    assert res["can_settle"] is False
    assert res["transactions"] == []
    assert all(r["share"] == 0 for r in res["rows"])


def test_everyone_even_no_payments():
    # Equal consumption, equal payment -> nobody owes anybody.
    res = compute_settlement(person_days={1: 2, 2: 2}, paid={1: 5000, 2: 5000})
    assert res["transactions"] == []
    assert all(r["balance"] == 0 for r in res["rows"])
