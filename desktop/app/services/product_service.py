import json
import uuid
from sqlalchemy import text, or_
from desktop.app.db.models import (
    Category,
    ProductType,
    Manufacturer,
    Supplier,
    Product,
    ProductBranch,
    ProductDocument,
    Branch,
    User,
)
from desktop.app.domain.exceptions import ValidationError
from desktop.app.services.base_service import BaseService
from shared.enums import PermissionCode, AuditAction, SyncOperation, SYNC_DEPENDENCY_LEVELS, SYNC_SCHEMA_VERSION
from desktop.app.db.models import SyncEvent


class ProductService(BaseService):
    """
    Service managing the Product Catalog, Categories, ProductTypes, Manufacturers,
    Suppliers, ProductBranch availability, ProductDocuments, and FTS5 product search.
    """

    def create_category(
        self,
        user_session,
        name: str,
        parent_id: str | None = None,
    ) -> Category:
        self.require_permission(user_session, PermissionCode.PRODUCTS_CREATE.value)
        if not name:
            raise ValidationError("Category name is required.")

        with self.transaction() as db:
            if parent_id:
                parent = (
                    db.query(Category)
                    .filter_by(id=parent_id, organization_id=user_session.organization_id)
                    .first()
                )
                if not parent:
                    raise ValidationError("Parent category not found in your organization.")

            category = Category(
                id=str(uuid.uuid4()),
                organization_id=user_session.organization_id,
                name=name,
                parent_id=parent_id,
                is_active=True,
            )
            db.add(category)
            db.flush()

            payload = {
                "id": category.id,
                "organization_id": category.organization_id,
                "name": category.name,
                "parent_id": category.parent_id,
                "is_active": True,
            }
            self.record_audit_and_sync(
                db_session=db,
                user_session=user_session,
                action=AuditAction.PRODUCT_CREATED.value,
                entity_type="category",
                entity_id=category.id,
                operation=SyncOperation.CREATE.value,
                payload=payload,
            )
            return category

    def list_categories(self, organization_id: str, active_only: bool = True) -> list[Category]:
        with self.transaction() as db:
            q = db.query(Category).filter_by(organization_id=organization_id)
            if active_only:
                q = q.filter_by(is_active=True)
            return q.order_by(Category.name.asc()).all()

    def create_product_type(
        self,
        user_session,
        name: str,
        description: str = "",
    ) -> ProductType:
        self.require_permission(user_session, PermissionCode.PRODUCTS_CREATE.value)
        if not name:
            raise ValidationError("Product type name is required.")

        with self.transaction() as db:
            pt = ProductType(
                id=str(uuid.uuid4()),
                organization_id=user_session.organization_id,
                name=name,
                description=description,
                is_active=True,
            )
            db.add(pt)
            db.flush()

            payload = {
                "id": pt.id,
                "organization_id": pt.organization_id,
                "name": pt.name,
                "description": pt.description,
                "is_active": True,
            }
            self.record_audit_and_sync(
                db_session=db,
                user_session=user_session,
                action=AuditAction.PRODUCT_CREATED.value,
                entity_type="product_type",
                entity_id=pt.id,
                operation=SyncOperation.CREATE.value,
                payload=payload,
            )
            return pt

    def list_product_types(self, organization_id: str, active_only: bool = True) -> list[ProductType]:
        with self.transaction() as db:
            q = db.query(ProductType).filter_by(organization_id=organization_id)
            if active_only:
                q = q.filter_by(is_active=True)
            return q.order_by(ProductType.name.asc()).all()

    def create_manufacturer(
        self,
        user_session,
        name: str,
        country: str = "",
        contact_info: str = "",
    ) -> Manufacturer:
        self.require_permission(user_session, PermissionCode.PRODUCTS_CREATE.value)
        if not name:
            raise ValidationError("Manufacturer name is required.")

        with self.transaction() as db:
            mfg = Manufacturer(
                id=str(uuid.uuid4()),
                organization_id=user_session.organization_id,
                name=name,
                country=country,
                contact_info=contact_info,
                is_active=True,
            )
            db.add(mfg)
            db.flush()

            payload = {
                "id": mfg.id,
                "organization_id": mfg.organization_id,
                "name": mfg.name,
                "country": mfg.country,
                "contact_info": mfg.contact_info,
                "is_active": True,
            }
            self.record_audit_and_sync(
                db_session=db,
                user_session=user_session,
                action=AuditAction.PRODUCT_CREATED.value,
                entity_type="manufacturer",
                entity_id=mfg.id,
                operation=SyncOperation.CREATE.value,
                payload=payload,
            )
            return mfg

    def list_manufacturers(self, organization_id: str, active_only: bool = True) -> list[Manufacturer]:
        with self.transaction() as db:
            q = db.query(Manufacturer).filter_by(organization_id=organization_id)
            if active_only:
                q = q.filter_by(is_active=True)
            return q.order_by(Manufacturer.name.asc()).all()

    def create_supplier(
        self,
        user_session,
        name: str,
        contact_person: str = "",
        phone: str = "",
        email: str = "",
        address: str = "",
        notes: str = "",
    ) -> Supplier:
        self.require_permission(user_session, PermissionCode.SUPPLIERS_MANAGE.value)
        if not name:
            raise ValidationError("Supplier name is required.")

        with self.transaction() as db:
            existing = (
                db.query(Supplier)
                .filter_by(organization_id=user_session.organization_id, name=name)
                .first()
            )
            if existing:
                raise ValidationError(f"Supplier '{name}' already exists.")

            supplier = Supplier(
                id=str(uuid.uuid4()),
                organization_id=user_session.organization_id,
                name=name,
                contact_person=contact_person,
                phone=phone,
                email=email,
                address=address,
                notes=notes,
                is_active=True,
            )
            db.add(supplier)
            db.flush()

            payload = {
                "id": supplier.id,
                "organization_id": supplier.organization_id,
                "name": supplier.name,
                "contact_person": supplier.contact_person,
                "phone": supplier.phone,
                "email": supplier.email,
                "address": supplier.address,
                "notes": supplier.notes,
                "is_active": True,
            }
            self.record_audit_and_sync(
                db_session=db,
                user_session=user_session,
                action=AuditAction.PRODUCT_CREATED.value,
                entity_type="supplier",
                entity_id=supplier.id,
                operation=SyncOperation.CREATE.value,
                payload=payload,
            )
            return supplier

    def list_suppliers(self, organization_id: str, active_only: bool = True) -> list[Supplier]:
        with self.transaction() as db:
            q = db.query(Supplier).filter_by(organization_id=organization_id)
            if active_only:
                q = q.filter_by(is_active=True)
            return q.order_by(Supplier.name.asc()).all()

    def create_product(
        self,
        user_session,
        sku: str,
        name: str,
        category_id: str,
        barcode: str | None = None,
        generic_name: str | None = None,
        brand_name: str | None = None,
        product_type_id: str | None = None,
        manufacturer_id: str | None = None,
        description: str = "",
        branch_ids: list[str] | None = None,
        select_all_branches: bool = False,
        **pharmaceutical_kwargs,
    ) -> Product:
        self.require_permission(user_session, PermissionCode.PRODUCTS_CREATE.value)
        if not sku or not name or not category_id:
            raise ValidationError("SKU, product name, and category are required.")

        with self.transaction() as db:
            existing_sku = (
                db.query(Product)
                .filter_by(organization_id=user_session.organization_id, sku=sku)
                .first()
            )
            if existing_sku:
                raise ValidationError(f"Product SKU '{sku}' already exists.")

            cat = (
                db.query(Category)
                .filter_by(id=category_id, organization_id=user_session.organization_id)
                .first()
            )
            if not cat:
                raise ValidationError("Category not found in your organization.")

            corr_id = str(uuid.uuid4())
            product = Product(
                id=str(uuid.uuid4()),
                organization_id=user_session.organization_id,
                sku=sku,
                barcode=barcode,
                name=name,
                generic_name=generic_name,
                brand_name=brand_name,
                category_id=category_id,
                product_type_id=product_type_id,
                manufacturer_id=manufacturer_id,
                description=description,
                is_active=True,
                **pharmaceutical_kwargs,
            )
            db.add(product)
            db.flush()

            # Resolve target branches for ProductBranch opt-in records
            target_branches = []
            if select_all_branches:
                target_branches = (
                    db.query(Branch)
                    .filter_by(organization_id=user_session.organization_id, is_active=True)
                    .all()
                )
            elif branch_ids:
                target_branches = (
                    db.query(Branch)
                    .filter(
                        Branch.organization_id == user_session.organization_id,
                        Branch.id.in_(branch_ids),
                    )
                    .all()
                )

            assigned_branch_ids = []
            for br in target_branches:
                pb = ProductBranch(
                    id=str(uuid.uuid4()),
                    product_id=product.id,
                    branch_id=br.id,
                    is_active=True,
                )
                db.add(pb)
                db.flush()
                assigned_branch_ids.append(br.id)

                pb_sync = SyncEvent(
                    id=str(uuid.uuid4()),
                    branch_id=user_session.branch_id or br.id,
                    device_id=user_session.device_id or "00000000-0000-0000-0000-000000000000",
                    entity_type="product_branch",
                    entity_id=pb.id,
                    operation=SyncOperation.CREATE.value,
                    payload=json.dumps({
                        "id": pb.id,
                        "product_id": pb.product_id,
                        "branch_id": pb.branch_id,
                        "is_active": True,
                    }),
                    correlation_id=corr_id,
                    dependency_level=SYNC_DEPENDENCY_LEVELS["product_branch"],
                    schema_version=SYNC_SCHEMA_VERSION,
                    status="PENDING",
                )
                db.add(pb_sync)

            payload = {
                "id": product.id,
                "organization_id": product.organization_id,
                "sku": product.sku,
                "barcode": product.barcode,
                "name": product.name,
                "generic_name": product.generic_name,
                "brand_name": product.brand_name,
                "category_id": product.category_id,
                "product_type_id": product.product_type_id,
                "manufacturer_id": product.manufacturer_id,
                "description": product.description,
                "branch_ids": assigned_branch_ids,
                "is_active": True,
            }
            self.record_audit_and_sync(
                db_session=db,
                user_session=user_session,
                action=AuditAction.PRODUCT_CREATED.value,
                entity_type="product",
                entity_id=product.id,
                operation=SyncOperation.CREATE.value,
                payload=payload,
                correlation_id=corr_id,
            )
            return product

    def update_product(self, user_session, product_id: str, **updates) -> Product:
        self.require_permission(user_session, PermissionCode.PRODUCTS_EDIT.value)
        with self.transaction() as db:
            product = (
                db.query(Product)
                .filter_by(id=product_id, organization_id=user_session.organization_id)
                .first()
            )
            if not product:
                raise ValidationError("Product not found.")

            before_data = {
                "name": product.name,
                "sku": product.sku,
                "barcode": product.barcode,
                "generic_name": product.generic_name,
                "brand_name": product.brand_name,
                "is_active": product.is_active,
            }
            for k, v in updates.items():
                if hasattr(product, k):
                    setattr(product, k, v)
            db.flush()

            after_data = {
                "id": product.id,
                "organization_id": product.organization_id,
                "name": product.name,
                "sku": product.sku,
                "barcode": product.barcode,
                "generic_name": product.generic_name,
                "brand_name": product.brand_name,
                "category_id": product.category_id,
                "is_active": product.is_active,
            }
            self.record_audit_and_sync(
                db_session=db,
                user_session=user_session,
                action=AuditAction.PRODUCT_UPDATED.value,
                entity_type="product",
                entity_id=product.id,
                operation=SyncOperation.UPDATE.value,
                payload=after_data,
                data_before=before_data,
                data_after=after_data,
            )
            return product

    def assign_product_to_branches(
        self, user_session, product_id: str, branch_ids: list[str]
    ) -> list[ProductBranch]:
        self.require_permission(user_session, PermissionCode.PRODUCTS_EDIT.value)
        with self.transaction() as db:
            product = (
                db.query(Product)
                .filter_by(id=product_id, organization_id=user_session.organization_id)
                .first()
            )
            if not product:
                raise ValidationError("Product not found.")

            result = []
            for bid in branch_ids:
                pb = (
                    db.query(ProductBranch)
                    .filter_by(product_id=product_id, branch_id=bid)
                    .first()
                )
                if not pb:
                    pb = ProductBranch(
                        id=str(uuid.uuid4()),
                        product_id=product_id,
                        branch_id=bid,
                        is_active=True,
                    )
                    db.add(pb)
                else:
                    pb.is_active = True
                db.flush()
                result.append(pb)
            return result

    def add_product_document(
        self,
        user_session,
        product_id: str,
        name: str,
        file_path: str,
        document_type: str = "",
    ) -> ProductDocument:
        self.require_permission(user_session, PermissionCode.PRODUCTS_EDIT.value)
        with self.transaction() as db:
            uploader_exists = (
                db.query(User).filter_by(id=user_session.user_id).first() is not None
            )
            doc = ProductDocument(
                id=str(uuid.uuid4()),
                product_id=product_id,
                name=name,
                file_path=file_path,
                document_type=document_type,
                uploaded_by_id=user_session.user_id if uploader_exists else None,
            )
            db.add(doc)
            db.flush()
            return doc

    def search_products(
        self,
        organization_id: str,
        query: str = "",
        branch_id: str | None = None,
        barcode: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Product]:
        """
        Fast product search using SQLite FTS5 virtual table (`products_fts`) or exact barcode index,
        with optional branch availability (`ProductBranch`) scoping.
        """
        with self.transaction() as db:
            q = db.query(Product).filter(
                Product.organization_id == organization_id,
                Product.is_active.is_(True),
            )
            if branch_id:
                q = q.join(
                    ProductBranch,
                    (ProductBranch.product_id == Product.id)
                    & (ProductBranch.branch_id == branch_id)
                    & (ProductBranch.is_active.is_(True)),
                )
            if barcode:
                q = q.filter(Product.barcode == barcode)
            elif query and query.strip():
                clean_q = query.strip()
                matched_ids = []
                clean_tokens = [
                    tok.replace('"', '').strip()
                    for tok in clean_q.split()
                    if tok.replace('"', '').strip()
                ]
                if clean_tokens:
                    try:
                        fts_expr = " AND ".join(f'"{t}"*' for t in clean_tokens)
                        matched_rows = db.execute(
                            text(
                                "SELECT product_id FROM products_fts WHERE organization_id = :org_id AND products_fts MATCH :expr"
                            ),
                            {"org_id": organization_id, "expr": fts_expr},
                        ).fetchall()
                        matched_ids = [r[0] for r in matched_rows]
                    except Exception:
                        matched_ids = []

                if matched_ids:
                    q = q.filter(Product.id.in_(matched_ids))
                else:
                    # Fallback to robust SQL ILIKE search on SKU, name, barcode, generic name
                    like_pattern = f"%{clean_q}%"
                    q = q.filter(
                        or_(
                            Product.name.ilike(like_pattern),
                            Product.sku.ilike(like_pattern),
                            Product.barcode.ilike(like_pattern),
                            Product.generic_name.ilike(like_pattern),
                            Product.brand_name.ilike(like_pattern),
                        )
                    )

            return q.order_by(Product.name.asc()).offset(offset).limit(limit).all()

    def delete_product(self, user_session, product_id: str) -> Product:
        self.require_permission(user_session, PermissionCode.PRODUCTS_DELETE.value)
        with self.transaction() as db:
            product = (
                db.query(Product)
                .filter_by(id=product_id, organization_id=user_session.organization_id)
                .first()
            )
            if not product:
                raise ValidationError("Product not found.")
            product.is_active = False
            db.flush()

            self.record_audit_and_sync(
                db_session=db,
                user_session=user_session,
                action=AuditAction.PRODUCT_UPDATED.value,
                entity_type="product",
                entity_id=product.id,
                operation=SyncOperation.UPDATE.value,
                payload={"id": product.id, "is_active": False},
            )
            return product

    def update_category(self, user_session, category_id: str, name: str) -> Category:
        self.require_permission(user_session, PermissionCode.PRODUCTS_EDIT.value)
        if not name or not name.strip():
            raise ValidationError("Category name is required.")
        with self.transaction() as db:
            cat = (
                db.query(Category)
                .filter_by(id=category_id, organization_id=user_session.organization_id)
                .first()
            )
            if not cat:
                raise ValidationError("Category not found.")
            cat.name = name.strip()
            db.flush()
            self.record_audit_and_sync(
                db_session=db,
                user_session=user_session,
                action=AuditAction.PRODUCT_UPDATED.value,
                entity_type="category",
                entity_id=cat.id,
                operation=SyncOperation.UPDATE.value,
                payload={"id": cat.id, "name": cat.name},
            )
            return cat

    def delete_category(self, user_session, category_id: str) -> Category:
        self.require_permission(user_session, PermissionCode.PRODUCTS_DELETE.value)
        with self.transaction() as db:
            cat = (
                db.query(Category)
                .filter_by(id=category_id, organization_id=user_session.organization_id)
                .first()
            )
            if not cat:
                raise ValidationError("Category not found.")
            cat.is_active = False
            db.flush()
            self.record_audit_and_sync(
                db_session=db,
                user_session=user_session,
                action=AuditAction.PRODUCT_UPDATED.value,
                entity_type="category",
                entity_id=cat.id,
                operation=SyncOperation.UPDATE.value,
                payload={"id": cat.id, "is_active": False},
            )
            return cat

    def update_supplier(
        self,
        user_session,
        supplier_id: str,
        name: str,
        contact_person: str = "",
        phone: str = "",
        email: str = "",
        address: str = "",
    ) -> Supplier:
        self.require_permission(user_session, PermissionCode.SUPPLIERS_MANAGE.value)
        if not name or not name.strip():
            raise ValidationError("Supplier name is required.")
        with self.transaction() as db:
            sup = (
                db.query(Supplier)
                .filter_by(id=supplier_id, organization_id=user_session.organization_id)
                .first()
            )
            if not sup:
                raise ValidationError("Supplier not found.")
            sup.name = name.strip()
            sup.contact_person = contact_person.strip()
            sup.phone = phone.strip()
            sup.email = email.strip()
            sup.address = address.strip()
            db.flush()
            self.record_audit_and_sync(
                db_session=db,
                user_session=user_session,
                action=AuditAction.PRODUCT_UPDATED.value,
                entity_type="supplier",
                entity_id=sup.id,
                operation=SyncOperation.UPDATE.value,
                payload={
                    "id": sup.id,
                    "name": sup.name,
                    "contact_person": sup.contact_person,
                    "phone": sup.phone,
                    "email": sup.email,
                },
            )
            return sup

    def delete_supplier(self, user_session, supplier_id: str) -> Supplier:
        self.require_permission(user_session, PermissionCode.SUPPLIERS_MANAGE.value)
        with self.transaction() as db:
            sup = (
                db.query(Supplier)
                .filter_by(id=supplier_id, organization_id=user_session.organization_id)
                .first()
            )
            if not sup:
                raise ValidationError("Supplier not found.")
            sup.is_active = False
            db.flush()
            self.record_audit_and_sync(
                db_session=db,
                user_session=user_session,
                action=AuditAction.PRODUCT_UPDATED.value,
                entity_type="supplier",
                entity_id=sup.id,
                operation=SyncOperation.UPDATE.value,
                payload={"id": sup.id, "is_active": False},
            )
            return sup
