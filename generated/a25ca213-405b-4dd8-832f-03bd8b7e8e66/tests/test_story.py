import pytest

def calculate_shipping_cost(weight, distance, shipping_method):
    if weight <= 0 or distance <= 0:
        raise ValueError("Weight and distance must be positive values.")
    
    if shipping_method not in ['standard', 'express']:
        raise ValueError("Invalid shipping method. Choose 'standard' or 'express'.")

    base_cost = 5.0
    weight_cost = weight * 0.5
    distance_cost = distance * 0.1

    if shipping_method == 'express':
        return base_cost + weight_cost + distance_cost + 10.0
    return base_cost + weight_cost + distance_cost

def test_calculate_shipping_cost_standard():
    assert calculate_shipping_cost(10, 100, 'standard') == 15.0
    assert calculate_shipping_cost(5, 50, 'standard') == 10.0
    assert calculate_shipping_cost(0.5, 10, 'standard') == 6.0

def test_calculate_shipping_cost_express():
    assert calculate_shipping_cost(10, 100, 'express') == 25.0
    assert calculate_shipping_cost(5, 50, 'express') == 20.0
    assert calculate_shipping_cost(0.5, 10, 'express') == 16.0

def test_calculate_shipping_cost_invalid_weight():
    with pytest.raises(ValueError, match="Weight and distance must be positive values."):
        calculate_shipping_cost(0, 100, 'standard')
    with pytest.raises(ValueError, match="Weight and distance must be positive values."):
        calculate_shipping_cost(-1, 100, 'standard')

def test_calculate_shipping_cost_invalid_distance():
    with pytest.raises(ValueError, match="Weight and distance must be positive values."):
        calculate_shipping_cost(10, 0, 'standard')
    with pytest.raises(ValueError, match="Weight and distance must be positive values."):
        calculate_shipping_cost(10, -1, 'standard')

def test_calculate_shipping_cost_invalid_shipping_method():
    with pytest.raises(ValueError, match="Invalid shipping method. Choose 'standard' or 'express'."):
        calculate_shipping_cost(10, 100, 'overnight')