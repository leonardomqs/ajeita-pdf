"""As páginas da interface.

São duas telas sobre a mesma rodada:

    /         comprimir, girar e juntar, em qualquer combinação
    /merge    só juntar: arquivos, ordem, nome do resultado

O que a tela resolve e o terminal não resolvia: **chegar até aqui**. Pela linha
de comando, comprimir um PDF exigia instalar o uv, abrir um terminal na pasta
certa, copiar os arquivos para `input/` e lembrar que `-c 3` é "ebook". Cada uma
dessas etapas é trivial para quem as conhece e é um muro para quem não as
conhece — e o programa é útil justamente para a segunda pessoa.
"""

from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from werkzeug.utils import secure_filename

import service
from service import LEVELS, ROTATIONS

from . import runner

bp = Blueprint("pdfc", __name__)

#: Nome de exibição de cada nível e de cada giro, para o resultado poder
#: repetir ao usuário a escolha que ele fez.
LEVEL_NAME = {code: name for code, name, _ in LEVELS}
ROTATION_NAME = dict(ROTATIONS)

#: Fundo de poço para o nome do PDF juntado, quando o campo vem vazio.
DEFAULT_MERGE_NAME = "juntado.pdf"

#: O valor que o campo de nível manda quando a pessoa escolhe não comprimir.
#: Vira `level=None` no serviço, que então nem procura o Ghostscript — juntar
#: e girar passam a funcionar numa máquina que não o tem instalado.
NO_COMPRESSION = "none"

#: Como cada fase da rodada se chama na tela. O `runner` guarda um código; a
#: palavra é daqui, pelo mesmo motivo que o terminal escreve as dele em
#: `cli._echo` — o serviço avisa o que aconteceu, quem exibe é que escolhe as
#: palavras.
PHASE_NAME = {
    "starting": "Preparando",
    "compressing": "Comprimindo",
    "copying": "Copiando",
    "rotating": "Girando",
    "merging": "Juntando",
}

#: Quem fez e onde o código mora. Aqui, e não escrito à mão em `base.html`,
#: porque o endereço do repositório é a primeira coisa a mudar se o projeto
#: for renomeado — e ninguém vai lembrar de procurá-lo dentro de um template.
AUTHOR = "Leonardo Garcia Marques"
REPO_URL = "https://github.com/leonardomqs/ajeita-pdf"


@bp.app_context_processor
def _shared() -> dict:
    """O que toda página usa e nenhuma rota deveria ter de repassar.

    O teto de envio está aqui porque a tela passou a avisar ANTES: a lista de
    arquivos compara o total escolhido com este número e barra na hora. O
    limite continua sendo do servidor — quem não tem JavaScript ainda esbarra
    nele no 413 —, mas esperar o envio de 600 MB inteiro para receber um erro
    que já se sabia no momento da escolha era a pior espera do programa.
    """
    limit = current_app.config["MAX_CONTENT_LENGTH"]
    return {
        "author": AUTHOR,
        "repo_url": REPO_URL,
        "max_upload_bytes": limit,
        "max_upload_mb": limit // (1024 * 1024),
    }


# ------------------------------------------------------- comprimir (e mais)


@bp.get("/")
def index():
    return render_template(
        "index.html",
        levels=LEVELS,
        rotations=ROTATIONS,
        default_level=2,
        no_compression=NO_COMPRESSION,
    )


@bp.post("/process")
def process():
    registry = current_app.config["JOBS"]

    chosen_level = request.form.get("level", "2")
    try:
        level = None if chosen_level == NO_COMPRESSION else int(chosen_level)
        degrees = int(request.form.get("rotate", 0))
    except ValueError:
        flash("Escolha um nível de compressão e um giro da lista.", "error")
        return redirect(url_for("pdfc.index"))

    if (level is not None and level not in LEVEL_NAME) or degrees not in ROTATION_NAME:
        flash("Escolha um nível de compressão e um giro da lista.", "error")
        return redirect(url_for("pdfc.index"))

    uploads = _uploaded_pdfs()
    if not uploads:
        flash("Escolha pelo menos um PDF.", "error")
        return redirect(url_for("pdfc.index"))

    wants_merge = bool(request.form.get("merge"))
    merge_name = _merged_name(request.form.get("merge_name", "")) if wants_merge else ""

    job = registry.open(level=level, degrees=degrees, merge_name=merge_name)
    order = _store(job, uploads)

    # A rodada sai daqui para uma thread, e a resposta é imediata. O que a
    # pessoa vê a seguir é a página da rodada, que conta o andamento enquanto
    # ele acontece — e vira o resultado quando acabar.
    runner.start(job, level=level, degrees=degrees, merge_into=merge_name, order=order)
    return redirect(url_for("pdfc.result", ident=job.id))


# ----------------------------------------------------------------- só juntar


@bp.get("/merge")
def merge():
    """A tela que faz uma coisa só.

    Juntar já era possível na tela de comprimir, como uma caixa a marcar depois
    de escolher um nível. Mas quem chega querendo grudar cinco PDFs não vem
    procurando um nível de compressão para recusar — vem procurando o botão de
    juntar, e tinha de atravessar decisões que não são dele para chegar lá.

    Por dentro é a mesma rodada: `service.run` com `level=None`. A tela é que
    é outra.
    """
    return render_template("merge.html")


@bp.post("/merge")
def run_merge():
    registry = current_app.config["JOBS"]

    uploads = _uploaded_pdfs()
    # Juntar um arquivo só devolveria uma cópia dele com outro nome. O
    # JavaScript já avisa, mas quem chega aqui com o JS desligado merece a
    # mesma explicação, e não um "resultado" que não é junção nenhuma.
    if len(uploads) < 2:
        flash("Escolha pelo menos dois PDFs para juntar.", "error")
        return redirect(url_for("pdfc.merge"))

    merge_name = _merged_name(request.form.get("merge_name", ""))
    job = registry.open(level=None, degrees=0, merge_name=merge_name, merge_only=True)
    order = _store(job, uploads)

    runner.start(job, level=None, degrees=0, merge_into=merge_name, order=order)
    return redirect(url_for("pdfc.result", ident=job.id))


# ---------------------------------------------------------- a rodada e seu fim


@bp.get("/job/<ident>")
def result(ident: str):
    """Uma URL para a rodada inteira: em andamento, pronta, ou recusada.

    Antes esta página só existia depois de tudo pronto, porque o POST só
    respondia no fim. Com a rodada numa thread, ela é o lugar onde o andamento
    aparece — e o mesmo endereço vira o resultado quando acaba. Recarregar não
    reenvia nada, e o erro de uma rodada deixou de ser uma página sem endereço.
    """
    job = current_app.config["JOBS"].get(ident)
    if job is None:
        flash("Essa rodada expirou. Envie os arquivos de novo.", "error")
        return redirect(url_for("pdfc.index"))

    if job.state == "error":
        return render_template("error.html", **job.error), 200
    if job.state == "running":
        return render_template("running.html", job=job, p=_progress(job))

    return render_template(
        "result.html",
        job=job,
        r=_ready(job),
        suggested_dir=str(current_app.config["SETTINGS"].suggested_output_dir),
    )


@bp.get("/job/<ident>/progress")
def progress(ident: str):
    """O andamento, para a página perguntar sem se recarregar inteira.

    Devolve HTML — o mesmo pedaço que a página já desenhou ao abrir — e não
    JSON. A lista de arquivos precisa existir nos dois caminhos: no primeiro
    desenho, que é o único que quem não tem JavaScript recebe, e a cada
    pergunta depois. Mandando JSON, a tabela teria de ser montada de novo em
    JavaScript, e a mesma decisão de layout viveria em dois lugares — que é
    exatamente o que o `selection.js` existe para não fazer.

    Os números que o JavaScript precisa ler viajam em `data-` no pedaço, e é
    de lá que ele descobre que a rodada acabou.
    """
    job = current_app.config["JOBS"].get(ident)
    if job is None:
        abort(404)
    return render_template("_progress.html", job=job, p=_progress(job), state=job.state)


@bp.get("/job/<ident>/download/<int:index>")
def download(ident: str, index: int):
    job = _finished(ident)
    if job is None:
        abort(404)
    summary = _ready(job)
    files = summary["files"]
    if not 0 <= index < len(files):
        abort(404)
    # Um arquivo retido não é entrega: é a cópia do que a pessoa já tem. A tela
    # não oferece o link, e a rota recusa quem montar a URL na mão — senão a
    # regra valeria só para quem não sabe escrever um endereço.
    if summary["holds_back"] and files[index]["kept"]:
        abort(404)
    path = Path(files[index]["path"])
    if not path.is_file():
        abort(404)
    # Um arquivo de trinta não é a entrega; o único de uma entrega de um, sim.
    if summary["smaller"] == 1:
        _collect(job)
    return send_file(path, as_attachment=True, download_name=path.name)


@bp.get("/job/<ident>/merged")
def download_merged(ident: str):
    job = _finished(ident)
    if job is None or not _ready(job)["merged_path"]:
        abort(404)
    path = Path(_ready(job)["merged_path"])
    if not path.is_file():
        abort(404)
    return send_file(path, as_attachment=True, download_name=path.name)


@bp.get("/job/<ident>/download-all")
def download_all(ident: str):
    """Tudo o que a rodada produziu, num .zip que preserva as subpastas.

    Com um arquivo só, o botão individual resolve. Com trinta — que é o caso
    que motivou a tela — clicar trinta vezes é pior do que a linha de comando
    que a tela veio substituir.

    Quando a rodada retém os que não encolheram, eles ficam de fora daqui
    também: o .zip é a entrega, e a entrega é o que melhorou.
    """
    job = _finished(ident)
    if job is None:
        abort(404)

    summary = _ready(job)
    wanted = None
    if summary["holds_back"]:
        wanted = {f["output_path"] for f in summary["files"] if not f["kept"]}
        if not wanted:
            abort(404)

    name = "encolheram.zip" if wanted is not None else "comprimidos.zip"
    bundle = job.dir / name
    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as zip_out:
        for path in sorted(job.output_dir.rglob("*.pdf")):
            relative = path.relative_to(job.output_dir).as_posix()
            if wanted is not None and relative not in wanted:
                continue
            zip_out.write(path, relative)

    # O .zip É a entrega: quem o leva, levou tudo o que havia para levar.
    _collect(job)
    return send_file(bundle, as_attachment=True, download_name=name)


@bp.post("/job/<ident>/retry")
def retry(ident: str):
    """Roda de novo, com outro nível, só os arquivos que não encolheram.

    Não precisa de envio nenhum: os originais continuam na pasta de ENTRADA da
    rodada. `service.run` lê de lá e escreve noutro lugar, então nada os tocou
    — nem o giro, que acontece sobre a saída. Reprocessar é abrir uma rodada
    nova com uma cópia deles.

    O giro da rodada anterior vai junto, porque a pessoa não está desfazendo o
    que pediu: está tentando o mesmo com outra compressão. Já a junção fica de
    fora — juntar um pedaço do lote não é o arquivo único que ninguém pediu.
    """
    old = _finished(ident)
    if old is None:
        flash("Essa rodada expirou. Envie os arquivos de novo.", "error")
        return redirect(url_for("pdfc.index"))

    kept = [f["relative_path"] for f in _ready(old)["files"] if f["kept"]]
    if not kept:
        flash("Nesta rodada todos os arquivos encolheram: não há o que tentar de novo.", "error")
        return redirect(url_for("pdfc.result", ident=ident))

    try:
        level = int(request.form.get("level", ""))
    except ValueError:
        level = -1
    if level not in LEVEL_NAME:
        flash("Escolha um nível de compressão da lista.", "error")
        return redirect(url_for("pdfc.result", ident=ident))

    registry = current_app.config["JOBS"]
    job = registry.open(level=level, degrees=old.degrees, merge_name="")
    for relative in kept:
        target = job.input_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(old.input_dir / relative, target)

    # O que já tinha encolhido e ninguém levou vem junto, PRONTO: entra direto
    # na saída da rodada nova, sem passar pelo serviço. Recomprimir o que já foi
    # comprimido não melhora — e, pior, cairia na lista dos que não encolheram,
    # dizendo que um arquivo que a pessoa já tinha conseguido deu errado.
    #
    # Assim a lista de prontos ACUMULA entre tentativas, em vez de reiniciar a
    # cada uma: quem tenta três níveis seguidos baixa um .zip só no fim.
    job.carried = [] if old.collected else _inherit(old, job)

    runner.start(job, level=level, degrees=old.degrees, merge_into="", order=kept)
    return redirect(url_for("pdfc.result", ident=job.id))


def _inherit(old, job) -> list:
    """Copia para a rodada nova os arquivos que já tinham encolhido.

    Fisicamente, e não por referência: a rodada nova precisa ser completa
    sozinha — o .zip varre a pasta dela, e a antiga vence e é apagada primeiro.
    """
    carried = []
    for produced in _produced(old):
        if produced.kept_original:
            continue
        target = job.output_dir / produced.output_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(produced.path, target)
        carried.append(
            service.ProcessedFile(
                relative_path=produced.relative_path,
                output_path=produced.output_path,
                path=target,
                size_before=produced.size_before,
                size_after=produced.size_after,
            )
        )
    return carried


@bp.post("/job/<ident>/save")
def save(ident: str):
    """Grava o resultado numa pasta da máquina.

    Faz sentido porque este servidor roda na máquina do próprio usuário: a
    "pasta de destino" dele e a do servidor são a mesma. Numa instalação
    compartilhada, este seria o caminho a remover — o download resolve sozinho.
    """
    job = _finished(ident)
    if job is None:
        flash("Essa rodada expirou, ou ainda não terminou. Confira na página dela.", "error")
        return redirect(url_for("pdfc.index"))

    target = Path(request.form.get("folder", "").strip()).expanduser()
    if not str(target).strip() or not target.is_dir():
        flash(f"A pasta '{target}' não existe. Confira o caminho.", "error")
        return redirect(url_for("pdfc.result", ident=ident))

    summary = _ready(job)
    if summary["holds_back"]:
        # A mesma regra do download, pelo mesmo motivo — e aqui ela pesa mais:
        # esta pasta costuma ser a dos originais, e gravar de volta um arquivo
        # idêntico ao que já está lá é, na melhor hipótese, ruído.
        saved = [f for f in summary["files"] if not f["kept"]]
        for f in saved:
            destination = target / f["output_path"]
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f["path"], destination)
        if summary["merged_path"]:
            shutil.copy2(summary["merged_path"], target / summary["merged_name"])
        count = len(saved)
    else:
        shutil.copytree(job.output_dir, target, dirs_exist_ok=True)
        count = summary["count"]

    _collect(job)
    flash(f"{count} arquivo(s) salvos em {target}", "ok")
    return redirect(url_for("pdfc.result", ident=ident))


@bp.app_errorhandler(413)
def too_large(_error):
    """A rede de segurança de quem não tem JavaScript.

    Com a tela inteira funcionando, ninguém chega aqui: a lista soma os
    arquivos escolhidos e barra o envio antes de começá-lo. Sem JavaScript não
    há essa conta, e o limite volta a aparecer onde sempre apareceu — no fim de
    uma espera longa, que é exatamente o que a conta da tela veio evitar.
    """
    limit = current_app.config["MAX_CONTENT_LENGTH"] // (1024 * 1024)
    return render_template(
        "error.html",
        title=f"o envio passou do limite de {limit} MB",
        hint="Mande os arquivos em duas levas, ou comprima o lote pela linha de comando.",
    ), 413


# ------------------------------------------------------------------- auxiliares


def _uploaded_pdfs() -> list:
    """Os PDFs que chegaram, de qualquer um dos dois campos de envio.

    Quem manda uma pasta manda junto tudo o que houver dentro dela, então o
    filtro por extensão acontece aqui, em silêncio: avisar "o .docx foi
    ignorado" seria ruído sobre algo que ninguém pediu.
    """
    return [
        f
        for name in ("pdfs", "folder")
        for f in request.files.getlist(name)
        if f and f.filename and f.filename.lower().endswith(".pdf")
    ]


def _store(job, uploads: list) -> list[str]:
    """Grava os arquivos na pasta da rodada e devolve a ordem escolhida.

    O nome que o navegador manda e o caminho que vai para o disco não são o
    mesmo — `_safe_path` higieniza, e dois envios podem colidir num nome só.
    A ordem escolhida na tela vem em nomes de navegador, então o mapa daqui é
    a ponte entre as duas formas.
    """
    stored: dict[str, list[str]] = {}
    taken: set[str] = set()
    for upload in uploads:
        relative = _unique_path(_safe_path(upload.filename), taken)
        target = job.input_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        upload.save(target)
        stored.setdefault(upload.filename, []).append(relative.as_posix())

    # Uma lista de caminhos por nome, e não um caminho só, porque o mesmo nome
    # pode ter chegado duas vezes — e aí cada ocorrência na ordem pedida
    # consome uma das cópias, em vez de as duas apontarem para a mesma.
    remaining = {name: list(paths) for name, paths in stored.items()}
    order: list[str] = []
    for name in _requested_order(request.form.get("order", "")):
        queue = remaining.get(name)
        if queue:
            order.append(queue.pop(0))
    return order


def _collect(job) -> None:
    """Marca que a entrega desta rodada foi levada.

    Só vale quando a rodada retém arquivos: aí a tela tem para onde ir depois —
    recolhe o que ficou pronto e passa a mostrar só o que falta, que é a razão
    de a pessoa ainda estar olhando para ela. Numa rodada em que tudo encolheu,
    a página é um recibo, e um recibo não se apaga depois de lido.

    É otimista: um GET não prova que o arquivo chegou ao disco de ninguém. Por
    isso a tela nunca fecha a porta — deixa um "baixar de novo" discreto.
    """
    if _ready(job)["holds_back"]:
        job.collected = True


def _finished(ident: str):
    """A rodada, se ela existe E já terminou bem.

    Baixar ou salvar o resultado de uma rodada que ainda está no meio do
    caminho não é um pedido válido: não há resultado. Antes a pergunta nem
    existia, porque só havia página depois de tudo pronto.
    """
    job = current_app.config["JOBS"].get(ident)
    if job is None or job.state != "done":
        return None
    return job


def _produced(job) -> list:
    """Tudo o que esta rodada entrega: o que ela processou e o que herdou.

    Os herdados vêm primeiro porque são mais antigos — encolheram numa
    tentativa anterior e ninguém os levou ainda.
    """
    return list(job.carried) + list(job.result.files)


def _ready(job) -> dict:
    """O resumo desta rodada, traduzido uma vez só.

    O `runner` guarda o `Result` do serviço; transformá-lo em texto é trabalho
    desta camada, e não faz sentido refazê-lo a cada download de um lote de
    trinta arquivos.
    """
    if not job.summary:
        combined = job.result
        if job.carried:
            # Um `Result` novo com as duas metades: o que veio da tentativa
            # anterior conta no total e na lista como qualquer outro arquivo.
            # A rodada é a soma do que foi conseguido até aqui, não só da
            # última passada.
            combined = service.Result(
                files=_produced(job),
                merged=job.result.merged,
                degrees=job.result.degrees,
                level=job.result.level,
            )
        job.summary = _summarize(
            combined, merge_only=job.merge_only, carried=len(job.carried)
        )
    # Muda DEPOIS que a rodada terminou, então não entra no que foi guardado.
    job.summary["collected"] = job.collected
    return job.summary


def _progress(job) -> dict:
    """O andamento cru do `runner`, virado frase e percentual.

    O percentual conta PASSOS, não arquivos: uma rodada passa duas vezes por
    cada arquivo quando também gira, e mais uma para juntar. Contar arquivos
    faria a barra chegar a 100% e continuar trabalhando — a única coisa pior
    do que não ter barra.
    """
    raw = job.progress or {}
    done = raw.get("done", 0)
    steps = raw.get("steps", 0)
    count = raw.get("count", 0)
    name = raw.get("file", "")
    phase = raw.get("phase", "starting")

    if phase == "merging":
        detail = f"{count} arquivos em {name}"
    elif count and name:
        detail = f"{raw.get('index', 0)} de {count} · {name}"
    else:
        detail = ""

    return {
        "label": PHASE_NAME.get(phase, "Processando"),
        "detail": detail,
        "percent": int(done * 100 / steps) if steps else 0,
        "done": done,
        "steps": steps,
        #: A rodada comprime? Decide as colunas da lista, do mesmo jeito que no
        #: resultado: sem compressão não há "antes" e "depois", há um tamanho.
        "compressed": job.level is not None,
        "files": [_row(row, phase) for row in raw.get("files", ())],
    }


#: O que a última coluna da lista diz em cada estado. "agora" e não um símbolo
#: girando: a linha já está destacada, e o que falta dizer é o que está sendo
#: feito com ela — que numa rodada que também gira não é sempre a mesma coisa.
WORKING_MARK = {
    "compressing": "comprimindo",
    "copying": "copiando",
    "rotating": "girando",
}


def _row(row: dict, phase: str) -> dict:
    """Uma linha da lista, pronta para a tela.

    Lida de outra thread enquanto o `runner` escreve nela. Por isso só campos
    soltos são tocados aqui, nunca o tamanho da lista: as chaves podem estar um
    passo atrás, e um tamanho a menos apareceria como uma linha sumida.
    """
    state = row.get("state", "pending")
    after = row.get("after")
    before = row.get("before") or 0
    kept = bool(row.get("kept"))
    grew = after is not None and after > before

    #: Como no resultado: "0%" leria como uma compressão que não rendeu, e o
    #: que houve foi a rodada devolver o arquivo que entrou.
    savings = ""
    if kept:
        savings = "original"
    elif after is not None and before:
        savings = ("+" if grew else "−") + _percent((before - after) / before)

    return {
        "name": row.get("name", ""),
        "state": state,
        "before": _human_size(before),
        #: "Depois" fica vazio até existir: um número ali antes da hora
        #: pareceria um resultado que ainda não houve.
        "after": _human_size(after) if after is not None else "",
        #: A coluna única das rodadas que não comprimem. Aí a pergunta é outra
        #: — "quanto tem este arquivo" —, e a resposta já se sabe desde o
        #: começo: o tamanho de entrada, que vira o exato quando o arquivo
        #: passa. Deixá-la vazia esconderia um dado que já estava na mão.
        "size": _human_size(after if after is not None else before),
        "savings": savings,
        "grew": grew,
        "kept": kept,
        "mark": {"pending": "na fila", "done": "pronto"}.get(
            state, WORKING_MARK.get(phase, "agora")
        ),
    }


def _unique_path(relative: Path, taken: set[str]) -> Path:
    """Garante que dois arquivos enviados não gravem por cima um do outro.

    Acontece de verdade: "Digitalizar.pdf" vindo de duas pastas diferentes, ou
    a mesma pessoa escolhendo o arquivo duas vezes. Antes, o segundo envio
    sobrescrevia o primeiro em silêncio e a junção saía com um documento a
    menos — o pior tipo de erro, porque o resultado parece inteiro.
    """
    key = relative.as_posix()
    if key not in taken:
        taken.add(key)
        return relative

    n = 2
    while True:
        candidate = relative.with_name(f"{relative.stem} ({n}){relative.suffix}")
        key = candidate.as_posix()
        if key not in taken:
            taken.add(key)
            return candidate
        n += 1


def _requested_order(text: str) -> list[str]:
    """A ordem escolhida na tela: um nome de arquivo por linha.

    Vem de um campo escondido que o JavaScript mantém em dia enquanto a pessoa
    arrasta os itens da lista. Se o JavaScript não rodar, o campo chega vazio e
    a ordem alfabética continua valendo — a página não quebra, só não reordena.
    """
    return [line.strip() for line in text.splitlines() if line.strip()]


def _safe_path(name: str) -> Path:
    """O nome enviado pelo navegador, reduzido a um caminho relativo seguro.

    Um envio de pasta traz o caminho dentro dela ("lote/ata_01.pdf"), e é ele
    que faz a saída espelhar a entrada — a mesma promessa que a pasta `input/`
    cumpre na linha de comando. Mas o nome vem do cliente, então cada pedaço
    passa por `secure_filename` e qualquer ".." desaparece: nada escapa da
    pasta da rodada.
    """
    parts = [p for p in name.replace("\\", "/").split("/") if p not in ("", ".", "..")]
    safe = [secure_filename(p) for p in parts]
    safe = [p for p in safe if p]
    if not safe:
        return Path("arquivo.pdf")
    # Profundidade de sobra para um lote real, e um teto para quem inventar.
    return Path(*safe[-6:])


def _merged_name(name: str) -> str:
    clean = secure_filename(name.strip()) or DEFAULT_MERGE_NAME
    if not clean.lower().endswith(".pdf"):
        clean += ".pdf"
    return clean


def _human_size(size: int) -> str:
    """Tamanho em português: vírgula decimal e a unidade que couber."""
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB".replace(".", ",")
    if size >= 1024:
        return f"{size / 1024:.0f} KB"
    return f"{size} B"


def _percent(fraction: float) -> str:
    return f"{abs(fraction):.0%}"


def _stronger_than(level: int | None) -> list[tuple[int, str]]:
    """Os níveis que comprimem MAIS do que o escolhido, com código e nome.

    A ordem de `LEVELS` é a da lista na interface, do que comprime menos ao que
    comprime mais — então "mais forte" é o que vem depois. Existe para o aviso
    não mandar a pessoa tentar o nível que ela acabou de usar, que é o jeito
    mais rápido de um conselho perder a credibilidade, e para a tentativa
    seguinte já vir com o próximo nível escolhido.
    """
    codes = [code for code, _, _ in LEVELS]
    if level not in codes:
        return []
    return [(code, name) for code, name, _ in LEVELS[codes.index(level) + 1:]]


def _summarize(result: service.Result, *, merge_only: bool = False, carried: int = 0) -> dict:
    """Traduz a rodada para o que a página desenha.

    A página não recebe objetos do serviço: recebe texto pronto. Assim o
    template não precisa saber o que é um `Result`, e mudar a aparência não
    esbarra em regra nenhuma.
    """
    files = [
        {
            #: A posição na lista completa, para o link de baixar continuar
            #: apontando certo depois que a tela passou a mostrar as duas
            #: metades em tabelas separadas.
            "index": i,
            #: O nome de SAIDA: e o que a pessoa vai baixar, e o unico
            #: que ela pode conferir contra a propria pasta depois.
            "relative_path": f.output_path,
            "output_path": f.output_path,
            "path": str(f.path),
            "before": _human_size(f.size_before),
            "after": _human_size(f.size_after),
            "savings": _percent(f.savings),
            "grew": f.savings < 0,
            #: Comprimir teria piorado e a rodada entregou o original. A linha
            #: não mostra "0%": mostra o que de fato aconteceu com o arquivo.
            "kept": f.kept_original,
        }
        for i, f in enumerate(result.files)
    ]

    # Um PDF já otimizado SAI MAIOR do Ghostscript, e a rodada devolve o
    # original nesse caso (ver `service.run`). Então já não há arquivo maior
    # para avisar — há arquivo intacto, e é isso que precisa ser dito: um
    # "0%" sozinho pareceria falha do programa, quando é a resposta certa.
    kept = sum(1 for f in files if f["kept"])
    nothing_gained = result.compressed and kept == len(files) and kept > 0
    stronger = _stronger_than(result.level) if result.compressed else []
    rotated = bool(result.degrees % 360)

    # A rodada RETÉM alguns arquivos: eles saem da entrega, e a tela passa a ser
    # a lista do que ainda não encolheu. Quem já tem o original na pasta de
    # origem não quer baixá-lo de volta idêntico — quer o que tem a substituir.
    #
    # A exceção é o giro. Girando, o arquivo mantido na saída é o original JÁ
    # GIRADO: é uma coisa nova, que a pessoa pediu e não tem. Retê-lo seria
    # engolir o giro em silêncio, então aí a rodada entrega tudo — e a lista do
    # que não encolheu continua aparecendo, porque a compressão ainda não
    # ajudou e a segunda tentativa continua fazendo sentido.
    holds_back = kept > 0 and not rotated

    if merge_only:
        verdict = f"Pronto — {len(files)} PDFs viraram um"
    elif not result.compressed:
        verdict = f"Pronto — {len(files)} arquivo(s), sem recomprimir"
    elif nothing_gained:
        verdict = (
            "Não havia o que comprimir"
            if len(files) > 1
            else "Não havia o que comprimir neste arquivo"
        )
    else:
        verdict = f"Pronto — {_percent(result.savings)} menor"

    return {
        "files": files,
        "count": len(files),
        "compressed": result.compressed,
        #: Veio da tela de juntar. A página então recolhe a lista de arquivos:
        #: quem pediu um PDF único não veio conferir os cinco que entraram.
        "merge_only": merge_only,
        "before": _human_size(result.size_before),
        "after": _human_size(result.size_after),
        "savings": _percent(result.savings),
        #: Quantos já estavam otimizados e saíram como entraram. Zero esconde o
        #: aviso inteiro; mais que zero o acende, com texto conforme sobrou
        #: algum ganho ou não.
        "kept": kept,
        "nothing_gained": nothing_gained,
        #: Quantos de fato encolheram. É o que o botão de baixar conta quando a
        #: rodada retém os outros — e o que decide se ele aparece: num lote em
        #: que nada encolheu, ele viria vazio.
        "smaller": len(files) - kept,
        #: A rodada só entrega os que encolheram; os outros ficam na tela como
        #: o que ainda falta resolver. Ver o comentário na conta acima.
        "holds_back": holds_back,
        #: Quantos vieram de uma tentativa anterior. A tela diz isso, porque o
        #: nível no alto da página é o desta rodada e não o deles.
        "carried": carried,
        #: O que oferecer a quem precisa reduzir assim mesmo. Vazio quando a
        #: pessoa já está no nível que mais comprime — e aí o aviso diz isso,
        #: em vez de sugerir o que ela acabou de fazer.
        "stronger": stronger,
        #: A lista do seletor de "tentar de novo", e qual vem escolhido. Todos
        #: os níveis, porque quem quiser pode tentar um mais leve; o escolhido
        #: é o próximo mais forte, que é a tentativa que faz sentido.
        "levels": [(code, name) for code, name, _ in LEVELS],
        "retry_level": stronger[0][0] if stronger else result.level,
        #: O total ainda pode crescer, mesmo com a compressão travada: girar
        #: reescreve o arquivo, e o PyPDF2 nem sempre devolve algo menor.
        "grew": result.savings < 0,
        "tone": "warn" if nothing_gained else "ok",
        "verdict": verdict,
        "level_name": (
            LEVEL_NAME.get(result.level, str(result.level))
            if result.compressed
            else "sem compressão"
        ),
        "rotation_name": ROTATION_NAME.get(result.degrees, ""),
        "rotated": bool(result.degrees % 360),
        "merged_path": str(result.merged) if result.merged else "",
        "merged_name": result.merged.name if result.merged else "",
        "merged_size": (_human_size(result.merged.stat().st_size) if result.merged else ""),
    }
