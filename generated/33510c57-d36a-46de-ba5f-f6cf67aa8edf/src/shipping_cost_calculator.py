def calculate_shipping_cost(weight):
    if weight <= 0:
        raise ValueError("Weight must be positive")
    elif weight <= 5:
        return 5.00
    elif weight <= 20:
        return 10.00
    else:
        return 20.00

# Example usage
weight = 8
shipping_cost = calculate_shipping_cost(weight)
print(f"The shipping cost for {weight} kg is ${shipping_cost:.2f}")
