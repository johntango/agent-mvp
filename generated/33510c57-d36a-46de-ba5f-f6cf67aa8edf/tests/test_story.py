# src/shipping_cost.py
from decimal import Decimal, ROUND_HALF_UP

BASE_COST = Decimal('3.50')
WEIGHT_FACTOR = Decimal('1.20')

def round_3(x):
    return x.quantize(Decimal('0.001'), rounding=ROUND_HALF_UP)

def round_2(x):
    return x.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

def calculate_shipping_cost(weight_kg):
    if not isinstance(weight_kg, (int, float, Decimal)):
        raise TypeError("NON_NUMERIC_WEIGHT")
    
    rounded_weight = round_3(Decimal(weight_kg))
    
    if rounded_weight < 0:
        raise ValueError("NEGATIVE_WEIGHT")
    if rounded_weight > 200:
        raise ValueError("WEIGHT_TOO_LARGE")
    
    cost = BASE_COST + WEIGHT_FACTOR * rounded_weight
    return round_2(cost)
```

```python
# test_shipping_cost.py
import pytest
from decimal import Decimal
from src.shipping_cost import calculate_shipping_cost

def test_calculate_shipping_cost():
    assert calculate_shipping_cost(0) == Decimal('3.50')
    assert calculate_shipping_cost(0.5) == Decimal('4.10')
    assert calculate_shipping_cost(1) == Decimal('4.70')
    assert calculate_shipping_cost(1.25) == Decimal('5.00')
    assert calculate_shipping_cost(5) == Decimal('9.50')
    assert calculate_shipping_cost(10) == Decimal('15.50')
    assert calculate_shipping_cost(20) == Decimal('27.50')
    assert calculate_shipping_cost(50) == Decimal('63.50')
    
    assert calculate_shipping_cost(0.004) == Decimal('3.50')
    assert calculate_shipping_cost(0.005) == Decimal('3.51')
    
    assert calculate_shipping_cost(2.499) == Decimal('6.50')
    assert calculate_shipping_cost(2.500) == Decimal('6.50')
    assert calculate_shipping_cost(2.504) == Decimal('6.50')
    assert calculate_shipping_cost(2.505) == Decimal('6.51')
    
    assert calculate_shipping_cost(0) == Decimal('3.50')
    assert calculate_shipping_cost(200) == Decimal('243.50')

    with pytest.raises(ValueError, match="WEIGHT_TOO_LARGE"):
        calculate_shipping_cost(200.001)

    with pytest.raises(ValueError, match="NEGATIVE_WEIGHT"):
        calculate_shipping_cost(-0.001)

    with pytest.raises(TypeError, match="NON_NUMERIC_WEIGHT"):
        calculate_shipping_cost("1.0")