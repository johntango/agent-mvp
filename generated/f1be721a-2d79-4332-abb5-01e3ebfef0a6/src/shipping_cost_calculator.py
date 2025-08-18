def calculate_weight_cost(weight):
    return weight * 0.5
def calculate_distance_cost(distance):
    return distance * 0.1
def calculate_total_cost(weight, distance):
    base_cost = 5
    weight_cost = calculate_weight_cost(weight)
    distance_cost = calculate_distance_cost(distance)
    return base_cost + weight_cost + distance_cost
def main():
    weight = float(input('Enter the weight of the package: '))
    distance = float(input('Enter the shipping distance: '))
    total_cost = calculate_total_cost(weight, distance)
    print(f'The total shipping cost is: ${total_cost:.2f}')
