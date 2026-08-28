from __future__ import annotations

import argparse
import json

from stech_agent.stech.product_reader import ProductReader, SUPPORTED_SECTIONS
from stech_agent.stech.session import StechSession


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspección live SOLO LECTURA de todas las secciones del producto")
    parser.add_argument("sku", nargs="?", default="PROD-TEST")
    args = parser.parse_args()

    print("=" * 78)
    print("STECH PRODUCT AGENT - INSPECTOR LIVE COMPLETO / SOLO LECTURA")
    print("=" * 78)
    print("SKU:", args.sku)
    print("NO modifica.")
    print("NO guarda.")
    print("NO presiona Aceptar.")
    print("Secciones:", ", ".join(SUPPORTED_SECTIONS))
    print()

    session = StechSession(log=print, slow_mo=250)
    try:
        session.start()
        reader = ProductReader(session.page)
        state = reader.read_product(args.sku, sections=SUPPORTED_SECTIONS)

        print("\n" + "=" * 78)
        print("VALORES CANÓNICOS / DETECTADOS")
        print("=" * 78)
        print(json.dumps(state.values, ensure_ascii=False, indent=2, default=str))

        print("\n" + "=" * 78)
        print("DIAGNÓSTICO POR SECCIÓN")
        print("=" * 78)
        for section in state.sections:
            raw = state.raw_sections.get(section)
            print(f"\n[{section}]")
            if isinstance(raw, list):
                print(f"elementos_raw={len(raw)}")
                print(json.dumps(raw[:40], ensure_ascii=False, indent=2, default=str))
                if len(raw) > 40:
                    print(f"... omitidos {len(raw)-40} elementos")
            else:
                print(json.dumps(raw, ensure_ascii=False, indent=2, default=str))

        print("\n[OK] Inspección terminada. No se realizó ningún cambio.")
        return 0
    except Exception as exc:
        print("\n" + "=" * 78)
        print("ERROR")
        print("=" * 78)
        print(type(exc).__name__ + ":", exc)
        try:
            print("Screenshot:", session.screenshot("INSPECTOR_LIVE_ALL_ERROR"))
        except Exception:
            pass
        return 1
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
