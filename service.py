"""Uma rodada de processamento, sem interface.

A arquitetura em uma frase: **esta camada não sabe desenhar nada**. Ela recebe
uma pasta de PDFs e devolve o que foi produzido; quem imprime no terminal é o
`cli`, quem monta a página é o `webui`. As duas interfaces chamam
`run` — a chamada ao Ghostscript, a rotação e a junção existem em um lugar só.

O motivo é prático, não estético. Havia UMA lista de nomes de executável do
Ghostscript, e corrigi-la corrigia o programa inteiro. Se a tela tivesse a sua
própria cópia dessa lista, a correção valeria para metade dos usuários — e a
metade que continuasse quebrada seria justamente a que não sabe ler um
traceback.

    service.py          o QUE acontece numa rodada        (sem interface)
    cli.py              interface 1: terminal
    webui/              interface 2: navegador

Nada aqui imprime, e nada aqui chama `sys.exit`. Em erro, levanta `PdfError`,
que carrega mensagem e sugestão prontas para serem exibidas tanto numa linha de
terminal quanto num cartão vermelho de página.

Sobre o idioma: identificadores em inglês, comentários e textos em português —
os textos porque são lidos por quem usa o programa, e essa pessoa é brasileira.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import PyPDF2

__all__ = [
    "PdfError",
    "ProcessedFile",
    "Result",
    "LEVELS",
    "ROTATIONS",
    "find_ghostscript",
    "compress_file",
    "rotate",
    "merge",
    "list_pdfs",
    "in_order",
    "compressed_name",
    "run",
]


#: Os níveis de compressão do Ghostscript, do mais pesado ao mais leve, com o
#: texto que a tela mostra. A ordem é a da lista na interface.
LEVELS: list[tuple[int, str, str]] = [
    (1, "Máxima qualidade (prepress)", "Para reimpressão gráfica. Comprime pouco."),
    (0, "Qualidade padrão (default)", "O padrão do Ghostscript, sem otimizar para um uso."),
    (2, "Impressão (printer)", "Bom equilíbrio. É o nível usado quando não se escolhe outro."),
    (3, "Leitura em tela (ebook)", "Bem menor, ótimo para enviar por e-mail."),
    (4, "Menor arquivo (screen)", "O mais leve. A imagem perde definição se for ampliada."),
]

#: Os giros oferecidos na tela. O Ghostscript aceita qualquer múltiplo de 90;
#: estes são os que resolvem o caso real, que é o scanner virar a folha.
ROTATIONS: list[tuple[int, str]] = [
    (0, "Não girar"),
    (90, "90° para a direita"),
    (180, "180° (de cabeça para baixo)"),
    (270, "90° para a esquerda"),
]

#: Onde baixar o Ghostscript. Aparece na sugestão do erro, que é o único
#: momento em que alguém precisa dessa informação.
GHOSTSCRIPT_RELEASES = "https://github.com/ArtifexSoftware/ghostpdl-downloads/releases"

#: O que vai no fim do nome de um arquivo que ENCOLHEU: "ata.pdf" sai como
#: "ata_compress.pdf". Existe para que o resultado possa cair na pasta dos
#: originais sem escrever por cima deles — que é exatamente o que a tela
#: oferece em "salvar direto nesta pasta da máquina".
#:
#: Só quem encolheu leva o sufixo. Um arquivo que a rodada manteve não é uma
#: versão comprimida de nada: é o próprio original, e chamá-lo de comprimido
#: seria mentir no nome — o pior lugar para uma mentira, porque o nome é o que
#: sobrevive ao programa.
COMPRESSED_SUFFIX = "_compress"


class PdfError(Exception):
    """Um erro que o usuário final precisa entender.

    `message` diz o que aconteceu; `hint` diz o que fazer. As duas são escritas
    para quem está usando o programa, não para quem o mantém — é a mesma
    exceção que vira linha de terminal e cartão de erro na página.
    """

    def __init__(self, message: str, hint: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint


@dataclass(slots=True)
class ProcessedFile:
    """Um PDF que passou pela rodada."""

    #: O caminho com que o arquivo ENTROU, relativo à pasta de entrada. É a
    #: identidade dele na rodada: quem acompanha o andamento encontra a linha
    #: por este nome, e ele não muda no meio do caminho.
    relative_path: str
    #: E o caminho com que ele SAIU, relativo à pasta de saída. Difere do de
    #: cima quando o arquivo encolheu e ganhou o `COMPRESSED_SUFFIX`.
    output_path: str
    path: Path
    size_before: int
    size_after: int
    #: Comprimir deixou este arquivo MAIOR, então a rodada descartou o
    #: resultado e entregou o original. Quem exibe precisa saber disso: sem
    #: essa distinção, "0%" pareceria uma compressão que não rendeu, quando na
    #: verdade é o arquivo que entrou, intacto.
    kept_original: bool = False

    @property
    def savings(self) -> float:
        """Quanto encolheu, de 0 a 1. Negativo quando o arquivo cresceu."""
        if not self.size_before:
            return 0.0
        return 1 - (self.size_after / self.size_before)


@dataclass(slots=True)
class Result:
    """O que uma rodada produziu.

    `level` é `None` quando a rodada não comprimiu nada — juntar e girar não
    dependem do Ghostscript, e quem só quer grudar dois PDFs não deveria
    precisar dele instalado.
    """

    files: list[ProcessedFile] = field(default_factory=list)
    merged: Path | None = None
    degrees: int = 0
    level: int | None = 2

    @property
    def compressed(self) -> bool:
        return self.level is not None

    @property
    def size_before(self) -> int:
        return sum(f.size_before for f in self.files)

    @property
    def size_after(self) -> int:
        return sum(f.size_after for f in self.files)

    @property
    def savings(self) -> float:
        if not self.size_before:
            return 0.0
        return 1 - (self.size_after / self.size_before)

    @property
    def kept(self) -> list[ProcessedFile]:
        """Os arquivos que já estavam otimizados, e saíram como entraram."""
        return [f for f in self.files if f.kept_original]


# ------------------------------------------------------------------ ghostscript


def find_ghostscript() -> str:
    """O executável do Ghostscript nesta máquina.

    A ordem dos nomes importa no Windows, e por um motivo que só aparece em
    uso: a instalação põe DOIS executáveis no PATH. O `gswin64c` é a versão de
    console e o `gswin64` é a de janela — que abre uma janela do Ghostscript a
    cada arquivo processado. Num lote de trinta PDFs pela tela, isso são trinta
    janelas piscando. Por isso as versões de console vêm primeiro.

    No Linux e no macOS existe só o `gs`, e nenhuma dessas duas formas aparece.
    """
    names = ["gs", "gswin64c", "gswin32c", "gswin64", "gswin32"]
    for name in names:
        path = shutil.which(name)
        if path:
            return path
    raise PdfError(
        "o Ghostscript não foi encontrado nesta máquina",
        hint=(
            "A compressão é feita por ele, que é instalado à parte e não vem pelo uv.\n"
            f"Baixe o instalador de 64 bits em:\n  {GHOSTSCRIPT_RELEASES}\n"
            "Depois de instalar, FECHE E REABRA esta janela: um terminal já aberto\n"
            "não enxerga o PATH novo."
        ),
    )


def compress_file(source: Path, target: Path, level: int = 2) -> tuple[int, int]:
    """Comprime um PDF. Devolve (bytes antes, bytes depois).

    O arquivo de entrada nunca é tocado: o Ghostscript escreve num caminho
    diferente do que lê.
    """
    quality = {0: "/default", 1: "/prepress", 2: "/printer", 3: "/ebook", 4: "/screen"}
    if level not in quality:
        raise PdfError(
            f"nível de compressão inválido: {level}",
            hint="Use um número de 0 a 4.",
        )

    source = Path(source)
    target = Path(target)
    if not source.is_file():
        raise PdfError(f"arquivo não encontrado: {source.name}")
    if source.suffix.lower() != ".pdf":
        raise PdfError(f"'{source.name}' não é um PDF")

    gs = find_ghostscript()
    before = source.stat().st_size
    target.parent.mkdir(parents=True, exist_ok=True)

    process = subprocess.run(
        [
            gs,
            "-sDEVICE=pdfwrite",
            "-dCompatibilityLevel=1.4",
            f"-dPDFSETTINGS={quality[level]}",
            "-dNOPAUSE",
            "-dQUIET",
            "-dBATCH",
            f"-sOutputFile={target}",
            str(source),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    # O script original usava `subprocess.call` e não olhava o código de
    # retorno: um PDF corrompido saía anunciando "Compression by 100%" com um
    # arquivo de zero byte no lugar. Aqui a falha do Ghostscript é uma falha
    # da rodada, e o motivo dele é o que vai para a sugestão.
    if process.returncode != 0 or not target.is_file():
        detail = (process.stderr or process.stdout or "").strip()
        raise PdfError(
            f"o Ghostscript não conseguiu processar '{source.name}'",
            hint=detail[:600] or "O arquivo pode estar corrompido ou protegido por senha.",
        )

    return before, target.stat().st_size


# ------------------------------------------------------------- girar e juntar


def rotate(path: Path, degrees: int = 180) -> None:
    """Gira todas as páginas de um PDF, no lugar."""
    if degrees % 90 != 0:
        raise PdfError(
            f"a rotação precisa ser múltipla de 90 (recebi {degrees})",
            hint="Use 90, 180 ou 270.",
        )
    if degrees % 360 == 0:
        return

    path = Path(path)
    reader = PyPDF2.PdfReader(str(path))
    writer = PyPDF2.PdfWriter()
    for page in reader.pages:
        page.rotate(degrees)
        writer.add_page(page)
    with open(path, "wb") as target:
        writer.write(target)
    writer.close()


def merge(paths: list[Path], target: Path) -> Path:
    """Junta vários PDFs num só, na ordem recebida."""
    if not paths:
        raise PdfError("não há nenhum PDF para juntar")

    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    writer = PyPDF2.PdfWriter()
    for path in paths:
        writer.append(str(path))
    with open(target, "wb") as out:
        writer.write(out)
    writer.close()
    return target


def list_pdfs(root: Path) -> list[Path]:
    """Todo PDF sob `root`, recursivamente, em ordem estável.

    A ordem é a que o operador vê na pasta, e é a ordem em que os arquivos
    entram no PDF juntado — então ela não pode depender do sistema de arquivos.
    """
    root = Path(root)
    found: list[Path] = []
    for folder, subfolders, names in os.walk(root):
        subfolders.sort()
        for name in sorted(names):
            if name.lower().endswith(".pdf"):
                found.append(Path(folder) / name)
    return found


def in_order(sources: list[Path], input_dir: Path, order: list[str] | None) -> list[Path]:
    """Reordena os arquivos segundo `order`, uma lista de caminhos relativos.

    Existe por causa da junção. A ordem alfabética é a certa para comprimir um
    lote e é a errada para juntar: quem gruda doze atas quer a ordem delas, não
    a do alfabeto. O que não estiver em `order` vai para o fim, mantendo entre
    si a ordem alfabética — `sorted` é estável.
    """
    if not order:
        return sources
    position = {name: i for i, name in enumerate(order)}
    last = len(position)
    return sorted(
        sources,
        key=lambda p: position.get(p.relative_to(input_dir).as_posix(), last),
    )


def compressed_name(name: str) -> str:
    """O nome com que um arquivo que ENCOLHEU sai da rodada.

        "Ata da reunião 2024.pdf"  ->  "Ata_da_reunião_2024_compress.pdf"
        "Ata  da   reunião.pdf"    ->  "Ata_da_reunião_compress.pdf"

    Espaço em branco vira "_": um só por sequência, por mais longa que ela
    seja. Um nome sem espaços em branco resiste melhor ao que acontece com ele
    depois — a linha de comando, um endereço, um anexo de e-mail —, e é
    justamente o arquivo novo, que ninguém batizou, quem pode ser renomeado
    sem contrariar ninguém.

    Só o `\\s+` de verdade é tocado; nada de trocar acento ou pontuação. O
    nome tem de continuar reconhecível para quem o escreveu, e "reunião" sem
    o til deixa de ser a palavra.

    Um "_" que sobre no fim é comido pelo do sufixo: a regra é um sublinhado
    por sequência, e "ata__compress.pdf" contraria a própria regra na emenda.

    Quem NÃO encolheu não passa por aqui. Aquele arquivo é o original, byte a
    byte, e renomeá-lo seria mexer num arquivo que a rodada não produziu.
    """
    path = Path(name)
    stem = re.sub(r"\s+", "_", path.stem).rstrip("_")
    return stem + COMPRESSED_SUFFIX + path.suffix


# ------------------------------------------------------------------- a rodada


def run(
    *,
    input_dir: Path,
    output_dir: Path,
    level: int | None = 2,
    degrees: int = 0,
    merge_into: str | None = None,
    order: list[str] | None = None,
    on_progress=None,
) -> Result:
    """Processa tudo o que houver em `input_dir`, espelhando a estrutura.

    Comprime, gira e junta — as três opcionais. `level=None` não comprime:
    copia o arquivo como está. Isso é o que permite usar o programa só para
    juntar ou só para girar, **sem o Ghostscript instalado**, já que ele só é
    procurado quando há o que comprimir.

    **Nada que sai daqui é maior do que entrou.** Um PDF já otimizado sai maior
    do Ghostscript; quando isso acontece, o resultado é descartado e o original
    ocupa o lugar dele na saída, com `kept_original=True` na ficha do arquivo.
    O giro, se houver, é aplicado normalmente sobre ele — o que se descarta é a
    recompressão que não ajudou, não o resto da rodada.

    **Quem encolheu sai renomeado por `compressed_name`**: espaços viram "_" e
    o `COMPRESSED_SUFFIX` entra no fim, para que o resultado possa cair na
    pasta dos originais sem escrever por cima deles. É aqui e não em
    `compress_file`, que recebe o caminho de saída pronto: lá quem nomeia é
    quem chama (o `-o` da linha de comando); aqui quem nomeia é o programa.

    `order` é uma lista de caminhos relativos que define a ordem dos arquivos —
    na listagem e, sobretudo, dentro do PDF juntado.

    `on_progress` recebe `(step, data)` a cada passo, e existe para que o
    terminal possa imprimir o andamento sem que esta camada saiba escrever.
    Os textos ficam todos do lado de quem exibe.

    Os passos, na ordem em que saem. Cada unidade de trabalho avisa duas vezes,
    antes e depois, porque quem mostra o andamento precisa nomear o arquivo em
    que a rodada está — não o último que ela terminou:

        found                    {count, dir, files}  a lista inteira, em ordem
        compressing | copying    {relative_path}     antes de cada arquivo
        compressed  | copied     {file}              depois de cada arquivo
        rotating                 {file, degrees}     antes de cada giro
        rotated                  {file, degrees}     depois de cada giro
        merging                  {name, count}       antes de juntar
        merged                   {path, count, size} depois de juntar
        done                     {result}

    Quem ouve pode ignorar o que não usa: o terminal não trata `rotating` nem
    `merging`, e nada quebra por isso.
    """
    input_dir = Path(input_dir)
    output_dir = Path(output_dir)
    if not input_dir.is_dir():
        raise PdfError(f"a pasta de entrada '{input_dir}' não existe")

    notify = on_progress or (lambda step, data: None)

    sources = in_order(list_pdfs(input_dir), input_dir, order)
    # A LISTA, e não só a contagem: quem mostra o andamento consegue desenhar
    # de saída todos os arquivos que vão ser processados, na ordem em que serão
    # — e preenchê-los conforme cada um termina, em vez de anunciar um por vez
    # sem dizer quantos faltam nem quais são. O tamanho de entrada vem junto
    # porque ele já é conhecido agora: os arquivos estão no disco.
    notify(
        "found",
        {
            "count": len(sources),
            "dir": str(input_dir),
            "files": [
                {
                    "relative_path": source.relative_to(input_dir).as_posix(),
                    "size": source.stat().st_size,
                }
                for source in sources
            ],
        },
    )
    if not sources:
        return Result(level=level)

    result = Result(level=level, degrees=degrees)
    for source in sources:
        relative = source.relative_to(input_dir)
        target = output_dir / relative
        # `as_posix` e não `str`: o `relative_path` do ProcessedFile logo abaixo
        # já troca a barra do Windows por "/", e sem isto o MESMO arquivo saía
        # com duas grafias no mesmo andamento — "lote\ata.pdf" ao comprimir e
        # "lote/ata.pdf" ao girar.
        notify(
            "compressing" if level is not None else "copying",
            {"relative_path": relative.as_posix()},
        )
        kept = False
        if level is None:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            before = after = target.stat().st_size
        else:
            # O nome do resultado só se decide DEPOIS de comprimir, porque ele
            # depende do desfecho: quem encolheu ganha o sufixo, quem não
            # encolheu sai com o nome que entrou.
            smaller = target.with_name(compressed_name(target.name))
            before, after = compress_file(source, smaller, level)
            if after >= before:
                # Um PDF já otimizado SAI MAIOR do Ghostscript, e entregar essa
                # versão seria trocar um arquivo bom por um pior — o usuário
                # pediu para diminuir. O trabalho é jogado fora e o original
                # ocupa o lugar dele na saída: nada que saia desta rodada é
                # maior do que o que entrou.
                #
                # Isso não desperdiça nada que pudesse ser evitado: só dá para
                # saber se comprimir ajudou depois de comprimir.
                smaller.unlink()
                shutil.copy2(source, target)
                after = before
                kept = True
            else:
                target = smaller
        processed = ProcessedFile(
            relative_path=str(relative).replace(os.sep, "/"),
            output_path=target.relative_to(output_dir).as_posix(),
            path=target,
            size_before=before,
            size_after=after,
            kept_original=kept,
        )
        result.files.append(processed)
        notify("compressed" if level is not None else "copied", {"file": processed})

    if degrees % 360:
        for processed in result.files:
            # Avisa ANTES, como "compressing" faz, e não só depois: quem exibe
            # o andamento precisa nomear o arquivo em que a rodada está agora,
            # e não o último que ela terminou.
            notify("rotating", {"file": processed, "degrees": degrees})
            rotate(processed.path, degrees)
            # O giro reescreve o arquivo: o tamanho final muda, e é esse que o
            # usuário vai ver na pasta.
            processed.size_after = processed.path.stat().st_size
            notify("rotated", {"file": processed, "degrees": degrees})

    if merge_into:
        notify("merging", {"name": merge_into, "count": len(result.files)})
        target = merge([f.path for f in result.files], output_dir / merge_into)
        result.merged = target
        notify(
            "merged",
            {"path": target, "count": len(result.files), "size": target.stat().st_size},
        )

    notify("done", {"result": result})
    return result
