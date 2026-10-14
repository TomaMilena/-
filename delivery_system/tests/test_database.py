"""
Тесты слоя БД (database.py).

Каждый тест прогоняется на ОБОИХ бэкендах (SQLite и TinyDB) через
параметризацию фикстуры. TinyDB-тесты пропускаются, если пакет не установлен.
"""

import importlib

import pytest

from database import SQLiteDatabase, IntegrityError
from models import Customer, Order, OrderItem, ValidationError

_HAS_TINYDB = importlib.util.find_spec("tinydb") is not None


@pytest.fixture(params=["sqlite", "tinydb"])
def db(request, tmp_path):
    """Параметризованная фикстура: чистая БД нужного бэкенда во временной папке."""
    backend = request.param
    if backend == "tinydb" and not _HAS_TINYDB:
        pytest.skip("tinydb не установлен")
    from database import get_database
    ext = "db" if backend == "sqlite" else "json"
    path = str(tmp_path / f"test.{ext}")
    database = get_database(backend=backend, path=path)
    yield database
    database.close()


# --------------------------- Клиенты ---------------------------------------- #
def test_add_and_get_customer(db):
    cid = db.add_customer(Customer(name="Иван", phone="111", address="Москва"))
    fetched = db.get_customer(cid)
    assert fetched is not None
    assert fetched.name == "Иван"


def test_list_customers(db):
    db.add_customer(Customer(name="A"))
    db.add_customer(Customer(name="B"))
    assert len(db.list_customers()) == 2


def test_update_customer(db):
    cid = db.add_customer(Customer(name="Старое"))
    cust = db.get_customer(cid)
    cust.name = "Новое"
    db.update_customer(cust)
    assert db.get_customer(cid).name == "Новое"


def test_delete_customer_without_orders(db):
    cid = db.add_customer(Customer(name="Удаляемый"))
    db.delete_customer(cid)
    assert db.get_customer(cid) is None


def test_cannot_delete_customer_with_orders(db):
    """Ключевое бизнес-правило: клиента с заказами удалять нельзя."""
    cid = db.add_customer(Customer(name="С заказом"))
    db.add_order(Order(customer_id=cid, items=[OrderItem("Товар", 1, 100)]))
    with pytest.raises(IntegrityError):
        db.delete_customer(cid)


# --------------------------- Заказы ----------------------------------------- #
def test_add_order_computes_total(db):
    cid = db.add_customer(Customer(name="К"))
    oid = db.add_order(Order(
        customer_id=cid,
        items=[OrderItem("Пицца", 2, 750), OrderItem("Кола", 1, 100)],
    ))
    order = db.get_order(oid)
    assert order.total == 1600.0
    assert len(order.items) == 2


def test_add_order_unknown_customer(db):
    with pytest.raises(IntegrityError):
        db.add_order(Order(customer_id=999, items=[OrderItem("X", 1, 10)]))


def test_update_order(db):
    cid = db.add_customer(Customer(name="К"))
    oid = db.add_order(Order(customer_id=cid, status="новый",
                             items=[OrderItem("A", 1, 100)]))
    order = db.get_order(oid)
    order.status = "выполнен"
    order.items = [OrderItem("B", 2, 200)]
    db.update_order(order)
    updated = db.get_order(oid)
    assert updated.status == "выполнен"
    assert updated.total == 400.0


def test_delete_order(db):
    cid = db.add_customer(Customer(name="К"))
    oid = db.add_order(Order(customer_id=cid, items=[OrderItem("A", 1, 100)]))
    db.delete_order(oid)
    assert db.get_order(oid) is None


def test_filter_orders_by_status(db):
    cid = db.add_customer(Customer(name="К"))
    db.add_order(Order(customer_id=cid, status="новый", items=[OrderItem("A", 1, 10)]))
    db.add_order(Order(customer_id=cid, status="выполнен", items=[OrderItem("B", 1, 20)]))
    done = db.list_orders(status="выполнен")
    assert len(done) == 1
    assert done[0].status == "выполнен"


def test_filter_orders_by_date(db):
    cid = db.add_customer(Customer(name="К"))
    db.add_order(Order(customer_id=cid, order_date="2025-01-01", items=[OrderItem("A", 1, 10)]))
    db.add_order(Order(customer_id=cid, order_date="2025-06-01", items=[OrderItem("B", 1, 20)]))
    res = db.list_orders(date_from="2025-03-01")
    assert len(res) == 1
    assert res[0].order_date == "2025-06-01"


# --------------------------- Аналитика -------------------------------------- #
def test_count_by_status(db):
    cid = db.add_customer(Customer(name="К"))
    db.add_order(Order(customer_id=cid, status="новый", items=[OrderItem("A", 1, 10)]))
    db.add_order(Order(customer_id=cid, status="новый", items=[OrderItem("B", 1, 20)]))
    db.add_order(Order(customer_id=cid, status="отменён", items=[OrderItem("C", 1, 30)]))
    counts = db.count_by_status()
    assert counts["новый"] == 2
    assert counts["отменён"] == 1
    assert counts["выполнен"] == 0


def test_top_customers(db):
    c1 = db.add_customer(Customer(name="Богатый"))
    c2 = db.add_customer(Customer(name="Скромный"))
    db.add_order(Order(customer_id=c1, items=[OrderItem("A", 10, 1000)]))  # 10000
    db.add_order(Order(customer_id=c2, items=[OrderItem("B", 1, 50)]))     # 50
    top = db.top_customers(3)
    assert top[0]["name"] == "Богатый"
    assert top[0]["total"] == 10000.0


def test_revenue_for_period_excludes_cancelled(db):
    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d")
    cid = db.add_customer(Customer(name="К"))
    db.add_order(Order(customer_id=cid, order_date=today, status="выполнен",
                       items=[OrderItem("A", 1, 1000)]))
    db.add_order(Order(customer_id=cid, order_date=today, status="отменён",
                       items=[OrderItem("B", 1, 5000)]))
    rev = db.revenue_for_period("month")
    assert rev["revenue"] == 1000.0  # отменённый заказ не учитывается
    assert rev["orders"] == 1


def test_revenue_invalid_period(db):
    with pytest.raises(ValueError):
        db.revenue_for_period("year")
