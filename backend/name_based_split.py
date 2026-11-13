"""Name-based Split Expenses using Finlumiq's EXISTING Phase 5 tables.

Requires name_based_split_migration.sql to have been applied first.
It does not create a second expenses/groups system.
"""
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_DOWN

CENT = Decimal("0.01")


def _money(value, field="amount", allow_zero=False):
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"Enter a valid {field}.")
    if not number.is_finite() or number < 0 or (number == 0 and not allow_zero):
        raise ValueError(f"{field.capitalize()} must be {'zero or greater' if allow_zero else 'greater than zero'}.")
    rounded = number.quantize(CENT)
    if rounded != number:
        raise ValueError(f"{field.capitalize()} can have at most 2 decimal places.")
    return rounded


def _date(value):
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        raise ValueError("Enter a valid date in YYYY-MM-DD format.")


def _shares(total, participant_ids, method, supplied):
    ids = sorted(int(value) for value in participant_ids)
    if not ids or len(ids) != len(set(ids)):
        raise ValueError("Select at least one different participant.")
    cents = int(total * 100)
    if method == "equal":
        base, remainder = divmod(cents, len(ids))
        return [(pid, Decimal(base + (1 if index < remainder else 0)) / 100) for index, pid in enumerate(ids)]
    if method not in {"custom", "percentage"}:
        raise ValueError("Choose equal, custom or percentage splitting.")
    if not isinstance(supplied, list) or len(supplied) != len(ids):
        raise ValueError("Enter a split value for every selected participant.")
    values = {}
    for item in supplied:
        if not isinstance(item, dict):
            raise ValueError("Invalid participant split.")
        try:
            person_id = int(item.get("person_id"))
            raw = Decimal(str(item.get("amount" if method == "custom" else "percentage")))
        except (InvalidOperation, TypeError, ValueError):
            raise ValueError("Enter valid split values for all participants.")
        if person_id not in ids or person_id in values or not raw.is_finite() or raw < 0:
            raise ValueError("Split values must be non-negative and match selected participants.")
        values[person_id] = raw
    if set(values) != set(ids):
        raise ValueError("Split members do not match the selected participants.")
    if method == "custom":
        amounts = {}
        for person_id, raw in values.items():
            rounded = raw.quantize(CENT)
            if rounded != raw:
                raise ValueError("Custom amounts can have at most 2 decimal places.")
            amounts[person_id] = rounded
        if sum(amounts.values(), Decimal("0.00")) != total:
            raise ValueError("Custom amounts must add up exactly to the bill total.")
        return [(person_id, amounts[person_id]) for person_id in ids]
    if sum(values.values(), Decimal("0")) != Decimal("100"):
        raise ValueError("Percentages must add up to exactly 100%.")
    raw_amounts = {person_id: total * values[person_id] / Decimal("100") for person_id in ids}
    rounded = {person_id: raw.quantize(CENT, rounding=ROUND_DOWN) for person_id, raw in raw_amounts.items()}
    remaining_cents = int((total - sum(rounded.values(), Decimal("0.00"))) * 100)
    order = sorted(ids, key=lambda person_id: (raw_amounts[person_id] - rounded[person_id], -person_id), reverse=True)
    for person_id in order[:remaining_cents]:
        rounded[person_id] += CENT
    return [(person_id, rounded[person_id]) for person_id in ids]


def _json_date(value):
    return value.isoformat() if value is not None and hasattr(value, "isoformat") else value


def register_name_based_split_routes(app, get_db, login_required):
    from flask import jsonify, request, session

    def group_for_owner(cur, group_id, user_id, lock=False):
        sql = "SELECT id,name,description,created_at FROM expense_groups WHERE id=%s AND created_by=%s"
        if lock:
            sql += " FOR UPDATE"
        cur.execute(sql, (group_id, user_id))
        return cur.fetchone()

    def people_for_group(cur, group_id):
        cur.execute(
            "SELECT id AS person_id,group_id,user_id,member_name AS name,role, "
            "(role='owner') AS is_owner,joined_at FROM expense_group_members "
            "WHERE group_id=%s ORDER BY (role='owner') DESC,member_name,id",
            (group_id,),
        )
        rows = cur.fetchall()
        for row in rows:
            row["is_owner"] = bool(row["is_owner"])
            row["joined_at"] = _json_date(row.get("joined_at"))
        return rows

    def balance_data(cur, group_id):
        people = people_for_group(cur, group_id)
        balances = {
            int(person["person_id"]): {
                "person_id": int(person["person_id"]),
                "name": person["name"],
                "role": person["role"],
                "is_owner": person["is_owner"],
                "balance": Decimal("0.00"),
            }
            for person in people
        }
        cur.execute(
            "SELECT paid_by_member_id,total_amount FROM shared_expenses "
            "WHERE group_id=%s AND paid_by_member_id IS NOT NULL",
            (group_id,),
        )
        for row in cur.fetchall():
            person_id = int(row["paid_by_member_id"])
            if person_id in balances:
                balances[person_id]["balance"] += Decimal(str(row["total_amount"]))
        cur.execute(
            "SELECT s.member_id,s.amount FROM expense_splits s "
            "JOIN shared_expenses e ON e.id=s.expense_id "
            "WHERE e.group_id=%s AND s.member_id IS NOT NULL",
            (group_id,),
        )
        for row in cur.fetchall():
            person_id = int(row["member_id"])
            if person_id in balances:
                balances[person_id]["balance"] -= Decimal(str(row["amount"]))
        cur.execute(
            "SELECT from_member_id,to_member_id,amount FROM shared_settlements "
            "WHERE group_id=%s AND from_member_id IS NOT NULL AND to_member_id IS NOT NULL",
            (group_id,),
        )
        for row in cur.fetchall():
            from_id, to_id = int(row["from_member_id"]), int(row["to_member_id"])
            amount = Decimal(str(row["amount"]))
            if from_id in balances:
                balances[from_id]["balance"] += amount
            if to_id in balances:
                balances[to_id]["balance"] -= amount
        for item in balances.values():
            item["balance"] = item["balance"].quantize(CENT)
        debtors = [[pid, -item["balance"]] for pid, item in balances.items() if item["balance"] < 0]
        creditors = [[pid, item["balance"]] for pid, item in balances.items() if item["balance"] > 0]
        suggestions, i, j = [], 0, 0
        while i < len(debtors) and j < len(creditors):
            amount = min(debtors[i][1], creditors[j][1]).quantize(CENT)
            if amount > 0:
                suggestions.append({
                    "from_person_id": debtors[i][0],
                    "from_name": balances[debtors[i][0]]["name"],
                    "to_person_id": creditors[j][0],
                    "to_name": balances[creditors[j][0]]["name"],
                    "amount": float(amount),
                })
            debtors[i][1] -= amount
            creditors[j][1] -= amount
            if debtors[i][1] == 0:
                i += 1
            if creditors[j][1] == 0:
                j += 1
        return list(balances.values()), suggestions

    def group_not_found():
        return jsonify({"error": "Group not found or you do not own this group."}), 404

    def safe_close(cur, db):
        try:
            if cur:
                cur.close()
        finally:
            if db:
                db.close()

    @app.route("/api/split-groups", methods=["GET", "POST"])
    @login_required
    def split_groups():
        uid = int(session["user_id"])
        db = get_db()
        cur = None
        try:
            cur = db.cursor(dictionary=True)
            if request.method == "POST":
                data = request.get_json(silent=True) or {}
                name = " ".join(str(data.get("name", "")).split())
                description = str(data.get("description", "")).strip()[:1000] or None
                if not name or len(name) > 100:
                    return jsonify({"error": "Enter a group name (maximum 100 characters)."}), 400
                cur.execute("SELECT name FROM users WHERE id=%s", (uid,))
                owner = cur.fetchone()
                if not owner:
                    return jsonify({"error": "Your account was not found. Please sign in again."}), 401
                cur.execute(
                    "INSERT INTO expense_groups (name,description,created_by) VALUES (%s,%s,%s)",
                    (name, description, uid),
                )
                group_id = cur.lastrowid
                owner_name = " ".join(str(owner.get("name") or "Student").split())[:100]
                cur.execute(
                    "INSERT INTO expense_group_members (group_id,user_id,member_name,role) VALUES (%s,%s,%s,'owner')",
                    (group_id, uid, owner_name),
                )
                db.commit()
                return jsonify({"id": group_id, "name": name, "description": description, "member_count": 1, "expense_count": 0}), 201
            cur.execute(
                "SELECT g.id,g.name,g.description,g.created_at, "
                "(SELECT COUNT(*) FROM expense_group_members m WHERE m.group_id=g.id) AS member_count, "
                "(SELECT COUNT(*) FROM shared_expenses e WHERE e.group_id=g.id) AS expense_count "
                "FROM expense_groups g WHERE g.created_by=%s ORDER BY g.created_at DESC,g.id DESC",
                (uid,),
            )
            rows = cur.fetchall()
            for row in rows:
                row["created_at"] = _json_date(row.get("created_at"))
            return jsonify(rows)
        except Exception:
            db.rollback()
            app.logger.exception("Name-based split group request failed")
            return jsonify({"error": "Could not process groups. Check backend logs."}), 500
        finally:
            safe_close(cur, db)

    @app.route("/api/split-groups/<int:group_id>", methods=["GET"])
    @login_required
    def split_group_detail(group_id):
        uid = int(session["user_id"])
        db = get_db(); cur = None
        try:
            cur = db.cursor(dictionary=True)
            group = group_for_owner(cur, group_id, uid)
            if not group:
                return group_not_found()
            group["created_at"] = _json_date(group.get("created_at"))
            group["my_role"] = "owner"
            group["members"] = people_for_group(cur, group_id)
            return jsonify(group)
        except Exception:
            app.logger.exception("Could not load split group")
            return jsonify({"error": "Could not load this group."}), 500
        finally:
            safe_close(cur, db)

    @app.route("/api/split-groups/<int:group_id>/members", methods=["POST"])
    @login_required
    def split_group_members(group_id):
        uid = int(session["user_id"])
        db = get_db(); cur = None
        try:
            cur = db.cursor(dictionary=True)
            if not group_for_owner(cur, group_id, uid):
                return group_not_found()
            data = request.get_json(silent=True) or {}
            name = " ".join(str(data.get("name", "")).split())
            if not name or len(name) > 100:
                return jsonify({"error": "Enter a member name (maximum 100 characters)."}), 400
            cur.execute(
                "SELECT id FROM expense_group_members WHERE group_id=%s AND LOWER(member_name)=LOWER(%s)",
                (group_id, name),
            )
            if cur.fetchone():
                return jsonify({"error": "A member with this name is already in the group."}), 409
            cur.execute(
                "INSERT INTO expense_group_members (group_id,user_id,member_name,role) VALUES (%s,NULL,%s,'member')",
                (group_id, name),
            )
            person_id = cur.lastrowid
            db.commit()
            return jsonify({"person_id": person_id, "name": name}), 201
        except Exception:
            db.rollback()
            app.logger.exception("Could not add name-only group member")
            return jsonify({"error": "Could not add this member. Check backend logs."}), 500
        finally:
            safe_close(cur, db)

    @app.route("/api/split-groups/<int:group_id>/members/<int:person_id>", methods=["DELETE"])
    @login_required
    def delete_split_group_member(group_id, person_id):
        uid = int(session["user_id"])
        db = get_db(); cur = None
        try:
            cur = db.cursor(dictionary=True)
            if not group_for_owner(cur, group_id, uid, lock=True):
                return group_not_found()
            cur.execute("SELECT role FROM expense_group_members WHERE id=%s AND group_id=%s FOR UPDATE", (person_id, group_id))
            person = cur.fetchone()
            if not person:
                return jsonify({"error": "Member not found."}), 404
            if person["role"] == "owner":
                return jsonify({"error": "The group owner cannot be removed."}), 400
            cur.execute(
                "SELECT (SELECT COUNT(*) FROM expense_splits WHERE member_id=%s) + "
                "(SELECT COUNT(*) FROM shared_expenses WHERE paid_by_member_id=%s) + "
                "(SELECT COUNT(*) FROM shared_settlements WHERE from_member_id=%s OR to_member_id=%s) AS used_count",
                (person_id, person_id, person_id, person_id),
            )
            if int(cur.fetchone()["used_count"]) > 0:
                return jsonify({"error": "This member is part of financial history. Keep the member so old calculations remain correct."}), 409
            cur.execute("DELETE FROM expense_group_members WHERE id=%s AND group_id=%s", (person_id, group_id))
            db.commit()
            return jsonify({"message": "Member removed."})
        except Exception:
            db.rollback(); app.logger.exception("Could not remove group member")
            return jsonify({"error": "Could not remove this member."}), 500
        finally:
            safe_close(cur, db)

    @app.route("/api/split-groups/<int:group_id>/expenses", methods=["GET", "POST"])
    @login_required
    def split_group_expenses(group_id):
        uid = int(session["user_id"])
        db = get_db(); cur = None
        try:
            cur = db.cursor(dictionary=True)
            if not group_for_owner(cur, group_id, uid):
                return group_not_found()
            if request.method == "POST":
                data = request.get_json(silent=True) or {}
                title = " ".join(str(data.get("title", "")).split())
                category = str(data.get("category", "Other")).strip()[:80] or "Other"
                description = str(data.get("description", "")).strip()[:1000] or None
                if not title or len(title) > 150:
                    return jsonify({"error": "Enter an expense title (maximum 150 characters)."}), 400
                try:
                    total = _money(data.get("total_amount"), "total amount")
                    expense_date = _date(data.get("expense_date"))
                    payer_id = int(data.get("paid_by_person_id"))
                    participant_ids = [int(x) for x in data.get("participant_person_ids", [])]
                    method = str(data.get("split_method", "equal")).lower()
                    splits = _shares(total, participant_ids, method, data.get("splits", []))
                except (ValueError, TypeError) as exc:
                    return jsonify({"error": str(exc)}), 400
                people = people_for_group(cur, group_id)
                people_by_id = {int(p["person_id"]): p for p in people}
                if payer_id not in people_by_id:
                    return jsonify({"error": "Choose who paid from this group."}), 400
                if not set(participant_ids).issubset(people_by_id):
                    return jsonify({"error": "Every participant must belong to this group."}), 400
                if sum((amount for _, amount in splits), Decimal("0.00")) != total:
                    return jsonify({"error": "Participant shares do not equal the bill total."}), 400
                payer = people_by_id[payer_id]
                try:
                    cur.execute(
                        "INSERT INTO shared_expenses "
                        "(group_id,title,category,total_amount,expense_date,description,paid_by_user_id,paid_by_member_id,created_by_user_id) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (group_id, title, category, total, expense_date, description, payer.get("user_id"), payer_id, uid),
                    )
                    expense_id = cur.lastrowid
                    cur.executemany(
                        "INSERT INTO expense_splits (expense_id,user_id,member_id,amount) VALUES (%s,%s,%s,%s)",
                        [(expense_id, people_by_id[pid].get("user_id"), pid, amount) for pid, amount in splits],
                    )
                    db.commit()
                    return jsonify({"id": expense_id, "total_amount": float(total), "paid_by_person_id": payer_id,
                                    "splits": [{"person_id": pid, "amount": float(amount)} for pid, amount in splits]}), 201
                except Exception:
                    db.rollback(); raise
            cur.execute(
                "SELECT e.id,e.title,e.category,e.total_amount,e.expense_date,e.description, "
                "e.paid_by_member_id,p.member_name AS paid_by_name,e.created_at "
                "FROM shared_expenses e JOIN expense_group_members p ON p.id=e.paid_by_member_id "
                "WHERE e.group_id=%s ORDER BY e.expense_date DESC,e.id DESC",
                (group_id,),
            )
            expenses = cur.fetchall()
            for item in expenses:
                item["total_amount"] = float(item["total_amount"])
                item["expense_date"] = _json_date(item["expense_date"])
                item["created_at"] = _json_date(item["created_at"])
                cur.execute(
                    "SELECT s.member_id AS person_id,m.member_name AS name,s.amount "
                    "FROM expense_splits s JOIN expense_group_members m ON m.id=s.member_id "
                    "WHERE s.expense_id=%s ORDER BY m.member_name,m.id",
                    (item["id"],),
                )
                item["splits"] = [{"person_id": r["person_id"], "name": r["name"], "amount": float(r["amount"])} for r in cur.fetchall()]
            return jsonify(expenses)
        except Exception:
            db.rollback(); app.logger.exception("Shared expense request failed")
            return jsonify({"error": "Could not process shared expenses. Check backend logs."}), 500
        finally:
            safe_close(cur, db)

    @app.route("/api/split-groups/<int:group_id>/balances", methods=["GET"])
    @login_required
    def split_group_balances(group_id):
        uid = int(session["user_id"]); db = get_db(); cur = None
        try:
            cur = db.cursor(dictionary=True)
            if not group_for_owner(cur, group_id, uid):
                return group_not_found()
            balances, suggestions = balance_data(cur, group_id)
            for row in balances:
                row["balance"] = float(row["balance"])
            return jsonify({"balances": balances, "suggested_settlements": suggestions})
        except Exception:
            app.logger.exception("Could not calculate group balances")
            return jsonify({"error": "Could not calculate group balances."}), 500
        finally:
            safe_close(cur, db)

    @app.route("/api/split-groups/<int:group_id>/settlements", methods=["GET", "POST"])
    @login_required
    def split_group_settlements(group_id):
        uid = int(session["user_id"]); db = get_db(); cur = None
        try:
            cur = db.cursor(dictionary=True)
            if not group_for_owner(cur, group_id, uid):
                return group_not_found()
            if request.method == "POST":
                data = request.get_json(silent=True) or {}
                try:
                    from_id = int(data.get("from_person_id")); to_id = int(data.get("to_person_id"))
                    amount = _money(data.get("amount")); payment_date = _date(data.get("payment_date") or date.today().isoformat())
                except (ValueError, TypeError) as exc:
                    return jsonify({"error": str(exc)}), 400
                if from_id == to_id:
                    return jsonify({"error": "A person cannot settle with themselves."}), 400
                cur.execute("SELECT id FROM expense_groups WHERE id=%s AND created_by=%s FOR UPDATE", (group_id, uid))
                if not cur.fetchone():
                    return group_not_found()
                balances, _ = balance_data(cur, group_id)
                balance_map = {int(item["person_id"]): Decimal(str(item["balance"])) for item in balances}
                people = {int(p["person_id"]): p for p in people_for_group(cur, group_id)}
                if from_id not in balance_map or to_id not in balance_map:
                    return jsonify({"error": "Choose members from this group."}), 400
                if balance_map[from_id] >= 0 or balance_map[to_id] <= 0:
                    return jsonify({"error": "Settlement must be paid by a member who owes money to a member who is owed money."}), 400
                if amount > -balance_map[from_id] or amount > balance_map[to_id]:
                    return jsonify({"error": "Settlement is greater than the outstanding balance."}), 400
                cur.execute(
                    "INSERT INTO shared_settlements "
                    "(group_id,from_user_id,from_member_id,to_user_id,to_member_id,amount,payment_date,note,created_by_user_id) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (group_id, people[from_id].get("user_id"), from_id, people[to_id].get("user_id"), to_id,
                     amount, payment_date, str(data.get("note", "")).strip()[:500] or None, uid),
                )
                db.commit()
                return jsonify({"message": "Settlement recorded.", "amount": float(amount)}), 201
            cur.execute(
                "SELECT s.id,s.from_member_id,a.member_name AS from_name,s.to_member_id,b.member_name AS to_name, "
                "s.amount,s.payment_date,s.note,s.created_at FROM shared_settlements s "
                "JOIN expense_group_members a ON a.id=s.from_member_id "
                "JOIN expense_group_members b ON b.id=s.to_member_id "
                "WHERE s.group_id=%s ORDER BY s.payment_date DESC,s.id DESC",
                (group_id,),
            )
            rows = cur.fetchall()
            for row in rows:
                row["amount"] = float(row["amount"]); row["payment_date"] = _json_date(row["payment_date"]); row["created_at"] = _json_date(row["created_at"])
            return jsonify(rows)
        except Exception:
            db.rollback(); app.logger.exception("Settlement request failed")
            return jsonify({"error": "Could not process settlement. Check backend logs."}), 500
        finally:
            safe_close(cur, db)
