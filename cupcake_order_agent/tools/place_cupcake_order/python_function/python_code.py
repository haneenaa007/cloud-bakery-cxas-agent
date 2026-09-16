def place_cupcake_order(flavor: str, quantity: int, frosting: str, pickup_time: str, customer_name: str) -> dict:
    """Internal task to place the final cupcake order."""
    total_inr = int(quantity) * 120
    return {
        "status": "CONFIRMED",
        "order_id": "CB-4092",
        "total_inr": total_inr,
        "tracking_link": "cloudbakery://orders/CB-4092"
    }
