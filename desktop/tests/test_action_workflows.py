import uuid
from decimal import Decimal
from desktop.app.auth.session import Session
from desktop.app.auth.offline_auth import OfflineAuthenticator
from desktop.app.db.models import Organization, Branch, Device, User, Category, Product, Batch, BranchInventory, OfflineCredential
from desktop.app.services.user_service import UserService
from desktop.app.services.purchase_service import PurchaseService
from desktop.app.services.stock_count_service import StockCountService
from desktop.app.services.expense_service import ExpenseService
from desktop.app.services.transfer_service import TransferService
from shared.enums import PermissionCode, StockCountStatus, TransferStatus, ExpenseStatus


def setup_test_environment(db_manager, code_prefix: str = "T"):
    org_id = str(uuid.uuid4())
    branch_id = str(uuid.uuid4())
    device_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    cat_id = str(uuid.uuid4())

    with db_manager.get_session() as db:
        org = Organization(id=org_id, name="Test Pharmacy Org", code=f"{code_prefix}_ORG")
        db.add(org)
        db.flush()

        branch = Branch(id=branch_id, organization_id=org_id, name="Main Branch", code=f"{code_prefix}_B1")
        db.add(branch)
        db.flush()

        device = Device(
            id=device_id,
            organization_id=org_id,
            branch_id=branch_id,
            name="Main Register",
            code="D1",
            device_identifier=f"DEV_{code_prefix}",
        )
        db.add(device)
        db.flush()

        admin_user = User(
            id=user_id,
            organization_id=org_id,
            username=f"{code_prefix.lower()}_admin",
            full_name="Admin Manager",
            is_org_admin=True,
            is_active=True,
            default_branch_id=branch_id,
        )
        db.add(admin_user)
        db.flush()

        category = Category(id=cat_id, organization_id=org_id, name="General")
        db.add(category)
        db.flush()

        db.commit()

    session = Session(
        user_id=user_id,
        username=f"{code_prefix.lower()}_admin",
        full_name="Admin Manager",
        organization_id=org_id,
        organization_name="Test Pharmacy Org",
        branch_id=branch_id,
        branch_name="Main Branch",
        device_id=device_id,
        device_code="D1",
        permissions=[p.value for p in PermissionCode],
        roles=[{"name": "Admin"}],
        is_offline=False,
        is_org_admin=True,
    )
    return org_id, branch_id, user_id, cat_id, session


def test_user_password_creation_and_reset(db_manager):
    org_id, branch_id, user_id, cat_id, session = setup_test_environment(db_manager, "U1")

    user_svc = UserService(db_manager)

    # 1. Create user with password and role
    created_user = user_svc.create_user(
        user_session=session,
        username="cashier1",
        full_name="Alice Cashier",
        email="alice@test.com",
        phone="08012345678",
        password="AliceSecurePassword123",
        default_branch_id=branch_id,
    )

    assert created_user.username == "cashier1"

    # Verify OfflineCredential was created and hashed
    with db_manager.get_session() as db:
        cred = db.query(OfflineCredential).filter_by(user_id=created_user.id).first()
        assert cred is not None
        assert OfflineAuthenticator().verify_password("AliceSecurePassword123", cred.offline_password_hash)
        assert not OfflineAuthenticator().verify_password("wrong", cred.offline_password_hash)

    # 2. Reset password
    user_svc.reset_password(session, created_user.id, "AliceNewPassword456")

    with db_manager.get_session() as db:
        cred = db.query(OfflineCredential).filter_by(user_id=created_user.id).first()
        assert cred is not None
        assert OfflineAuthenticator().verify_password("AliceNewPassword456", cred.offline_password_hash)
        assert not OfflineAuthenticator().verify_password("AliceSecurePassword123", cred.offline_password_hash)


def test_purchase_order_and_receive_workflow(db_manager):
    org_id, branch_id, user_id, cat_id, session = setup_test_environment(db_manager, "PO1")

    prod_id = str(uuid.uuid4())
    with db_manager.get_session() as db:
        prod = Product(id=prod_id, organization_id=org_id, category_id=cat_id, name="Paracetamol 500mg", sku="PCM-500")
        db.add(prod)
        db.flush()
        db.commit()

    pur_svc = PurchaseService(db_manager)

    # Create supplier
    sup = pur_svc.create_supplier(session, "Emzor Pharma Ltd", "Dr. Emzor", "08099998888")
    assert sup.name == "Emzor Pharma Ltd"

    # Create Purchase
    po = pur_svc.create_purchase(
        user_session=session,
        supplier_id=sup.id,
        purchase_reference="PO-TEST-001",
        purchase_date="2026-09-26",
        items=[{
            "product_id": prod_id,
            "quantity_ordered": 50,
            "purchase_price": "200.00",
            "selling_price": "300.00",
        }],
    )
    assert po.purchase_reference == "PO-TEST-001"

    # Fetch details
    details = pur_svc.get_purchase_details(po.id)
    assert details is not None
    assert len(details["items"]) == 1
    assert details["items"][0]["remaining_quantity"] == 50

    # Receive Stock
    rec_res = pur_svc.receive_purchase(
        user_session=session,
        purchase_id=po.id,
        items=[{
            "purchase_item_id": details["items"][0]["id"],
            "quantity_received": 50,
            "batch_number": "BN-2026-09",
            "expiry_date": "2028-12-31",
            "update_selling_price": True,
        }],
    )
    assert rec_res["receiving_status"] == "RECEIVED"

    # Verify BranchInventory
    with db_manager.get_session() as db:
        inv = db.query(BranchInventory).filter_by(branch_id=branch_id).first()
        assert inv is not None
        assert inv.quantity == 50


def test_stock_count_and_approval_workflow(db_manager):
    org_id, branch_id, user_id, cat_id, session = setup_test_environment(db_manager, "SC1")

    prod_id = str(uuid.uuid4())
    batch_id = str(uuid.uuid4())
    with db_manager.get_session() as db:
        db.add(Product(id=prod_id, organization_id=org_id, category_id=cat_id, name="Amoxicillin 500mg", sku="AMX-500"))
        db.flush()
        db.add(Batch(
            id=batch_id,
            organization_id=org_id,
            product_id=prod_id,
            batch_number="B-AMX-1",
            expiry_date="2028-01-01",
            received_date="2026-09-26",
            purchase_price=Decimal("150.00"),
        ))
        db.flush()
        db.add(BranchInventory(
            id=str(uuid.uuid4()),
            organization_id=org_id,
            branch_id=branch_id,
            batch_id=batch_id,
            quantity=100,
        ))
        db.flush()
        db.commit()

    sc_svc = StockCountService(db_manager)

    # 1. Start stock count
    sc = sc_svc.start_stock_count(session, count_type="CYCLE_COUNT", notes="Testing cycle count")
    assert sc.status == StockCountStatus.IN_PROGRESS.value

    # 2. Get details
    details = sc_svc.get_stock_count_details(sc.id)
    assert len(details["branch_batches"]) == 1

    # 3. Submit counted quantity (counted 95 instead of 100, variance = -5)
    sub_res = sc_svc.submit_stock_count(
        session,
        stock_count_id=sc.id,
        items=[{"batch_id": batch_id, "counted_quantity": 95}],
    )
    assert sub_res["status"] == StockCountStatus.SUBMITTED.value

    # 4. Approve variance
    det_after_submit = sc_svc.get_stock_count_details(sc.id)
    item_id = det_after_submit["items"][0]["id"]

    appr_res = sc_svc.approve_stock_count(
        session,
        stock_count_id=sc.id,
        reviews=[{"stock_count_item_id": item_id, "action": "APPROVE"}],
    )
    assert appr_res["status"] == StockCountStatus.APPROVED.value

    # Verify inventory was reconciled to 95
    with db_manager.get_session() as db:
        inv = db.query(BranchInventory).filter_by(branch_id=branch_id, batch_id=batch_id).first()
        assert inv.quantity == 95


def test_expenses_workflow(db_manager):
    org_id, branch_id, user_id, cat_id, session = setup_test_environment(db_manager, "EXP1")

    exp_svc = ExpenseService(db_manager)

    cat = exp_svc.create_category(session, "Generator Fuel", "Diesel for branch generator")
    assert cat.name == "Generator Fuel"

    exp = exp_svc.record_expense(
        user_session=session,
        expense_category_id=cat.id,
        description="Purchased 50L diesel",
        amount=Decimal("45000.00"),
        payment_method="CASH",
    )
    assert exp.status == ExpenseStatus.PENDING_APPROVAL.value

    # Approve expense
    appr_exp = exp_svc.approve_expense(session, exp.id)
    assert appr_exp.status == ExpenseStatus.APPROVED.value


def test_stock_transfer_workflow(db_manager):
    org_id, branch_a, user_id, cat_id, session_a = setup_test_environment(db_manager, "TR1")

    branch_b = str(uuid.uuid4())
    prod_id = str(uuid.uuid4())
    batch_id = str(uuid.uuid4())

    with db_manager.get_session() as db:
        db.add(Branch(id=branch_b, organization_id=org_id, name="Branch B", code="TR1_BB"))
        db.flush()
        db.add(Product(id=prod_id, organization_id=org_id, category_id=cat_id, name="Ibuprofen 400mg", sku="IBU-400"))
        db.flush()
        db.add(Batch(
            id=batch_id,
            organization_id=org_id,
            product_id=prod_id,
            batch_number="B-IBU-1",
            expiry_date="2028-01-01",
            received_date="2026-09-26",
            purchase_price=Decimal("120.00"),
        ))
        db.flush()
        db.add(BranchInventory(
            id=str(uuid.uuid4()),
            organization_id=org_id,
            branch_id=branch_a,
            batch_id=batch_id,
            quantity=100,
        ))
        db.flush()
        db.commit()

    xfer_svc = TransferService(db_manager)
    session_b = Session(
        user_id=user_id,
        username="admin_b",
        full_name="Admin Manager",
        organization_id=org_id,
        organization_name="Test Pharmacy Org",
        branch_id=branch_b,
        branch_name="Branch B",
        device_id=session_a.device_id,
        device_code="D1",
        permissions=[p.value for p in PermissionCode],
        roles=[{"name": "Admin"}],
        is_offline=False,
        is_org_admin=True,
    )

    # 1. Create transfer from A to B
    xfer = xfer_svc.create_transfer(
        user_session=session_a,
        destination_branch_id=branch_b,
        items=[{"product_id": prod_id, "batch_id": batch_id, "quantity": 30}],
        notes="Transfer to branch B",
    )
    assert xfer.status == TransferStatus.REQUESTED.value

    # 2. Approve transfer (reserves 30 at Branch A)
    xfer_svc.approve_transfer(session_a, xfer.id)
    with db_manager.get_session() as db:
        inv_a = db.query(BranchInventory).filter_by(branch_id=branch_a, batch_id=batch_id).first()
        assert inv_a.reserved_quantity == 30

    # 3. Dispatch transfer
    xfer_svc.dispatch_transfer(session_a, xfer.id)
    with db_manager.get_session() as db:
        inv_a = db.query(BranchInventory).filter_by(branch_id=branch_a, batch_id=batch_id).first()
        assert inv_a.quantity == 70
        assert inv_a.reserved_quantity == 0

    # 4. Receive transfer at Branch B
    xfer_svc.receive_transfer(session_b, xfer.id)
    with db_manager.get_session() as db:
        inv_b = db.query(BranchInventory).filter_by(branch_id=branch_b, batch_id=batch_id).first()
        assert inv_b is not None
        assert inv_b.quantity == 30


def test_role_permission_matrix_management(db_manager):
    org_id, branch_id, user_id, cat_id, session = setup_test_environment(db_manager, "RPM")
    user_svc = UserService(db_manager)

    # 1. Ensure default pharmacy roles exist
    user_svc.ensure_default_roles(session)
    roles = user_svc.list_roles(session.organization_id)
    assert len(roles) >= 4

    role_names = [r.name for r in roles]
    assert "Pharmacist" in role_names
    assert "Cashier" in role_names
    assert "Inventory Manager" in role_names
    assert "Accountant" in role_names

    cashier_role = next(r for r in roles if r.name == "Cashier")
    cashier_perms = user_svc.get_role_permissions(cashier_role.id)
    assert PermissionCode.SALES_SELL.value in cashier_perms

    # 2. Update Cashier permissions via matrix editor
    updated_perms = [
        PermissionCode.SALES_SELL.value,
        PermissionCode.SALES_RETURN.value,
        PermissionCode.PRODUCTS_VIEW.value,
    ]
    user_svc.update_role_permissions(
        user_session=session,
        role_id=cashier_role.id,
        permission_codes=updated_perms,
        name="Senior Cashier",
        description="Senior sales cashier with return authorization",
    )

    senior_perms = user_svc.get_role_permissions(cashier_role.id)
    assert len(senior_perms) == 3
    assert PermissionCode.SALES_RETURN.value in senior_perms
