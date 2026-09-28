import pytest
from django.urls import reverse
from apps.branches.models import Branch
from apps.products.models import Category, Product
from apps.users.services import seed_permissions_and_roles


@pytest.mark.django_db
class TestPhase3Acceptance:
    """Phase 3 Acceptance Tests: Product Catalog, Categories, Suppliers, and Branch Availability."""

    def test_category_hierarchy_and_supplier_crud(
        self, authenticated_client, staff_client, test_organization
    ):
        seed_permissions_and_roles(test_organization)

        # Parent category
        parent_res = authenticated_client.post(
            reverse('category-list'), {'name': 'Medications'}
        )
        assert parent_res.status_code == 201
        parent_id = parent_res.data['id']

        # Child category
        child_res = authenticated_client.post(
            reverse('category-list'),
            {'name': 'Antibiotics', 'parent': parent_id},
        )
        assert child_res.status_code == 201
        assert str(child_res.data['parent']) == parent_id

        # Supplier CRUD + RBAC check
        assert (
            staff_client.post(reverse('supplier-list'), {'name': 'Forbidden Supplier'}).status_code
            == 403
        )
        sup_res = authenticated_client.post(
            reverse('supplier-list'),
            {
                'name': 'Emzor Pharma Distributors',
                'contact_person': 'Chidi',
                'phone': '+2348011112222',
            },
        )
        assert sup_res.status_code == 201
        assert sup_res.data['name'] == 'Emzor Pharma Distributors'

    def test_pharmaceutical_and_non_drug_products_with_branch_opt_in(
        self, authenticated_client, test_organization
    ):
        branch_a = Branch.objects.create(
            organization=test_organization, name='Ikeja Branch', code='IKJ'
        )
        branch_b = Branch.objects.create(
            organization=test_organization, name='Lekki Branch', code='LEK'
        )
        cat = Category.objects.create(organization=test_organization, name='General')

        # 1. Pharmaceutical product assigned to ALL branches
        drug_res = authenticated_client.post(
            reverse('product-list'),
            {
                'sku': 'DRG-AMOX-500',
                'barcode': '6151100012345',
                'name': 'Amoxil 500mg Capsules',
                'generic_name': 'Amoxicillin Trihydrate',
                'brand_name': 'Amoxil',
                'category': str(cat.id),
                'active_ingredients': 'Amoxicillin 500mg',
                'strength': '500mg',
                'dosage_form': 'Capsule',
                'route': 'Oral',
                'prescription_required': True,
                'pregnancy_caution': False,
                'select_all_branches': True,
            },
            format='json',
        )
        assert drug_res.status_code == 201
        assert set(drug_res.data['active_branch_ids']) == {str(branch_a.id), str(branch_b.id)}

        # 2. Cosmetic product (all pharmaceutical fields null) assigned ONLY to Branch A
        cosmetic_res = authenticated_client.post(
            reverse('product-list'),
            {
                'sku': 'COS-SHEA-200',
                'barcode': '6151100099999',
                'name': 'Pure Shea Body Lotion 200ml',
                'category': str(cat.id),
                'branch_ids': [str(branch_a.id)],
            },
            format='json',
        )
        assert cosmetic_res.status_code == 201
        assert cosmetic_res.data['active_ingredients'] is None
        assert cosmetic_res.data['active_branch_ids'] == [str(branch_a.id)]

        # 3. Branch-scoped product query: Branch A sees 2 products, Branch B sees 1 product
        res_branch_a = authenticated_client.get(
            reverse('product-list'), {'branch_id': str(branch_a.id)}
        )
        assert res_branch_a.status_code == 200
        assert len(res_branch_a.data['results']) == 2

        res_branch_b = authenticated_client.get(
            reverse('product-list'), {'branch_id': str(branch_b.id)}
        )
        assert res_branch_b.status_code == 200
        assert len(res_branch_b.data['results']) == 1
        assert res_branch_b.data['results'][0]['sku'] == 'DRG-AMOX-500'

        # 4. Barcode lookup and search
        barcode_res = authenticated_client.get(
            reverse('product-list'), {'barcode': '6151100099999'}
        )
        assert len(barcode_res.data['results']) == 1
        assert barcode_res.data['results'][0]['sku'] == 'COS-SHEA-200'

        search_res = authenticated_client.get(
            reverse('product-list'), {'search': 'Amoxicillin'}
        )
        assert len(search_res.data['results']) == 1
        assert search_res.data['results'][0]['sku'] == 'DRG-AMOX-500'

    def test_product_tenant_isolation(
        self, authenticated_client, other_organization
    ):
        other_cat = Category.objects.create(organization=other_organization, name='Other Cat')
        other_prod = Product.objects.create(
            organization=other_organization,
            sku='OTH-001',
            name='Other Org Drug',
            category=other_cat,
        )

        res = authenticated_client.get(reverse('product-list'))
        assert len(res.data['results']) == 0

        detail_res = authenticated_client.get(
            reverse('product-detail', kwargs={'pk': other_prod.id})
        )
        assert detail_res.status_code == 404
