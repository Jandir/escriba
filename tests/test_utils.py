import pytest
from utils import format_date

@pytest.mark.parametrize("input_date,expected", [
    # Caso 1: YouTube formato 8 digitos
    ("20260316", "2026-03-16"),
    (20260316, "2026-03-16"),
    ("  20260316  ", "2026-03-16"),

    # Caso 2: Formato ISO
    ("2026-03-16", "2026-03-16"),
    ("  2026-03-16", "2026-03-16"),

    # Vazio / None
    (None, "Desconhecida"),
    ("", "Desconhecida"),
    ("   ", "Desconhecida"),

    # Fallback suave (valores textuais especificos para rejeitar)
    ("N/A", "Desconhecida"),
    ("None", "Desconhecida"),
    ("  N/A  ", "Desconhecida"),

    # Fallback suave (outros valores estranhos devem retornar a propria string)
    ("2026/03/16", "2026/03/16"),
    ("16-03-2026", "16-03-2026"),
    ("ontem", "ontem"),
])
def test_format_date(input_date, expected):
    assert format_date(input_date) == expected
