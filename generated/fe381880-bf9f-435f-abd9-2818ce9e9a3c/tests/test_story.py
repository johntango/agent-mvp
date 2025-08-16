```python
import pytest

def calculate_shipping_cost(weight: float, distance: float) -> float:
    if weight <= 0 or distance <= 0:
        raise ValueError("Weight and distance must be positive values.")
    
    base_cost = 5.0
    cost_per_kg = 2.0
    cost_per_km = 0.5
    
    return base_cost + (cost_per_kg * weight) + (cost_per_km * distance)

def test_calculate_shipping_cost_valid():
    assert calculate_shipping_cost(10, 100) == 5.0 + (2.0 * 10) + (0.5 * 100)
    assert calculate_shipping_cost(0.5, 50) == 5.0 + (2.0 * 0.5) + (0.5 * 50)
    assert calculate_shipping_cost(20, 200) == 5.0 + (2.0 * 20) + (0.5 * 200)

def test_calculate_shipping_cost_zero_weight():
    with pytest.raises(ValueError, match="Weight and distance must be positive values."):
        calculate_shipping_cost(0, 50)

def test_calculate_shipping_cost_zero_distance():
    with pytest.raises(ValueError, match="Weight and distance must be positive values."):
        calculate_shipping_cost(10, 0)

def test_calculate_shipping_cost_negative_weight():
    with pytest.raises(ValueError, match="Weight and distance must be positive values."):
        calculate_shipping_cost(-1, 50)

def test_calculate_shipping_cost_negative_distance():
    with pytest.raises(ValueError, match="Weight and distance must be positive values."):
        calculate_shipping_cost(10, -1)
```