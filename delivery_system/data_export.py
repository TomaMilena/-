"""
data_export.py
==============
Экспорт и импорт заказов в форматах JSON и XML (бонус: оба формата).

Формат файла определяется по расширению (.json / .xml) либо явным аргументом.
При импорте выполняется проверка корректности данных:
  * структура файла;
  * валидация каждой модели Order/OrderItem;
  * существование клиента (заказ привязывается к существующему клиенту).

Публичные функции:
  export_orders(db, file_path, fmt=None)  -> int (число выгруженных заказов)
  import_orders(db, file_path, fmt=None)  -> dict (статистика импорта)
"""

from __future__ import annotations

import json
import os
import xml.etree.ElementTree as ET
from typing import List, Optional, Dict, Any
from xml.dom import minidom

from models import Order, OrderItem, ValidationError
from logger_config import get_logger

log = get_logger("data_export")


class ImportError_(Exception):
    """Ошибка при импорте данных (некорректный файл/структура)."""


# --------------------------------------------------------------------------- #
# Вспомогательное: определение формата
# --------------------------------------------------------------------------- #
def _detect_format(file_path: str, fmt: Optional[str]) -> str:
    if fmt:
        fmt = fmt.lower()
        if fmt not in ("json", "xml"):
            raise ValueError("fmt должен быть 'json' или 'xml'")
        return fmt
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".json":
        return "json"
    if ext == ".xml":
        return "xml"
    raise ValueError(
        f"Не удалось определить формат по расширению {ext!r}. "
        "Используйте .json/.xml или укажите fmt явно."
    )


# --------------------------------------------------------------------------- #
# JSON
# --------------------------------------------------------------------------- #
def _orders_to_json(orders: List[Order], file_path: str) -> None:
    payload = {"orders": [o.to_dict() for o in orders]}
    with open(file_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)


def _orders_from_json(file_path: str) -> List[Dict[str, Any]]:
    with open(file_path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if isinstance(data, dict):
        orders = data.get("orders", [])
    elif isinstance(data, list):
        orders = data
    else:
        raise ImportError_("Некорректная структура JSON: ожидался объект или список")
    if not isinstance(orders, list):
        raise ImportError_("Поле 'orders' должно быть списком")
    return orders


# --------------------------------------------------------------------------- #
# XML
# --------------------------------------------------------------------------- #
def _orders_to_xml(orders: List[Order], file_path: str) -> None:
    root = ET.Element("orders")
    for o in orders:
        d = o.to_dict()
        order_el = ET.SubElement(root, "order")
        order_el.set("id", str(d.get("id", "")))
        ET.SubElement(order_el, "customer_id").text = str(d["customer_id"])
        ET.SubElement(order_el, "order_date").text = str(d["order_date"])
        ET.SubElement(order_el, "status").text = str(d["status"])
        ET.SubElement(order_el, "total").text = str(d["total"])
        items_el = ET.SubElement(order_el, "items")
        for it in d["items"]:
            item_el = ET.SubElement(items_el, "item")
            ET.SubElement(item_el, "product_name").text = str(it["product_name"])
            ET.SubElement(item_el, "quantity").text = str(it["quantity"])
            ET.SubElement(item_el, "price").text = str(it["price"])

    # Красивое форматирование
    rough = ET.tostring(root, encoding="utf-8")
    pretty = minidom.parseString(rough).toprettyxml(indent="  ", encoding="utf-8")
    with open(file_path, "wb") as fh:
        fh.write(pretty)


def _orders_from_xml(file_path: str) -> List[Dict[str, Any]]:
    try:
        tree = ET.parse(file_path)
    except ET.ParseError as exc:
        raise ImportError_(f"Некорректный XML-файл: {exc}") from exc
    root = tree.getroot()
    if root.tag != "orders":
        raise ImportError_("Корневой элемент XML должен называться <orders>")

    result: List[Dict[str, Any]] = []
    for order_el in root.findall("order"):
        def _text(tag: str, default: str = "") -> str:
            node = order_el.find(tag)
            return node.text.strip() if node is not None and node.text else default

        items: List[Dict[str, Any]] = []
        items_el = order_el.find("items")
        if items_el is not None:
            for item_el in items_el.findall("item"):
                def _itext(tag: str, default: str = "") -> str:
                    node = item_el.find(tag)
                    return node.text.strip() if node is not None and node.text else default

                items.append(
                    {
                        "product_name": _itext("product_name"),
                        "quantity": int(_itext("quantity", "1")),
                        "price": float(_itext("price", "0")),
                    }
                )

        id_attr = order_el.get("id")
        order_dict: Dict[str, Any] = {
            "id": int(id_attr) if id_attr and id_attr.isdigit() else None,
            "customer_id": int(_text("customer_id", "0")),
            "order_date": _text("order_date"),
            "status": _text("status"),
            "total": float(_text("total", "0")),
            "items": items,
        }
        result.append(order_dict)
    return result


# --------------------------------------------------------------------------- #
# Публичные функции
# --------------------------------------------------------------------------- #
def export_orders(db, file_path: str, fmt: Optional[str] = None) -> int:
    """Выгружает все заказы из БД в файл. Возвращает количество заказов."""
    fmt = _detect_format(file_path, fmt)
    orders = db.list_orders()
    if fmt == "json":
        _orders_to_json(orders, file_path)
    else:
        _orders_to_xml(orders, file_path)
    log.info("Экспортировано %d заказов в %s (%s)", len(orders), file_path, fmt)
    return len(orders)


def import_orders(db, file_path: str, fmt: Optional[str] = None) -> Dict[str, Any]:
    """
    Импортирует заказы из файла с проверкой корректности.

    Возвращает статистику: {"total", "imported", "skipped", "errors"[]}.
    Некорректные записи пропускаются, ошибки собираются в список.
    """
    if not os.path.exists(file_path):
        raise ImportError_(f"Файл не найден: {file_path}")

    fmt = _detect_format(file_path, fmt)
    raw_orders = _orders_from_json(file_path) if fmt == "json" else _orders_from_xml(file_path)

    stats = {"total": len(raw_orders), "imported": 0, "skipped": 0, "errors": []}
    for idx, raw in enumerate(raw_orders, start=1):
        try:
            order = Order.from_dict(raw)
            order.id = None  # id присваивается хранилищем заново
            order.compute_total()
            order.validate()
            # Проверка существования клиента
            if db.get_customer(order.customer_id) is None:
                raise ValidationError(f"клиент id={order.customer_id} не найден")
            db.add_order(order)
            stats["imported"] += 1
        except (ValidationError, ValueError, KeyError, TypeError) as exc:
            stats["skipped"] += 1
            stats["errors"].append(f"Запись #{idx}: {exc}")
            log.warning("Пропущена запись #%d при импорте: %s", idx, exc)

    log.info(
        "Импорт завершён: всего=%d, загружено=%d, пропущено=%d",
        stats["total"], stats["imported"], stats["skipped"],
    )
    return stats
