def calculate_shipping_cost(weight, length, width, height):
    base_cost = 5.00
    weight_factor = 1.5
    size_factor = 0.05
    extra_charges = 2.00 if weight > 10 else 0.00
    
    weight_cost = weight * weight_factor
    size_cost = (length + width + height) * size_factor
    
    total_cost = base_cost + weight_cost + size_cost + extra_charges
    return total_cost

# Example usage:
weight = 12  # in kg
length = 20  # in cm
width = 15   # in cm
height = 10  # in cm
cost = calculate_shipping_cost(weight, length, width, height)
print(f"The total shipping cost is: ${cost:.2f}")
