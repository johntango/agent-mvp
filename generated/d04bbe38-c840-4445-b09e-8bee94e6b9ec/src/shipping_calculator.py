def calculate_shipping_cost(weight, shipping_type):
    # Define rate per kg for different shipping types
    STANDARD_RATE = 5.0
    EXPRESS_RATE = 10.0
    
    # Calculate cost based on shipping type
    if shipping_type == 'standard':
        cost = weight * STANDARD_RATE
    elif shipping_type == 'express':
        cost = weight * EXPRESS_RATE
    else:
        raise ValueError('Invalid shipping type. Choose standard or express.')

    return cost
def main():
    # User input for weight and shipping type
    weight = float(input("Enter the package weight (in kg): "))
    shipping_type = input("Enter the shipping type (standard/express): ").lower()

    try:
        cost = calculate_shipping_cost(weight, shipping_type)
        print(f"The shipping cost is: ${cost:.2f}")
    except ValueError as e:
        print(e)

if __name__ == "__main__":
    main()
