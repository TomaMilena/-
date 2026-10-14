"""
models.py
=========
Доменные модели системы учёта заказов: Customer, OrderItem, Order.

Модели — это «чистые» классы данных (без обращения к БД). Они умеют:
  * валидировать собственные поля;
  * сериализоваться в dict / из dict (для JSON, TinyDB, экспорта);
  * вычислять производные значения (например, сумму заказа).
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import List, Optional, Dict, Any

# Допустимые статусы заказа (соответствуют CHECK-ограничению в SQLite)
ORDER_STATUSES = ("новый", "в доставке", "выполнен", "отменён")


class ValidationError(ValueError):
    """Исключение, выбрасываемое при некорректных данных модели."""


# --------------------------------------------------------------------------- #
# Клиент
# --------------------------------------------------------------------------- #
@dataclass
class Customer:
    name: str
    phone: str = ""
    address: str = ""
    id: Optional[int] = None

    def validate(self) -> None:
        if not self.name or not str(self.name).strip():
            raise ValidationError("Имя клиента не может быть пустым")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "phone": self.phone,
            "address": self.address,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Customer":
        return cls(
            id=data.get("id"),
            name=data.get("name", ""),
            phone=data.get("phone", "") or "",
            address=data.get("address", "") or "",
        )


# --------------------------------------------------------------------------- #
# Позиция заказа
# --------------------------------------------------------------------------- #
@dataclass
class OrderItem:
    product_name: str
    quantity: int = 1
    price: float = 0.0
    id: Optional[int] = None

    def validate(self) -> None:
        if not self.product_name or not str(self.product_name).strip():
            raise ValidationError("Название товара не может быть пустым")
        if int(self.quantity) <= 0:
            raise ValidationError("Количество товара должно быть положительным")
        if float(self.price) < 0:
            raise ValidationError("Цена товара не может быть отрицательной")

    @property
    def subtotal(self) -> float:
        """Стоимость позиции = количество * цена."""
        return float(self.quantity) * float(self.price)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "product_name": self.product_name,
            "quantity": int(self.quantity),
            "price": float(self.price),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OrderItem":
        return cls(
            id=data.get("id"),
            product_name=data.get("product_name", ""),
            quantity=int(data.get("quantity", 1)),
            price=float(data.get("price", 0.0)),
        )


# --------------------------------------------------------------------------- #
# Заказ
# --------------------------------------------------------------------------- #
@dataclass
class Order:
    customer_id: int
    order_date: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d"))
    status: str = "новый"
    items: List[OrderItem] = field(default_factory=list)
    total: Optional[float] = None
    id: Optional[int] = None

    def validate(self) -> None:
        if self.customer_id is None:
            raise ValidationError("Заказ должен быть привязан к клиенту")
        if self.status not in ORDER_STATUSES:
            raise ValidationError(
                f"Недопустимый статус заказа: {self.status!r}. "
                f"Разрешены: {', '.join(ORDER_STATUSES)}"
            )
        # Проверка формата даты
        try:
            datetime.strptime(self.order_date, "%Y-%m-%d")
        except (ValueError, TypeError):
            raise ValidationError(
                f"Дата заказа должна быть в формате ГГГГ-ММ-ДД, получено {self.order_date!r}"
            )
        for item in self.items:
            item.validate()

    def compute_total(self) -> float:
        """Пересчитывает и возвращает итоговую сумму по позициям."""
        self.total = round(sum(item.subtotal for item in self.items), 2)
        return self.total

    def to_dict(self) -> Dict[str, Any]:
        if self.total is None:
            self.compute_total()
        return {
            "id": self.id,
            "customer_id": self.customer_id,
            "order_date": self.order_date,
            "status": self.status,
            "total": float(self.total),
            "items": [item.to_dict() for item in self.items],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Order":
        items = [OrderItem.from_dict(i) for i in data.get("items", [])]
        order = cls(
            id=data.get("id"),
            customer_id=data.get("customer_id"),
            order_date=data.get("order_date", datetime.now().strftime("%Y-%m-%d")),
            status=data.get("status", "новый"),
            items=items,
            total=data.get("total"),
        )
        if order.total is None:
            order.compute_total()
        return order
