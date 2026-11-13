"""Phase 5 API extension for the Expenses-tracker Flask application.

Integration (at the bottom of app.py, before the __main__ block):
    from phase5 import register_phase5_routes
    register_phase5_routes(app, get_db, login_required)

This module is additive: it does not replace existing routes or write shared
expenses into the personal `expenses` table.
"""
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from functools import wraps
import logging

from flask import jsonify, request, session

log = logging.getLogger(__name__)
CENT = Decimal("0.01")
ALLOWED_CATEGORIES = {
    "College Fees", "Scholarship", "Savings Goal", "Budget Alert",
    "Daily Expense", "Recurring Expense", "Group Settlement", "Personal", "Other"
}
ALLOWED_PRIORITIES = {"Low", "Medium", "High"}
ALLOWED_REPEATS = {"none", "daily", "weekly", "monthly"}


def _money(value):
    try:
        amount = Decimal(str(value)).quantize(CENT)
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("Enter a valid amount")
    if not amount.is_finite() or amount <= 0:
        raise ValueError("Amount must be greater than zero")
    return amount


def _date(value, field="date"):
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        raise ValueError(f"Enter a valid {field} in YYYY-MM-DD format")


def _split_amounts(total, participant_ids, method, supplied_splits):
    """Return [(user_id, Decimal amount), ...], with exact cent equality."""
    ids = sorted(set(int(x) for x in participant_ids))
    if not ids or len(ids) != len(participant_ids):
        raise ValueError("Select one or more different group members")
    total = _money(total)
    cents = int(total * 100)

    if method == "equal":
        base, remainder = divmod(cents, len(ids))
        return [(uid, (Decimal(base + (1 if i < remainder else 0)) / Decimal(100)).quantize(CENT))
                for i, uid in enumerate(ids)]

    if method not in {"custom", "percentage"}:
        raise ValueError("Split method must be equal, custom, or percentage")
    if not isinstance(supplied_splits, list) or len(supplied_splits) != len(ids):
        raise ValueError("Provide one split value for every selected member")

    values = {}
    for item in supplied_splits:
        if not isinstance(item, dict):
            raise ValueError("Each split must contain user_id and amount/percentage")
        try:
            uid = int(item.get("user_id"))
            value = Decimal(str(item.get("percentage" if method == "percentage" else "amount")))
        except (TypeError, ValueError, InvalidOperation):
            raise ValueError("Invalid split member or split value")
        if uid not in ids or uid in values or not value.is_finite() or value < 0:
            raise ValueError("Split values must be non-negative and members must be unique")
        values[uid] = value
    if set(values) != set(ids):
        raise ValueError("Split members do not match selected participants")

    if method == "custom":
        rounded = {uid: value.quantize(CENT) for uid, value in values.items()}
        if sum(rounded.values(), Decimal("0.00")) != total:
            raise ValueError("Custom split amounts must add up exactly to the total")
        return [(uid, rounded[uid]) for uid in ids]

    if sum(values.values(), Decimal("0")) != Decimal("100"):
        raise ValueError("Percentage split values must total exactly 100")
    raw = {uid: (total * values[uid] / Decimal("100")) for uid in ids}
    rounded = {uid: raw[uid].quantize(CENT, rounding=ROUND_DOWN) for uid in ids}
    remaining = int((total - sum(rounded.values(), Decimal("0.00"))) * 100)
    # Allocate leftover paise to the largest fractional remainders; stable by user ID.
    order = sorted(ids, key=lambda uid: (raw[uid] - rounded[uid], -uid), reverse=True)
    for uid in order[:remaining]:
        rounded[uid] += CENT
    return [(uid, rounded[uid]) for uid in ids]


def _iso(value):
    return value.isoformat() if hasattr(value, "isoformat") and value is not None else value


def _notify(cur, user_id, title, message, link_url=None, kind="info"):
    cur.execute(
        "INSERT INTO notifications (user_id, title, message, link_url, notification_type) "
        "VALUES (%s,%s,%s,%s,%s)",
        (user_id, title[:120], message[:500], link_url, kind)
    )


def register_phase5_routes(app, get_db, login_required):
    """Register Phase 5 routes on the existing Flask app."""

    def member_role(cur, group_id, user_id, lock=False):
        sql = "SELECT role FROM expense_group_members WHERE group_id=%s AND user_id=%s"
        if lock:
            sql += " FOR UPDATE"
        cur.execute(sql, (group_id, user_id))
        row = cur.fetchone()
        return row["role"] if row else None

    def require_group_member(cur, group_id, user_id):
        role = member_role(cur, group_id, user_id)
        if role is None:
            return None, (jsonify({"error": "Group not found or you are not a member"}), 404)
        return role, None

    def fetch_balances(cur, group_id):
        cur.execute(
            "SELECT gm.user_id, gm.role, u.name, u.email FROM expense_group_members gm "
            "JOIN users u ON u.id=gm.user_id WHERE gm.group_id=%s ORDER BY u.name, u.id",
            (group_id,)
        )
        members = cur.fetchall()
        balances = {int(m["user_id"]): {"user_id": int(m["user_id"]),
                    "name": m["name"], "email": m["email"], "role": m["role"], "balance": Decimal("0.00")} for m in members}
        cur.execute(
            "SELECT e.paid_by_user_id, e.total_amount, s.user_id AS participant_id, s.amount AS share_amount "
            "FROM shared_expenses e JOIN expense_splits s ON s.expense_id=e.id "
            "WHERE e.group_id=%s", (group_id,)
        )
        for row in cur.fetchall():
            payer = int(row["paid_by_user_id"])
            participant = int(row["participant_id"])
            if participant in balances:
                balances[participant]["balance"] -= Decimal(str(row["share_amount"]))
        # A payer is credited once per expense, not once for every participant.
        cur.execute("SELECT paid_by_user_id, total_amount FROM shared_expenses WHERE group_id=%s", (group_id,))
        for row in cur.fetchall():
            payer = int(row["paid_by_user_id"])
            if payer in balances:
                balances[payer]["balance"] += Decimal(str(row["total_amount"]))
        cur.execute("SELECT from_user_id, to_user_id, amount FROM shared_settlements WHERE group_id=%s", (group_id,))
        for row in cur.fetchall():
            from_id, to_id = int(row["from_user_id"]), int(row["to_user_id"])
            amount = Decimal(str(row["amount"]))
            if from_id in balances:
                balances[from_id]["balance"] += amount
            if to_id in balances:
                balances[to_id]["balance"] -= amount
        for item in balances.values():
            item["balance"] = item["balance"].quantize(CENT)
        debtors = [[uid, -item["balance"]] for uid, item in balances.items() if item["balance"] < 0]
        creditors = [[uid, item["balance"]] for uid, item in balances.items() if item["balance"] > 0]
        suggestions = []
        i = j = 0
        while i < len(debtors) and j < len(creditors):
            amount = min(debtors[i][1], creditors[j][1]).quantize(CENT)
            if amount > 0:
                suggestions.append({"from_user_id": debtors[i][0], "from_name": balances[debtors[i][0]]["name"],
                                    "to_user_id": creditors[j][0], "to_name": balances[creditors[j][0]]["name"],
                                    "amount": float(amount)})
            debtors[i][1] -= amount
            creditors[j][1] -= amount
            if debtors[i][1] == 0: i += 1
            if creditors[j][1] == 0: j += 1
        return members, balances, suggestions

    # ----------------------- Expense groups -----------------------
    @app.route("/api/expense-groups", methods=["GET", "POST"])
    @login_required
    def phase5_groups():
        uid = int(session["user_id"])
        db = get_db()
        try:
            cur = db.cursor(dictionary=True)
            if request.method == "POST":
                data = request.get_json(silent=True) or {}
                name = str(data.get("name", "")).strip()
                description = str(data.get("description", "")).strip()
                if not name or len(name) > 100:
                    return jsonify({"error": "Group name is required (maximum 100 characters)"}), 400
                cur.execute("INSERT INTO expense_groups (name, description, created_by) VALUES (%s,%s,%s)",
                            (name, description[:1000] or None, uid))
                group_id = cur.lastrowid
                cur.execute("INSERT INTO expense_group_members (group_id,user_id,role) VALUES (%s,%s,'owner')",
                            (group_id, uid))
                db.commit()
                return jsonify({"id": group_id, "name": name, "description": description, "role": "owner"}), 201
            cur.execute(
                "SELECT g.id,g.name,g.description,g.created_at,gm.role, "
                "(SELECT COUNT(*) FROM expense_group_members x WHERE x.group_id=g.id) AS member_count, "
                "(SELECT COUNT(*) FROM shared_expenses e WHERE e.group_id=g.id) AS expense_count "
                "FROM expense_groups g JOIN expense_group_members gm ON gm.group_id=g.id "
                "WHERE gm.user_id=%s ORDER BY g.created_at DESC", (uid,)
            )
            rows = cur.fetchall()
            for row in rows: row["created_at"] = _iso(row["created_at"])
            return jsonify(rows)
        finally:
            db.close()

    @app.route("/api/expense-groups/<int:group_id>", methods=["GET"])
    @login_required
    def phase5_group_detail(group_id):
        uid = int(session["user_id"])
        db = get_db()
        try:
            cur = db.cursor(dictionary=True)
            role, error = require_group_member(cur, group_id, uid)
            if error: return error
            cur.execute("SELECT id,name,description,created_by,created_at FROM expense_groups WHERE id=%s", (group_id,))
            group = cur.fetchone()
            group["created_at"] = _iso(group["created_at"])
            cur.execute("SELECT u.id AS user_id,u.name,u.email,gm.role,gm.joined_at FROM expense_group_members gm "
                        "JOIN users u ON u.id=gm.user_id WHERE gm.group_id=%s ORDER BY gm.role DESC,u.name", (group_id,))
            group["members"] = cur.fetchall()
            for m in group["members"]: m["joined_at"] = _iso(m["joined_at"])
            group["my_role"] = role
            _, balances, suggestions = fetch_balances(cur, group_id)
            group["balances"] = [{**v, "balance": float(v["balance"])} for v in balances.values()]
            group["suggested_settlements"] = suggestions
            return jsonify(group)
        finally:
            db.close()

    @app.route("/api/expense-groups/<int:group_id>/members", methods=["POST"])
    @login_required
    def phase5_add_member(group_id):
        uid = int(session["user_id"])
        data = request.get_json(silent=True) or {}
        email = str(data.get("email", "")).strip().lower()
        if not email or len(email) > 120 or "@" not in email:
            return jsonify({"error": "Enter a valid registered email address"}), 400
        db = get_db()
        try:
            cur = db.cursor(dictionary=True)
            role, error = require_group_member(cur, group_id, uid)
            if error: return error
            if role != "owner": return jsonify({"error": "Only the group owner can add members"}), 403
            cur.execute("SELECT id,name,email FROM users WHERE LOWER(email)=LOWER(%s)", (email,))
            person = cur.fetchone()
            if not person: return jsonify({"error": "No registered account found for this email"}), 404
            if int(person["id"]) == uid: return jsonify({"error": "You are already the group owner"}), 409
            cur.execute("SELECT 1 FROM expense_group_members WHERE group_id=%s AND user_id=%s", (group_id, person["id"]))
            if cur.fetchone(): return jsonify({"error": "This user is already a group member"}), 409
            cur.execute("INSERT INTO expense_group_members (group_id,user_id,role) VALUES (%s,%s,'member')",
                        (group_id, person["id"]))
            cur.execute("SELECT name FROM expense_groups WHERE id=%s", (group_id,))
            group_name = cur.fetchone()["name"]
            _notify(cur, person["id"], "Added to an expense group", f"You were added to {group_name}.", "split-expenses.html", "success")
            db.commit()
            return jsonify({"message": f"{person['name']} added to the group", "member": person}), 201
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @app.route("/api/expense-groups/<int:group_id>/members/<int:member_id>", methods=["DELETE"])
    @login_required
    def phase5_remove_member(group_id, member_id):
        uid = int(session["user_id"])
        db = get_db()
        try:
            cur = db.cursor(dictionary=True)
            role, error = require_group_member(cur, group_id, uid)
            if error: return error
            if role != "owner" and uid != member_id:
                return jsonify({"error": "Only the owner can remove another member"}), 403
            cur.execute("SELECT role FROM expense_group_members WHERE group_id=%s AND user_id=%s", (group_id, member_id))
            target = cur.fetchone()
            if not target: return jsonify({"error": "Group member not found"}), 404
            if target["role"] == "owner": return jsonify({"error": "The group owner cannot be removed"}), 400
            _, balances, _ = fetch_balances(cur, group_id)
            bal = balances.get(member_id, {}).get("balance", Decimal("0.00"))
            if bal != 0:
                return jsonify({"error": "This member has an outstanding balance. Settle it before removal."}), 409
            cur.execute("DELETE FROM expense_group_members WHERE group_id=%s AND user_id=%s", (group_id, member_id))
            db.commit()
            return jsonify({"message": "Member removed"})
        finally:
            db.close()

    # ----------------------- Shared expenses -----------------------
    @app.route("/api/expense-groups/<int:group_id>/expenses", methods=["GET", "POST"])
    @login_required
    def phase5_group_expenses(group_id):
        uid = int(session["user_id"])
        db = get_db()
        try:
            cur = db.cursor(dictionary=True)
            _, error = require_group_member(cur, group_id, uid)
            if error: return error
            if request.method == "POST":
                data = request.get_json(silent=True) or {}
                title = str(data.get("title", "")).strip()
                category = str(data.get("category", "Other")).strip()[:80]
                description = str(data.get("description", "")).strip()
                if not title or len(title) > 150:
                    return jsonify({"error": "Expense title is required (maximum 150 characters)"}), 400
                try:
                    total = _money(data.get("total_amount"))
                    expense_date = _date(data.get("expense_date"), "expense date")
                    payer = int(data.get("paid_by_user_id", uid))
                    participant_ids = [int(x) for x in data.get("participant_user_ids", [])]
                    method = str(data.get("split_method", "equal")).lower()
                    splits = _split_amounts(total, participant_ids, method, data.get("splits", []))
                except (ValueError, TypeError) as exc:
                    return jsonify({"error": str(exc)}), 400
                cur.execute("SELECT 1 FROM expense_group_members WHERE group_id=%s AND user_id=%s", (group_id, payer))
                if not cur.fetchone(): return jsonify({"error": "Payer must be a member of this group"}), 400
                cur.execute("SELECT user_id FROM expense_group_members WHERE group_id=%s", (group_id,))
                valid_ids = {int(r["user_id"]) for r in cur.fetchall()}
                if not set(participant_ids).issubset(valid_ids):
                    return jsonify({"error": "Every participant must belong to this group"}), 400
                if sum((Decimal(str(v)) for _, v in splits), Decimal("0.00")) != total:
                    return jsonify({"error": "Split amounts do not equal the expense total"}), 400
                try:
                    cur.execute("INSERT INTO shared_expenses (group_id,title,category,total_amount,expense_date,description,paid_by_user_id,created_by_user_id) "
                                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                                (group_id,title,category,total,expense_date,description[:1000] or None,payer,uid))
                    expense_id = cur.lastrowid
                    cur.executemany("INSERT INTO expense_splits (expense_id,user_id,amount) VALUES (%s,%s,%s)",
                                    [(expense_id, member_id, amount) for member_id, amount in splits])
                    cur.execute("SELECT name FROM expense_groups WHERE id=%s", (group_id,))
                    group_name = cur.fetchone()["name"]
                    for member_id in participant_ids:
                        if member_id != uid:
                            _notify(cur, member_id, "New shared expense", f"{title} was added to {group_name}.", "split-expenses.html", "info")
                    db.commit()
                    return jsonify({"id": expense_id, "group_id": group_id, "title": title,
                                    "total_amount": float(total), "paid_by_user_id": payer,
                                    "split_method": method,
                                    "splits": [{"user_id": m, "amount": float(a)} for m,a in splits]}), 201
                except Exception:
                    db.rollback()
                    raise
            cur.execute("SELECT e.id,e.title,e.category,e.total_amount,e.expense_date,e.description, "
                        "e.paid_by_user_id,u.name AS paid_by_name,e.created_at "
                        "FROM shared_expenses e JOIN users u ON u.id=e.paid_by_user_id "
                        "WHERE e.group_id=%s ORDER BY e.expense_date DESC,e.id DESC", (group_id,))
            expenses = cur.fetchall()
            for item in expenses:
                item["total_amount"] = float(item["total_amount"])
                item["expense_date"] = _iso(item["expense_date"])
                item["created_at"] = _iso(item["created_at"])
                cur.execute("SELECT s.user_id,u.name,s.amount FROM expense_splits s JOIN users u ON u.id=s.user_id WHERE s.expense_id=%s ORDER BY u.name", (item["id"],))
                item["splits"] = [{"user_id": r["user_id"], "name": r["name"], "amount": float(r["amount"])} for r in cur.fetchall()]
            return jsonify(expenses)
        finally:
            db.close()

    @app.route("/api/expense-groups/<int:group_id>/balances", methods=["GET"])
    @login_required
    def phase5_group_balances(group_id):
        uid = int(session["user_id"])
        db = get_db()
        try:
            cur = db.cursor(dictionary=True)
            _, error = require_group_member(cur, group_id, uid)
            if error: return error
            _, balances, suggestions = fetch_balances(cur, group_id)
            return jsonify({"balances": [{**v, "balance": float(v["balance"])} for v in balances.values()],
                            "suggested_settlements": suggestions})
        finally:
            db.close()

    @app.route("/api/expense-groups/<int:group_id>/settlements", methods=["GET", "POST"])
    @login_required
    def phase5_settlements(group_id):
        uid = int(session["user_id"])
        db = get_db()
        try:
            cur = db.cursor(dictionary=True)
            _, error = require_group_member(cur, group_id, uid)
            if error: return error
            if request.method == "POST":
                data = request.get_json(silent=True) or {}
                try:
                    to_id = int(data.get("to_user_id"))
                    amount = _money(data.get("amount"))
                    payment_date = _date(data.get("payment_date") or date.today().isoformat(), "payment date")
                except (ValueError, TypeError) as exc:
                    return jsonify({"error": str(exc)}), 400
                if to_id == uid: return jsonify({"error": "You cannot settle a balance with yourself"}), 400
                # Lock the group row so two simultaneous settlement requests cannot overspend a balance.
                cur.execute("SELECT id FROM expense_groups WHERE id=%s FOR UPDATE", (group_id,))
                if not cur.fetchone(): return jsonify({"error": "Group not found"}), 404
                _, balances, _ = fetch_balances(cur, group_id)
                if uid not in balances or to_id not in balances:
                    return jsonify({"error": "Both users must be group members"}), 400
                if balances[uid]["balance"] >= 0 or balances[to_id]["balance"] <= 0:
                    return jsonify({"error": "Settlement must be paid by a member who owes money to a member who is owed money"}), 400
                if amount > -balances[uid]["balance"] or amount > balances[to_id]["balance"]:
                    return jsonify({"error": "Settlement exceeds the outstanding balance"}), 400
                cur.execute("INSERT INTO shared_settlements (group_id,from_user_id,to_user_id,amount,payment_date,note,created_by_user_id) "
                            "VALUES (%s,%s,%s,%s,%s,%s,%s)",
                            (group_id,uid,to_id,amount,payment_date,str(data.get("note", "")).strip()[:500] or None,uid))
                cur.execute("SELECT name FROM users WHERE id=%s", (uid,))
                payer_name = cur.fetchone()["name"]
                _notify(cur, to_id, "Group settlement recorded", f"{payer_name} recorded a settlement of ₹{amount}.", "split-expenses.html", "success")
                db.commit()
                return jsonify({"message": "Settlement recorded", "amount": float(amount)}), 201
            cur.execute("SELECT s.id,s.from_user_id,uf.name AS from_name,s.to_user_id,ut.name AS to_name, "
                        "s.amount,s.payment_date,s.note,s.created_at FROM shared_settlements s "
                        "JOIN users uf ON uf.id=s.from_user_id JOIN users ut ON ut.id=s.to_user_id "
                        "WHERE s.group_id=%s ORDER BY s.payment_date DESC,s.id DESC", (group_id,))
            rows = cur.fetchall()
            for row in rows:
                row["amount"] = float(row["amount"]); row["payment_date"] = _iso(row["payment_date"]); row["created_at"] = _iso(row["created_at"])
            return jsonify(rows)
        finally:
            db.close()

    # ----------------------- Personal reminders -----------------------
    @app.route("/api/user-reminders", methods=["GET", "POST"])
    @login_required
    def phase5_user_reminders():
        uid = int(session["user_id"])
        db = get_db()
        try:
            cur = db.cursor(dictionary=True)
            if request.method == "POST":
                data = request.get_json(silent=True) or {}
                title = str(data.get("title", "")).strip()
                description = str(data.get("description", "")).strip()
                category = str(data.get("category", "Personal")).strip()
                priority = str(data.get("priority", "Medium")).strip().title()
                repeat = str(data.get("repeat_frequency", "none")).strip().lower()
                try:
                    due_date = _date(data.get("due_date"), "due date")
                    due_time = time.fromisoformat(str(data["due_time"])) if data.get("due_time") else None
                except (ValueError, TypeError, KeyError) as exc:
                    return jsonify({"error": str(exc) or "Invalid due time"}), 400
                if not title or len(title) > 150: return jsonify({"error": "Reminder title is required (maximum 150 characters)"}), 400
                if category not in ALLOWED_CATEGORIES: return jsonify({"error": "Choose a valid reminder category"}), 400
                if priority not in ALLOWED_PRIORITIES: return jsonify({"error": "Priority must be Low, Medium, or High"}), 400
                if repeat not in ALLOWED_REPEATS: return jsonify({"error": "Repeat must be none, daily, weekly, or monthly"}), 400
                cur.execute("INSERT INTO user_reminders (user_id,title,description,category,due_date,due_time,priority,repeat_frequency) "
                            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                            (uid,title,description[:2000] or None,category,due_date,due_time,priority,repeat))
                reminder_id = cur.lastrowid
                db.commit()
                return jsonify({"id": reminder_id, "title": title, "due_date": due_date.isoformat(), "due_time": _iso(due_time),
                                "category": category, "priority": priority, "repeat_frequency": repeat, "status": "pending"}), 201
            status = request.args.get("status")
            query = "SELECT id,title,description,category,due_date,due_time,priority,repeat_frequency,status,completed_at,completed_count,created_at FROM user_reminders WHERE user_id=%s"
            params = [uid]
            if status in {"pending", "completed"}:
                query += " AND status=%s"; params.append(status)
            query += " ORDER BY CASE WHEN status='pending' THEN 0 ELSE 1 END,due_date ASC, due_time ASC, id DESC"
            cur.execute(query, params)
            rows = cur.fetchall()
            for row in rows:
                for key in ("due_date", "due_time", "completed_at", "created_at"):
                    row[key] = _iso(row[key])
                row["is_overdue"] = row["status"] == "pending" and row["due_date"] < date.today().isoformat()
            return jsonify(rows)
        finally:
            db.close()

    @app.route("/api/user-reminders/<int:reminder_id>", methods=["PUT", "DELETE"])
    @login_required
    def phase5_user_reminder_item(reminder_id):
        uid = int(session["user_id"])
        db = get_db()
        try:
            cur = db.cursor(dictionary=True)
            cur.execute("SELECT id FROM user_reminders WHERE id=%s AND user_id=%s", (reminder_id, uid))
            if not cur.fetchone(): return jsonify({"error": "Reminder not found"}), 404
            if request.method == "DELETE":
                cur.execute("DELETE FROM user_reminders WHERE id=%s AND user_id=%s", (reminder_id, uid))
                db.commit(); return jsonify({"message": "Reminder deleted"})
            data = request.get_json(silent=True) or {}
            title = str(data.get("title", "")).strip()
            category = str(data.get("category", "Personal")).strip()
            priority = str(data.get("priority", "Medium")).strip().title()
            repeat = str(data.get("repeat_frequency", "none")).strip().lower()
            try:
                due_date = _date(data.get("due_date"), "due date")
                due_time = time.fromisoformat(str(data["due_time"])) if data.get("due_time") else None
            except (ValueError, TypeError, KeyError) as exc:
                return jsonify({"error": str(exc) or "Invalid due time"}), 400
            if not title or len(title) > 150: return jsonify({"error": "Reminder title is required (maximum 150 characters)"}), 400
            if category not in ALLOWED_CATEGORIES or priority not in ALLOWED_PRIORITIES or repeat not in ALLOWED_REPEATS:
                return jsonify({"error": "Invalid category, priority, or repeat frequency"}), 400
            cur.execute("UPDATE user_reminders SET title=%s,description=%s,category=%s,due_date=%s,due_time=%s,priority=%s,repeat_frequency=%s "
                        "WHERE id=%s AND user_id=%s",
                        (title,str(data.get("description", "")).strip()[:2000] or None,category,due_date,due_time,priority,repeat,reminder_id,uid))
            db.commit(); return jsonify({"message": "Reminder updated"})
        finally:
            db.close()

    @app.route("/api/user-reminders/<int:reminder_id>/complete", methods=["POST"])
    @login_required
    def phase5_complete_reminder(reminder_id):
        uid = int(session["user_id"])
        db = get_db()
        try:
            cur = db.cursor(dictionary=True)
            cur.execute("SELECT due_date,repeat_frequency,status FROM user_reminders WHERE id=%s AND user_id=%s FOR UPDATE", (reminder_id,uid))
            row = cur.fetchone()
            if not row: return jsonify({"error": "Reminder not found"}), 404
            if row["status"] == "completed": return jsonify({"message": "Reminder is already completed"})
            if row["repeat_frequency"] == "none":
                cur.execute("UPDATE user_reminders SET status='completed',completed_at=NOW(),completed_count=completed_count+1 WHERE id=%s AND user_id=%s", (reminder_id,uid))
                message = "Reminder marked as completed"
            else:
                next_date = row["due_date"]
                if row["repeat_frequency"] == "daily": next_date += timedelta(days=1)
                elif row["repeat_frequency"] == "weekly": next_date += timedelta(days=7)
                else:
                    # Preserve the day where possible; clamp to the last day of the next month.
                    year = next_date.year + (1 if next_date.month == 12 else 0)
                    month = 1 if next_date.month == 12 else next_date.month + 1
                    import calendar
                    next_date = date(year, month, min(next_date.day, calendar.monthrange(year, month)[1]))
                while next_date <= date.today():
                    if row["repeat_frequency"] == "daily": next_date += timedelta(days=1)
                    elif row["repeat_frequency"] == "weekly": next_date += timedelta(days=7)
                    else:
                        import calendar
                        year = next_date.year + (1 if next_date.month == 12 else 0)
                        month = 1 if next_date.month == 12 else next_date.month + 1
                        next_date = date(year, month, min(next_date.day, calendar.monthrange(year, month)[1]))
                cur.execute("UPDATE user_reminders SET due_date=%s,last_completed_at=NOW(),completed_count=completed_count+1 WHERE id=%s AND user_id=%s", (next_date,reminder_id,uid))
                message = f"Recurring reminder completed. Next due date: {next_date.isoformat()}"
            db.commit(); return jsonify({"message": message})
        except Exception:
            db.rollback(); raise
        finally:
            db.close()

    # ----------------------- Notifications -----------------------
    @app.route("/api/notifications", methods=["GET"])
    @login_required
    def phase5_notifications():
        uid = int(session["user_id"])
        db = get_db()
        try:
            cur = db.cursor(dictionary=True)
            cur.execute("SELECT id,title,message,link_url,notification_type,is_read,created_at FROM notifications "
                        "WHERE user_id=%s ORDER BY is_read ASC,created_at DESC LIMIT 100", (uid,))
            rows = cur.fetchall()
            for row in rows: row["created_at"] = _iso(row["created_at"]); row["is_read"] = bool(row["is_read"])
            cur.execute("SELECT COUNT(*) AS unread_count FROM notifications WHERE user_id=%s AND is_read=0", (uid,))
            unread = cur.fetchone()["unread_count"]
            return jsonify({"notifications": rows, "unread_count": unread})
        finally:
            db.close()

    @app.route("/api/notifications/<int:notification_id>/read", methods=["PATCH"])
    @login_required
    def phase5_read_notification(notification_id):
        uid = int(session["user_id"])
        db = get_db()
        try:
            cur = db.cursor(); cur.execute("UPDATE notifications SET is_read=1 WHERE id=%s AND user_id=%s", (notification_id,uid))
            if cur.rowcount == 0: return jsonify({"error": "Notification not found"}), 404
            db.commit(); return jsonify({"message": "Notification marked as read"})
        finally: db.close()

    @app.route("/api/notifications/read-all", methods=["PATCH"])
    @login_required
    def phase5_read_all_notifications():
        uid = int(session["user_id"])
        db = get_db()
        try:
            cur = db.cursor(); cur.execute("UPDATE notifications SET is_read=1 WHERE user_id=%s AND is_read=0", (uid,))
            count = cur.rowcount; db.commit(); return jsonify({"message": "All notifications marked as read", "updated": count})
        finally: db.close()

    @app.route("/api/notifications/<int:notification_id>", methods=["DELETE"])
    @login_required
    def phase5_delete_notification(notification_id):
        uid = int(session["user_id"])
        db = get_db()
        try:
            cur = db.cursor(); cur.execute("DELETE FROM notifications WHERE id=%s AND user_id=%s", (notification_id,uid))
            if cur.rowcount == 0: return jsonify({"error": "Notification not found"}), 404
            db.commit(); return jsonify({"message": "Notification deleted"})
        finally: db.close()

    @app.route("/api/phase5/health", methods=["GET"])
    @login_required
    def phase5_health():
        return jsonify({"status": "ok", "phase": 5, "message": "Phase 5 routes are registered"})
