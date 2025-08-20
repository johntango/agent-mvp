def calculate_shipping_cost(weight):
    if weight <= 1:
        return 5.00
    elif weight <= 5:
        return 10.00
    elif weight <= 10:
        return 20.00
    else:
        return 50.00
