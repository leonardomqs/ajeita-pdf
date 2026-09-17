"""A rodada em segundo plano, e o andamento que ela relata.

Por que em segundo plano: até aqui o POST rodava `service.run` inteiro antes de
responder, e um lote de trinta digitalizações é um minuto de página parada.
Enquanto a resposta não sai, não há o que contar — nem quantos arquivos já
foram, nem em qual a rodada está agora. Com a rodada numa thread, a resposta sai
na hora e quem está olhando pode perguntar o andamento.

O `service.run` já sabia relatar: ele recebe `on_progress(step, data)` desde que
o terminal precisou imprimir o andamento, e o docstring do `cli._echo` diz, com
todas as letras, que é isso "que permite à interface de navegador contar a mesma
rodada de outro jeito". Este módulo é o segundo ouvinte daquele sinal.

O que sai daqui é andamento CRU — códigos e contadores. Virar frase é problema
de `routes.py`, pelo mesmo motivo que `_summarize` existe lá: a página recebe
texto pronto, e o texto mora do lado de quem exibe.
"""

from __future__ import annotations

import threading
import traceback

import service
from service import PdfError

__all__ = ["start"]


def start(job, *, level: int | None, degrees: int, merge_into: str, order: list[str] | None) -> None:
    """Põe a rodada para rodar e devolve na hora.

    `daemon=True` de propósito: fechar a janela do servidor é como o programa
    termina, e uma thread que segurasse o encerramento faria a janela preta
    recusar-se a fechar — que é exatamente o tipo de coisa que leva alguém a
    matar o processo no gerenciador de tarefas.
    """
    job.state = "running"
    job.progress = {
        "phase": "starting", "done": 0, "steps": 0, "count": 0, "index": 0,
        "file": "", "files": [],
    }
    threading.Thread(
        target=_work,
        args=(job,),
        kwargs={"level": level, "degrees": degrees, "merge_into": merge_into, "order": order},
        daemon=True,
    ).start()


def _work(job, *, level, degrees, merge_into, order) -> None:
    try:
        result = service.run(
            input_dir=job.input_dir,
            output_dir=job.output_dir,
            level=level,
            degrees=degrees,
            merge_into=merge_into or None,
            order=order or None,
            on_progress=_reporter(job),
        )
    except PdfError as exc:
        # A pasta temporária da rodada não diz nada a quem está na tela: é
        # encanamento desta camada, e some da mensagem antes de virar página.
        job.error = {
            "title": str(exc.message).replace(str(job.input_dir), "os arquivos que você enviou"),
            "hint": exc.hint,
        }
        job.state = "error"
        return
    except Exception as exc:  # noqa: BLE001
        # Numa thread não há Flask para transformar o inesperado numa página de
        # erro: sem este ramo a rodada ficaria "em andamento" para sempre, e a
        # tela perguntaria o andamento até o fim dos tempos. Um PDF corrompido
        # chega aqui — o `service.rotate` e o `service.merge` deixam o erro do
        # PyPDF2 escapar em vez de embrulhá-lo num `PdfError`. Consertar isso é
        # lá, não aqui; o que este ramo garante é que a rodada termina e diz
        # alguma coisa, em vez de ficar pendurada.
        traceback.print_exc()
        job.error = {
            "title": "a rodada parou por um erro inesperado",
            "hint": f"{type(exc).__name__}: {exc}",
        }
        job.state = "error"
        return

    job.result = result
    # Por último, sempre: é `state` que a página consulta, e ninguém pode ler
    # "pronto" antes de o resultado estar onde vai ser lido.
    job.state = "done"


def _reporter(job):
    """Traduz os passos do serviço em contadores e numa lista de linhas.

    O andamento é contado em PASSOS, não em arquivos, porque uma rodada pode
    passar duas vezes por cada arquivo — comprimir e depois girar — e mais uma
    para juntar. Contar arquivos faria a barra chegar a 100% e continuar
    trabalhando, que é a única coisa pior do que não ter barra.

    A lista de linhas nasce inteira no `found` e só muda de conteúdo depois:
    nenhuma linha é acrescentada nem removida enquanto a rodada anda. É o que
    torna seguro o `routes` lê-la de outra thread enquanto esta escreve — a
    lista não muda de tamanho debaixo de quem a percorre.
    """
    #: Nome do arquivo -> posição dele na lista. Os caminhos são únicos dentro
    #: de uma rodada (o `_store` garante isso ao gravar), então dá para achar a
    #: linha pelo nome em vez de confiar na aritmética dos contadores.
    where: dict[str, int] = {}

    def touch(name: str, **changes) -> None:
        position = where.get(name)
        if position is None:
            return
        job.progress["files"][position].update(changes)

    def report(step, data):
        progress = job.progress

        if step == "found":
            count = data["count"]
            progress["count"] = count
            progress["steps"] = (
                count + (count if job.degrees % 360 else 0) + (1 if job.merge_name else 0)
            )
            progress["files"] = [
                {
                    "name": found["relative_path"],
                    "before": found["size"],
                    "after": None,
                    "state": "pending",
                    "kept": False,
                }
                for found in data.get("files", [])
            ]
            where.clear()
            where.update({row["name"]: i for i, row in enumerate(progress["files"])})

        elif step in ("compressing", "copying"):
            progress["phase"] = step
            progress["file"] = data["relative_path"]
            progress["index"] = progress["done"] + 1
            touch(data["relative_path"], state="working")

        elif step in ("compressed", "copied"):
            progress["done"] += 1
            processed = data["file"]
            touch(
                processed.relative_path,
                state="done",
                before=processed.size_before,
                after=processed.size_after,
                kept=processed.kept_original,
            )

        elif step == "rotating":
            progress["phase"] = "rotating"
            progress["file"] = data["file"].relative_path
            progress["index"] = progress["done"] - progress["count"] + 1
            # De volta a "working": o arquivo já tem tamanho, e está sendo
            # mexido outra vez. É essa segunda passada que a lista mostra.
            touch(data["file"].relative_path, state="working")

        elif step == "rotated":
            progress["done"] += 1
            processed = data["file"]
            # Girar reescreve o arquivo, e o tamanho final muda.
            touch(processed.relative_path, state="done", after=processed.size_after)

        elif step == "merging":
            progress["phase"] = "merging"
            progress["file"] = data["name"]
            progress["index"] = data["count"]

        elif step == "merged":
            progress["done"] += 1

    return report
