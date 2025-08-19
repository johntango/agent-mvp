import pytest
from decimal import Decimal, ROUND_HALF_UP
from src.shipping_cost import calculate_shipping_cost

def test_calculate_shipping_cost():
    # Exact values
    assert calculate_shipping_cost(0) == Decimal('3.50')
    assert calculate_shipping_cost(0.5) == Decimal('4.10')
    assert calculate_shipping_cost(1) == Decimal('4.70')
    assert calculate_shipping_cost(1.25) == Decimal('5.00')
    assert calculate_shipping_cost(5) == Decimal('9.50')
    assert calculate_shipping_cost(10) == Decimal('15.50')
    assert calculate_shipping_cost(20) == Decimal('27.50')
    assert calculate_shipping_cost(50) == Decimal('63.50')

    # Rounding around very small weights
    assert calculate_shipping_cost(0.004) == Decimal('3.50')
    assert calculate_shipping_cost(0.005) == Decimal('3.51')

    # Boundary behavior near 2.5 kg
    assert calculate_shipping_cost(2.499) == Decimal('6.50')
    assert calculate_shipping_cost(2.500) == Decimal('6.50')
    assert calculate_shipping_cost(2.504) == Decimal('6.50')
    assert calculate_shipping_cost(2.505) == Decimal('6.51')

    # Domain limits
    assert calculate_shipping_cost(0) == Decimal('3.50')
    assert calculate_shipping_cost(200) == Decimal('243.50')
    
    with pytest.raises(ValueError, match="WEIGHT_TOO_LARGE"):
        calculate_shipping_cost(200.001)

    # Invalid inputs
    with pytest.raises(ValueError, match="NEGATIVE_WEIGHT"):
        calculate_shipping_cost(-0.001)

    with pytest.raises(TypeError, match="NON_NUMERIC_WEIGHT"):
        calculate_shipping_cost("1.0")