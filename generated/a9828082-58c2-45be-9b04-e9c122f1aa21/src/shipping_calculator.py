def calculate_shipping_cost(weight):
    if weight <= 0:
        return "Invalid weight"
    elif weight <= 2:
        return 5.00  # Flat rate for small packages
    elif weight <= 5:
        return 10.00  # Medium rate
    elif weight <= 10:
        return 15.00  # Large rate
    else:
        return 25.00  # Extra large rate
package_weight = 3.5
cost = calculate_shipping_cost(package_weight)
print(f"The shipping cost for a package weighing {package_weight} lbs is ${cost:.2f}.")
