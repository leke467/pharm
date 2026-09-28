import uuid
from decimal import Decimal
import pytest
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from apps.branches.models import Branch, Device
from apps.organizations.models import Organization
from apps.products.models import Product, Category, ProductType
from apps.pricing.models import Price, PriceHistory
from apps.pricing.views import resolve_product_price
from apps.users.models import User
from shared.enums import SyncOperation, PermissionCode


@pytest.mark.django_db
class TestPhase11ServerPricingAcceptance:
    @pytest.fixture
    def setup_data(self):
        org = Organization.objects.create(name="Pricing Org", code="PORG")
        branch_a = Branch.objects.create(organization=org, name="Branch A", code="BRA")
        branch_b = Branch.objects.create(organization=org, name="Branch B", code="BRB")

        user = User.objects.create_user(
            username="pricingadmin",
            organization_id=org.id,
            password="adminpassword123",
            full_name="Pricing Admin",
            is_org_admin=True,
        )

        cat = Category.objects.create(organization=org, name="Analgesics")
        ptype = ProductType.objects.create(organization=org, name="Caplet")
        product = Product.objects.create(
            organization=org,
            category=cat,
            product_type=ptype,
            name="Paracetamol 500mg",
            sku="PARA-500",
        )

        client = APIClient()
        client.force_authenticate(user=user)

        return {
            'org': org,
            'branch_a': branch_a,
            'branch_b': branch_b,
            'user': user,
            'product': product,
            'client': client,
        }

    def test_price_versioning_and_history_generation(self, setup_data):
        client = setup_data['client']
        product = setup_data['product']

        # 1. Create initial org-wide price
        url = "/api/v1/prices/"
        p1_data = {
            "product": str(product.id),
            "selling_price": "500.00",
            "currency": "NGN",
            "change_reason": "Initial launch price",
        }
        res1 = client.post(url, p1_data, format="json")
        assert res1.status_code == status.HTTP_201_CREATED, res1.data
        price1_id = res1.data['id']
        assert res1.data['version'] == 1
        assert res1.data['is_current'] is True
        assert res1.data['selling_price'] == "500.00"

        # Check PriceHistory entry created
        h1 = PriceHistory.objects.filter(price_id=price1_id).first()
        assert h1 is not None
        assert h1.version == 1
        assert h1.old_price is None
        assert h1.new_price == Decimal("500.00")
        assert h1.change_reason == "Initial launch price"

        # 2. Update price for the same product (org-wide)
        p2_data = {
            "product": str(product.id),
            "selling_price": "600.00",
            "currency": "NGN",
            "change_reason": "Price hike due to inflation",
        }
        res2 = client.post(url, p2_data, format="json")
        assert res2.status_code == status.HTTP_201_CREATED, res2.data
        price2_id = res2.data['id']
        assert res2.data['version'] == 2
        assert res2.data['is_current'] is True
        assert res2.data['selling_price'] == "600.00"

        # Verify previous price is now is_current=False
        old_price = Price.objects.get(id=price1_id)
        assert old_price.is_current is False
        assert old_price.effective_to is not None

        # Verify second PriceHistory entry
        h2 = PriceHistory.objects.filter(price_id=price2_id).first()
        assert h2 is not None
        assert h2.version == 2
        assert h2.old_price == Decimal("500.00")
        assert h2.new_price == Decimal("600.00")
        assert h2.change_reason == "Price hike due to inflation"

        # 3. Query price history endpoint
        hist_resp = client.get(f"/api/v1/price-history/?product_id={product.id}")
        assert hist_resp.status_code == status.HTTP_200_OK
        results = hist_resp.data['results'] if 'results' in hist_resp.data else hist_resp.data
        assert len(results) == 2
        versions = [r['version'] for r in results]
        assert 1 in versions and 2 in versions

        # 4. Check price detail history action
        action_hist = client.get(f"/api/v1/prices/{price2_id}/history/")
        assert action_hist.status_code == status.HTTP_200_OK
        assert len(action_hist.data) == 2

    def test_force_all_branches_operation(self, setup_data):
        client = setup_data['client']
        product = setup_data['product']
        branch_a = setup_data['branch_a']
        branch_b = setup_data['branch_b']
        org = setup_data['org']

        # 1. Create org-wide default price: NGN 1000.00
        res_org = client.post("/api/v1/prices/", {
            "product": str(product.id),
            "selling_price": "1000.00",
            "currency": "NGN",
        }, format="json")
        assert res_org.status_code == status.HTTP_201_CREATED
        org_price_id = res_org.data['id']

        # 2. Create branch override for Branch A: NGN 1200.00
        res_bra = client.post("/api/v1/prices/", {
            "product": str(product.id),
            "branch": str(branch_a.id),
            "selling_price": "1200.00",
            "currency": "NGN",
        }, format="json")
        assert res_bra.status_code == status.HTTP_201_CREATED
        bra_price_id = res_bra.data['id']

        # Verify resolution before force:
        # Branch A gets override (1200.00)
        # Branch B gets org default (1000.00)
        resolved_a = resolve_product_price(org.id, product.id, branch_a.id)
        assert resolved_a.selling_price == Decimal("1200.00")
        assert resolved_a.branch_id == branch_a.id

        resolved_b = resolve_product_price(org.id, product.id, branch_b.id)
        assert resolved_b.selling_price == Decimal("1000.00")
        assert resolved_b.branch_id is None

        # 3. Force all branches on org price:
        force_resp = client.post(f"/api/v1/prices/{org_price_id}/force-all-branches/", {
            "change_reason": "Standardizing national price",
        }, format="json")
        assert force_resp.status_code == status.HTTP_200_OK
        assert "retired" in force_resp.data['message']

        # Verify Branch A's override is retired!
        bra_price = Price.objects.get(id=bra_price_id)
        assert bra_price.is_current is False

        # Now Branch A resolves to the org default price!
        resolved_a_after = resolve_product_price(org.id, product.id, branch_a.id)
        assert resolved_a_after.selling_price == Decimal("1000.00")
        assert resolved_a_after.branch_id is None

    def test_sync_upload_price_and_history(self, setup_data):
        client = setup_data['client']
        org = setup_data['org']
        branch_a = setup_data['branch_a']
        user = setup_data['user']
        product = setup_data['product']

        device = Device.objects.create(
            organization=org,
            branch=branch_a,
            name="Main Register",
            code="MR01",
            device_identifier="DEV-PRICING-01",
        )

        p_id = uuid.uuid4()
        hist_id = uuid.uuid4()
        now_str = timezone.now().isoformat()

        events = [
            {
                "id": str(uuid.uuid4()),
                "entity_type": "price",
                "entity_id": str(p_id),
                "operation": SyncOperation.CREATE.value,
                "dependency_level": 3,
                "schema_version": 1,
                "local_created_at": now_str,
                "payload": {
                    "id": str(p_id),
                    "product_id": str(product.id),
                    "branch_id": str(branch_a.id),
                    "selling_price": "750.00",
                    "currency": "NGN",
                    "is_current": True,
                    "version": 1,
                    "effective_from": now_str,
                },
            },
            {
                "id": str(uuid.uuid4()),
                "entity_type": "price_history",
                "entity_id": str(hist_id),
                "operation": SyncOperation.CREATE.value,
                "dependency_level": 4,
                "schema_version": 1,
                "local_created_at": now_str,
                "payload": {
                    "id": str(hist_id),
                    "price_id": str(p_id),
                    "product_id": str(product.id),
                    "branch_id": str(branch_a.id),
                    "old_price": None,
                    "new_price": "750.00",
                    "change_reason": "Synced local price",
                    "version": 1,
                    "local_timestamp": now_str,
                },
            },
        ]

        resp = client.post(
            "/api/v1/sync/upload/",
            {
                "device_id": str(device.id),
                "branch_id": str(branch_a.id),
                "events": events,
            },
            format="json",
        )
        assert resp.status_code == status.HTTP_200_OK, resp.data
        statuses = [r["status"] for r in resp.data["results"]]
        assert statuses == ["PROCESSED", "PROCESSED"]

        # Verify created in db
        price = Price.objects.filter(id=p_id).first()
        assert price is not None
        assert price.selling_price == Decimal("750.00")

        hist = PriceHistory.objects.filter(id=hist_id).first()
        assert hist is not None
        assert hist.new_price == Decimal("750.00")
        assert hist.change_reason == "Synced local price"
