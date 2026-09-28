from datetime import date, timedelta, datetime
from decimal import Decimal
from sqlalchemy import func
from desktop.app.db.models import (
    Sale,
    SaleItem,
    Payment,
    BranchInventory,
    Batch,
    Product,
    Expense,
    ExpenseCategory,
    User,
)
from desktop.app.services.base_service import BaseService
from shared.enums import SaleStatus, ExpenseStatus


class ReportService(BaseService):
    """
    Offline-capable Report & Analytics Service (Architecture Plan §14).
    Calculates sales, inventory valuation, expenses, profit & loss, and cashier shifts from local SQLite.
    """

    def get_sales_summary(
        self,
        organization_id: str,
        branch_id: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict:
        with self.transaction() as db:
            q = db.query(Sale).filter(
                Sale.organization_id == organization_id,
                Sale.status.in_([SaleStatus.COMPLETED.value, SaleStatus.PARTIALLY_RETURNED.value]),
            )
            if branch_id:
                q = q.filter(Sale.branch_id == branch_id)
            if start_date:
                q = q.filter(Sale.sale_date >= start_date)
            if end_date:
                q = q.filter(Sale.sale_date <= end_date)

            sales = q.all()
            total_count = len(sales)
            total_revenue = sum((Decimal(str(s.total)) for s in sales), Decimal("0.00"))
            total_tax = sum((Decimal(str(s.tax_amount or 0)) for s in sales), Decimal("0.00"))
            total_discount = sum((Decimal(str(s.discount_amount or 0)) for s in sales), Decimal("0.00"))

            sale_ids = [s.id for s in sales]
            cogs = Decimal("0.00")
            items_sold_count = 0

            if sale_ids:
                items = db.query(SaleItem).filter(SaleItem.sale_id.in_(sale_ids)).all()
                for it in items:
                    items_sold_count += it.quantity
                    batch = db.query(Batch).filter_by(id=it.batch_id).first()
                    unit_cost = Decimal(str(batch.purchase_price)) if batch else Decimal("0.00")
                    cogs += unit_cost * it.quantity

            # Payment breakdown
            payments_data = []
            if sale_ids:
                payments = db.query(Payment).filter(Payment.sale_id.in_(sale_ids)).all()
                method_totals: dict[str, Decimal] = {}
                method_counts: dict[str, int] = {}
                for p in payments:
                    m = p.payment_method or "OTHER"
                    amt = Decimal(str(p.amount))
                    method_totals[m] = method_totals.get(m, Decimal("0.00")) + amt
                    method_counts[m] = method_counts.get(m, 0) + 1
                payments_data = [
                    {"method": k, "total": str(v), "count": method_counts[k]}
                    for k, v in method_totals.items()
                ]

            gross_profit = total_revenue - cogs

            return {
                "total_sales_count": total_count,
                "total_revenue": str(total_revenue),
                "total_tax": str(total_tax),
                "total_discount": str(total_discount),
                "total_items_sold": items_sold_count,
                "cost_of_goods_sold": str(cogs),
                "gross_profit": str(gross_profit),
                "payment_breakdown": payments_data,
            }

    def get_inventory_valuation(
        self,
        organization_id: str,
        branch_id: str | None = None,
    ) -> dict:
        with self.transaction() as db:
            q = db.query(BranchInventory).filter(
                BranchInventory.organization_id == organization_id,
                BranchInventory.quantity > 0,
            )
            if branch_id:
                q = q.filter(BranchInventory.branch_id == branch_id)

            inventories = q.all()
            total_units = 0
            total_cost_valuation = Decimal("0.00")
            low_stock_count = 0
            low_stock_items = []

            for inv in inventories:
                total_units += inv.quantity
                batch = db.query(Batch).filter_by(id=inv.batch_id).first()
                cost = Decimal(str(batch.purchase_price)) if batch else Decimal("0.00")
                total_cost_valuation += cost * inv.quantity
                reorder = inv.reorder_level or 10
                if inv.quantity <= reorder:
                    low_stock_count += 1
                    prod = db.query(Product).filter_by(id=batch.product_id).first() if batch else None
                    if len(low_stock_items) < 20:
                        low_stock_items.append({
                            "product_name": prod.name if prod else "",
                            "batch_number": batch.batch_number if batch else "",
                            "current_quantity": inv.quantity,
                            "reorder_level": reorder,
                        })

            today_iso = date.today().isoformat()
            ninety_days_iso = (date.today() + timedelta(days=90)).isoformat()

            # Batch expiry counts
            batch_ids = list({inv.batch_id for inv in inventories})
            expired_count = 0
            expiring_soon_count = 0
            if batch_ids:
                batches = db.query(Batch).filter(Batch.id.in_(batch_ids)).all()
                for b in batches:
                    if str(b.expiry_date) < today_iso:
                        expired_count += 1
                    elif today_iso <= str(b.expiry_date) <= ninety_days_iso:
                        expiring_soon_count += 1

            return {
                "total_batches_in_stock": len(inventories),
                "total_units_in_stock": total_units,
                "total_cost_valuation": str(total_cost_valuation),
                "low_stock_count": low_stock_count,
                "low_stock_items": low_stock_items,
                "expired_batches_count": expired_count,
                "expiring_soon_batches_count": expiring_soon_count,
            }

    def get_expense_summary(
        self,
        organization_id: str,
        branch_id: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        status: str = ExpenseStatus.APPROVED.value,
    ) -> dict:
        with self.transaction() as db:
            q = db.query(Expense).filter(Expense.organization_id == organization_id)
            if status:
                q = q.filter(Expense.status == status)
            if branch_id:
                q = q.filter(Expense.branch_id == branch_id)
            if start_date:
                q = q.filter(Expense.expense_date >= start_date)
            if end_date:
                q = q.filter(Expense.expense_date <= end_date)

            expenses = q.all()
            total_amount = sum((Decimal(str(e.amount)) for e in expenses), Decimal("0.00"))

            category_totals: dict[str, Decimal] = {}
            category_counts: dict[str, int] = {}
            for e in expenses:
                cat = db.query(ExpenseCategory).filter_by(id=e.expense_category_id).first()
                cname = cat.name if cat else "Uncategorized"
                amt = Decimal(str(e.amount))
                category_totals[cname] = category_totals.get(cname, Decimal("0.00")) + amt
                category_counts[cname] = category_counts.get(cname, 0) + 1

            category_breakdown = [
                {"category": k, "total": str(v), "count": category_counts[k]}
                for k, v in category_totals.items()
            ]

            method_totals: dict[str, Decimal] = {}
            method_counts: dict[str, int] = {}
            for e in expenses:
                m = e.payment_method or "CASH"
                amt = Decimal(str(e.amount))
                method_totals[m] = method_totals.get(m, Decimal("0.00")) + amt
                method_counts[m] = method_counts.get(m, 0) + 1

            payment_breakdown = [
                {"method": k, "total": str(v), "count": method_counts[k]}
                for k, v in method_totals.items()
            ]

            return {
                "total_expenses": str(total_amount),
                "total_count": len(expenses),
                "category_breakdown": category_breakdown,
                "payment_breakdown": payment_breakdown,
            }

    def get_profit_loss(
        self,
        organization_id: str,
        branch_id: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict:
        sales = self.get_sales_summary(organization_id, branch_id, start_date, end_date)
        expenses = self.get_expense_summary(organization_id, branch_id, start_date, end_date)

        rev = Decimal(sales["total_revenue"])
        cogs = Decimal(sales["cost_of_goods_sold"])
        gross_profit = rev - cogs
        operating_expenses = Decimal(expenses["total_expenses"])
        net_profit = gross_profit - operating_expenses

        return {
            "revenue": str(rev),
            "cost_of_goods_sold": str(cogs),
            "gross_profit": str(gross_profit),
            "operating_expenses": str(operating_expenses),
            "net_profit": str(net_profit),
            "sales_count": sales["total_sales_count"],
        }

    def get_cashier_shift_summary(
        self,
        organization_id: str,
        branch_id: str | None = None,
        date_str: str | None = None,
    ) -> dict:
        target_date = date_str or date.today().isoformat()
        with self.transaction() as db:
            q = db.query(Sale).filter(
                Sale.organization_id == organization_id,
                Sale.status.in_([SaleStatus.COMPLETED.value, SaleStatus.PARTIALLY_RETURNED.value]),
            )
            if branch_id:
                q = q.filter(Sale.branch_id == branch_id)
            sales = [s for s in q.all() if str(s.sale_date).startswith(target_date)]

            # Group sales by user_id
            user_sales_map: dict[str, list[Sale]] = {}
            for s in sales:
                user_sales_map.setdefault(s.user_id, []).append(s)

            shifts_data = []
            for uid, usales in user_sales_map.items():
                user = db.query(User).filter_by(id=uid).first()
                total_collected = sum((Decimal(str(s.total)) for s in usales), Decimal("0.00"))

                usale_ids = [s.id for s in usales]
                payments = db.query(Payment).filter(Payment.sale_id.in_(usale_ids)).all()
                pm_map: dict[str, Decimal] = {}
                for p in payments:
                    m = p.payment_method or "CASH"
                    pm_map[m] = pm_map.get(m, Decimal("0.00")) + Decimal(str(p.amount))

                shifts_data.append({
                    "user_id": uid,
                    "username": user.username if user else "unknown",
                    "full_name": user.full_name if user else "Unknown User",
                    "sales_count": len(usales),
                    "total_collected": str(total_collected),
                    "payments": {k: f"{v:.2f}" for k, v in pm_map.items()},
                })

            return {
                "date": target_date,
                "shifts": shifts_data,
            }
