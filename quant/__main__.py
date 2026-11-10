"""让 ``python -m quant`` 直接等于 CLI。"""
from .cli import main

raise SystemExit(main())
