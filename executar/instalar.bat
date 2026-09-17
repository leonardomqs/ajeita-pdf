@echo off
chcp 65001 >nul
set PYTHONUTF8=1
setlocal

rem ============================================================================
rem  Instalacao do ajeita-pdf
rem
rem  Roda uma vez por maquina, por duplo clique. Cria o ambiente do projeto com
rem  as versoes exatas registradas em uv.lock e confere se o Ghostscript esta
rem  no lugar.
rem
rem  Por que um .bat e nao "so rode uv sync": porque abrir um terminal na pasta
rem  certa ja e a etapa em que a maioria das pessoas para. O arquivo existe para
rem  que a instalacao inteira seja um duplo clique e uma leitura.
rem ============================================================================

set "RAIZ=%~dp0.."
cd /d "%RAIZ%"

echo.
echo  Instalando o ajeita-pdf em: %RAIZ%
echo.

rem --------------------------------------------------------------- [1/3] uv
echo  [1/3] procurando o uv...
where uv >nul 2>nul
if errorlevel 1 goto :sem_uv
echo        ok

rem ------------------------------------------------------- [2/3] dependencias
echo.
echo  [2/3] criando o ambiente e instalando as dependencias...
echo        (inclui o Flask, que e o que faz a interface de navegador funcionar)

rem  Por padrao o uv nao copia as bibliotecas: ele cria hardlinks para o cache
rem  dele -- mais rapido e sem ocupar disco duas vezes. So que hardlink exige os
rem  dois lados no mesmo volume e fora do alcance de um sincronizador de arquivos.
rem  Dentro do OneDrive, do Google Drive ou num drive de rede, o Windows recusa
rem  ("os error 396") e a instalacao morre no meio, com uma mensagem que nao
rem  ajuda ninguem a entender o que fazer.
rem
rem  Copiar funciona em qualquer lugar. O custo e irrisorio -- sao nove pacotes,
rem  alguns megabytes -- e vale trocar um segundo de instalacao por uma falha a
rem  menos para a equipe decifrar.
set UV_LINK_MODE=copy

uv sync --group interface
if errorlevel 1 goto :recriar_ambiente
goto :ghostscript

:recriar_ambiente
rem O ambiente virtual guarda o caminho ABSOLUTO em que foi criado, dentro de
rem .venv\pyvenv.cfg e nos atalhos de .venv\Scripts. Se a pasta do projeto foi
rem movida ou copiada de outra maquina, esse caminho aponta para o lugar antigo
rem e o ambiente fica invalido -- o sintoma costuma ser um erro confuso de
rem interpretador, nao um "ambiente movido".
rem
rem Recriar e sempre seguro: as versoes vem travadas do uv.lock, entao o
rem ambiente reconstruido e identico. Nada de seu e apagado -- o .venv nao
rem contem configuracao, so bibliotecas.
echo.
echo        A primeira tentativa falhou. Se este projeto foi movido ou copiado,
echo        o ambiente antigo aponta para o caminho anterior.
echo        Recriando o ambiente do zero...
echo.
rmdir /s /q "%RAIZ%\.venv" 2>nul
uv sync --group interface
if errorlevel 1 goto :falhou

rem ------------------------------------------------------- [3/3] ghostscript
:ghostscript
echo.
echo  [3/3] procurando o Ghostscript...
where gs gswin64c gswin32c gswin64 gswin32 >nul 2>nul
if errorlevel 1 goto :sem_ghostscript
echo        ok

echo.
echo  ============================================================
echo   Instalacao concluida.
echo.
echo   Para usar: de um duplo clique em  executar\interface.bat
echo   Uma pagina abre no navegador e o resto e escolher arquivo.
echo  ============================================================
echo.
echo  Pressione qualquer tecla para fechar.
pause >nul
exit /b 0

:sem_uv
echo.
echo  ============================================================
echo   O uv nao esta instalado nesta maquina.
echo.
echo   Ele e quem baixa o Python e as bibliotecas do projeto.
echo   Instale com UM destes comandos, no PowerShell, e rode este
echo   arquivo de novo:
echo.
echo      winget install --id=astral-sh.uv -e
echo.
echo      powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 ^| iex"
echo.
echo   Depois de instalar, FECHE esta janela e abra de novo: um
echo   terminal ja aberto nao enxerga o PATH novo.
echo  ============================================================
echo.
pause >nul
exit /b 1

:sem_ghostscript
echo.
echo  ============================================================
echo   As dependencias foram instaladas, MAS falta o Ghostscript.
echo.
echo   E ele quem comprime o PDF, e e instalado a parte -- nao vem
echo   pelo uv e NAO ESTA no winget.
echo.
echo   1. Baixe o instalador de 64 bits em:
echo      https://github.com/ArtifexSoftware/ghostpdl-downloads/releases
echo.
echo      O arquivo tem um nome como  gs10080w64.exe
echo.
echo   2. Instale (duplo clique, e avance ate o fim).
echo.
echo   3. FECHE esta janela e rode este arquivo de novo: um terminal
echo      ja aberto nao enxerga o PATH novo.
echo  ============================================================
echo.
pause >nul
exit /b 1

:falhou
echo.
echo  ============================================================
echo   A instalacao FALHOU. A mensagem acima diz o motivo.
echo  ============================================================
echo.
pause >nul
exit /b 1
