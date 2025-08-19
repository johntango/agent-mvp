def calculate_shipping_cost(weight, destination='domestic'):
    if destination == 'domestic':
        if weight <= 5:
            cost = 5
        elif weight <= 20:
            cost = 10
        else:
            cost = 20
    else:  # international
        if weight <= 5:
            cost = 15
        elif weight <= 20:
            cost = 30
        else:
            cost = 60
    return cost

# Example usage
weight = 10
cost_domestic = calculate_shipping_cost(weight)
cost_international = calculate_shipping_cost(weight, 'international')
print(f"Domestic cost for {weight}kg: ${cost_domestic}")
print(f"International cost for {weight}kg: ${cost_international}")
