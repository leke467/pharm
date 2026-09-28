"""Phase 10 Acceptance Tests — Stock Transfers (Desktop)."""
import json
import uuid
from datetime import date, timedelta
from decimal import Decimal
import pytest
from desktop.app.auth.session import Session
from desktop.app.db.models import (
    Organization,
    Branch,
    Device,
    Category,
    Product,
    Batch,
    BranchInventory,
    InventoryMovement,
    StockTransfer,
    StockTransferItem,
    SyncEvent,
    AuditEvent,
    User,
)
from desktop.app.domain.enums import (
    MovementType,
    TransferStatus,
    AuditAction,
)
from desktop.app.domain.exceptions import ValidationError
from desktop.app.services.transfer_service import TransferService, _download_stock_transfer, _download_stock_transfer_item
from desktop.app.utils.date_utils import utc_now
from desktop.app.utils.uuid_utils import generate_uuid


class TestPhase10DesktopStockTransfersAcceptance:
    """Desktop acceptance tests for Phase 10 Stock Transfers."""

    def _seed(self, db_manager):
        org_id = generate_uuid()
        src_branch_id = generate_uuid()
        dst_branch_id = generate_uuid()
        device_id = generate_uuid()
        user_id = generate_uuid()
        cat_id = generate_uuid()
        product_id = generate_uuid()
        batch_id = generate_uuid()

        with db_manager.get_session() as db:
            db.add(Organization(id=org_id, name="Transfer Pharmacy", code="TPHARM"))
            db.flush()
            db.add(Branch(id=src_branch_id, organization_id=org_id, name="Source Branch", code="SRC01"))
            db.add(Branch(id=dst_branch_id, organization_id=org_id, name="Dest Branch", code="DST01"))
            db.flush()
            db.add(Device(
                id=device_id,
                organization_id=org_id,
                branch_id=src_branch_id,
                name="Main POS",
                code="MP01",
                device_identifier="DEV-SRC-001",
            ))
            db.flush()
            db.add(User(
                id=user_id,
                organization_id=org_id,
                username="transadmin",
                full_name="Transfer Manager",
                is_org_admin=True,
            ))
            db.flush()
            db.add(Category(id=cat_id, organization_id=org_id, name="Antibiotics"))
            db.flush()
            db.add(Product(
                id=product_id,
                organization_id=org_id,
                category_id=cat_id,
                sku="AMX-250",
                name="Amoxicillin 250mg",
            ))
            db.flush()
            db.add(Batch(
                id=batch_id,
                organization_id=org_id,
                product_id=product_id,
                batch_number="BAT-D-TRANS",
                expiry_date=(date.today() + timedelta(days=365)).isoformat(),
                received_date=date.today().isoformat(),
                purchase_price=Decimal("100.00"),
                status="ACTIVE",
            ))
            db.flush()
            # 50 units at source branch
            db.add(BranchInventory(
                id=generate_uuid(),
                organization_id=org_id,
                branch_id=src_branch_id,
                batch_id=batch_id,
                quantity=50,
                reserved_quantity=0,
                status="AVAILABLE",
            ))
            db.commit()

        session = Session(
            user_id=user_id,
            username="transadmin",
            full_name="Transfer Manager",
            organization_id=org_id,
            organization_name="Transfer Pharmacy",
            branch_id=src_branch_id,
            branch_name="Source Branch",
            device_id=device_id,
            device_code="MP01",
            permissions=["stock.transfer"],
            roles=["Admin"],
            is_offline=True,
            is_org_admin=True,
            access_token=None,
            refresh_token=None,
            logged_in_at=utc_now(),
        )

        return {
            'org_id': org_id,
            'src_branch_id': src_branch_id,
            'dst_branch_id': dst_branch_id,
            'device_id': device_id,
            'user_id': user_id,
            'product_id': product_id,
            'batch_id': batch_id,
            'session': session,
        }

    def test_full_transfer_lifecycle_and_reserved_quantity(self, db_manager):
        data = self._seed(db_manager)
        service = TransferService(db_manager)
        session = data['session']
        src_id = data['src_branch_id']
        dst_id = data['dst_branch_id']
        prod_id = data['product_id']
        batch_id = data['batch_id']

        # 1. Validation: cannot transfer to same branch
        with pytest.raises(ValidationError):
            service.create_transfer(session, destination_branch_id=src_id, items=[{"product_id": prod_id, "batch_id": batch_id, "quantity": 10}])

        # 2. Create valid transfer (20 units)
        transfer = service.create_transfer(
            session,
            destination_branch_id=dst_id,
            items=[{"product_id": prod_id, "batch_id": batch_id, "quantity": 20}],
            notes="Transfer to branch 2",
        )
        assert transfer.status == TransferStatus.REQUESTED.value

        with db_manager.get_session() as db:
            inv = db.query(BranchInventory).filter_by(branch_id=src_id, batch_id=batch_id).first()
            assert inv.quantity == 50
            assert inv.reserved_quantity == 0

            # Verify sync events queued
            sync_events = db.query(SyncEvent).filter_by(entity_id=transfer.id).all()
            assert len(sync_events) == 1
            assert sync_events[0].entity_type == "stock_transfer"

        # 3. Insufficient stock check on approval
        with db_manager.get_session() as db:
            huge_transfer = StockTransfer(
                id=generate_uuid(),
                organization_id=data['org_id'],
                source_branch_id=src_id,
                destination_branch_id=dst_id,
                status=TransferStatus.REQUESTED.value,
                requested_by_id=session.user_id,
                requested_at=utc_now(),
            )
            db.add(huge_transfer)
            db.add(StockTransferItem(
                id=generate_uuid(),
                stock_transfer_id=huge_transfer.id,
                product_id=prod_id,
                batch_id=batch_id,
                quantity=100,  # only 50 available
            ))
            db.commit()

        with pytest.raises(ValidationError) as exc:
            service.approve_transfer(session, huge_transfer.id)
        assert "Insufficient available stock" in str(exc.value)

        # 4. Approve valid transfer (reserves 20 units)
        approved = service.approve_transfer(session, transfer.id)
        assert approved.status == TransferStatus.APPROVED.value

        with db_manager.get_session() as db:
            inv = db.query(BranchInventory).filter_by(branch_id=src_id, batch_id=batch_id).first()
            assert inv.quantity == 50
            assert inv.reserved_quantity == 20

        # 5. Dispatch transfer
        dispatched = service.dispatch_transfer(session, transfer.id)
        assert dispatched.status == TransferStatus.DISPATCHED.value

        with db_manager.get_session() as db:
            inv = db.query(BranchInventory).filter_by(branch_id=src_id, batch_id=batch_id).first()
            assert inv.quantity == 30
            assert inv.reserved_quantity == 0

            # Check immutable InventoryMovement at source
            mov_out = db.query(InventoryMovement).filter_by(
                branch_id=src_id,
                batch_id=batch_id,
                reference_id=transfer.id,
                movement_type=MovementType.STOCK_TRANSFER_OUT.value,
            ).first()
            assert mov_out is not None
            assert mov_out.quantity_change == -20
            assert mov_out.quantity_before == 50
            assert mov_out.quantity_after == 30

        # 6. Receive transfer at destination
        received = service.receive_transfer(session, transfer.id)
        assert received.status == TransferStatus.RECEIVED.value

        with db_manager.get_session() as db:
            dest_inv = db.query(BranchInventory).filter_by(branch_id=dst_id, batch_id=batch_id).first()
            assert dest_inv is not None
            assert dest_inv.quantity == 20
            assert dest_inv.reserved_quantity == 0

            # Check immutable InventoryMovement at destination
            mov_in = db.query(InventoryMovement).filter_by(
                branch_id=dst_id,
                batch_id=batch_id,
                reference_id=transfer.id,
                movement_type=MovementType.STOCK_TRANSFER_IN.value,
            ).first()
            assert mov_in is not None
            assert mov_in.quantity_change == 20
            assert mov_in.quantity_before == 0
            assert mov_in.quantity_after == 20

    def test_cancel_transfer_releases_reserved_stock(self, db_manager):
        data = self._seed(db_manager)
        service = TransferService(db_manager)
        session = data['session']
        src_id = data['src_branch_id']
        dst_id = data['dst_branch_id']
        prod_id = data['product_id']
        batch_id = data['batch_id']

        t = service.create_transfer(
            session,
            destination_branch_id=dst_id,
            items=[{"product_id": prod_id, "batch_id": batch_id, "quantity": 15}],
        )
        service.approve_transfer(session, t.id)

        with db_manager.get_session() as db:
            inv = db.query(BranchInventory).filter_by(branch_id=src_id, batch_id=batch_id).first()
            assert inv.reserved_quantity == 15

        # Cancel
        cancelled = service.cancel_transfer(session, t.id)
        assert cancelled.status == TransferStatus.CANCELLED.value

        with db_manager.get_session() as db:
            inv = db.query(BranchInventory).filter_by(branch_id=src_id, batch_id=batch_id).first()
            assert inv.quantity == 50
            assert inv.reserved_quantity == 0

    def test_download_handlers_for_stock_transfers(self, db_manager):
        data = self._seed(db_manager)
        t_id = generate_uuid()
        item_id = generate_uuid()
        src_id = data['src_branch_id']
        dst_id = data['dst_branch_id']
        prod_id = data['product_id']
        batch_id = data['batch_id']

        # Download transfer
        transfer_payload = {
            "id": t_id,
            "source_branch_id": src_id,
            "destination_branch_id": dst_id,
            "status": TransferStatus.REQUESTED.value,
            "requested_by_id": data['user_id'],
            "requested_at": utc_now(),
            "notes": "Downloaded transfer",
        }
        with db_manager.get_session() as db:
            _download_stock_transfer(db, data['org_id'], t_id, "CREATE", transfer_payload, None)
            db.commit()

        # Download transfer item
        item_payload = {
            "id": item_id,
            "stock_transfer_id": t_id,
            "product_id": prod_id,
            "batch_id": batch_id,
            "quantity": 12,
        }
        with db_manager.get_session() as db:
            _download_stock_transfer_item(db, data['org_id'], item_id, "CREATE", item_payload, None)
            db.commit()

        with db_manager.get_session() as db:
            t = db.query(StockTransfer).filter_by(id=t_id).first()
            assert t is not None
            assert t.status == TransferStatus.REQUESTED.value
            assert t.notes == "Downloaded transfer"

            it = db.query(StockTransferItem).filter_by(id=item_id).first()
            assert it is not None
            assert it.quantity == 12
