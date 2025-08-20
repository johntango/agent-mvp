import pytest
from decimal import Decimal, ROUND_HALF_UP
from src.shipping_cost import calculate_shipping_cost

def round_3(value):
    return Decimal(value).quantize(Decimal('0.001'), rounding=ROUND_HALF_UP)

def round_2(value):
    return Decimal(value).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

def test_calculate_shipping_cost():
    assert calculate_shipping_cost(0) == round_2(3.50)
    assert calculate_shipping_cost(0.5) == round_2(4.10)
    assert calculate_shipping_cost(1) == round_2(4.70)
    assert calculate_shipping_cost(1.25) == round_2(5.00)
    assert calculate_shipping_cost(5) == round_2(9.50)
    assert calculate_shipping_cost(10) == round_2(15.50)
    assert calculate_shipping_cost(20) == round_2(27.50)
    assert calculate_shipping_cost(50) == round_2(63.50)

    assert calculate_shipping_cost(0.004) == round_2(3.50)
    assert calculate_shipping_cost(0.005) == round_2(3.51)

    assert calculate_shipping_cost(2.499) == round_2(6.50)
    assert calculate_shipping_cost(2.500) == round_2(6.50)
    assert calculate_shipping_cost(2.504) == round_2(6.50)
    assert calculate_shipping_cost(2.505) == round_2(6.51)

    assert calculate_shipping_cost(0) == round_2(3.50)
    assert calculate_shipping_cost(200) == round_2(243.50)

def test_weight_too_large():
    with pytest.raises(ValueError, match="WEIGHT_TOO_LARGE"):
        calculate_shipping_cost(200.001)

def test_negative_weight():
    with pytest.raises(ValueError, match="NEGATIVE_WEIGHT"):
        calculate_shipping_cost(-0.001)

def test_non_numeric_weight():
    with pytest.raises(TypeError, match="NON_NUMERIC_WEIGHT"):
        calculate_shipping_cost("1.0")