"""
main_gui.py
===========
GUI-точка входа системы учёта заказов (Tkinter).

Возможности:
  * список заказов в Treeview;
  * фильтр по статусу;
  * добавление / редактирование / удаление заказа через форму;
  * экспорт/импорт с выбором формата (XML/JSON);
  * кнопка «Показать отчёт» — статистика в отдельном окне.

Запуск:
    python main_gui.py
    python main_gui.py --backend tinydb
"""

from __future__ import annotations

import argparse
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from database import get_database, IntegrityError
from data_export import export_orders, import_orders
from models import Order, OrderItem, Customer, ORDER_STATUSES, ValidationError
from logger_config import get_logger

log = get_logger("gui")


class OrderForm(tk.Toplevel):
    """Модальная форма добавления/редактирования заказа."""

    def __init__(self, master, db, on_saved, order: Order = None):
        super().__init__(master)
        self.db = db
        self.on_saved = on_saved
        self.order = order
        self.title("Редактирование заказа" if order else "Новый заказ")
        self.geometry("520x520")
        self.resizable(False, False)
        self.grab_set()

        self.customers = self.db.list_customers()
        self._build()
        if order:
            self._fill_from_order(order)

    def _build(self) -> None:
        pad = {"padx": 8, "pady": 4}

        tk.Label(self, text="Клиент:").grid(row=0, column=0, sticky="w", **pad)
        self.customer_var = tk.StringVar()
        cust_labels = [f"{c.id}: {c.name}" for c in self.customers]
        self.customer_cb = ttk.Combobox(
            self, textvariable=self.customer_var, values=cust_labels, state="readonly", width=35
        )
        self.customer_cb.grid(row=0, column=1, **pad)
        if cust_labels:
            self.customer_cb.current(0)

        tk.Label(self, text="Дата (ГГГГ-ММ-ДД):").grid(row=1, column=0, sticky="w", **pad)
        self.date_var = tk.StringVar(value=Order(customer_id=0).order_date)
        tk.Entry(self, textvariable=self.date_var, width=37).grid(row=1, column=1, **pad)

        tk.Label(self, text="Статус:").grid(row=2, column=0, sticky="w", **pad)
        self.status_var = tk.StringVar(value="новый")
        ttk.Combobox(
            self, textvariable=self.status_var, values=list(ORDER_STATUSES),
            state="readonly", width=35,
        ).grid(row=2, column=1, **pad)

        # Позиции заказа
        tk.Label(self, text="Позиции (название / кол-во / цена):").grid(
            row=3, column=0, columnspan=2, sticky="w", **pad
        )
        self.items_tree = ttk.Treeview(
            self, columns=("name", "qty", "price"), show="headings", height=7
        )
        for col, txt, w in (("name", "Товар", 220), ("qty", "Кол-во", 80), ("price", "Цена", 100)):
            self.items_tree.heading(col, text=txt)
            self.items_tree.column(col, width=w)
        self.items_tree.grid(row=4, column=0, columnspan=2, **pad)

        add_frame = tk.Frame(self)
        add_frame.grid(row=5, column=0, columnspan=2, **pad)
        self.in_name = tk.Entry(add_frame, width=22)
        self.in_qty = tk.Entry(add_frame, width=6)
        self.in_price = tk.Entry(add_frame, width=8)
        self.in_name.grid(row=0, column=0, padx=2)
        self.in_qty.grid(row=0, column=1, padx=2)
        self.in_price.grid(row=0, column=2, padx=2)
        tk.Button(add_frame, text="+ позиция", command=self._add_item).grid(row=0, column=3, padx=4)
        tk.Button(add_frame, text="− убрать", command=self._remove_item).grid(row=0, column=4, padx=4)

        btns = tk.Frame(self)
        btns.grid(row=6, column=0, columnspan=2, pady=12)
        tk.Button(btns, text="Сохранить", command=self._save, width=14).grid(row=0, column=0, padx=6)
        tk.Button(btns, text="Отмена", command=self.destroy, width=14).grid(row=0, column=1, padx=6)

    def _add_item(self) -> None:
        try:
            name = self.in_name.get().strip()
            qty = int(self.in_qty.get())
            price = float(self.in_price.get())
            if not name:
                raise ValueError("название пустое")
            self.items_tree.insert("", "end", values=(name, qty, price))
            self.in_name.delete(0, "end")
            self.in_qty.delete(0, "end")
            self.in_price.delete(0, "end")
        except ValueError as exc:
            messagebox.showwarning("Позиция", f"Проверьте поля позиции: {exc}")

    def _remove_item(self) -> None:
        for iid in self.items_tree.selection():
            self.items_tree.delete(iid)

    def _fill_from_order(self, order: Order) -> None:
        for i, c in enumerate(self.customers):
            if c.id == order.customer_id:
                self.customer_cb.current(i)
                break
        self.date_var.set(order.order_date)
        self.status_var.set(order.status)
        for it in order.items:
            self.items_tree.insert("", "end", values=(it.product_name, it.quantity, it.price))

    def _collect_items(self):
        items = []
        for iid in self.items_tree.get_children():
            name, qty, price = self.items_tree.item(iid, "values")
            items.append(OrderItem(product_name=name, quantity=int(qty), price=float(price)))
        return items

    def _save(self) -> None:
        try:
            if not self.customer_var.get():
                raise ValidationError("Не выбран клиент")
            customer_id = int(self.customer_var.get().split(":")[0])
            items = self._collect_items()
            if self.order:  # редактирование
                self.order.customer_id = customer_id
                self.order.order_date = self.date_var.get().strip()
                self.order.status = self.status_var.get()
                self.order.items = items
                self.db.update_order(self.order)
            else:  # создание
                order = Order(
                    customer_id=customer_id,
                    order_date=self.date_var.get().strip(),
                    status=self.status_var.get(),
                    items=items,
                )
                self.db.add_order(order)
            self.on_saved()
            self.destroy()
        except (ValidationError, ValueError, IntegrityError) as exc:
            messagebox.showerror("Ошибка сохранения", str(exc))


class App(tk.Tk):
    def __init__(self, db):
        super().__init__()
        self.db = db
        self.title("Быстрая доставка — учёт заказов")
        self.geometry("820x520")
        self._build()
        self.refresh()

    def _build(self) -> None:
        top = tk.Frame(self)
        top.pack(fill="x", padx=10, pady=8)

        tk.Label(top, text="Фильтр по статусу:").pack(side="left")
        self.filter_var = tk.StringVar(value="(все)")
        ttk.Combobox(
            top, textvariable=self.filter_var,
            values=["(все)"] + list(ORDER_STATUSES), state="readonly", width=16,
        ).pack(side="left", padx=6)
        tk.Button(top, text="Применить", command=self.refresh).pack(side="left", padx=4)

        tk.Label(top, text="  Формат:").pack(side="left", padx=(16, 0))
        self.fmt_var = tk.StringVar(value="json")
        ttk.Combobox(
            top, textvariable=self.fmt_var, values=["json", "xml"],
            state="readonly", width=6,
        ).pack(side="left", padx=4)
        tk.Button(top, text="Экспорт", command=self.export_orders).pack(side="left", padx=2)
        tk.Button(top, text="Импорт", command=self.import_orders).pack(side="left", padx=2)

        # Таблица заказов
        cols = ("id", "date", "status", "customer", "total", "items")
        self.tree = ttk.Treeview(self, columns=cols, show="headings", height=16)
        headers = {
            "id": ("ID", 50), "date": ("Дата", 110), "status": ("Статус", 110),
            "customer": ("Клиент", 200), "total": ("Сумма", 100), "items": ("Позиций", 80),
        }
        for c, (txt, w) in headers.items():
            self.tree.heading(c, text=txt)
            self.tree.column(c, width=w, anchor="center")
        self.tree.pack(fill="both", expand=True, padx=10, pady=4)

        bottom = tk.Frame(self)
        bottom.pack(fill="x", padx=10, pady=8)
        tk.Button(bottom, text="Добавить", width=14, command=self.add_order).pack(side="left", padx=4)
        tk.Button(bottom, text="Редактировать", width=14, command=self.edit_order).pack(side="left", padx=4)
        tk.Button(bottom, text="Удалить", width=14, command=self.delete_order).pack(side="left", padx=4)
        tk.Button(bottom, text="Показать отчёт", width=16, command=self.show_report).pack(side="right", padx=4)

    def _customer_name(self, cid: int) -> str:
        c = self.db.get_customer(cid)
        return c.name if c else f"(удалён #{cid})"

    def refresh(self) -> None:
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        status = None if self.filter_var.get() == "(все)" else self.filter_var.get()
        for o in self.db.list_orders(status=status):
            self.tree.insert(
                "", "end", iid=str(o.id),
                values=(o.id, o.order_date, o.status,
                        self._customer_name(o.customer_id), f"{o.total:.2f}", len(o.items)),
            )

    def _selected_order_id(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Заказ", "Сначала выберите заказ в списке")
            return None
        return int(sel[0])

    def add_order(self) -> None:
        if not self.db.list_customers():
            messagebox.showwarning("Заказ", "Сначала добавьте хотя бы одного клиента (через CLI)")
            return
        OrderForm(self, self.db, self.refresh)

    def edit_order(self) -> None:
        oid = self._selected_order_id()
        if oid is None:
            return
        order = self.db.get_order(oid)
        OrderForm(self, self.db, self.refresh, order=order)

    def delete_order(self) -> None:
        oid = self._selected_order_id()
        if oid is None:
            return
        if messagebox.askyesno("Удаление", f"Удалить заказ #{oid}?"):
            self.db.delete_order(oid)
            self.refresh()

    def export_orders(self) -> None:
        fmt = self.fmt_var.get()
        path = filedialog.asksaveasfilename(
            defaultextension=f".{fmt}",
            filetypes=[(fmt.upper(), f"*.{fmt}")],
            initialfile=f"orders_export.{fmt}",
        )
        if not path:
            return
        try:
            n = export_orders(self.db, path, fmt)
            messagebox.showinfo("Экспорт", f"Экспортировано заказов: {n}\n{path}")
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Экспорт", str(exc))

    def import_orders(self) -> None:
        path = filedialog.askopenfilename(
            filetypes=[("JSON/XML", "*.json *.xml"), ("Все файлы", "*.*")]
        )
        if not path:
            return
        try:
            stats = import_orders(self.db, path)
            self.refresh()
            msg = (f"Всего: {stats['total']}\nЗагружено: {stats['imported']}\n"
                   f"Пропущено: {stats['skipped']}")
            if stats["errors"]:
                msg += "\n\nОшибки:\n" + "\n".join(stats["errors"][:10])
            messagebox.showinfo("Импорт", msg)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Импорт", str(exc))

    def show_report(self) -> None:
        win = tk.Toplevel(self)
        win.title("Отчёт")
        win.geometry("420x400")
        txt = tk.Text(win, wrap="word", font=("Consolas", 11))
        txt.pack(fill="both", expand=True, padx=10, pady=10)

        lines = ["=== ОТЧЁТ ПО ЗАКАЗАМ ===\n", "Заказы по статусам:"]
        for status, count in self.db.count_by_status().items():
            lines.append(f"  {status:<12} : {count}")
        lines.append("\nТоп-3 клиента по сумме заказов:")
        top = self.db.top_customers(3)
        if not top:
            lines.append("  (нет данных)")
        for i, row in enumerate(top, start=1):
            lines.append(f"  {i}. {row['name']:<18} — {row['total']:.2f}")
        for period in ("day", "week", "month"):
            rev = self.db.revenue_for_period(period)
            lines.append(
                f"\nВыручка за '{period}' (с {rev['since']}): "
                f"{rev['revenue']:.2f} ({rev['orders']} зак.)"
            )
        txt.insert("1.0", "\n".join(lines))
        txt.config(state="disabled")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="GUI системы учёта заказов")
    parser.add_argument("--backend", choices=("sqlite", "tinydb"), default=None)
    parser.add_argument("--db", default=None)
    args = parser.parse_args(argv)

    db = get_database(backend=args.backend, path=args.db)
    try:
        app = App(db)
        app.mainloop()
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
