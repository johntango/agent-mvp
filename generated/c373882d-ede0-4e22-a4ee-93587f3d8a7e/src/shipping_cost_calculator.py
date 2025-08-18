def calculate_shipping_cost(weight, distance):
    weight_cost = weight * 0.5
    distance_cost = distance * 0.1
    total_cost = weight_cost + distance_cost
    return total_cost
result = calculate_shipping_cost(10, 50)
print(f"The total shipping cost is: ${result:.2f}")
