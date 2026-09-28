from datetime import datetime, timezone
import pytest
from desktop.app.auth.session import Session
from desktop.app.db.models import Organization, Branch, SyncEvent
from desktop.app.domain.exceptions import PermissionDeniedError
from desktop.app.services.product_service import ProductService
from shared.enums import PermissionCode


def _make_session(org_id: str, perms: list[str], is_admin: bool = False) -> Session:
    return Session(
        user_id="u-prod-1",
        username="pharmacist",
        full_name="Pharmacist User",
        organization_id=org_id,
        organization_name="Prime Pharmacy",
        branch_id="",
        branch_name="",
        device_id="dev-1",
        device_code="D1",
        permissions=perms,
        roles=[],
        is_offline=True,
        is_org_admin=is_admin,
        logged_in_at=datetime.now(timezone.utc).isoformat(),
    )


def test_desktop_product_catalog_fts5_search_and_branch_availability(db_manager):
    svc = ProductService(db_manager)

    with db_manager.get_session() as db:
        org = Organization(id="org-p3", name="Prime Pharmacy", code="PRIME")
        db.add(org)
        db.flush()
        b1 = Branch(id="br-p3-1", organization_id="org-p3", name="Branch 1", code="B1")
        b2 = Branch(id="br-p3-2", organization_id="org-p3", name="Branch 2", code="B2")
        db.add_all([b1, b2])

    admin_sess = _make_session("org-p3", [p.value for p in PermissionCode], is_admin=True)
    readonly_sess = _make_session("org-p3", [PermissionCode.PRODUCTS_VIEW.value])

    # 1. Read-only user cannot create categories, suppliers, or products
    with pytest.raises(PermissionDeniedError):
        svc.create_category(readonly_sess, name="Analgesics")

    # 2. Admin creates Category, ProductType, Manufacturer, Supplier
    cat = svc.create_category(admin_sess, name="Analgesics")
    pt = svc.create_product_type(admin_sess, name="Medicine", description="Pharmaceuticals")
    mfg = svc.create_manufacturer(admin_sess, name="Emzor", country="Nigeria")
    sup = svc.create_supplier(
        admin_sess,
        name="Prime Meds Ltd",
        contact_person="Bola",
        phone="08030000000",
    )
    assert sup.name == "Prime Meds Ltd"

    # 3. Create pharmaceutical product for all branches & cosmetic product for Branch 1 only
    p1 = svc.create_product(
        admin_sess,
        sku="PCM-500",
        barcode="8901112223334",
        name="Emzor Paracetamol 500mg Tablets",
        generic_name="Acetaminophen",
        brand_name="Emzor",
        category_id=cat.id,
        product_type_id=pt.id,
        manufacturer_id=mfg.id,
        strength="500mg",
        dosage_form="Tablet",
        select_all_branches=True,
    )
    p2 = svc.create_product(
        admin_sess,
        sku="VIT-C-100",
        barcode="8901112229999",
        name="Ascorbic Acid Syrup 100ml",
        generic_name="Vitamin C",
        category_id=cat.id,
        branch_ids=["br-p3-1"],
    )

    # 4. FTS5 search by generic name, brand/product name, SKU, and barcode
    by_generic = svc.search_products("org-p3", query="Acetamin")
    assert len(by_generic) == 1
    assert by_generic[0].id == p1.id

    by_barcode = svc.search_products("org-p3", barcode="8901112229999")
    assert len(by_barcode) == 1
    assert by_barcode[0].id == p2.id

    # 5. Branch availability filtering (Branch 1 has 2 products; Branch 2 has 1 product)
    b1_prods = svc.search_products("org-p3", branch_id="br-p3-1")
    assert len(b1_prods) == 2

    b2_prods = svc.search_products("org-p3", branch_id="br-p3-2")
    assert len(b2_prods) == 1
    assert b2_prods[0].id == p1.id

    # 6. Updating product updates FTS5 index
    svc.update_product(admin_sess, p2.id, generic_name="Sodium Ascorbate")
    updated_fts = svc.search_products("org-p3", query="Ascorbate")
    assert len(updated_fts) == 1
    assert updated_fts[0].id == p2.id

    # 7. Correlated SyncEvents check for p1 (product + 2 product_branches + audit_event share correlation_id)
    with db_manager.get_session() as db:
        prod_sync = (
            db.query(SyncEvent)
            .filter_by(entity_type="product", entity_id=p1.id)
            .first()
        )
        assert prod_sync is not None
        correlated = (
            db.query(SyncEvent)
            .filter_by(correlation_id=prod_sync.correlation_id)
            .all()
        )
        # 1 product + 2 product_branches + 1 audit_event = 4 events in correlation group
        assert len(correlated) == 4
