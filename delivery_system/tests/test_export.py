"""
Тесты экспорта/импорта (data_export.py) для обоих форматов: JSON и XML.
"""

import pytest

from database import get_database
from data_export import export_orders, import_orders, ImportError_, _detect_format
from models import Customer, Order, OrderItem


@pytest.fixture
def db(tmp_path):
    database = get_database(backend="sqlite", path=str(tmp_path / "exp.db"))
    yield database
    database.close()


@pytest.fixture
def populated_db(db):
    cid = db.add_customer(Customer(name="Иван", phone="111", address="Москва"))
    db.add_order(Order(customer_id=cid, order_date="2025-04-20", status="новый",
                       items=[OrderItem("Пицца", 2, 750), OrderItem("Кола", 1, 120)]))
    db.add_order(Order(customer_id=cid, order_date="2025-04-21", status="выполнен",
                       items=[OrderItem("Суши", 1, 500)]))
    return db, cid


# --------------------------- Определение формата ---------------------------- #
def test_detect_format_by_extension():
    assert _detect_format("a.json", None) == "json"
    assert _detect_format("a.xml", None) == "xml"


def test_detect_format_explicit():
    assert _detect_format("a.txt", "json") == "json"


def test_detect_format_unknown():
    with pytest.raises(ValueError):
        _detect_format("a.txt", None)


# --------------------------- JSON ------------------------------------------- #
def test_export_import_json(populated_db, tmp_path):
    db, cid = populated_db
    path = str(tmp_path / "orders.json")
    n = export_orders(db, path)
    assert n == 2

    # Импортируем в новую БД (с тем же клиентом)
    db2 = get_database(backend="sqlite", path=str(tmp_path / "new.db"))
    db2.add_customer(Customer(name="Иван"))  # получит id=1
    stats = import_orders(db2, path)
    assert stats["imported"] == 2
    assert stats["skipped"] == 0
    assert len(db2.list_orders()) == 2
    db2.close()


# --------------------------- XML -------------------------------------------- #
def test_export_import_xml(populated_db, tmp_path):
    db, cid = populated_db
    path = str(tmp_path / "orders.xml")
    n = export_orders(db, path)
    assert n == 2

    db2 = get_database(backend="sqlite", path=str(tmp_path / "new2.db"))
    db2.add_customer(Customer(name="Иван"))
    stats = import_orders(db2, path)
    assert stats["imported"] == 2
    # Проверяем, что сумма заказа сохранилась корректно
    orders = db2.list_orders()
    totals = sorted(o.total for o in orders)
    assert totals == [500.0, 1620.0]
    db2.close()


# --------------------------- Проверки корректности импорта ------------------ #
def test_import_skips_unknown_customer(db, tmp_path):
    """Заказ на несуществующего клиента должен быть пропущен."""
    path = str(tmp_path / "bad.json")
    src = get_database(backend="sqlite", path=str(tmp_path / "src.db"))
    cid = src.add_customer(Customer(name="Кто-то"))
    src.add_order(Order(customer_id=cid, items=[OrderItem("A", 1, 10)]))
    export_orders(src, path)
    src.close()

    # В целевой БД клиента нет -> запись пропускается
    stats = import_orders(db, path)
    assert stats["imported"] == 0
    assert stats["skipped"] == 1
    assert stats["errors"]


def test_import_missing_file(db):
    with pytest.raises(ImportError_):
        import_orders(db, "/nonexistent/path/orders.json")


def test_import_bad_xml(db, tmp_path):
    path = tmp_path / "broken.xml"
    path.write_text("<orders><order></orders>", encoding="utf-8")  # незакрытый тег
    with pytest.raises(ImportError_):
        import_orders(db, str(path))


def test_import_wrong_xml_root(db, tmp_path):
    path = tmp_path / "wrong.xml"
    path.write_text("<root></root>", encoding="utf-8")
    with pytest.raises(ImportError_):
        import_orders(db, str(path))
