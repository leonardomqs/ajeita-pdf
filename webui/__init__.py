"""Interface de navegador: a mesma rodada da linha de comando, com tela.

A arquitetura em uma frase: **esta camada não sabe comprimir PDF**. Ela recebe
arquivos, monta os parâmetros e chama `service.run` — o mesmo que o terminal
chama. A chamada ao Ghostscript, a rotação e a junção são os mesmos objetos,
não uma segunda implementação.

Isso não é purismo. O programa tem uma única lista de nomes de executável do
Ghostscript, e é ela que decide se a compressão funciona nesta máquina. Uma
tela que trouxesse a sua própria cópia dessa lista funcionaria até a primeira
correção feita de um lado só — e quem usa a tela é exatamente quem não vai
saber dizer por que parou.

    service.py            o QUE acontece numa rodada        (sem interface)
    cli.py                interface 1: terminal
    webui/
      __init__.py         fábrica da aplicação
      routes.py           as páginas
      jobs.py             as rodadas em andamento, em disco temporário
      templates/          HTML
      static/             CSS e JS

A fábrica (`create_app`) existe para que a aplicação seja construída com
configuração explícita — em teste, apontando para pastas temporárias; em uso,
para as pastas reais. Sem estado global, sem import com efeito colateral.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

__all__ = ["create_app", "WebConfig"]


def create_app(config: WebConfig | None = None):
    """Monta a aplicação Flask. Importar este módulo não liga servidor nenhum."""
    from flask import Flask

    from .jobs import JobRegistry
    from .routes import bp

    cfg = config or WebConfig.default()
    app = Flask(__name__)
    app.config["SETTINGS"] = cfg
    app.config["JOBS"] = JobRegistry(cfg.work_dir)
    # PDF digitalizado é grande: um lote de trinta páginas coloridas passa
    # fácil de 100 MB. 512 MB cobre o envio legítimo e recusa em voz alta o
    # que não é.
    app.config["MAX_CONTENT_LENGTH"] = 512 * 1024 * 1024
    app.secret_key = cfg.session_key
    app.register_blueprint(bp)
    return app


class WebConfig:
    """Onde a aplicação trabalha e o que ela sugere ao usuário.

    Explícito de propósito: nada aqui é descoberto na hora do import. O teste
    monta a sua instância apontando para `tmp_path`, e a execução real usa a
    raiz do projeto.
    """

    def __init__(
        self,
        *,
        work_dir: Path,
        suggested_output_dir: Path | None = None,
        session_key: str = "ajeita-pdf-local",
    ) -> None:
        self.work_dir = Path(work_dir)
        self.suggested_output_dir = Path(suggested_output_dir or Path.cwd() / "output")
        self.session_key = session_key

    @classmethod
    def default(cls) -> WebConfig:
        root = _project_root()
        return cls(
            work_dir=Path(tempfile.gettempdir()) / "ajeita-pdf-interface",
            suggested_output_dir=root / "output",
        )


def _project_root() -> Path:
    """A pasta que contém `pyproject.toml`, a partir do pacote ou do cwd."""
    here = Path(__file__).resolve().parent.parent
    if (here / "pyproject.toml").is_file():
        return here
    current = Path.cwd()
    for candidate in (current, *current.parents):
        if (candidate / "pyproject.toml").is_file():
            return candidate
    return here
