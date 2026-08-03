from dataclasses import FrozenInstanceError
from datetime import datetime

import pytest

from broker.zerodha_execution_provider import ZerodhaExecutionProvider
from domain.trade import TradeDirection
from execution.exceptions import (
    ExecutionProviderError,
    OrderNotFoundError,
    OrderValidationError,
)
from execution.execution_result import ExecutionResult, OrderStatus
from execution.order_manager import OrderManager
from execution.order_request import OrderRequest, OrderType, Product
from execution.order_validator import OrderValidator
from execution.paper_broker import PaperExecutionProvider
from execution.provider import ExecutionProvider


def _order(**overrides) -> OrderRequest:
    fields = dict(
        symbol="RELIANCE",
        exchange="NSE",
        side=TradeDirection.BUY,
        quantity=10,
        order_type=OrderType.MARKET,
        product=Product.INTRADAY,
    )
    fields.update(overrides)
    return OrderRequest(**fields)


class FakeProvider(ExecutionProvider):
    """Test double used to verify OrderManager orchestration in isolation."""

    def __init__(self, *, raise_on_place: Exception | None = None) -> None:
        self.raise_on_place = raise_on_place
        self.placed: list[OrderRequest] = []
        self.cancelled: list[str] = []
        self.modified: list[tuple[str, OrderRequest]] = []
        self.status_checked: list[str] = []

    def place_order(self, order: OrderRequest) -> ExecutionResult:
        if self.raise_on_place:
            raise self.raise_on_place
        self.placed.append(order)
        return ExecutionResult(
            success=True,
            status=OrderStatus.SUBMITTED,
            timestamp=datetime.now(),
            broker_order_id="FAKE-1",
        )

    def cancel_order(self, broker_order_id: str) -> ExecutionResult:
        self.cancelled.append(broker_order_id)
        return ExecutionResult(
            success=True,
            status=OrderStatus.CANCELLED,
            timestamp=datetime.now(),
            broker_order_id=broker_order_id,
        )

    def modify_order(self, broker_order_id: str, order: OrderRequest) -> ExecutionResult:
        self.modified.append((broker_order_id, order))
        return ExecutionResult(
            success=True,
            status=OrderStatus.PENDING,
            timestamp=datetime.now(),
            broker_order_id=broker_order_id,
        )

    def get_order_status(self, broker_order_id: str) -> ExecutionResult:
        self.status_checked.append(broker_order_id)
        return ExecutionResult(
            success=True,
            status=OrderStatus.FILLED,
            timestamp=datetime.now(),
            broker_order_id=broker_order_id,
        )


class FakeKite:
    """Stands in for KiteConnect so ZerodhaExecutionProvider never touches the network."""

    def __init__(self) -> None:
        self.place_order_calls: list[dict] = []
        self.cancel_order_calls: list[dict] = []
        self.modify_order_calls: list[dict] = []
        self.order_history_calls: list[str] = []

    def place_order(self, **kwargs):
        self.place_order_calls.append(kwargs)
        return "KITE-1"

    def cancel_order(self, **kwargs):
        self.cancel_order_calls.append(kwargs)
        return "KITE-1"

    def modify_order(self, **kwargs):
        self.modify_order_calls.append(kwargs)
        return "KITE-1"

    def order_history(self, order_id):
        self.order_history_calls.append(order_id)
        return [{"status": "OPEN"}, {"status": "COMPLETE", "status_message": None}]


class FailingKite(FakeKite):
    def place_order(self, **kwargs):
        raise RuntimeError("network error")


# --- Contract objects ---


def test_order_request_is_immutable():
    order = _order()
    with pytest.raises(FrozenInstanceError):
        order.quantity = 20


def test_execution_result_is_immutable():
    result = ExecutionResult(
        success=True, status=OrderStatus.FILLED, timestamp=datetime.now()
    )
    with pytest.raises(FrozenInstanceError):
        result.success = False


def test_order_status_enum_has_expected_lifecycle_values():
    assert {status.value for status in OrderStatus} == {
        "NEW",
        "VALIDATED",
        "SUBMITTED",
        "PENDING",
        "PARTIALLY_FILLED",
        "FILLED",
        "CANCELLED",
        "REJECTED",
        "UNKNOWN",
    }


# --- OrderValidator ---


def test_order_validator_accepts_valid_market_order():
    OrderValidator().validate(_order())


def test_order_validator_rejects_zero_quantity():
    with pytest.raises(OrderValidationError, match="quantity must be greater than zero"):
        OrderValidator().validate(_order(quantity=0))


def test_order_validator_rejects_limit_order_without_price():
    with pytest.raises(OrderValidationError, match="Limit orders require a price"):
        OrderValidator().validate(_order(order_type=OrderType.LIMIT))


def test_order_validator_accepts_limit_order_with_price():
    OrderValidator().validate(_order(order_type=OrderType.LIMIT, price=100.0))


def test_order_validator_rejects_stop_order_without_trigger_price():
    with pytest.raises(OrderValidationError, match="Stop orders require a trigger price"):
        OrderValidator().validate(_order(order_type=OrderType.STOP_LOSS))


def test_order_validator_accepts_stop_order_with_trigger_price():
    OrderValidator().validate(
        _order(order_type=OrderType.STOP_LOSS_MARKET, trigger_price=95.0)
    )


def test_order_validator_rejects_unsupported_order_type():
    validator = OrderValidator(supported_order_types=frozenset({OrderType.MARKET}))
    with pytest.raises(OrderValidationError, match="Unsupported order type"):
        validator.validate(_order(order_type=OrderType.LIMIT, price=100.0))


def test_order_validator_rejects_unsupported_product():
    validator = OrderValidator(supported_products=frozenset({Product.INTRADAY}))
    with pytest.raises(OrderValidationError, match="Unsupported product"):
        validator.validate(_order(product=Product.DELIVERY))


# --- OrderManager orchestration ---


def test_order_manager_submits_valid_order_via_provider():
    provider = FakeProvider()
    manager = OrderManager(provider)

    result = manager.submit_order(_order())

    assert result.success is True
    assert result.broker_order_id == "FAKE-1"
    assert provider.placed == [_order()]


def test_order_manager_rejects_invalid_order_without_calling_provider():
    provider = FakeProvider()
    manager = OrderManager(provider)

    result = manager.submit_order(_order(quantity=0))

    assert result.success is False
    assert result.status is OrderStatus.REJECTED
    assert "quantity" in result.message
    assert provider.placed == []


def test_order_manager_propagates_provider_execution_errors():
    provider = FakeProvider(raise_on_place=ExecutionProviderError("broker down"))
    manager = OrderManager(provider)

    with pytest.raises(ExecutionProviderError, match="broker down"):
        manager.submit_order(_order())


def test_order_manager_delegates_cancel_modify_and_status_to_provider():
    provider = FakeProvider()
    manager = OrderManager(provider)

    cancel_result = manager.cancel_order("FAKE-1")
    modify_result = manager.modify_order("FAKE-1", _order(quantity=5))
    status_result = manager.get_order_status("FAKE-1")

    assert provider.cancelled == ["FAKE-1"]
    assert provider.modified == [("FAKE-1", _order(quantity=5))]
    assert provider.status_checked == ["FAKE-1"]
    assert cancel_result.status is OrderStatus.CANCELLED
    assert modify_result.status is OrderStatus.PENDING
    assert status_result.status is OrderStatus.FILLED


def test_order_manager_uses_custom_validator():
    provider = FakeProvider()
    validator = OrderValidator(supported_order_types=frozenset({OrderType.MARKET}))
    manager = OrderManager(provider, validator=validator)

    result = manager.submit_order(_order(order_type=OrderType.LIMIT, price=100.0))

    assert result.success is False
    assert provider.placed == []


# --- PaperExecutionProvider ---


def test_paper_execution_provider_place_order_returns_success_with_fake_id():
    provider = PaperExecutionProvider()

    result = provider.place_order(_order())

    assert result.success is True
    assert result.status is OrderStatus.SUBMITTED
    assert result.broker_order_id == "PAPER-000001"


def test_paper_execution_provider_generates_unique_incrementing_ids():
    provider = PaperExecutionProvider()

    first = provider.place_order(_order())
    second = provider.place_order(_order())

    assert first.broker_order_id == "PAPER-000001"
    assert second.broker_order_id == "PAPER-000002"


def test_paper_execution_provider_cancel_order_updates_status():
    provider = PaperExecutionProvider()
    placed = provider.place_order(_order())

    result = provider.cancel_order(placed.broker_order_id)

    assert result.status is OrderStatus.CANCELLED
    assert provider.get_order_status(placed.broker_order_id).status is OrderStatus.CANCELLED


def test_paper_execution_provider_modify_order_updates_stored_request():
    provider = PaperExecutionProvider()
    placed = provider.place_order(_order(quantity=10))

    result = provider.modify_order(placed.broker_order_id, _order(quantity=25))

    assert result.status is OrderStatus.SUBMITTED
    assert provider._orders[placed.broker_order_id].request.quantity == 25


def test_paper_execution_provider_get_order_status_returns_last_known_status():
    provider = PaperExecutionProvider()
    placed = provider.place_order(_order())

    result = provider.get_order_status(placed.broker_order_id)

    assert result.status is OrderStatus.SUBMITTED
    assert result.broker_order_id == placed.broker_order_id


def test_paper_execution_provider_unknown_order_raises_not_found():
    provider = PaperExecutionProvider()

    with pytest.raises(OrderNotFoundError, match="Unknown paper order id"):
        provider.get_order_status("MISSING")

    with pytest.raises(OrderNotFoundError):
        provider.cancel_order("MISSING")

    with pytest.raises(OrderNotFoundError):
        provider.modify_order("MISSING", _order())


# --- ZerodhaExecutionProvider ---


def test_zerodha_execution_provider_place_order_maps_request_and_response():
    kite = FakeKite()
    provider = ZerodhaExecutionProvider(kite_client=kite)

    result = provider.place_order(_order(quantity=15))

    assert result.success is True
    assert result.status is OrderStatus.SUBMITTED
    assert result.broker_order_id == "KITE-1"
    call = kite.place_order_calls[0]
    assert call["transaction_type"] == "BUY"
    assert call["order_type"] == "MARKET"
    assert call["product"] == "MIS"
    assert call["quantity"] == 15


def test_zerodha_execution_provider_cancel_order_delegates_to_kite():
    kite = FakeKite()
    provider = ZerodhaExecutionProvider(kite_client=kite)

    result = provider.cancel_order("KITE-1")

    assert result.status is OrderStatus.CANCELLED
    assert kite.cancel_order_calls[0]["order_id"] == "KITE-1"


def test_zerodha_execution_provider_modify_order_delegates_to_kite():
    kite = FakeKite()
    provider = ZerodhaExecutionProvider(kite_client=kite)

    result = provider.modify_order("KITE-1", _order(quantity=20, price=101.5))

    assert result.status is OrderStatus.PENDING
    call = kite.modify_order_calls[0]
    assert call["order_id"] == "KITE-1"
    assert call["quantity"] == 20
    assert call["price"] == 101.5


def test_zerodha_execution_provider_get_order_status_maps_latest_history_entry():
    kite = FakeKite()
    provider = ZerodhaExecutionProvider(kite_client=kite)

    result = provider.get_order_status("KITE-1")

    assert result.status is OrderStatus.FILLED
    assert kite.order_history_calls == ["KITE-1"]


def test_zerodha_execution_provider_wraps_broker_errors():
    provider = ZerodhaExecutionProvider(kite_client=FailingKite())

    with pytest.raises(ExecutionProviderError, match="network error"):
        provider.place_order(_order())


def test_zerodha_execution_provider_maps_unrecognized_status_to_unknown_and_warns(caplog):
    class UnrecognizedStatusKite(FakeKite):
        def order_history(self, order_id):
            self.order_history_calls.append(order_id)
            return [{"status": "EXPIRED"}]

    provider = ZerodhaExecutionProvider(kite_client=UnrecognizedStatusKite())

    with caplog.at_level("WARNING"):
        result = provider.get_order_status("KITE-1")

    assert result.status is OrderStatus.UNKNOWN
    assert "EXPIRED" in caplog.text
