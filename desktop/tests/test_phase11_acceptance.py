"""Phase 11 Acceptance Tests — Price Versioning & Sync (Desktop)."""
import json
import uuid
from decimal import Decimal
import pytest
from desktop.app.auth.session import Session
from desktop.app.db.models import (
    Organization,
    Branch,
    Device,
    Category,
    Product,
    Price,
    PriceHistory,
    SyncEvent,
    AuditEvent,
    User,
)
from desktop.app.domain.enums import PermissionCode, AuditAction
from desktop.app.domain.exceptions import ValidationError
from desktop.app.services.pricing_service import (
    PricingService,
    _download_price,
    _download_price_history,
)
from desktop.app.utils.date_utils import utc_now
from desktop.app.utils.uuid_utils import generate_uuid


class TestPhase11DesktopPricingAcceptance:
    """Desktop acceptance tests for Phase 11 Price Versioning & Price Synchronization."""

    def _seed(self, db_manager):
        org_id = generate_uuid()
        branch_a_id = generate_uuid()
        branch_b_id = generate_uuid()
        device_id = generate_uuid()
        user_id = generate_uuid()
        cat_id = generate_uuid()
        product_id = generate_uuid()

        with db_manager.get_session() as db:
            db.add(Organization(id=org_id, name="Medix Pharmacy", code="MDX"))
            db.flush()
            db.add(Branch(id=branch_a_id, organization_id=org_id, name="Branch A", code="BRA"))
            db.add(Branch(id=branch_b_id, organization_id=org_id, name="Branch B", code="BRB"))
            db.flush()
            db.add(Device(
                id=device_id,
                organization_id=org_id,
                branch_id=branch_a_id,
                name="POS 1",
                code="P01",
                device_identifier="DEV-MDX-01",
            ))
            db.flush()
            db.add(User(
                id=user_id,
                organization_id=org_id,
                username="pricemaster",
                full_name="Price Manager",
                is_org_admin=True,
            ))
            db.flush()
            db.add(Category(id=cat_id, organization_id=org_id, name="Analgesics"))
            db.flush()
            db.add(Product(
                id=product_id,
                organization_id=org_id,
                category_id=cat_id,
                sku="IBU-400",
                name="Ibuprofen 400mg",
            ))
            db.commit()

        session = Session(
            user_id=user_id,
            username="pricemaster",
            full_name="Price Manager",
            organization_id=org_id,
            organization_name="Medix Pharmacy",
            branch_id=branch_a_id,
            branch_name="Branch A",
            device_id=device_id,
            device_code="P01",
            permissions=[PermissionCode.PRICES_VIEW.value, PermissionCode.PRICES_MANAGE.value],
            roles=["Admin"],
            is_offline=True,
            is_org_admin=True,
            access_token=None,
            refresh_token=None,
            logged_in_at=utc_now(),
        )

        return {
            'org_id': org_id,
            'branch_a_id': branch_a_id,
            'branch_b_id': branch_b_id,
            'device_id': device_id,
            'user_id': user_id,
            'product_id': product_id,
            'session': session,
        }

    def test_price_versioning_and_history_creation(self, db_manager):
        data = self._seed(db_manager)
        service = PricingService(db_manager)
        session = data['session']
        product_id = data['product_id']

        # 1. Set initial price: 500.00
        p1 = service.set_price(
            session,
            product_id=product_id,
            selling_price=Decimal("500.00"),
            change_reason="Initial rollout",
        )
        assert p1.version == 1
        assert p1.selling_price == Decimal("500.00")
        assert p1.is_current is True

        with db_manager.get_session() as db:
            h1 = db.query(PriceHistory).filter_by(price_id=p1.id).first()
            assert h1 is not None
            assert h1.version == 1
            assert h1.old_price is None
            assert h1.new_price == Decimal("500.00")
            assert h1.change_reason == "Initial rollout"

            # Check sync event queued for price and price history
            syncs = db.query(SyncEvent).filter_by(entity_id=p1.id).all()
            assert len(syncs) == 1
            assert syncs[0].entity_type == "price"

            hist_sync = db.query(SyncEvent).filter_by(entity_id=h1.id).first()
            assert hist_sync is not None
            assert hist_sync.entity_type == "price_history"

        # 2. Update price to 600.00
        p2 = service.set_price(
            session,
            product_id=product_id,
            selling_price=Decimal("600.00"),
            change_reason="Supplier increased cost",
        )
        assert p2.version == 2
        assert p2.selling_price == Decimal("600.00")
        assert p2.is_current is True

        with db_manager.get_session() as db:
            old_p = db.query(Price).filter_by(id=p1.id).first()
            assert old_p.is_current is False
            assert old_p.effective_to is not None

            h2 = db.query(PriceHistory).filter_by(price_id=p2.id).first()
            assert h2 is not None
            assert h2.version == 2
            assert h2.old_price == Decimal("500.00")
            assert h2.new_price == Decimal("600.00")

        # 3. Query price history
        history_list = service.get_price_history(product_id)
        assert len(history_list) == 2
        versions = [h['version'] for h in history_list]
        assert versions == [2, 1]

    def test_force_all_branches_retires_overrides(self, db_manager):
        data = self._seed(db_manager)
        service = PricingService(db_manager)
        session = data['session']
        product_id = data['product_id']
        branch_a_id = data['branch_a_id']
        branch_b_id = data['branch_b_id']
        org_id = data['org_id']

        # Set org default price: 1000.00
        p_org = service.set_price(session, product_id, Decimal("1000.00"), branch_id=None)

        # Set branch override for Branch A: 1200.00
        p_bra = service.set_price(session, product_id, Decimal("1200.00"), branch_id=branch_a_id)

        # Resolution before force:
        # Branch A gets 1200
        resolved_a = service.resolve_price(org_id, product_id, branch_a_id)
        assert resolved_a.selling_price == Decimal("1200.00")
        assert resolved_a.branch_id == branch_a_id

        # Branch B gets org default (1000)
        resolved_b = service.resolve_price(org_id, product_id, branch_b_id)
        assert resolved_b.selling_price == Decimal("1000.00")
        assert resolved_b.branch_id is None

        # Now set org default price with force_all_branches=True at 1100.00
        p_forced = service.set_price(
            session,
            product_id,
            Decimal("1100.00"),
            branch_id=None,
            force_all_branches=True,
            change_reason="National harmonization",
        )
        assert p_forced.selling_price == Decimal("1100.00")

        # Verify branch override for Branch A is retired
        with db_manager.get_session() as db:
            bo = db.query(Price).filter_by(id=p_bra.id).first()
            assert bo.is_current is False

        # Now Branch A resolves to org default price (1100.00)
        resolved_a_after = service.resolve_price(org_id, product_id, branch_a_id)
        assert resolved_a_after.selling_price == Decimal("1100.00")
        assert resolved_a_after.branch_id is None

    def test_download_handlers_for_price_and_history(self, db_manager):
        data = self._seed(db_manager)
        product_id = data['product_id']
        org_id = data['org_id']

        p_id = generate_uuid()
        hist_id = generate_uuid()

        # Download price
        price_payload = {
            "id": p_id,
            "product_id": product_id,
            "branch_id": None,
            "selling_price": "850.00",
            "currency": "NGN",
            "is_current": True,
            "version": 1,
            "effective_from": utc_now(),
        }
        with db_manager.get_session() as db:
            _download_price(db, org_id, p_id, "CREATE", price_payload, None)
            db.commit()

        # Download price history
        hist_payload = {
            "id": hist_id,
            "price_id": p_id,
            "product_id": product_id,
            "branch_id": None,
            "old_price": None,
            "new_price": "850.00",
            "change_reason": "Central price push",
            "version": 1,
            "local_timestamp": utc_now(),
        }
        with db_manager.get_session() as db:
            _download_price_history(db, org_id, hist_id, "CREATE", hist_payload, None)
            db.commit()

        with db_manager.get_session() as db:
            p = db.query(Price).filter_by(id=p_id).first()
            assert p is not None
            assert p.selling_price == Decimal("850.00")
            assert p.is_current is True

            h = db.query(PriceHistory).filter_by(id=hist_id).first()
            assert h is not None
            assert h.new_price == Decimal("850.00")
            assert h.change_reason == "Central price push"
