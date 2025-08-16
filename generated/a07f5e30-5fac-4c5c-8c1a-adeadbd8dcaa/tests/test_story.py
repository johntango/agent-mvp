```python
import pytest

def calculate_shipping_cost(weight, distance, shipping_method):
    if weight <= 0 or distance < 0:
        raise ValueError("Weight must be positive and distance cannot be negative.")
    
    base_cost = 5.0
    weight_cost = weight * 0.5
    distance_cost = distance * 0.1
    
    if shipping_method == "express":
        return base_cost + weight_cost + distance_cost + 10.0
    elif shipping_method == "standard":
        return base_cost + weight_cost + distance_cost
    else:
        raise ValueError("Invalid shipping method.")

def test_calculate_shipping_cost_standard():
    assert calculate_shipping_cost(10, 100, "standard") == 15.0

def test_calculate_shipping_cost_express():
    assert calculate_shipping_cost(10, 100, "express") == 25.0

def test_calculate_shipping_cost_zero_weight():
    with pytest.raises(ValueError):
        calculate_shipping_cost(0, 100, "standard")

def test_calculate_shipping_cost_negative_distance():
    with pytest.raises(ValueError):
        calculate_shipping_cost(10, -1, "standard")

def test_calculate_shipping_cost_invalid_method():
    with pytest.raises(ValueError):
        calculate_shipping_cost(10, 100, "invalid_method")

def test_calculate_shipping_cost_edge_case():
    assert calculate_shipping_cost(1, 1, "standard") == 6.6
    assert calculate_shipping_cost(1, 1, "express") == 16.6
```