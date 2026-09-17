# ajeita-pdf

Compressão, junção e rotação de PDFs em lote. As três são independentes: dá para só juntar, só
girar, ou comprimir — e só a compressão depende do Ghostscript.

Há duas maneiras de usar, e elas fazem exatamente a mesma coisa:

- **[Interface de navegador](#interface-de-navegador-duplo-clique)** — dois duplo cliques, uma página
  onde você escolhe os arquivos. É o caminho para quem só quer comprimir um PDF.
- **[Linha de comando](#uso-pela-linha-de-comando)** — `uv run ajeita-pdf`, com as pastas `input/`
  e `output/`. É o caminho para automatizar e para lotes grandes.

As duas chamam o mesmo `service.py`: não existe uma "versão da tela" que possa divergir da outra.

O projeto usa [uv](https://docs.astral.sh/uv/) para gerenciar o Python e as dependências.

## Pré-requisitos

### 1. uv

```powershell
winget install astral-sh.uv
```

### 2. Ghostscript (dependência de sistema, não vem pelo uv)

A compressão é feita pelo executável do Ghostscript, que precisa ser instalado à parte.

> **Só quer juntar ou girar PDFs?** Então não precisa dele. Escolhendo "Não comprimir" na tela, ou
> `--no-compress` na linha de comando, o Ghostscript nem é procurado.

**O Ghostscript não está no winget** — a Artifex publica apenas o `mutool` por lá. Baixe o
instalador oficial no repositório de releases da Artifex:

<https://github.com/ArtifexSoftware/ghostpdl-downloads/releases>

Pegue o `.exe` de 64 bits do release mais recente (por exemplo `gs10080w64.exe`, do release
`gs10080`, que é o Ghostscript 10.08.0). Instale com duplo clique, ou em silêncio num PowerShell
**como administrador**:

```powershell
.\gs10080w64.exe /S
```

A instalação padrão vai para `C:\Program Files\gs\gs<versão>\`, com os executáveis em `bin`.

O executável precisa estar no `PATH` — o script procura por `gs`, `gswin64c`, `gswin32c`, `gswin64` e `gswin32`, nessa ordem.
O instalador acrescenta o `bin` da instalação (algo como `C:\Program Files\gs\gs10.08.0\bin`) ao
`PATH` da máquina, mas **terminais já abertos não enxergam a mudança**: feche e reabra o terminal
depois de instalar.

Para conferir:

```powershell
gswin64c --version
```

Se não responder nem depois de reabrir o terminal, acrescente o `bin` ao `PATH` à mão — PowerShell
como administrador, uma vez só — e reabra o terminal de novo:

```powershell
[Environment]::SetEnvironmentVariable(
  "Path",
  [Environment]::GetEnvironmentVariable("Path", "Machine") + ";C:\Program Files\gs\gs10.08.0\bin",
  "Machine"
)
```

## Instalação

Por duplo clique, sem abrir terminal nenhum:

```
executar\instalar.bat
```

Ele procura o uv, cria o ambiente com as versões travadas em `uv.lock` (incluindo o Flask, que a
interface usa) e confere o Ghostscript — cada uma dessas três coisas, quando falta, é avisada com o
que fazer para resolver.

Pela linha de comando, o equivalente é:

```powershell
uv sync --group interface
```

Esse comando baixa o Python 3.12 (definido em `.python-version`), cria o `.venv` e instala as
dependências exatamente nas versões travadas em `uv.lock`. Não é preciso ativar o venv: use `uv run`.
Sem o `--group interface`, tudo funciona igual, menos a interface de navegador.

Se a pasta do projeto estiver dentro do OneDrive, do Google Drive ou num drive de rede, o uv falha
ao criar os hardlinks que usa por padrão, com um `os error 396` no meio da instalação. A saída é
mandar ele copiar:

```powershell
$env:UV_LINK_MODE = "copy"
uv sync --group interface
```

Os `.bat` já fazem isso sozinhos — essa nota é só para quem instala pelo terminal.

## Interface de navegador (duplo clique)

```
executar\interface.bat
```

Abre uma página em `http://127.0.0.1:5200` com **duas telas**, nas abas do topo:

| Aba | Para quê |
| --- | --- |
| **Comprimir** | Comprimir, girar e juntar — as três, em qualquer combinação, numa passada. |
| **Juntar** | Só grudar vários PDFs num só. Nada é recomprimido e o Ghostscript não é preciso. |

Em qualquer uma delas você escolhe os PDFs — ou uma pasta inteira, com subpastas — e vê o
resultado antes de baixar: um a um, num `.zip`, ou salvando direto numa pasta da máquina.

**As três operações são independentes.** Dá para juntar sem comprimir, girar sem comprimir, ou
comprimir sem mais nada. Escolher "Não comprimir" dispensa o Ghostscript por completo.

**Arraste os arquivos do Explorer** para a área tracejada, ou clique em *Escolher arquivos* se
preferir a caixa de diálogo. Arrastar uma pasta funciona igual a escolhê-la: todo PDF lá dentro
entra, e as subpastas são preservadas na saída.

**A lista é sua.** Assim que você escolhe os PDFs, eles aparecem numa lista numerada:

- **reordene** arrastando as linhas, ou pelas setas de cada uma — é essa a ordem em que entram no
  PDF juntado. Os atalhos *Ordenar por nome* e *Inverter* resolvem o lote que o scanner entregou
  ao contrário;
- **tire** o que entrou por engano no `✕` da linha, ou esvazie tudo em *Limpar a lista*;
- **some** mais arquivos escolhendo ou arrastando de novo — a segunda escolha acrescenta à lista
  em vez de substituí-la, e um arquivo que já esteja lá não entra duas vezes.

O total escolhido aparece ao lado dos atalhos. O servidor aceita 512 MB por envio, e passar disso
é avisado ali mesmo — antes de enviar, não depois da espera.

**Dá para acompanhar, arquivo por arquivo.** Depois do envio a rodada ganha um endereço próprio, e
nele a lista inteira aparece de saída — todos os arquivos, na ordem em que serão processados. Cada
linha se preenche conforme a vez dela chega:

| # | Arquivo | Antes | Depois | Economia | |
| --- | --- | --- | --- | --- | --- |
| 29 | `L119_-_Portaria_2382-2012.pdf` | 1,6 MB | 525 KB | −69% | pronto |
| **30** | **`L120_-_Portaria_2395-2013.pdf`** | **428 KB** | | | **comprimindo** |
| 31 | `L121_-_Portaria_2408-2014.pdf` | 31 KB | | | na fila |

A barra em cima diz a fase e o percentual. Um lote que também gira passa duas vezes por cada PDF, e
mais uma para juntar: por isso a conta é em **passos**, e não em arquivos — senão a barra bateria
100% com metade do trabalho por fazer. A lista acompanha sozinha o arquivo em curso, e para de
acompanhar assim que você rolar por conta própria.

Terminada, a mesma página vira o resultado sozinha. Recarregar não reenvia nada, e fechar a janela
do navegador não cancela a rodada.

**Quem encolhe sai com `_compress` no nome, e sem espaços.** `Ata da reunião 2024.pdf` vira
`Ata_da_reunião_2024_compress.pdf` — cada sequência de espaços vira um único `_`, e o acento fica
(sem o til, "reunião" deixa de ser a palavra). O sufixo é para que o resultado possa cair na pasta
dos originais sem escrever por cima deles, que é exatamente o que o *salvar direto nesta pasta*
oferece. Quem **não** encolheu sai com o nome que entrou, espaços inclusive: ele não é uma versão
comprimida de nada, é o próprio original, e renomeá-lo seria mexer num arquivo que a rodada não
produziu.

**A entrega é só o que melhorou.** Um PDF já otimizado sai *maior* do Ghostscript; nesse caso não há
o que entregar — o que sairia daqui seria uma cópia do arquivo que você já tem. Então o download e o
*salvar na pasta* levam apenas os que encolheram, e a tela passa a ser a lista do que **ainda não
encolheu**, em amarelo, com a segunda tentativa logo abaixo dela:

```
Pronto — 95% menor          3 de 7 encolheram · 2,0 MB → 102 KB

AINDA NÃO ENCOLHERAM (4)
 #  Arquivo                                       Antes   Depois   Economia
 1  L03_-_Portaria_264-2014_designacao.pdf        428 B    428 B   original
 2  L03b_-_Portaria_1885-2017_dispensa.pdf        428 B    428 B   original
 ...
 tentar de novo nestes 4 arquivos, com outro nível
 [ Leitura em tela (ebook)  v ]  [ Tentar de novo ]

▸ ver os 3 arquivos que encolheram

[ Baixar os 3 que encolheram (.zip) ]
```

A segunda tentativa **não pede upload**: os arquivos que você mandou continuam na pasta temporária
da rodada, intactos, porque o programa lê de lá e escreve noutro lugar. O giro que você pediu vai
junto, a junção não vai (juntar um pedaço do lote seria um arquivo que ninguém pediu), e a rodada
anterior continua valendo no endereço dela. O nível já vem no próximo mais forte — e quando não há
um mais forte, a oferta não aparece, porque repetir o mesmo não renderia nada.

**A lista de prontos acumula entre as tentativas.** Se você tentar de novo sem ter baixado, o que já
tinha encolhido atravessa para a rodada nova, já comprimido, e o que encolher agora entra junto —
três níveis seguidos terminam num `.zip` só. Quando você **baixa** (ou salva na pasta), aquela
entrega sai da tela: o botão e a lista dos prontos somem, fica um `✓ … foram baixados` com um
*baixar de novo* discreto, e o que continua ali é só o que falta. Daí em diante, tentar de novo
começa uma lista nova.

> Com **giro** é diferente: aí o arquivo mantido é o original *já girado*, que é coisa nova e que
> você pediu. Ele volta a ser entrega, e o download leva o lote inteiro. A lista dos que não
> encolheram continua aparecendo, porque a compressão ainda não ajudou neles.

> Com o JavaScript desligado a tela continua funcionando: os arquivos são enviados pelo caminho
> comum do navegador e a ordem passa a ser a alfabética. Some a lista de escolha, não a função — e
> a lista do andamento continua aparecendo, porque é desenhada no servidor; ela só se atualiza de
> dois em dois segundos, recarregando a página, em vez de ao vivo.

O servidor roda **só nesta máquina**. Nada é publicado na rede e nenhum arquivo sai daqui: o que é
enviado fica numa pasta temporária e é apagado depois de algumas horas. Para encerrar, feche a
janela preta que abriu junto.

> A porta 5200 está em dois lugares que precisam concordar: `executar\interface.bat`, que abre o
> navegador, e `webui\__main__.py`, que sobe o servidor.

## Uso pela linha de comando

### Pastas `input/` e `output/` (modo padrão do terminal)

Coloque em `input/` o que quiser comprimir — um PDF solto, vários PDFs, ou pastas com PDFs — e rode:

```powershell
uv run ajeita-pdf
```

Todo PDF encontrado em `input/` é comprimido para `output/`, **preservando a estrutura de pastas**:

```
input/                          output/
├── contrato.pdf        ──>     ├── contrato.pdf
└── lote_agosto/                └── lote_agosto/
    ├── ata_01.pdf                  ├── ata_01.pdf
    └── ata_02.pdf                  └── ata_02.pdf
```

Os arquivos de `input/` nunca são alterados. Para escolher o nível de compressão:

```powershell
uv run ajeita-pdf -c 3
```

Níveis de compressão (`-c`): `0` default, `1` prepress, `2` printer (padrão), `3` ebook, `4` screen.

**Nada que sai é maior do que entrou.** Um PDF já otimizado sai *maior* do Ghostscript — recomprimir
acrescenta mais do que economiza. Quando isso acontece, a rodada descarta esse resultado e entrega o
original, e diz que fez isso (`Already optimized: kept the original`, ou *original* na coluna de
economia da tela). O giro, se você pediu, continua sendo aplicado. Para reduzir mesmo assim, só há
um caminho: um nível mais forte, que diminui a resolução das imagens — é de lá que vem o tamanho.

**Quem encolhe sai com `_compress` no nome e sem espaços** (`Ata da reunião.pdf` →
`Ata_da_reunião_compress.pdf`); quem não encolhe sai com o nome que entrou. Assim `output/` pode ser
despejado por cima de `input/` sem perder nada. Isso vale para o modo pasta, em que é o programa que
nomeia. No modo arquivo avulso quem nomeia é você, com `-o`, e o programa não se intromete.

> As duas pastas são versionadas vazias (via `.gitkeep`) e todo o conteúdo delas é ignorado pelo
> git — os PDFs que você processar não sobem para o GitHub. Veja [Nenhum PDF no repositório](#nenhum-pdf-no-repositório).

### Juntar e rotacionar

Para juntar tudo o que foi comprimido em um PDF único, use `-m` com o nome do arquivo final:

```powershell
uv run ajeita-pdf -c 3 -m atas.pdf
```

O resultado sai em `output/atas.pdf`, na mesma ordem em que os arquivos aparecem em `input/`.

Para girar todas as páginas (útil quando o scanner inverte a folha), use `-r` com um múltiplo de 90:

```powershell
uv run ajeita-pdf -c 3 -r 180
```

As duas opções se combinam — comprime, gira e junta em uma passada:

```powershell
uv run ajeita-pdf -c 3 -r 180 -m atas.pdf
```

### Juntar ou girar sem comprimir

`--no-compress` (ou `-n`) pula a compressão e copia os arquivos como estão. Serve para quem quer
só grudar PDFs, ou só desvirar um lote digitalizado, e **não exige o Ghostscript instalado**:

```powershell
uv run ajeita-pdf --no-compress -m atas.pdf     # só junta
uv run ajeita-pdf --no-compress -r 180          # só gira
```

A ordem dentro do PDF juntado é a ordem alfabética dos nomes em `input/` — numere os arquivos
(`01-`, `02-`) se precisar de outra. Para reordenar visualmente, use a
[interface de navegador](#interface-de-navegador-duplo-clique).

### Arquivo avulso

Passando um caminho explícito, o comportamento antigo continua valendo:

```powershell
uv run ajeita-pdf arquivo.pdf -o saida.pdf -c 3
```

Sem `-o`, o arquivo original é sobrescrito — use `-b` para guardar um `_BACKUP.pdf` antes.

O `-m` não vale aqui: juntar exige vários arquivos, então ele só funciona no modo de pastas.
Passá-lo com um arquivo avulso agora dá erro em vez de ser ignorado em silêncio.

## Nenhum PDF no repositório

Este repositório é público e **nenhum PDF deve ser versionado**. A garantia é feita em duas camadas:

1. **`.gitignore`** — `*.pdf` e `*.PDF` são ignorados em qualquer diretório, então um `git add .`
   nunca pega um PDF por acidente.
2. **Hook `pre-commit`** — mesmo um `git add -f` é barrado na hora do commit. O hook vive em
   `.githooks/pre-commit`, versionado junto do projeto.

O hook é ativado por `core.hooksPath`, que é uma configuração local. **Depois de clonar o
repositório, rode uma vez:**

```powershell
git config core.hooksPath .githooks
```

Sem esse comando, apenas o `.gitignore` protege. Para conferir que está ativo:

```powershell
git config core.hooksPath      # deve responder: .githooks
```

Trabalhe sempre pelas pastas `input/` e `output/` e nenhuma das duas camadas será acionada.

## Gerenciando dependências

```powershell
uv add <pacote>              # adiciona ao projeto e atualiza o lock
uv add --dev <pacote>        # adiciona ao grupo de desenvolvimento
uv remove <pacote>           # remove
uv lock --upgrade            # atualiza as versões travadas
uv run python -c "..."       # roda qualquer comando dentro do ambiente
```

O arquivo `uv.lock` é versionado no git para garantir builds reproduzíveis.

## Estrutura

| Arquivo | Descrição |
| --- | --- |
| `executar/instalar.bat` | Instalação por duplo clique: confere uv, ambiente e Ghostscript. |
| `executar/interface.bat` | Abre a interface de navegador por duplo clique. |
| `service.py` | O que acontece numa rodada — Ghostscript, rotação e junção. Sem interface: não imprime nada e não conhece nem terminal nem tela. |
| `cli.py` | Interface 1: o terminal. Argumentos, mensagens e a CLI. Baseado em [Theeko74](https://github.com/theeko74/pdfc), licença MIT. |
| `webui/` | Interface 2: o navegador. Fábrica Flask, rotas, `runner.py` (a rodada em segundo plano), `templates/` e `static/`. Duas telas — comprimir e juntar — sobre a mesma rodada. |
| `input/` | Entrada: PDFs ou pastas de PDFs a comprimir. Versionada vazia. |
| `output/` | Saída: resultado da compressão, espelhando a estrutura de `input/`. Versionada vazia. |
| `.githooks/pre-commit` | Hook que bloqueia commits contendo PDFs. |
| `pyproject.toml` | Metadados e dependências do projeto. |
| `.python-version` | Versão do Python usada pelo uv. |

As duas interfaces chamam `service.run`. É de propósito: a lista de nomes de executável do
Ghostscript, a ordem dos arquivos numa junção e o tratamento de PDF corrompido existem em um lugar
só, e uma correção vale para as duas.
