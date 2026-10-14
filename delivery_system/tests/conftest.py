"""
conftest.py
===========
Общие фикстуры pytest. Добавляет корень проекта в sys.path, чтобы тесты
могли импортировать модули (models, database, data_export) напрямую.
"""

import os
import sys

# Корень проекта = на уровень выше каталога tests/
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
