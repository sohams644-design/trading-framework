import pytest

from performance.charges_calculator import ChargesCalculator


def test_calculate_intraday_computes_each_charge_component():
    calculator = ChargesCalculator()

    charges = calculator.calculate_intraday(buy_price=100.0, sell_price=102.0, quantity=50)

    turnover = (100.0 + 102.0) * 50
    assert charges.brokerage == 0.0
    assert charges.stt == pytest.approx(round(102.0 * 50 * 0.00025, 2))
    assert charges.exchange_charge == pytest.approx(round(turnover * 0.0000297, 2))
    assert charges.sebi_charge == pytest.approx(round(turnover * 0.000001, 2))
    assert charges.gst == pytest.approx(round((0.0 + turnover * 0.0000297) * 0.18, 2))
    assert charges.stamp_duty == pytest.approx(round(100.0 * 50 * 0.00003, 2))


def test_total_sums_every_charge_component():
    calculator = ChargesCalculator()

    charges = calculator.calculate_intraday(buy_price=100.0, sell_price=102.0, quantity=50)

    expected_total = round(
        charges.brokerage
        + charges.stt
        + charges.exchange_charge
        + charges.sebi_charge
        + charges.gst
        + charges.stamp_duty,
        2,
    )
    assert charges.total == expected_total


def test_charges_scale_with_quantity():
    calculator = ChargesCalculator()

    small = calculator.calculate_intraday(buy_price=100.0, sell_price=102.0, quantity=1)
    large = calculator.calculate_intraday(buy_price=100.0, sell_price=102.0, quantity=100)

    assert large.total > small.total


def test_charges_are_never_negative_on_a_losing_trade():
    calculator = ChargesCalculator()

    charges = calculator.calculate_intraday(buy_price=100.0, sell_price=90.0, quantity=10)

    assert charges.total > 0
