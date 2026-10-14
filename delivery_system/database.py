"""
database.py
===========
Слой доступа к данным системы учёта заказов.

Поддерживаются ДВА взаимозаменяемых бэкенда (бонус «поддержка двух БД»):

  * SQLiteDatabase  — на встроенном модуле sqlite3 (вариант А ТЗ);
  * TinyDBDatabase  — на TinyDB, внешние ключи и JOIN эмулируются
                      программно фильтрацией списков (вариант Б ТЗ).

Выбор бэкенда:
  * через переменную окружения DELIVERY_BACKEND = "sqlite" | "tinydb";
  * либо явно через фабрику get_database(backend=...).

Оба класса реализуют единый интерфейс (абстрактный класс Database), что
позволяет CLI, GUI и тестам работать с любым бэкендом без изменений.

Бизнес-правила:
  * Клиента нельзя удалить, пока на него ссылается хотя бы один заказ
    (ON DELETE RESTRICT в SQLite, ручная проверка в TinyDB).
"""

from __future__ import annotations

import abc
import os
import sqlite3
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any

from models import Customer, Order, OrderItem, ORDER_STATUSES, ValidationError
from logger_config import get_logger

log = get_logger("database")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DEFAULT_SQLITE_PATH = os.path.join(DATA_DIR, "delivery.db")
DEFAULT_TINYDB_PATH = os.path.join(DATA_DIR, "tinydb.json")


class IntegrityError(Exception):
    """Нарушение целостности данных (например, удаление клиента с заказами)."""


# =========================================================================== #
# Абстрактный интерфейс
# =========================================================================== #
class Database(abc.ABC):
    """Единый интерфейс хранилища для клиентов и заказов."""

    # ---- Клиенты -------------------------------------------------------- #
    @abc.abstractmethod
    def add_customer(self, customer: Customer) -> int: ...

    @abc.abstractmethod
    def get_customer(self, customer_id: int) -> Optional[Customer]: ...

    @abc.abstractmethod
    def list_customers(self) -> List[Customer]: ...

    @abc.abstractmethod
    def update_customer(self, customer: Customer) -> None: ...

    @abc.abstractmethod
    def delete_customer(self, customer_id: int) -> None: ...

    # ---- Заказы --------------------------------------------------------- #
    @abc.abstractmethod
    def add_order(self, order: Order) -> int: ...

    @abc.abstractmethod
    def get_order(self, order_id: int) -> Optional[Order]: ...

    @abc.abstractmethod
    def list_orders(
        self,
        status: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> List[Order]: ...

    @abc.abstractmethod
    def update_order(self, order: Order) -> None: ...

    @abc.abstractmethod
    def delete_order(self, order_id: int) -> None: ...

    @abc.abstractmethod
    def close(self) -> None: ...

    # ---- Аналитика (общая реализация поверх list_orders) ---------------- #
    def count_by_status(self) -> Dict[str, int]:
        """Количество заказов по каждому статусу."""
        result = {s: 0 for s in ORDER_STATUSES}
        for order in self.list_orders():
            result[order.status] = result.get(order.status, 0) + 1
        return result

    def top_customers(self, limit: int = 3) -> List[Dict[str, Any]]:
        """Топ клиентов по суммарной стоимости заказов."""
        totals: Dict[int, float] = {}
        for order in self.list_orders():
            order.compute_total()
            totals[order.customer_id] = totals.get(order.customer_id, 0.0) + order.total
        ranked = sorted(totals.items(), key=lambda kv: kv[1], reverse=True)[:limit]
        out: List[Dict[str, Any]] = []
        for cid, total in ranked:
            cust = self.get_customer(cid)
            out.append(
                {
                    "customer_id": cid,
                    "name": cust.name if cust else f"(удалён #{cid})",
                    "total": round(total, 2),
                }
            )
        return out

    def revenue_for_period(self, period: str = "month") -> Dict[str, Any]:
        """
        Общая выручка за период: 'day' | 'week' | 'month'.
        Учитываются только заказы со статусом, отличным от «отменён».
        """
        period = (period or "month").lower()
        days = {"day": 1, "week": 7, "month": 30}.get(period)
        if days is None:
            raise ValueError("period должен быть одним из: day, week, month")

        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        revenue = 0.0
        count = 0
        for order in self.list_orders(date_from=cutoff):
            if order.status == "отменён":
                continue
            order.compute_total()
            revenue += order.total
            count += 1
        return {
            "period": period,
            "since": cutoff,
            "orders": count,
            "revenue": round(revenue, 2),
        }


# =========================================================================== #
# Реализация на SQLite
# =========================================================================== #
class SQLiteDatabase(Database):
    def __init__(self, path: str = DEFAULT_SQLITE_PATH):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")  # включаем внешние ключи
        self._create_schema()
        log.info("SQLite-хранилище открыто: %s", path)

    def _create_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS customers (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                name    TEXT NOT NULL,
                phone   TEXT,
                address TEXT
            );

            CREATE TABLE IF NOT EXISTS orders (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id INTEGER REFERENCES customers(id) ON DELETE RESTRICT,
                order_date  TEXT NOT NULL,
                status      TEXT CHECK(status IN ('новый','в доставке','выполнен','отменён')),
                total       REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS order_items (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id     INTEGER REFERENCES orders(id) ON DELETE CASCADE,
                product_name TEXT,
                quantity     INTEGER,
                price        REAL
            );
            """
        )
        self.conn.commit()

    # ---- Клиенты -------------------------------------------------------- #
    def add_customer(self, customer: Customer) -> int:
        customer.validate()
        cur = self.conn.execute(
            "INSERT INTO customers (name, phone, address) VALUES (?, ?, ?)",
            (customer.name, customer.phone, customer.address),
        )
        self.conn.commit()
        customer.id = cur.lastrowid
        log.info("Добавлен клиент id=%s name=%s", customer.id, customer.name)
        return customer.id

    def get_customer(self, customer_id: int) -> Optional[Customer]:
        row = self.conn.execute(
            "SELECT * FROM customers WHERE id = ?", (customer_id,)
        ).fetchone()
        if row is None:
            return None
        return Customer(id=row["id"], name=row["name"], phone=row["phone"] or "",
                        address=row["address"] or "")

    def list_customers(self) -> List[Customer]:
        rows = self.conn.execute("SELECT * FROM customers ORDER BY id").fetchall()
        return [
            Customer(id=r["id"], name=r["name"], phone=r["phone"] or "",
                     address=r["address"] or "")
            for r in rows
        ]

    def update_customer(self, customer: Customer) -> None:
        customer.validate()
        if customer.id is None:
            raise ValidationError("Для обновления требуется id клиента")
        self.conn.execute(
            "UPDATE customers SET name = ?, phone = ?, address = ? WHERE id = ?",
            (customer.name, customer.phone, customer.address, customer.id),
        )
        self.conn.commit()
        log.info("Обновлён клиент id=%s", customer.id)

    def delete_customer(self, customer_id: int) -> None:
        # Проверяем наличие заказов вручную, чтобы выдать понятную ошибку
        cnt = self.conn.execute(
            "SELECT COUNT(*) AS c FROM orders WHERE customer_id = ?", (customer_id,)
        ).fetchone()["c"]
        if cnt > 0:
            raise IntegrityError(
                f"Нельзя удалить клиента id={customer_id}: у него есть заказы ({cnt})"
            )
        self.conn.execute("DELETE FROM customers WHERE id = ?", (customer_id,))
        self.conn.commit()
        log.info("Удалён клиент id=%s", customer_id)

    # ---- Заказы --------------------------------------------------------- #
    def add_order(self, order: Order) -> int:
        order.compute_total()
        order.validate()
        if self.get_customer(order.customer_id) is None:
            raise IntegrityError(f"Клиент id={order.customer_id} не существует")
        cur = self.conn.execute(
            "INSERT INTO orders (customer_id, order_date, status, total) "
            "VALUES (?, ?, ?, ?)",
            (order.customer_id, order.order_date, order.status, order.total),
        )
        order.id = cur.lastrowid
        for item in order.items:
            self.conn.execute(
                "INSERT INTO order_items (order_id, product_name, quantity, price) "
                "VALUES (?, ?, ?, ?)",
                (order.id, item.product_name, item.quantity, item.price),
            )
        self.conn.commit()
        log.info("Добавлен заказ id=%s на сумму %.2f", order.id, order.total)
        return order.id

    def _load_items(self, order_id: int) -> List[OrderItem]:
        rows = self.conn.execute(
            "SELECT * FROM order_items WHERE order_id = ?", (order_id,)
        ).fetchall()
        return [
            OrderItem(id=r["id"], product_name=r["product_name"],
                      quantity=r["quantity"], price=r["price"])
            for r in rows
        ]

    def _row_to_order(self, row: sqlite3.Row) -> Order:
        return Order(
            id=row["id"],
            customer_id=row["customer_id"],
            order_date=row["order_date"],
            status=row["status"],
            total=row["total"],
            items=self._load_items(row["id"]),
        )

    def get_order(self, order_id: int) -> Optional[Order]:
        row = self.conn.execute(
            "SELECT * FROM orders WHERE id = ?", (order_id,)
        ).fetchone()
        return self._row_to_order(row) if row else None

    def list_orders(self, status=None, date_from=None, date_to=None) -> List[Order]:
        query = "SELECT * FROM orders WHERE 1=1"
        params: List[Any] = []
        if status:
            query += " AND status = ?"
            params.append(status)
        if date_from:
            query += " AND order_date >= ?"
            params.append(date_from)
        if date_to:
            query += " AND order_date <= ?"
            params.append(date_to)
        query += " ORDER BY order_date DESC, id DESC"
        rows = self.conn.execute(query, params).fetchall()
        return [self._row_to_order(r) for r in rows]

    def update_order(self, order: Order) -> None:
        if order.id is None:
            raise ValidationError("Для обновления требуется id заказа")
        order.compute_total()
        order.validate()
        self.conn.execute(
            "UPDATE orders SET customer_id = ?, order_date = ?, status = ?, total = ? "
            "WHERE id = ?",
            (order.customer_id, order.order_date, order.status, order.total, order.id),
        )
        # Полностью пересоздаём позиции заказа
        self.conn.execute("DELETE FROM order_items WHERE order_id = ?", (order.id,))
        for item in order.items:
            self.conn.execute(
                "INSERT INTO order_items (order_id, product_name, quantity, price) "
                "VALUES (?, ?, ?, ?)",
                (order.id, item.product_name, item.quantity, item.price),
            )
        self.conn.commit()
        log.info("Обновлён заказ id=%s", order.id)

    def delete_order(self, order_id: int) -> None:
        self.conn.execute("DELETE FROM order_items WHERE order_id = ?", (order_id,))
        self.conn.execute("DELETE FROM orders WHERE id = ?", (order_id,))
        self.conn.commit()
        log.info("Удалён заказ id=%s", order_id)

    def close(self) -> None:
        self.conn.close()


# =========================================================================== #
# Реализация на TinyDB
# =========================================================================== #
class TinyDBDatabase(Database):
    def __init__(self, path: str = DEFAULT_TINYDB_PATH):
        try:
            from tinydb import TinyDB, Query
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "Для бэкенда TinyDB установите пакет: pip install tinydb"
            ) from exc

        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.path = path
        self._Query = Query
        self.db = TinyDB(path, ensure_ascii=False, indent=2, encoding="utf-8")
        self.customers_tbl = self.db.table("customers")
        self.orders_tbl = self.db.table("orders")
        log.info("TinyDB-хранилище открыто: %s", path)

    def _next_id(self, table) -> int:
        existing = [doc.get("id", 0) for doc in table.all()]
        return (max(existing) + 1) if existing else 1

    # ---- Клиенты -------------------------------------------------------- #
    def add_customer(self, customer: Customer) -> int:
        customer.validate()
        customer.id = self._next_id(self.customers_tbl)
        self.customers_tbl.insert(customer.to_dict())
        log.info("Добавлен клиент id=%s name=%s", customer.id, customer.name)
        return customer.id

    def get_customer(self, customer_id: int) -> Optional[Customer]:
        Q = self._Query()
        doc = self.customers_tbl.get(Q.id == customer_id)
        return Customer.from_dict(doc) if doc else None

    def list_customers(self) -> List[Customer]:
        docs = sorted(self.customers_tbl.all(), key=lambda d: d.get("id", 0))
        return [Customer.from_dict(d) for d in docs]

    def update_customer(self, customer: Customer) -> None:
        customer.validate()
        if customer.id is None:
            raise ValidationError("Для обновления требуется id клиента")
        Q = self._Query()
        self.customers_tbl.update(customer.to_dict(), Q.id == customer.id)
        log.info("Обновлён клиент id=%s", customer.id)

    def delete_customer(self, customer_id: int) -> None:
        Q = self._Query()
        # Эмуляция ON DELETE RESTRICT: ищем зависимые заказы
        related = self.orders_tbl.count(Q.customer_id == customer_id)
        if related > 0:
            raise IntegrityError(
                f"Нельзя удалить клиента id={customer_id}: у него есть заказы ({related})"
            )
        self.customers_tbl.remove(Q.id == customer_id)
        log.info("Удалён клиент id=%s", customer_id)

    # ---- Заказы --------------------------------------------------------- #
    def add_order(self, order: Order) -> int:
        order.compute_total()
        order.validate()
        if self.get_customer(order.customer_id) is None:
            raise IntegrityError(f"Клиент id={order.customer_id} не существует")
        order.id = self._next_id(self.orders_tbl)
        self.orders_tbl.insert(order.to_dict())
        log.info("Добавлен заказ id=%s на сумму %.2f", order.id, order.total)
        return order.id

    def get_order(self, order_id: int) -> Optional[Order]:
        Q = self._Query()
        doc = self.orders_tbl.get(Q.id == order_id)
        return Order.from_dict(doc) if doc else None

    def list_orders(self, status=None, date_from=None, date_to=None) -> List[Order]:
        orders = [Order.from_dict(d) for d in self.orders_tbl.all()]
        # JOIN/фильтрация эмулируются программно
        if status:
            orders = [o for o in orders if o.status == status]
        if date_from:
            orders = [o for o in orders if o.order_date >= date_from]
        if date_to:
            orders = [o for o in orders if o.order_date <= date_to]
        orders.sort(key=lambda o: (o.order_date, o.id or 0), reverse=True)
        return orders

    def update_order(self, order: Order) -> None:
        if order.id is None:
            raise ValidationError("Для обновления требуется id заказа")
        order.compute_total()
        order.validate()
        Q = self._Query()
        self.orders_tbl.update(order.to_dict(), Q.id == order.id)
        log.info("Обновлён заказ id=%s", order.id)

    def delete_order(self, order_id: int) -> None:
        Q = self._Query()
        self.orders_tbl.remove(Q.id == order_id)
        log.info("Удалён заказ id=%s", order_id)

    def close(self) -> None:
        self.db.close()


# =========================================================================== #
# Фабрика
# =========================================================================== #
def get_database(backend: Optional[str] = None, path: Optional[str] = None) -> Database:
    """
    Возвращает экземпляр хранилища нужного типа.

    backend: 'sqlite' (по умолчанию) или 'tinydb'.
             Если не задан — берётся из переменной окружения DELIVERY_BACKEND.
    path:    путь к файлу БД (опционально).
    """
    backend = (backend or os.environ.get("DELIVERY_BACKEND", "sqlite")).lower()
    if backend == "sqlite":
        return SQLiteDatabase(path or DEFAULT_SQLITE_PATH)
    if backend == "tinydb":
        return TinyDBDatabase(path or DEFAULT_TINYDB_PATH)
    raise ValueError(f"Неизвестный бэкенд БД: {backend!r} (ожидается sqlite|tinydb)")
