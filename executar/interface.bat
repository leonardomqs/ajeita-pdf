@echo off
chcp 65001 >nul
set PYTHONUTF8=1
setlocal

rem ============================================================================
rem  Interface de navegador - duplo clique.
rem
rem  Abre uma pagina onde a pessoa escolhe os PDFs, o nivel de compressao, e
rem  baixa o resultado. Nenhum terminal, nenhum comando, nenhum -c 3.
rem
rem  O servidor roda SO nesta maquina (127.0.0.1). Nada e publicado na rede e
rem  nenhum arquivo sai daqui. Feche esta janela para encerrar.
rem ============================================================================

set "RAIZ=%~dp0.."
cd /d "%RAIZ%"

where uv >nul 2>nul
if errorlevel 1 goto :sem_uv

echo.
echo  Preparando a interface...

rem  Mesmo motivo de instalar.bat: copiar em vez de criar hardlink para o cache
rem  do uv, para nao quebrar em pasta de nuvem nem em drive de rede.
set UV_LINK_MODE=copy

uv sync --group interface >nul 2>nul
if errorlevel 1 goto :sem_ambiente

rem  A porta 5000 ja esta ocupada nas maquinas da equipe e a 5100 e do
rem  mira-carga; daqui sai a URL e a variavel que o servidor le, para os dois
rem  nunca discordarem. Quem le AJEITA_PORT e webui\__main__.py.
set AJEITA_PORT=5200
start "" http://127.0.0.1:%AJEITA_PORT%
uv run python -m webui

echo.
echo  Interface encerrada. Pressione qualquer tecla para fechar.
pause >nul
exit /b 0

:sem_uv
echo.
echo  O uv nao esta instalado nesta maquina.
echo  Rode primeiro:  executar\instalar.bat
echo.
pause >nul
exit /b 1

:sem_ambiente
echo.
echo  O ambiente do projeto nao esta pronto.
echo  Rode primeiro:  executar\instalar.bat
echo.
pause >nul
exit /b 1
