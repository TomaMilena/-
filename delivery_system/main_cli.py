"""
main_cli.py
===========
CLI-точка входа системы учёта заказов (argparse).

Примеры:
    # Отчёт за период
    python main_cli.py report --period month

    # Экспорт всех заказов (формат — по расширению файла)
    python main_cli.py export --file orders_backup.xml
    python main_cli.py export --file orders_backup.json

    # Импорт заказов с проверкой корректности
    python main_cli.py import --file orders_new.xml
    python main_cli.py import --file orders_new.json

    # Управление клиентами
    python main_cli.py customer add --name "Иван" --phone "+7..." --address "..."
    python main_cli.py customer list

    # Управление заказами
    python main_cli.py order list --status новый
    python main_cli.py order add --customer 1 --date 2025-04-20 \\
        --item "Пицца:2:750" --item "Кола:1:120"

Выбор бэкенда БД: глобальный флаг --backend sqlite|tinydb
(или переменная окружения DELIVERY_BACKEND).
"""

from __future__ import annotations

import argparse
import sys

from database import get_database, IntegrityError
from data_export import export_orders, import_orders, ImportError_
from models import Customer, Order, OrderItem, ValidationError, ORDER_STATUSES
from logger_config import get_logger

log = get_logger("cli")


# --------------------------------------------------------------------------- #
# Парсер
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="delivery",
        description="Система учёта заказов «Быстрая доставка» (CLI-режим)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--backend",
        choices=("sqlite", "tinydb"),
        default=None,
        help="Бэкенд БД (по умолчанию sqlite либо DELIVERY_BACKEND)",
    )
    parser.add_argument("--db", default=None, help="Путь к файлу БД (опционально)")

    sub = parser.add_subparsers(dest="command", required=True)

    # report
    p_report = sub.add_parser("report", help="Отчёты и аналитика")
    p_report.add_argument(
        "--period", choices=("day", "week", "month"), default="month",
        help="Период для расчёта выручки",
    )

    # export
    p_export = sub.add_parser("export", help="Экспорт заказов в XML/JSON")
    p_export.add_argument("--file", required=True, help="Путь к файлу (.xml/.json)")
    p_export.add_argument("--format", choices=("xml", "json"), default=None)

    # import
    p_import = sub.add_parser("import", help="Импорт заказов из XML/JSON")
    p_import.add_argument("--file", required=True, help="Путь к файлу (.xml/.json)")
    p_import.add_argument("--format", choices=("xml", "json"), default=None)

    # customer
    p_cust = sub.add_parser("customer", help="Управление клиентами")
    cust_sub = p_cust.add_subparsers(dest="action", required=True)
    c_add = cust_sub.add_parser("add", help="Добавить клиента")
    c_add.add_argument("--name", required=True)
    c_add.add_argument("--phone", default="")
    c_add.add_argument("--address", default="")
    cust_sub.add_parser("list", help="Список клиентов")
    c_del = cust_sub.add_parser("delete", help="Удалить клиента")
    c_del.add_argument("--id", type=int, required=True)

    # order
    p_order = sub.add_parser("order", help="Управление заказами")
    order_sub = p_order.add_subparsers(dest="action", required=True)
    o_add = order_sub.add_parser("add", help="Добавить заказ")
    o_add.add_argument("--customer", type=int, required=True)
    o_add.add_argument("--date", default=None, help="Дата ГГГГ-ММ-ДД (по умолчанию сегодня)")
    o_add.add_argument("--status", choices=ORDER_STATUSES, default="новый")
    o_add.add_argument(
        "--item", action="append", default=[],
        help="Позиция в формате 'название:количество:цена' (можно несколько раз)",
    )
    o_list = order_sub.add_parser("list", help="Список заказов")
    o_list.add_argument("--status", choices=ORDER_STATUSES, default=None)
    o_list.add_argument("--date-from", default=None)
    o_list.add_argument("--date-to", default=None)
    o_del = order_sub.add_parser("delete", help="Удалить заказ")
    o_del.add_argument("--id", type=int, required=True)

    return parser


# --------------------------------------------------------------------------- #
# Обработчики команд
# --------------------------------------------------------------------------- #
def cmd_report(db, args) -> None:
    print("\n=== ОТЧЁТ ПО ЗАКАЗАМ ===\n")

    print("Заказы по статусам:")
    for status, count in db.count_by_status().items():
        print(f"  {status:<12} : {count}")

    print("\nТоп-3 клиента по сумме заказов:")
    top = db.top_customers(3)
    if not top:
        print("  (нет данных)")
    for i, row in enumerate(top, start=1):
        print(f"  {i}. {row['name']:<20} — {row['total']:.2f}")

    rev = db.revenue_for_period(args.period)
    print(f"\nВыручка за период '{rev['period']}' (с {rev['since']}):")
    print(f"  заказов: {rev['orders']}, выручка: {rev['revenue']:.2f}\n")


def cmd_export(db, args) -> None:
    n = export_orders(db, args.file, args.format)
    print(f"Экспортировано заказов: {n} -> {args.file}")


def cmd_import(db, args) -> None:
    stats = import_orders(db, args.file, args.format)
    print(f"Импорт из {args.file}:")
    print(f"  всего записей : {stats['total']}")
    print(f"  загружено     : {stats['imported']}")
    print(f"  пропущено     : {stats['skipped']}")
    for err in stats["errors"]:
        print(f"    ! {err}")


def cmd_customer(db, args) -> None:
    if args.action == "add":
        cust = Customer(name=args.name, phone=args.phone, address=args.address)
        cid = db.add_customer(cust)
        print(f"Клиент добавлен, id={cid}")
    elif args.action == "list":
        customers = db.list_customers()
        if not customers:
            print("(клиентов нет)")
        for c in customers:
            print(f"  #{c.id:<3} {c.name:<20} {c.phone:<16} {c.address}")
    elif args.action == "delete":
        db.delete_customer(args.id)
        print(f"Клиент id={args.id} удалён")


def _parse_item(spec: str) -> OrderItem:
    parts = spec.split(":")
    if len(parts) != 3:
        raise ValidationError(
            f"Неверный формат позиции {spec!r}, ожидается 'название:количество:цена'"
        )
    name, qty, price = parts
    return OrderItem(product_name=name.strip(), quantity=int(qty), price=float(price))


def cmd_order(db, args) -> None:
    if args.action == "add":
        items = [_parse_item(s) for s in args.item]
        order = Order(
            customer_id=args.customer,
            status=args.status,
            items=items,
        )
        if args.date:
            order.order_date = args.date
        oid = db.add_order(order)
        print(f"Заказ добавлен, id={oid}, сумма={order.total:.2f}")
    elif args.action == "list":
        orders = db.list_orders(
            status=args.status, date_from=args.date_from, date_to=args.date_to
        )
        if not orders:
            print("(заказов нет)")
        for o in orders:
            print(
                f"  #{o.id:<3} {o.order_date} | {o.status:<12} | "
                f"клиент={o.customer_id} | сумма={o.total:.2f} | позиций={len(o.items)}"
            )
    elif args.action == "delete":
        db.delete_order(args.id)
        print(f"Заказ id={args.id} удалён")


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    db = get_database(backend=args.backend, path=args.db)
    try:
        handlers = {
            "report": cmd_report,
            "export": cmd_export,
            "import": cmd_import,
            "customer": cmd_customer,
            "order": cmd_order,
        }
        handlers[args.command](db, args)
        return 0
    except (IntegrityError, ValidationError, ImportError_, ValueError) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        log.error("Ошибка выполнения команды %s: %s", args.command, exc)
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
