"""Finlumiq Receipt Scanner Phase 2 API routes.

This module adds receipt metadata/history and duplicate-check endpoints.
It does not replace or modify the existing POST /api/expenses route.
"""

from datetime import datetime
from decimal import Decimal, InvalidOperation
import re

from flask import jsonify, request, session


_HASH_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def _date_text(value):
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _parse_date(value):
    if not isinstance(value, str):
        raise ValueError("A valid expense date is required.")
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError("Expense date must use YYYY-MM-DD format.") from exc


def _parse_amount(value):
    try:
        amount = Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("A valid expense amount is required.")
    if not amount.is_finite() or amount <= 0:
        raise ValueError("Expense amount must be greater than zero.")
    if amount > Decimal("9999999999.99"):
        raise ValueError("Expense amount is too large.")
    return amount


def register_receipt_scanner_phase2_routes(app, get_db, login_required):
    """Register the Phase 2 routes exactly once from app.py."""

    @app.route("/api/receipt-scans/check-duplicate", methods=["POST"])
    @login_required
    def receipt_scans_check_duplicate():
        data = request.get_json(silent=True) or {}
        uid = session.get("user_id")
        image_hash = str(data.get("image_hash", "")).strip().lower()

        if not uid:
            return jsonify({"error": "Please log in again."}), 401
        if not _HASH_RE.fullmatch(image_hash):
            return jsonify({"error": "Invalid receipt image fingerprint."}), 400

        try:
            expense_date = _parse_date(data.get("date"))
            amount = _parse_amount(data.get("amount"))
            category_id = int(data.get("category_id"))
            title = str(data.get("title", "")).strip()[:150]
            if category_id <= 0 or not title:
                raise ValueError("A valid category and expense title are required.")
        except (ValueError, TypeError) as exc:
            return jsonify({"error": str(exc)}), 400

        db = get_db()
        cur = None
        try:
            cur = db.cursor(dictionary=True)

            cur.execute(
                "SELECT id, expense_id, merchant_name, expense_title, amount, expense_date "
                "FROM receipt_scans WHERE user_id=%s AND image_sha256=%s LIMIT 1",
                (uid, image_hash),
            )
            existing_scan = cur.fetchone()
            if existing_scan:
                existing_scan["expense_date"] = _date_text(existing_scan.get("expense_date"))
                existing_scan["amount"] = float(existing_scan.get("amount") or 0)
                return jsonify({
                    "duplicate": True,
                    "possible_duplicate": True,
                    "match_type": "same_receipt_image",
                    "match": existing_scan,
                })

            # A matching date + amount + category is a warning, not a hard block.
            # A student may legitimately buy the same item twice on one day.
            cur.execute(
                "SELECT id, title, amount, expense_date, category_id "
                "FROM expenses "
                "WHERE user_id=%s AND expense_date=%s AND category_id=%s "
                "AND amount=%s "
                "ORDER BY CASE WHEN LOWER(TRIM(title))=LOWER(TRIM(%s)) THEN 0 ELSE 1 END, id DESC "
                "LIMIT 1",
                (uid, expense_date, category_id, amount, title),
            )
            existing_expense = cur.fetchone()
            if existing_expense:
                existing_expense["expense_date"] = _date_text(existing_expense.get("expense_date"))
                existing_expense["amount"] = float(existing_expense["amount"])
                return jsonify({
                    "duplicate": False,
                    "possible_duplicate": True,
                    "match_type": "similar_expense",
                    "match": existing_expense,
                })

            return jsonify({"duplicate": False, "possible_duplicate": False})
        finally:
            try:
                if cur is not None:
                    cur.close()
            except Exception:
                pass
            db.close()

    @app.route("/api/receipt-scans", methods=["GET"])
    @login_required
    def receipt_scans_list():
        uid = session.get("user_id")
        if not uid:
            return jsonify({"error": "Please log in again."}), 401

        db = get_db()
        cur = None
        try:
            cur = db.cursor(dictionary=True)
            cur.execute(
                "SELECT rs.id, rs.expense_id, rs.merchant_name, rs.expense_title, "
                "rs.amount, rs.expense_date, rs.category_id, c.name AS category_name, "
                "rs.status, rs.created_at "
                "FROM receipt_scans rs "
                "LEFT JOIN categories c ON c.id=rs.category_id "
                "WHERE rs.user_id=%s "
                "ORDER BY rs.created_at DESC, rs.id DESC LIMIT 25",
                (uid,),
            )
            rows = cur.fetchall()
            result = []
            for row in rows:
                row["expense_date"] = _date_text(row.get("expense_date"))
                row["created_at"] = _date_text(row.get("created_at"))
                row["amount"] = float(row.get("amount") or 0)
                result.append(row)
            return jsonify(result)
        finally:
            try:
                if cur is not None:
                    cur.close()
            except Exception:
                pass
            db.close()

    @app.route("/api/receipt-scans", methods=["POST"])
    @login_required
    def receipt_scans_create():
        data = request.get_json(silent=True) or {}
        uid = session.get("user_id")
        if not uid:
            return jsonify({"error": "Please log in again."}), 401

        image_hash = str(data.get("image_hash", "")).strip().lower()
        merchant = str(data.get("merchant_name", "")).strip()[:150] or None
        title = str(data.get("expense_title", "")).strip()[:150]
        extracted_text = str(data.get("extracted_text", ""))[:20000]
        notes = str(data.get("notes", "")).strip()[:500] or None
        status = "saved"

        try:
            expense_date = _parse_date(data.get("expense_date"))
            amount = _parse_amount(data.get("amount"))
            category_id = int(data.get("category_id"))
            if category_id <= 0:
                raise ValueError("Select a valid category.")
            if not title:
                raise ValueError("Expense title is required.")
            if not _HASH_RE.fullmatch(image_hash):
                raise ValueError("Invalid receipt image fingerprint.")
            expense_id_raw = data.get("expense_id")
            expense_id = int(expense_id_raw) if expense_id_raw not in (None, "", 0, "0") else None
            if expense_id is not None and expense_id <= 0:
                raise ValueError("Invalid expense reference.")
        except (ValueError, TypeError) as exc:
            return jsonify({"error": str(exc)}), 400

        db = get_db()
        cur = None
        try:
            cur = db.cursor(dictionary=True)

            cur.execute("SELECT id FROM categories WHERE id=%s LIMIT 1", (category_id,))
            if not cur.fetchone():
                return jsonify({"error": "The selected category does not exist."}), 400

            if expense_id is not None:
                cur.execute(
                    "SELECT id FROM expenses WHERE id=%s AND user_id=%s LIMIT 1",
                    (expense_id, uid),
                )
                if not cur.fetchone():
                    return jsonify({"error": "The linked expense was not found for this account."}), 400

            cur.execute(
                "SELECT id FROM receipt_scans WHERE user_id=%s AND image_sha256=%s LIMIT 1",
                (uid, image_hash),
            )
            if cur.fetchone():
                return jsonify({"error": "This receipt image has already been saved."}), 409

            cur.execute(
                "INSERT INTO receipt_scans "
                "(user_id, expense_id, merchant_name, expense_title, amount, category_id, "
                "expense_date, image_sha256, extracted_text, notes, status) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (uid, expense_id, merchant, title, amount, category_id, expense_date,
                 image_hash, extracted_text or None, notes, status),
            )
            scan_id = cur.lastrowid
            db.commit()
            return jsonify({"message": "Receipt history saved.", "id": scan_id, "expense_id": expense_id}), 201
        except Exception as exc:
            try:
                db.rollback()
            except Exception:
                pass
            # A simultaneous request may have inserted the same user/image hash.
            if "duplicate" in str(exc).lower() or "1062" in str(exc):
                return jsonify({"error": "This receipt image has already been saved."}), 409
            app.logger.exception("Could not save receipt scan history")
            return jsonify({"error": "Could not save receipt history. Check the server log."}), 500
        finally:
            try:
                if cur is not None:
                    cur.close()
            except Exception:
                pass
            db.close()

    return True
