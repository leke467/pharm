import uuid
from datetime import date, timedelta
from decimal import Decimal
import pytest
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.branches.models import Branch, Device
from apps.inventory.models import Batch, BranchInventory, InventoryMovement
from apps.organizations.models import Organization
from apps.products.models import Product, Category, ProductType
from apps.transfers.models import StockTransfer, StockTransferItem
from apps.users.models import User
from apps.sync.models import ProcessedEvent
from shared.enums import (
    TransferStatus,
    MovementType,
    AuditAction,
    AuditSource,
    BatchStatus,
    SyncOperation,
)


@pytest.mark.django_db
class TestPhase10ServerStockTransfersAcceptance:
    @pytest.fixture
    def setup_data(self):
        org = Organization.objects.create(name="Transfer Org", code="TORG")
        source_branch = Branch.objects.create(organization=org, name="Source Branch", code="SRC")
        dest_branch = Branch.objects.create(organization=org, name="Dest Branch", code="DST")

        user = User.objects.create_user(
            username="transferadmin",
            organization_id=org.id,
            password="adminpassword123",
            full_name="Transfer Admin",
            is_org_admin=True,
        )

        cat = Category.objects.create(organization=org, name="Antibiotics")
        ptype = ProductType.objects.create(organization=org, name="Tablet")
        product = Product.objects.create(
            organization=org,
            category=cat,
            product_type=ptype,
            name="Amoxicillin 500mg",
            sku="AMX-500",
        )

        batch = Batch.objects.create(
            organization=org,
            product=product,
            batch_number="BAT-TRANS-01",
            expiry_date=date.today() + timedelta(days=365),
            received_date=date.today(),
            purchase_price=Decimal("15.00"),
            status=BatchStatus.ACTIVE.value,
        )

        # 100 units at source branch
        source_inv = BranchInventory.objects.create(
            organization=org,
            branch=source_branch,
            batch=batch,
            quantity=100,
            reserved_quantity=0,
            status="AVAILABLE",
        )

        client = APIClient()
        client.force_authenticate(user=user)

        return {
            'org': org,
            'source_branch': source_branch,
            'dest_branch': dest_branch,
            'user': user,
            'product': product,
            'batch': batch,
            'source_inv': source_inv,
            'client': client,
        }

    def test_full_stock_transfer_lifecycle(self, setup_data):
        client = setup_data['client']
        source_b = setup_data['source_branch']
        dest_b = setup_data['dest_branch']
        product = setup_data['product']
        batch = setup_data['batch']

        # 1. Create Transfer Request (30 units)
        url = "/api/v1/transfers/"
        payload = {
            "source_branch_id": str(source_b.id),
            "destination_branch_id": str(dest_b.id),
            "notes": "Emergency transfer of Amoxicillin",
            "items": [
                {
                    "product_id": str(product.id),
                    "batch_id": str(batch.id),
                    "quantity": 30,
                }
            ],
        }

        resp = client.post(url, payload, format="json")
        assert resp.status_code == status.HTTP_201_CREATED, resp.data
        transfer_id = resp.data['id']
        assert resp.data['status'] == TransferStatus.REQUESTED.value
        assert len(resp.data['items']) == 1

        # Check inventory at source: not reserved yet
        source_inv = BranchInventory.objects.get(branch=source_b, batch=batch)
        assert source_inv.quantity == 100
        assert source_inv.reserved_quantity == 0

        # 2. Insufficient stock guard on approval
        # If we try to approve a transfer whose requested quantity exceeds available stock, it must fail
        oversized_transfer = StockTransfer.objects.create(
            organization=setup_data['org'],
            source_branch=source_b,
            destination_branch=dest_b,
            status=TransferStatus.REQUESTED.value,
            requested_by=setup_data['user'],
            requested_at=timezone.now(),
        )
        StockTransferItem.objects.create(
            stock_transfer=oversized_transfer,
            product=product,
            batch=batch,
            quantity=500,  # only 100 available
        )
        approve_fail_resp = client.post(f"/api/v1/transfers/{oversized_transfer.id}/approve/")
        assert approve_fail_resp.status_code == status.HTTP_400_BAD_REQUEST

        # 3. Approve Valid Transfer
        approve_resp = client.post(f"/api/v1/transfers/{transfer_id}/approve/")
        assert approve_resp.status_code == status.HTTP_200_OK
        assert approve_resp.data['status'] == TransferStatus.APPROVED.value
        assert str(approve_resp.data['approved_by']) == str(setup_data['user'].id)

        # Inventory check: 30 units reserved!
        source_inv.refresh_from_db()
        assert source_inv.quantity == 100
        assert source_inv.reserved_quantity == 30

        # 4. Dispatch Transfer
        dispatch_resp = client.post(f"/api/v1/transfers/{transfer_id}/dispatch/")
        assert dispatch_resp.status_code == status.HTTP_200_OK
        assert dispatch_resp.data['status'] == TransferStatus.DISPATCHED.value
        assert str(dispatch_resp.data['dispatched_by']) == str(setup_data['user'].id)

        # Inventory check at source: 30 units removed, reserved decremented to 0
        source_inv.refresh_from_db()
        assert source_inv.quantity == 70
        assert source_inv.reserved_quantity == 0

        # Check immutable InventoryMovement at source
        movement_out = InventoryMovement.objects.get(
            branch=source_b,
            batch=batch,
            reference_id=uuid.UUID(transfer_id),
            movement_type=MovementType.STOCK_TRANSFER_OUT.value,
        )
        assert movement_out.quantity_change == -30
        assert movement_out.quantity_before == 100
        assert movement_out.quantity_after == 70

        # 5. Receive Transfer at Destination Branch
        receive_resp = client.post(f"/api/v1/transfers/{transfer_id}/receive/")
        assert receive_resp.status_code == status.HTTP_200_OK
        assert receive_resp.data['status'] == TransferStatus.RECEIVED.value
        assert str(receive_resp.data['received_by']) == str(setup_data['user'].id)

        # Inventory check at destination: 30 units created/present
        dest_inv = BranchInventory.objects.get(branch=dest_b, batch=batch)
        assert dest_inv.quantity == 30
        assert dest_inv.reserved_quantity == 0

        # Check immutable InventoryMovement at destination
        movement_in = InventoryMovement.objects.get(
            branch=dest_b,
            batch=batch,
            reference_id=uuid.UUID(transfer_id),
            movement_type=MovementType.STOCK_TRANSFER_IN.value,
        )
        assert movement_in.quantity_change == 30
        assert movement_in.quantity_before == 0
        assert movement_in.quantity_after == 30

    def test_cancel_transfer_releases_reserved_stock(self, setup_data):
        client = setup_data['client']
        source_b = setup_data['source_branch']
        dest_b = setup_data['dest_branch']
        product = setup_data['product']
        batch = setup_data['batch']

        # Create transfer
        t = StockTransfer.objects.create(
            organization=setup_data['org'],
            source_branch=source_b,
            destination_branch=dest_b,
            status=TransferStatus.REQUESTED.value,
            requested_by=setup_data['user'],
            requested_at=timezone.now(),
        )
        StockTransferItem.objects.create(
            stock_transfer=t,
            product=product,
            batch=batch,
            quantity=25,
        )

        # Approve -> reserves 25 units
        client.post(f"/api/v1/transfers/{t.id}/approve/")
        source_inv = BranchInventory.objects.get(branch=source_b, batch=batch)
        assert source_inv.reserved_quantity == 25

        # Cancel -> releases 25 units
        cancel_resp = client.post(f"/api/v1/transfers/{t.id}/cancel/")
        assert cancel_resp.status_code == status.HTTP_200_OK
        assert cancel_resp.data['status'] == TransferStatus.CANCELLED.value

        source_inv.refresh_from_db()
        assert source_inv.quantity == 100
        assert source_inv.reserved_quantity == 0

    def test_sync_upload_stock_transfer(self, setup_data):
        client = setup_data['client']
        org = setup_data['org']
        source_b = setup_data['source_branch']
        dest_b = setup_data['dest_branch']
        user = setup_data['user']
        product = setup_data['product']
        batch = setup_data['batch']

        device = Device.objects.create(
            organization=org,
            branch=source_b,
            name="Source POS 1",
            code="SP1",
            device_identifier="DEV-SRC-001",
        )

        t_id = uuid.uuid4()
        item_id = uuid.uuid4()
        ev_transfer_id = uuid.uuid4()
        ev_item_id = uuid.uuid4()
        now_str = timezone.now().isoformat()

        events = [
            {
                "id": str(ev_transfer_id),
                "entity_type": "stock_transfer",
                "entity_id": str(t_id),
                "operation": SyncOperation.CREATE.value,
                "dependency_level": 4,
                "correlation_id": str(t_id),
                "schema_version": 1,
                "local_created_at": now_str,
                "payload": {
                    "id": str(t_id),
                    "source_branch_id": str(source_b.id),
                    "destination_branch_id": str(dest_b.id),
                    "status": TransferStatus.REQUESTED.value,
                    "requested_by_id": str(user.id),
                    "requested_at": now_str,
                    "notes": "Offline created transfer",
                },
            },
            {
                "id": str(ev_item_id),
                "entity_type": "stock_transfer_item",
                "entity_id": str(item_id),
                "operation": SyncOperation.CREATE.value,
                "dependency_level": 5,
                "correlation_id": str(t_id),
                "schema_version": 1,
                "local_created_at": now_str,
                "payload": {
                    "id": str(item_id),
                    "stock_transfer_id": str(t_id),
                    "product_id": str(product.id),
                    "batch_id": str(batch.id),
                    "quantity": 15,
                },
            },
        ]

        resp = client.post(
            "/api/v1/sync/upload/",
            {
                "device_id": str(device.id),
                "branch_id": str(source_b.id),
                "events": events,
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK, resp.data
        statuses = [r["status"] for r in resp.data["results"]]
        assert statuses == ["PROCESSED", "PROCESSED"], resp.data["results"]

        # Verify transfer exists in database
        transfer = StockTransfer.objects.filter(id=t_id).first()
        assert transfer is not None
        assert transfer.status == TransferStatus.REQUESTED.value
        assert transfer.items.count() == 1
        item = transfer.items.first()
        assert item.quantity == 15
