```python
import pytest

def calculate_shipping_cost(weight: float, distance: float, rate_per_kg: float = 5.0) -> float:
    if weight <= 0 or distance <= 0:
        raise ValueError("Weight and distance must be greater than zero.")
    return weight * distance * rate_per_kg

def test_calculate_shipping_cost_valid():
    assert calculate_shipping_cost(10, 100) == 5000.0
    assert calculate_shipping_cost(5, 50) == 1250.0
    assert calculate_shipping_cost(0.5, 10) == 25.0

def test_calculate_shipping_cost_zero_weight():
    with pytest.raises(ValueError, match="Weight and distance must be greater than zero."):
        calculate_shipping_cost(0, 100)

def test_calculate_shipping_cost_zero_distance():
    with pytest.raises(ValueError, match="Weight and distance must be greater than zero."):
        calculate_shipping_cost(10, 0)

def test_calculate_shipping_cost_negative_weight():
    with pytest.raises(ValueError, match="Weight and distance must be greater than zero."):
        calculate_shipping_cost(-1, 100)

def test_calculate_shipping_cost_negative_distance():
    with pytest.raises(ValueError, match="Weight and distance must be greater than zero."):
        calculate_shipping_cost(10, -100)

def test_calculate_shipping_cost_custom_rate():
    assert calculate_shipping_cost(10, 100, rate_per_kg=10.0) == 10000.0
    assert calculate_shipping_cost(2, 20, rate_per_kg=2.5) == 100.0
```