"""Тесты доменных моделей (models.py)."""

import pytest

from models import Customer, Order, OrderItem, ValidationError, ORDER_STATUSES


# --------------------------- Customer --------------------------------------- #
def test_customer_valid():
    c = Customer(name="Иван", phone="+70000000000", address="Москва")
    c.validate()  # не должно бросать исключение
    assert c.to_dict()["name"] == "Иван"


def test_customer_empty_name_invalid():
    with pytest.raises(ValidationError):
        Customer(name="   ").validate()


def test_customer_roundtrip_dict():
    c = Customer(id=5, name="Анна", phone="123", address="ул. Ленина")
    restored = Customer.from_dict(c.to_dict())
    assert restored.id == 5
    assert restored.name == "Анна"
    assert restored.phone == "123"


# --------------------------- OrderItem -------------------------------------- #
def test_order_item_subtotal():
    item = OrderItem(product_name="Пицца", quantity=2, price=750.0)
    assert item.subtotal == 1500.0


def test_order_item_invalid_quantity():
    with pytest.raises(ValidationError):
        OrderItem(product_name="Кола", quantity=0, price=100).validate()


def test_order_item_negative_price():
    with pytest.raises(ValidationError):
        OrderItem(product_name="Кола", quantity=1, price=-5).validate()


def test_order_item_empty_name():
    with pytest.raises(ValidationError):
        OrderItem(product_name="", quantity=1, price=10).validate()


# --------------------------- Order ------------------------------------------ #
def test_order_compute_total():
    order = Order(
        customer_id=1,
        order_date="2025-04-20",
        items=[
            OrderItem(product_name="Пицца", quantity=2, price=750),
            OrderItem(product_name="Кола", quantity=3, price=100),
        ],
    )
    assert order.compute_total() == 1800.0


def test_order_default_status_is_new():
    order = Order(customer_id=1)
    assert order.status == "новый"
    assert order.status in ORDER_STATUSES


def test_order_invalid_status():
    order = Order(customer_id=1, status="доставлено")
    with pytest.raises(ValidationError):
        order.validate()


def test_order_invalid_date():
    order = Order(customer_id=1, order_date="20-04-2025")
    with pytest.raises(ValidationError):
        order.validate()


def test_order_roundtrip_dict():
    order = Order(
        id=10, customer_id=2, order_date="2025-01-01", status="выполнен",
        items=[OrderItem(product_name="Суши", quantity=1, price=500)],
    )
    restored = Order.from_dict(order.to_dict())
    assert restored.id == 10
    assert restored.customer_id == 2
    assert restored.status == "выполнен"
    assert restored.total == 500.0
    assert restored.items[0].product_name == "Суши"
