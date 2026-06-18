"""Pure split / settlement logic for Comidas Campo.

No Flask or database imports here on purpose: this module is the heart of the
app and is unit-tested in isolation (see tests/test_calculations.py).

The split is based on *person-days*: a family that brings 3 people for 2 days
consumes 6 person-days. The total food cost is divided across all person-days,
so each family's fair share is proportional to how much it actually consumed.
"""


def compute_settlement(person_days, paid):
    """Compute the fair split and a suggested set of payments.

    Args:
        person_days: dict {family_id: total_person_days_present}
        paid:        dict {family_id: total_pesos_spent}

    Returns a dict with:
        total_cost           total pesos spent by everyone (int)
        total_person_days    total person-days across all families (int)
        cost_per_person_day  total_cost / total_person_days (float; 0 if no days)
        rows                 list of per-family dicts:
                                {family_id, person_days, paid, share, balance}
                             where balance = paid - share
                                (positive => family is owed money,
                                 negative => family owes money)
        transactions         list of {from, to, amount} suggested payments
                             ('from' pays 'to' amount pesos)
        can_settle           False when there are no person-days (can't divide)

    Shares are integer pesos computed with the *largest remainder* method so
    that the shares sum exactly to total_cost and every balance nets to zero.
    """
    family_ids = sorted(set(person_days) | set(paid))
    total_pd = sum(int(person_days.get(f, 0)) for f in family_ids)
    total_cost = sum(int(paid.get(f, 0)) for f in family_ids)

    shares = {f: 0 for f in family_ids}
    if total_pd > 0:
        remainders = {}
        allocated = 0
        for f in family_ids:
            pd = int(person_days.get(f, 0))
            # exact share = total_cost * pd / total_pd, split into quotient + remainder
            quotient, remainder = divmod(total_cost * pd, total_pd)
            shares[f] = quotient
            remainders[f] = remainder
            allocated += quotient
        # distribute the leftover pesos (0 <= leftover < len(families)) to the
        # families with the largest fractional remainder (ties: larger group first)
        leftover = total_cost - allocated
        order = sorted(
            family_ids,
            key=lambda f: (remainders[f], int(person_days.get(f, 0))),
            reverse=True,
        )
        for f in order[:leftover]:
            shares[f] += 1

    balances = {f: int(paid.get(f, 0)) - shares[f] for f in family_ids}

    rows = [
        {
            "family_id": f,
            "person_days": int(person_days.get(f, 0)),
            "paid": int(paid.get(f, 0)),
            "share": shares[f],
            "balance": balances[f],
        }
        for f in family_ids
    ]

    transactions = _settle(balances) if total_pd > 0 else []

    return {
        "total_cost": total_cost,
        "total_person_days": total_pd,
        "cost_per_person_day": (total_cost / total_pd) if total_pd else 0,
        "rows": rows,
        "transactions": transactions,
        "can_settle": total_pd > 0,
    }


def _settle(balances):
    """Greedily minimise the number of payments.

    Repeatedly match the biggest debtor with the biggest creditor and settle
    the smaller of the two amounts. Produces at most (n - 1) transactions.
    """
    creditors = sorted(
        ([f, b] for f, b in balances.items() if b > 0),
        key=lambda x: x[1],
        reverse=True,
    )
    debtors = sorted(
        ([f, -b] for f, b in balances.items() if b < 0),
        key=lambda x: x[1],
        reverse=True,
    )

    transactions = []
    i = j = 0
    while i < len(debtors) and j < len(creditors):
        debtor, owes = debtors[i]
        creditor, due = creditors[j]
        amount = min(owes, due)
        if amount > 0:
            transactions.append({"from": debtor, "to": creditor, "amount": amount})
        debtors[i][1] -= amount
        creditors[j][1] -= amount
        if debtors[i][1] == 0:
            i += 1
        if creditors[j][1] == 0:
            j += 1
    return transactions
