def calculate_shipping_cost(weight):
    if weight <= 1:
        return 5
    elif weight <= 5:
        return 10
    else:
        return 20
 
def story():
    packages = [
        {'description': 'tiny package', 'weight': 0.5},
        {'description': 'medium package', 'weight': 3},
        {'description': 'large package', 'weight': 10},
    ]
    for package in packages:
        cost = calculate_shipping_cost(package['weight'])
        print(f"The {package['description']} costs ${cost} to ship.")
 
story()
