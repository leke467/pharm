from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    CategoryViewSet,
    ProductTypeViewSet,
    ManufacturerViewSet,
    SupplierViewSet,
    ProductViewSet,
    ProductBranchViewSet,
    ProductDocumentViewSet,
)

router = DefaultRouter()
router.register(r'categories', CategoryViewSet, basename='category')
router.register(r'product-types', ProductTypeViewSet, basename='product-type')
router.register(r'manufacturers', ManufacturerViewSet, basename='manufacturer')
router.register(r'suppliers', SupplierViewSet, basename='supplier')
router.register(r'products', ProductViewSet, basename='product')
router.register(r'product-branches', ProductBranchViewSet, basename='product-branch')
router.register(r'product-documents', ProductDocumentViewSet, basename='product-document')

urlpatterns = [
    path('', include(router.urls)),
]
