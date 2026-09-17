"""`python -m webui` — sobe a interface para uso local.

A porta e o host ficam aqui e em `executar/interface.bat`, e os dois precisam
concordar: o .bat abre o navegador na URL antes de o servidor subir. Mudar um
sem o outro dá uma página em branco que parece defeito do programa.
"""

from __future__ import annotations

import os

from . import create_app

HOST = os.environ.get("AJEITA_HOST", "127.0.0.1")
PORT = int(os.environ.get("AJEITA_PORT", "5200"))

if __name__ == "__main__":
    # Sem acento e sem "·": estas tres linhas aparecem numa janela do cmd, que
    # nem sempre esta em UTF-8, e um titulo com mojibake e a primeira coisa
    # que a pessoa ve.
    print("ajeita-pdf - interface")
    print(f"abra no navegador:  http://{HOST}:{PORT}")
    print("para encerrar, feche esta janela ou pressione Ctrl+C")
    create_app().run(host=HOST, port=PORT, debug=False)
