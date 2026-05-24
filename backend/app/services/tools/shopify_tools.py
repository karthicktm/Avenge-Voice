"""Shopify integration tools for voice agents."""

from collections.abc import Awaitable, Callable
from http import HTTPStatus
from typing import Any

import httpx
import structlog

logger = structlog.get_logger()

ToolHandler = Callable[..., Awaitable[dict[str, Any]]]


class ShopifyTools:
    """Shopify Admin API integration tools.

    Provides tools for:
    - Looking up orders by number, email, or phone
    - Checking product inventory
    - Searching customers
    - Getting order status and tracking
    """

    API_VERSION = "2024-10"

    def __init__(self, access_token: str, shop_domain: str) -> None:
        """Initialize Shopify tools.

        Args:
            access_token: Shopify Admin API Access Token
            shop_domain: Shop domain (e.g., your-store.myshopify.com)
        """
        self.access_token = access_token
        self.shop_domain = shop_domain.replace("https://", "").replace("http://", "")
        self._client: httpx.AsyncClient | None = None

    @property
    def client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            base_url = f"https://{self.shop_domain}/admin/api/{self.API_VERSION}"
            self._client = httpx.AsyncClient(
                base_url=base_url,
                headers={
                    "X-Shopify-Access-Token": self.access_token,
                    "Content-Type": "application/json",
                },
                timeout=30.0,
            )
        return self._client

    async def close(self) -> None:
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    @staticmethod
    def get_tool_definitions() -> list[dict[str, Any]]:
        """Get OpenAI function calling tool definitions."""
        return [
            {
                "type": "function",
                "name": "shopify_search_orders",
                "description": "Search for orders by order number, email, or phone number",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query (order number, email, phone)",
                        },
                        "status": {
                            "type": "string",
                            "enum": ["any", "open", "closed", "cancelled"],
                            "description": "Filter by order status (default: any)",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Max results (default 10, max 50)",
                        },
                    },
                    "required": ["query"],
                },
            },
            {
                "type": "function",
                "name": "shopify_get_order",
                "description": "Get detailed order information including items, shipping, and payment status",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "order_id": {
                            "type": "string",
                            "description": "The Shopify order ID or order number",
                        },
                    },
                    "required": ["order_id"],
                },
            },
            {
                "type": "function",
                "name": "shopify_get_order_tracking",
                "description": "Get shipping/tracking information for an order",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "order_id": {
                            "type": "string",
                            "description": "The Shopify order ID",
                        },
                    },
                    "required": ["order_id"],
                },
            },
            {
                "type": "function",
                "name": "shopify_search_products",
                "description": "Search for products by name or SKU",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Product name or SKU to search for",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Max results (default 10, max 50)",
                        },
                    },
                    "required": ["query"],
                },
            },
            {
                "type": "function",
                "name": "shopify_check_inventory",
                "description": "Check inventory/stock levels for a product",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "product_id": {
                            "type": "string",
                            "description": "The Shopify product ID",
                        },
                    },
                    "required": ["product_id"],
                },
            },
            {
                "type": "function",
                "name": "shopify_search_customers",
                "description": "Search for customers by email, phone, or name",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Customer email, phone, or name",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Max results (default 10, max 50)",
                        },
                    },
                    "required": ["query"],
                },
            },
            {
                "type": "function",
                "name": "shopify_get_customer_orders",
                "description": "Get order history for a specific customer",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "customer_id": {
                            "type": "string",
                            "description": "The Shopify customer ID",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Max results (default 10, max 50)",
                        },
                    },
                    "required": ["customer_id"],
                },
            },
        ]

    async def search_orders(
        self,
        query: str,
        status: str = "any",
        limit: int = 10,
    ) -> dict[str, Any]:
        """Search for orders."""
        try:
            params: dict[str, Any] = {
                "limit": min(limit, 50),
                "fields": "id,name,email,phone,created_at,financial_status,"
                "fulfillment_status,total_price,currency,line_items",
            }

            if status != "any":
                params["status"] = status

            # Try to find by order number first
            if query.startswith("#"):
                query = query[1:]

            # Search by name (order number) or use general query
            params["name"] = query

            response = await self.client.get("/orders.json", params=params)

            if response.status_code != HTTPStatus.OK:
                # Try email search
                del params["name"]
                params["email"] = query
                response = await self.client.get("/orders.json", params=params)

            if response.status_code != HTTPStatus.OK:
                return {
                    "success": False,
                    "error": f"Failed to search orders: {response.text}",
                }

            data = response.json()
            orders = []
            for order in data.get("orders", []):
                orders.append(
                    {
                        "id": order["id"],
                        "order_number": order["name"],
                        "email": order.get("email"),
                        "phone": order.get("phone"),
                        "created_at": order["created_at"],
                        "financial_status": order["financial_status"],
                        "fulfillment_status": order.get("fulfillment_status"),
                        "total": f"{order['total_price']} {order['currency']}",
                        "item_count": len(order.get("line_items", [])),
                    }
                )

            return {"success": True, "orders": orders, "total": len(orders)}

        except Exception as e:
            logger.exception("shopify_search_orders_error", error=str(e))
            return {"success": False, "error": str(e)}

    async def get_order(self, order_id: str) -> dict[str, Any]:
        """Get detailed order information."""
        try:
            # Handle order number vs ID
            if order_id.startswith("#"):
                order_id = order_id[1:]

            response = await self.client.get(f"/orders/{order_id}.json")

            if response.status_code != HTTPStatus.OK:
                # Try searching by name
                search_response = await self.client.get(
                    "/orders.json", params={"name": order_id, "limit": 1}
                )
                if search_response.status_code == HTTPStatus.OK:
                    orders = search_response.json().get("orders", [])
                    if orders:
                        order_id = str(orders[0]["id"])
                        response = await self.client.get(f"/orders/{order_id}.json")

            if response.status_code != HTTPStatus.OK:
                return {
                    "success": False,
                    "error": f"Order not found: {response.text}",
                }

            order = response.json()["order"]

            # Format line items
            items = []
            for item in order.get("line_items", []):
                items.append(
                    {
                        "name": item["name"],
                        "quantity": item["quantity"],
                        "price": item["price"],
                        "sku": item.get("sku"),
                    }
                )

            # Format shipping address
            shipping = order.get("shipping_address", {})
            shipping_addr = None
            if shipping:
                shipping_addr = {
                    "name": shipping.get("name"),
                    "address": f"{shipping.get('address1', '')} {shipping.get('address2', '')}".strip(),
                    "city": shipping.get("city"),
                    "province": shipping.get("province"),
                    "zip": shipping.get("zip"),
                    "country": shipping.get("country"),
                }

            return {
                "success": True,
                "order": {
                    "id": order["id"],
                    "order_number": order["name"],
                    "email": order.get("email"),
                    "phone": order.get("phone"),
                    "created_at": order["created_at"],
                    "financial_status": order["financial_status"],
                    "fulfillment_status": order.get("fulfillment_status"),
                    "total": f"{order['total_price']} {order['currency']}",
                    "subtotal": order["subtotal_price"],
                    "shipping_cost": order.get("total_shipping_price_set", {})
                    .get("shop_money", {})
                    .get("amount"),
                    "items": items,
                    "shipping_address": shipping_addr,
                    "note": order.get("note"),
                },
            }

        except Exception as e:
            logger.exception("shopify_get_order_error", error=str(e))
            return {"success": False, "error": str(e)}

    async def get_order_tracking(self, order_id: str) -> dict[str, Any]:
        """Get tracking information for an order."""
        try:
            response = await self.client.get(f"/orders/{order_id}/fulfillments.json")

            if response.status_code != HTTPStatus.OK:
                return {
                    "success": False,
                    "error": f"Failed to get tracking: {response.text}",
                }

            data = response.json()
            fulfillments = []
            for f in data.get("fulfillments", []):
                tracking = []
                for t in f.get("tracking_numbers", []):
                    tracking.append(t)

                fulfillments.append(
                    {
                        "id": f["id"],
                        "status": f["status"],
                        "created_at": f["created_at"],
                        "tracking_company": f.get("tracking_company"),
                        "tracking_numbers": tracking,
                        "tracking_urls": f.get("tracking_urls", []),
                    }
                )

            return {
                "success": True,
                "order_id": order_id,
                "fulfillments": fulfillments,
                "has_tracking": len(fulfillments) > 0,
            }

        except Exception as e:
            logger.exception("shopify_get_order_tracking_error", error=str(e))
            return {"success": False, "error": str(e)}

    async def search_products(self, query: str, limit: int = 10) -> dict[str, Any]:
        """Search for products."""
        try:
            params: dict[str, str | int] = {
                "limit": min(limit, 50),
                "title": query,
                "fields": "id,title,handle,status,variants,images",
            }

            response = await self.client.get("/products.json", params=params)

            if response.status_code != HTTPStatus.OK:
                return {
                    "success": False,
                    "error": f"Failed to search products: {response.text}",
                }

            data = response.json()
            products = []
            for product in data.get("products", []):
                variants = []
                for v in product.get("variants", []):
                    variants.append(
                        {
                            "id": v["id"],
                            "title": v["title"],
                            "sku": v.get("sku"),
                            "price": v["price"],
                            "inventory_quantity": v.get("inventory_quantity"),
                            "available": v.get("inventory_quantity", 0) > 0,
                        }
                    )

                products.append(
                    {
                        "id": product["id"],
                        "title": product["title"],
                        "handle": product["handle"],
                        "status": product["status"],
                        "variants": variants,
                        "image": product.get("images", [{}])[0].get("src")
                        if product.get("images")
                        else None,
                    }
                )

            return {"success": True, "products": products, "total": len(products)}

        except Exception as e:
            logger.exception("shopify_search_products_error", error=str(e))
            return {"success": False, "error": str(e)}

    async def check_inventory(self, product_id: str) -> dict[str, Any]:
        """Check inventory levels for a product."""
        try:
            response = await self.client.get(f"/products/{product_id}.json")

            if response.status_code != HTTPStatus.OK:
                return {
                    "success": False,
                    "error": f"Product not found: {response.text}",
                }

            product = response.json()["product"]
            inventory = []
            total_available = 0

            for variant in product.get("variants", []):
                qty = variant.get("inventory_quantity", 0)
                total_available += qty
                inventory.append(
                    {
                        "variant_id": variant["id"],
                        "variant_title": variant["title"],
                        "sku": variant.get("sku"),
                        "quantity": qty,
                        "available": qty > 0,
                    }
                )

            return {
                "success": True,
                "product_id": product_id,
                "product_title": product["title"],
                "total_available": total_available,
                "in_stock": total_available > 0,
                "variants": inventory,
            }

        except Exception as e:
            logger.exception("shopify_check_inventory_error", error=str(e))
            return {"success": False, "error": str(e)}

    async def search_customers(self, query: str, limit: int = 10) -> dict[str, Any]:
        """Search for customers."""
        try:
            params: dict[str, str | int] = {
                "limit": min(limit, 50),
                "query": query,
                "fields": "id,email,phone,first_name,last_name,orders_count,total_spent",
            }

            response = await self.client.get("/customers/search.json", params=params)

            if response.status_code != HTTPStatus.OK:
                return {
                    "success": False,
                    "error": f"Failed to search customers: {response.text}",
                }

            data = response.json()
            customers = []
            for customer in data.get("customers", []):
                customers.append(
                    {
                        "id": customer["id"],
                        "email": customer.get("email"),
                        "phone": customer.get("phone"),
                        "name": f"{customer.get('first_name', '')} {customer.get('last_name', '')}".strip(),
                        "orders_count": customer.get("orders_count", 0),
                        "total_spent": customer.get("total_spent"),
                    }
                )

            return {"success": True, "customers": customers, "total": len(customers)}

        except Exception as e:
            logger.exception("shopify_search_customers_error", error=str(e))
            return {"success": False, "error": str(e)}

    async def get_customer_orders(self, customer_id: str, limit: int = 10) -> dict[str, Any]:
        """Get order history for a customer."""
        try:
            params: dict[str, str | int] = {
                "customer_id": customer_id,
                "limit": min(limit, 50),
                "status": "any",
                "fields": "id,name,created_at,financial_status,fulfillment_status,total_price,currency",
            }

            response = await self.client.get("/orders.json", params=params)

            if response.status_code != HTTPStatus.OK:
                return {
                    "success": False,
                    "error": f"Failed to get customer orders: {response.text}",
                }

            data = response.json()
            orders = []
            for order in data.get("orders", []):
                orders.append(
                    {
                        "id": order["id"],
                        "order_number": order["name"],
                        "created_at": order["created_at"],
                        "financial_status": order["financial_status"],
                        "fulfillment_status": order.get("fulfillment_status"),
                        "total": f"{order['total_price']} {order['currency']}",
                    }
                )

            return {
                "success": True,
                "customer_id": customer_id,
                "orders": orders,
                "total": len(orders),
            }

        except Exception as e:
            logger.exception("shopify_get_customer_orders_error", error=str(e))
            return {"success": False, "error": str(e)}

    async def execute_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute a Shopify tool by name."""
        tool_map: dict[str, ToolHandler] = {
            "shopify_search_orders": self.search_orders,
            "shopify_get_order": self.get_order,
            "shopify_get_order_tracking": self.get_order_tracking,
            "shopify_search_products": self.search_products,
            "shopify_check_inventory": self.check_inventory,
            "shopify_search_customers": self.search_customers,
            "shopify_get_customer_orders": self.get_customer_orders,
        }

        handler = tool_map.get(tool_name)
        if not handler:
            return {"success": False, "error": f"Unknown tool: {tool_name}"}

        result: dict[str, Any] = await handler(**arguments)
        return result
