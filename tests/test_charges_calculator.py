from performance.charges_calculator import ChargesCalculator

calculator = ChargesCalculator()

charges = calculator.calculate_intraday(
    buy_price=100,
    sell_price=102,
    quantity=50
)

print(charges)
print("Total Charges:", charges.total)