"""Finlumiq Receipt Scanner Phase 3 routes.

Adds monthly insights over existing receipt_scans data. It does not change
or replace any Phase 2 routes, the expenses table, or expense-saving logic.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal

from flask import jsonify, request, session


def _as_float(value):
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _json_date(value):
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _month_bounds(month_value):
    """Return (YYYY-MM, first day, first day of next month, previous start, current start)."""
    if month_value:
        try:
            start = datetime.strptime(month_value, "%Y-%m").date().replace(day=1)
        except (TypeError, ValueError) as exc:
            raise ValueError("Month must use YYYY-MM format.") from exc
    else:
        start = date.today().replace(day=1)

    if start.month == 12:
        end = date(start.year + 1, 1, 1)
    else:
        end = date(start.year, start.month + 1, 1)

    previous_day = start - timedelta(days=1)
    previous_start = previous_day.replace(day=1)
    return start.strftime("%Y-%m"), start, end, previous_start, start


def _summary_row(cursor, uid, start, end):
    cursor.execute(
        "SELECT COUNT(*) AS scan_count, "
        "COALESCE(SUM(amount), 0) AS total_amount, "
        "COALESCE(AVG(amount), 0) AS average_amount, "
        "COUNT(DISTINCT category_id) AS category_count, "
        "COUNT(DISTINCT NULLIF(TRIM(merchant_name), '')) AS merchant_count "
        "FROM receipt_scans "
        "WHERE user_id=%s AND expense_date >= %s AND expense_date < %s AND status='saved'",
        (uid, start, end),
    )
    row = cursor.fetchone() or {}
    return {
        "scan_count": int(row.get("scan_count") or 0),
        "total_amount": _as_float(row.get("total_amount")),
        "average_amount": _as_float(row.get("average_amount")),
        "category_count": int(row.get("category_count") or 0),
        "merchant_count": int(row.get("merchant_count") or 0),
    }


def register_receipt_scanner_phase3_routes(app, get_db, login_required):
    """Register Phase 3 monthly insights route once from app.py."""

    @app.route("/api/receipt-scans/insights", methods=["GET"])
    @login_required
    def receipt_scans_insights():
        uid = session.get("user_id")
        if not uid:
            return jsonify({"error": "Please log in again."}), 401

        try:
            month, start, end, previous_start, _ = _month_bounds(
                request.args.get("month", "").strip()
            )
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

        db = get_db()
        cur = None
        try:
            cur = db.cursor(dictionary=True)
            summary = _summary_row(cur, uid, start, end)
            previous_summary = _summary_row(cur, uid, previous_start, start)

            cur.execute(
                "SELECT COALESCE(NULLIF(TRIM(c.grp), ''), NULLIF(TRIM(c.name), ''), 'Uncategorized') "
                "AS category_group, COUNT(*) AS scan_count, COALESCE(SUM(rs.amount), 0) AS total_amount "
                "FROM receipt_scans rs "
                "LEFT JOIN categories c ON c.id=rs.category_id "
                "WHERE rs.user_id=%s AND rs.expense_date >= %s AND rs.expense_date < %s "
                "AND rs.status='saved' "
                "GROUP BY category_group ORDER BY total_amount DESC, scan_count DESC LIMIT 5",
                (uid, start, end),
            )
            category_rows = cur.fetchall() or []
            categories = [
                {
                    "category_group": row.get("category_group") or "Uncategorized",
                    "scan_count": int(row.get("scan_count") or 0),
                    "total_amount": _as_float(row.get("total_amount")),
                }
                for row in category_rows
            ]

            cur.execute(
                "SELECT COALESCE(NULLIF(TRIM(merchant_name), ''), 'Unknown merchant') AS merchant_name, "
                "COUNT(*) AS scan_count, COALESCE(SUM(amount), 0) AS total_amount "
                "FROM receipt_scans "
                "WHERE user_id=%s AND expense_date >= %s AND expense_date < %s AND status='saved' "
                "GROUP BY merchant_name ORDER BY scan_count DESC, total_amount DESC LIMIT 5",
                (uid, start, end),
            )
            merchant_rows = cur.fetchall() or []
            merchants = [
                {
                    "merchant_name": row.get("merchant_name") or "Unknown merchant",
                    "scan_count": int(row.get("scan_count") or 0),
                    "total_amount": _as_float(row.get("total_amount")),
                }
                for row in merchant_rows
            ]

            cur.execute(
                "SELECT merchant_name, expense_title, amount, expense_date "
                "FROM receipt_scans "
                "WHERE user_id=%s AND expense_date >= %s AND expense_date < %s AND status='saved' "
                "ORDER BY amount DESC, expense_date DESC, id DESC LIMIT 1",
                (uid, start, end),
            )
            largest = cur.fetchone()
            if largest:
                largest = {
                    "merchant_name": largest.get("merchant_name") or "Unknown merchant",
                    "expense_title": largest.get("expense_title") or "Receipt expense",
                    "amount": _as_float(largest.get("amount")),
                    "expense_date": _json_date(largest.get("expense_date")),
                }

            previous_total = previous_summary["total_amount"]
            current_total = summary["total_amount"]
            if previous_total > 0:
                percentage_change = ((current_total - previous_total) / previous_total) * 100
                direction = "up" if percentage_change > 0.5 else ("down" if percentage_change < -0.5 else "same")
                percentage_change = round(percentage_change, 1)
            else:
                percentage_change = None
                direction = "no_baseline"

            insights = []
            if summary["scan_count"] == 0:
                insights.append("No saved receipt scans were recorded for this month. Scan a receipt to start building this summary.")
            else:
                insights.append(
                    f"You saved {summary['scan_count']} receipt(s) totalling ₹{current_total:,.2f} this month."
                )
                if categories:
                    top_category = categories[0]
                    insights.append(
                        f"{top_category['category_group']} is your highest receipt category at ₹{top_category['total_amount']:,.2f}."
                    )
                if merchants:
                    top_merchant = merchants[0]
                    insights.append(
                        f"{top_merchant['merchant_name']} appears on {top_merchant['scan_count']} saved receipt(s)."
                    )
                if percentage_change is not None:
                    if direction == "up":
                        insights.append(f"Receipt-scanned spending is up {abs(percentage_change):.1f}% compared with last month.")
                    elif direction == "down":
                        insights.append(f"Receipt-scanned spending is down {abs(percentage_change):.1f}% compared with last month.")
                    else:
                        insights.append("Receipt-scanned spending is almost unchanged compared with last month.")
                else:
                    insights.append("There is no saved receipt history for the previous month to compare against.")
                if largest:
                    insights.append(
                        f"Your largest saved receipt is {largest['expense_title']} at ₹{largest['amount']:,.2f}."
                    )

            return jsonify({
                "month": month,
                "summary": summary,
                "previous_month": previous_summary,
                "comparison": {
                    "percentage_change": percentage_change,
                    "direction": direction,
                },
                "categories": categories,
                "merchants": merchants,
                "largest_receipt": largest,
                "insights": insights,
                "note": "Insights are calculated from saved receipt_scans records only; they do not include manually entered expenses.",
            })
        except Exception:
            app.logger.exception("Could not calculate receipt scanner insights")
            return jsonify({
                "error": "Could not load receipt insights. Confirm the Phase 2 receipt_scans table and categories table are available."
            }), 500
        finally:
            try:
                if cur is not None:
                    cur.close()
            except Exception:
                pass
            db.close()

    return True
