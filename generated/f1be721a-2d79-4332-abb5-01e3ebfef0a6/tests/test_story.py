import pytest

def calculate_shipping_cost(weight: float, distance: float) -> float:
    if weight <= 0 or distance <= 0:
        raise ValueError("Weight and distance must be positive values.")
    base_cost = 5.0
    weight_cost = weight * 0.5
    distance_cost = distance * 0.1
    return base_cost + weight_cost + distance_cost

def test_calculate_shipping_cost_valid():
    assert calculate_shipping_cost(10, 100) == 15.0
    assert calculate_shipping_cost(5, 50) == 10.0
    assert calculate_shipping_cost(0.5, 10) == 6.0

def test_calculate_shipping_cost_zero_weight():
    with pytest.raises(ValueError, match="Weight and distance must be positive values."):
        calculate_shipping_cost(0, 100)

def test_calculate_shipping_cost_zero_distance():
    with pytest.raises(ValueError, match="Weight and distance must be positive values."):
        calculate_shipping_cost(10, 0)

def test_calculate_shipping_cost_negative_weight():
    with pytest.raises(ValueError, match="Weight and distance must be positive values."):
        calculate_shipping_cost(-1, 100)

def test_calculate_shipping_cost_negative_distance():
    with pytest.raises(ValueError, match="Weight and distance must be positive values."):
        calculate_shipping_cost(10, -1)