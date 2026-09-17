"""As rodadas em andamento: o que foi enviado e o que saiu.

Uma rodada pela tela tem duas metades separadas no tempo: processar e decidir o
que fazer com o resultado. Entre uma e outra, alguma coisa precisa guardar os
arquivos.

Duas decisões que valem o comentário:

**Em disco, não em memória.** O resultado é um ou mais PDFs que o usuário vai
baixar ou mandar salvar numa pasta. Guardá-los em memória seria manter lotes
inteiros de arquivo por rodada e perdê-los se o servidor reiniciar. Cada rodada
vive numa pasta própria dentro da área de trabalho.

**Com prazo.** Uma pasta por rodada, sem limpeza, vira um depósito de PDFs de
outra pessoa esquecido no disco — e este repositório inteiro é construído em
torno da ideia de que PDF de terceiro não fica onde não deve. As pastas
vencidas são removidas na rodada seguinte.
"""

from __future__ import annotations

import datetime as dt
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path

__all__ = ["Job", "JobRegistry", "LIFETIME"]

#: Quanto tempo uma rodada fica disponível para baixar ou salvar. Passado isso,
#: a pasta é apagada na primeira oportunidade.
LIFETIME = dt.timedelta(hours=6)


@dataclass(slots=True)
class Job:
    """Uma rodada: em andamento, pronta, ou recusada.

    Deixou de ser "uma rodada já processada" quando o processamento saiu do
    pedido e foi para uma thread (ver `runner.py`). Agora a rodada tem um
    estado, e `state` é o que a página consulta para saber o que desenhar.
    """

    id: str
    dir: Path
    created_at: dt.datetime
    #: `None` quer dizer "não comprimiu": a rodada só juntou e/ou girou.
    level: int | None = 2
    degrees: int = 0
    merge_name: str = ""
    #: Veio da tela de juntar. A página de resultado recolhe a lista de
    #: arquivos quando é o caso: quem pediu um PDF único não veio conferir os
    #: cinco que entraram.
    merge_only: bool = False

    #: "running" enquanto o serviço trabalha, "done" com o resultado pronto,
    #: "error" quando a rodada foi recusada. Escrito pela thread da rodada e
    #: lido por quem está olhando a página — e é o ÚLTIMO campo a mudar, para
    #: que ninguém veja "pronto" antes de o resultado estar lá.
    state: str = "running"
    #: O andamento cru: passos feitos, passos previstos, e em que arquivo a
    #: rodada está. Quem transforma isso em frase é `routes.py`.
    progress: dict = field(default_factory=dict)
    #: O `Result` do serviço, quando a rodada termina. Objeto do serviço, não
    #: de exibição — `routes` o traduz uma vez, para `summary`.
    result: object = None

    #: Arquivos que já tinham encolhido numa tentativa anterior e vieram junto
    #: para esta, porque ninguém os baixou ainda. São `ProcessedFile` prontos:
    #: não passam pelo serviço de novo — recomprimir o que já foi comprimido
    #: não melhora, e eles cairiam na lista errada. Ficam fisicamente na pasta
    #: de saída desta rodada, para que ela seja completa sozinha.
    carried: list = field(default_factory=list)

    #: A entrega já foi levada — baixada ou salva numa pasta. A tela então
    #: recolhe o que ficou pronto e passa a mostrar só o que falta, que é a
    #: razão de o usuário ainda estar olhando para ela.
    collected: bool = False
    #: Quando `state == "error"`: a mensagem e a sugestão a mostrar.
    error: dict = field(default_factory=dict)

    #: O que a tela precisa desenhar, já no formato de exibição. A página não
    #: recebe objetos do serviço: recebe texto pronto.
    summary: dict = field(default_factory=dict)

    @property
    def input_dir(self) -> Path:
        return self.dir / "input"

    @property
    def output_dir(self) -> Path:
        return self.dir / "output"

    @property
    def expired(self) -> bool:
        return dt.datetime.now() - self.created_at > LIFETIME


class JobRegistry:
    """Guarda as rodadas da sessão. Uma instância por aplicação."""

    def __init__(self, work_dir: Path) -> None:
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self._jobs: dict[str, Job] = {}

    def open(
        self,
        *,
        level: int | None,
        degrees: int,
        merge_name: str = "",
        merge_only: bool = False,
    ) -> Job:
        """Cria a pasta desta rodada e limpa as que já venceram."""
        self.purge_expired()
        ident = uuid.uuid4().hex[:12]
        folder = self.work_dir / ident
        (folder / "input").mkdir(parents=True, exist_ok=True)
        (folder / "output").mkdir(parents=True, exist_ok=True)
        job = Job(
            id=ident,
            dir=folder,
            created_at=dt.datetime.now(),
            level=level,
            degrees=degrees,
            merge_name=merge_name,
            merge_only=merge_only,
        )
        self._jobs[ident] = job
        return job

    def get(self, ident: str) -> Job | None:
        job = self._jobs.get(ident)
        if job is None or job.expired:
            return None
        return job

    def purge_expired(self) -> int:
        """Apaga as pastas vencidas. PDF de ninguém fica no disco à toa."""
        expired = [i for i, j in self._jobs.items() if j.expired]
        for ident in expired:
            shutil.rmtree(self._jobs[ident].dir, ignore_errors=True)
            del self._jobs[ident]

        # Pastas órfãs de uma execução anterior do servidor: o registro em
        # memória morreu junto com o processo, mas os arquivos ficaram.
        cutoff = dt.datetime.now() - LIFETIME
        for folder in self.work_dir.iterdir():
            if not folder.is_dir() or folder.name in self._jobs:
                continue
            try:
                if dt.datetime.fromtimestamp(folder.stat().st_mtime) < cutoff:
                    shutil.rmtree(folder, ignore_errors=True)
            except OSError:
                continue
        return len(expired)
