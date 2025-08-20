def calculate_shipping_cost(weight):
    if weight <= 1:
        return 5.0  # flat rate for packages 1 kg or less
    elif weight <= 5:
        return 10.0  # flat rate for packages between 1 and 5 kg
    elif weight <= 10:
        return 20.0  # flat rate for packages between 5 and 10 kg
    elif weight <= 20:
        return 30.0  # flat rate for packages between 10 and 20 kg
    else:
        return 30.0 + (weight - 20) * 2  # additional charge for packages over 20 kg

# Example usage
weight = 25  # Example weight in kg
cost = calculate_shipping_cost(weight)
print(f"The shipping cost for a package weighing {weight} kg is ${cost}.")
