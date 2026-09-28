import uuid
from django.db.models import Q
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.permissions import IsAuthenticated, SAFE_METHODS
from apps.audit.models import AuditEvent
from apps.core.mixins import OrganizationQuerysetMixin
from apps.core.permissions import IsOrganizationMember, require_permission, user_has_permission
from shared.enums import PermissionCode, AuditAction, AuditSource
from .models import (
    Category,
    ProductType,
    Manufacturer,
    Supplier,
    Product,
    ProductBranch,
    ProductDocument,
)
from .serializers import (
    CategorySerializer,
    ProductTypeSerializer,
    ManufacturerSerializer,
    SupplierSerializer,
    ProductSerializer,
    ProductBranchSerializer,
    ProductDocumentSerializer,
)


class CategoryViewSet(OrganizationQuerysetMixin, viewsets.ModelViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    permission_classes = [
        IsAuthenticated,
        IsOrganizationMember,
        require_permission(
            read_perm=PermissionCode.PRODUCTS_VIEW.value,
            write_perm=PermissionCode.PRODUCTS_CREATE.value,
        ),
    ]

    def perform_create(self, serializer):
        org_id = self.get_organization_id()
        parent = serializer.validated_data.get('parent')
        if parent and parent.organization_id != org_id:
            raise DRFValidationError("Parent category must belong to your organization.")
        serializer.save(organization_id=org_id)


class ProductTypeViewSet(OrganizationQuerysetMixin, viewsets.ModelViewSet):
    queryset = ProductType.objects.all()
    serializer_class = ProductTypeSerializer
    permission_classes = [
        IsAuthenticated,
        IsOrganizationMember,
        require_permission(
            read_perm=PermissionCode.PRODUCTS_VIEW.value,
            write_perm=PermissionCode.PRODUCTS_CREATE.value,
        ),
    ]


class ManufacturerViewSet(OrganizationQuerysetMixin, viewsets.ModelViewSet):
    queryset = Manufacturer.objects.all()
    serializer_class = ManufacturerSerializer
    permission_classes = [
        IsAuthenticated,
        IsOrganizationMember,
        require_permission(
            read_perm=PermissionCode.PRODUCTS_VIEW.value,
            write_perm=PermissionCode.PRODUCTS_CREATE.value,
        ),
    ]


class SupplierViewSet(OrganizationQuerysetMixin, viewsets.ModelViewSet):
    queryset = Supplier.objects.all()
    serializer_class = SupplierSerializer
    permission_classes = [
        IsAuthenticated,
        IsOrganizationMember,
        require_permission(
            read_perm=PermissionCode.PRODUCTS_VIEW.value,
            write_perm=PermissionCode.SUPPLIERS_MANAGE.value,
        ),
    ]


class ProductPermission(IsOrganizationMember):
    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        if request.method in SAFE_METHODS:
            return user_has_permission(request.user, PermissionCode.PRODUCTS_VIEW.value)
        if request.method == 'POST':
            return user_has_permission(request.user, PermissionCode.PRODUCTS_CREATE.value)
        if request.method in ('PUT', 'PATCH'):
            return user_has_permission(request.user, PermissionCode.PRODUCTS_EDIT.value)
        if request.method == 'DELETE':
            return user_has_permission(request.user, PermissionCode.PRODUCTS_DELETE.value)
        return False


class ProductViewSet(OrganizationQuerysetMixin, viewsets.ModelViewSet):
    queryset = Product.objects.all()
    serializer_class = ProductSerializer
    permission_classes = [IsAuthenticated, ProductPermission]

    def get_queryset(self):
        qs = super().get_queryset()
        search = self.request.query_params.get('search')
        barcode = self.request.query_params.get('barcode')
        sku = self.request.query_params.get('sku')
        branch_id = self.request.query_params.get('branch_id')
        category_id = self.request.query_params.get('category_id')
        active_only = self.request.query_params.get('active_only', 'true').lower() == 'true'

        if active_only and self.action == 'list':
            qs = qs.filter(is_active=True)
        if barcode:
            qs = qs.filter(barcode=barcode)
        if sku:
            qs = qs.filter(sku=sku)
        if category_id:
            qs = qs.filter(category_id=category_id)
        if branch_id:
            qs = qs.filter(
                product_branches__branch_id=branch_id,
                product_branches__is_active=True,
            ).distinct()
        if search:
            qs = qs.filter(
                Q(name__icontains=search)
                | Q(generic_name__icontains=search)
                | Q(brand_name__icontains=search)
                | Q(sku__icontains=search)
                | Q(barcode__icontains=search)
            )
        return qs

    def _validate_foreign_keys(self, serializer, org_id):
        category = serializer.validated_data.get('category')
        if category and category.organization_id != org_id:
            raise DRFValidationError("Category must belong to your organization.")
        product_type = serializer.validated_data.get('product_type')
        if product_type and product_type.organization_id != org_id:
            raise DRFValidationError("ProductType must belong to your organization.")
        manufacturer = serializer.validated_data.get('manufacturer')
        if manufacturer and manufacturer.organization_id != org_id:
            raise DRFValidationError("Manufacturer must belong to your organization.")

    def perform_create(self, serializer):
        org_id = self.get_organization_id()
        self._validate_foreign_keys(serializer, org_id)
        product = serializer.save(organization_id=org_id)
        now = timezone.now()
        AuditEvent.objects.create(
            organization_id=org_id,
            branch_id=self.request.user.default_branch_id or uuid.UUID(int=0),
            user_id=self.request.user.id,
            action=AuditAction.PRODUCT_CREATED.value,
            entity_type='product',
            entity_id=product.id,
            data_after=ProductSerializer(product).data,
            local_timestamp=now,
            server_timestamp=now,
            is_offline=False,
            source=AuditSource.SERVER.value,
        )

    def perform_update(self, serializer):
        org_id = self.get_organization_id()
        self._validate_foreign_keys(serializer, org_id)
        before_data = ProductSerializer(serializer.instance).data
        product = serializer.save()
        now = timezone.now()
        AuditEvent.objects.create(
            organization_id=org_id,
            branch_id=self.request.user.default_branch_id or uuid.UUID(int=0),
            user_id=self.request.user.id,
            action=AuditAction.PRODUCT_UPDATED.value,
            entity_type='product',
            entity_id=product.id,
            data_before=before_data,
            data_after=ProductSerializer(product).data,
            local_timestamp=now,
            server_timestamp=now,
            is_offline=False,
            source=AuditSource.SERVER.value,
        )


class ProductBranchViewSet(viewsets.ModelViewSet):
    queryset = ProductBranch.objects.all()
    serializer_class = ProductBranchSerializer
    permission_classes = [
        IsAuthenticated,
        IsOrganizationMember,
        require_permission(
            read_perm=PermissionCode.PRODUCTS_VIEW.value,
            write_perm=PermissionCode.PRODUCTS_EDIT.value,
        ),
    ]

    def get_organization_id(self):
        return getattr(self.request, 'organization_id', None) or getattr(
            self.request.user, 'organization_id', None
        )

    def get_queryset(self):
        org_id = self.get_organization_id()
        if not org_id:
            return ProductBranch.objects.none()
        qs = ProductBranch.objects.filter(product__organization_id=org_id)
        branch_id = self.request.query_params.get('branch_id')
        product_id = self.request.query_params.get('product_id')
        if branch_id:
            qs = qs.filter(branch_id=branch_id)
        if product_id:
            qs = qs.filter(product_id=product_id)
        return qs

    def perform_create(self, serializer):
        org_id = self.get_organization_id()
        product = serializer.validated_data['product']
        branch = serializer.validated_data['branch']
        if product.organization_id != org_id or branch.organization_id != org_id:
            raise DRFValidationError("Product and Branch must belong to your organization.")
        serializer.save()


class ProductDocumentViewSet(viewsets.ModelViewSet):
    queryset = ProductDocument.objects.all()
    serializer_class = ProductDocumentSerializer
    permission_classes = [
        IsAuthenticated,
        IsOrganizationMember,
        require_permission(
            read_perm=PermissionCode.PRODUCTS_VIEW.value,
            write_perm=PermissionCode.PRODUCTS_EDIT.value,
        ),
    ]

    def get_organization_id(self):
        return getattr(self.request, 'organization_id', None) or getattr(
            self.request.user, 'organization_id', None
        )

    def get_queryset(self):
        org_id = self.get_organization_id()
        if not org_id:
            return ProductDocument.objects.none()
        qs = ProductDocument.objects.filter(product__organization_id=org_id)
        product_id = self.request.query_params.get('product_id')
        if product_id:
            qs = qs.filter(product_id=product_id)
        return qs

    def perform_create(self, serializer):
        org_id = self.get_organization_id()
        product = serializer.validated_data['product']
        if product.organization_id != org_id:
            raise DRFValidationError("Product must belong to your organization.")
        serializer.save(uploaded_by=self.request.user)
