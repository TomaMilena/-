"""
Тесты CLI-режима (main_cli.py) через вызов main() с аргументами.
Проверяют сквозные сценарии: добавление клиента/заказа, отчёт, экспорт/импорт.
"""

import pytest

import main_cli


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "cli.db")


def run(argv, db_path):
    """Вспомогательная обёртка: всегда указываем sqlite-бэкенд и временный файл."""
    return main_cli.main(["--backend", "sqlite", "--db", db_path] + argv)


def test_cli_customer_add_and_list(db_path, capsys):
    assert run(["customer", "add", "--name", "Иван", "--phone", "111"], db_path) == 0
    assert run(["customer", "list"], db_path) == 0
    out = capsys.readouterr().out
    assert "Иван" in out


def test_cli_order_add_and_list(db_path, capsys):
    run(["customer", "add", "--name", "Клиент"], db_path)
    rc = run(["order", "add", "--customer", "1", "--date", "2025-04-20",
              "--item", "Пицца:2:750", "--item", "Кола:1:120"], db_path)
    assert rc == 0
    run(["order", "list"], db_path)
    out = capsys.readouterr().out
    assert "1620.00" in out  # 2*750 + 1*120


def test_cli_report(db_path, capsys):
    run(["customer", "add", "--name", "К"], db_path)
    run(["order", "add", "--customer", "1", "--item", "A:1:1000"], db_path)
    rc = run(["report", "--period", "month"], db_path)
    assert rc == 0
    out = capsys.readouterr().out
    assert "ОТЧЁТ" in out
    assert "Топ-3" in out


def test_cli_export_import_roundtrip(db_path, tmp_path, capsys):
    run(["customer", "add", "--name", "К"], db_path)
    run(["order", "add", "--customer", "1", "--item", "A:2:100"], db_path)

    export_file = str(tmp_path / "orders.xml")
    assert run(["export", "--file", export_file], db_path) == 0

    # Импорт в новую БД с тем же клиентом
    db2 = str(tmp_path / "cli2.db")
    run(["customer", "add", "--name", "К"], db2)
    assert run(["import", "--file", export_file], db2) == 0
    out = capsys.readouterr().out
    assert "загружено" in out


def test_cli_delete_customer_with_orders_fails(db_path, capsys):
    run(["customer", "add", "--name", "К"], db_path)
    run(["order", "add", "--customer", "1", "--item", "A:1:10"], db_path)
    rc = run(["customer", "delete", "--id", "1"], db_path)
    assert rc == 1  # удаление должно завершиться ошибкой


def test_cli_bad_item_format(db_path, capsys):
    run(["customer", "add", "--name", "К"], db_path)
    rc = run(["order", "add", "--customer", "1", "--item", "плохой_формат"], db_path)
    assert rc == 1
