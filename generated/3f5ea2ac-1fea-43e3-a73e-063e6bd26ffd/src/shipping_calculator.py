def calculate_shipping_cost(weight):
    # Define base cost and rate per kilogram
    base_cost = 5.00
    rate_per_kg = 1.50
    
    # Calculate total cost
    total_cost = base_cost + (weight * rate_per_kg)
    
    return total_cost

# Input weight of the package
weight = float(input("Enter the weight of the package in kg: "))

# Calculate shipping cost
shipping_cost = calculate_shipping_cost(weight)

# Output the result
print(f"The shipping cost for a package weighing {weight} kg is ${shipping_cost:.2f}.")
