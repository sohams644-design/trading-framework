from dataclasses import dataclass


@dataclass(slots=True)
class Charges:
    brokerage: float
    stt: float
    exchange_charge: float
    sebi_charge: float
    gst: float
    stamp_duty: float

    @property
    def total(self):
        return round(
            self.brokerage
            + self.stt
            + self.exchange_charge
            + self.sebi_charge
            + self.gst
            + self.stamp_duty,
            2
        )


class ChargesCalculator:

    def calculate_intraday(
        self,
        buy_price: float,
        sell_price: float,
        quantity: int
    ) -> Charges:

        turnover = (buy_price + sell_price) * quantity

        brokerage = 0.0

        stt = sell_price * quantity * 0.00025

        exchange_charge = turnover * 0.0000297

        sebi_charge = turnover * 0.000001

        gst = (brokerage + exchange_charge) * 0.18

        stamp_duty = buy_price * quantity * 0.00003

        return Charges(
            brokerage=round(brokerage, 2),
            stt=round(stt, 2),
            exchange_charge=round(exchange_charge, 2),
            sebi_charge=round(sebi_charge, 2),
            gst=round(gst, 2),
            stamp_duty=round(stamp_duty, 2)
        )