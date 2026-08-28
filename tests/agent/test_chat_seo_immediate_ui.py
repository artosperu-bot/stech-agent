from pathlib import Path

from scripts.stech_agent_chat import _print_bulk_failures


def test_bulk_failures_does_not_report_an_empty_sku_that_was_completed(capsys):
    _print_bulk_failures({
        "items": [
            {
                "sku": "A",
                "status": "SEO_EMPTY",
                "message": "A estaba vacío",
                "preparation": {"action": "COMPLETED", "state": "VERIFIED"},
            }
        ]
    })
    assert "INCIDENCIAS" not in capsys.readouterr().out


def test_chat_script_no_longer_promises_background_seo_preparation():
    text = Path("scripts/stech_agent_chat.py").read_text(encoding="utf-8")
    assert "preparará Research/QA en segundo plano" not in text
    assert "lo verificará y recién seguirá al siguiente" in text
