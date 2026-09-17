#!/usr/bin/env python3
# Author: Theeko74
# Contributor(s): skjerns
# Oct, 2021
# MIT license -- free to use as you want, cheers.

"""Interface de terminal.

Compressão, junção e rotação de PDFs em lote. As três são independentes: dá
para só juntar, só girar, ou comprimir — e só a compressão precisa do
Ghostscript.

Níveis de compressão:
    0: default
    1: prepress
    2: printer
    3: ebook
    4: screen

Sem argumento de entrada, todo PDF da pasta `input` é processado para `output`,
espelhando as subpastas. Um arquivo avulso pode ser passado explicitamente.

O que acontece numa rodada mora em `service.py`, que a interface de navegador
(`webui/`) também chama. Tudo o que é impresso no console é escrito aqui;
nada é impresso de dentro do serviço.

Baseado no script de Theeko74 (https://github.com/theeko74/pdfc), licença MIT.
"""

import argparse
import os.path
import shutil
import subprocess
import sys

import service
from service import PdfError

INPUT_DIR = 'input'
OUTPUT_DIR = 'output'


def _die(error):
    """Um erro do serviço vira mensagem de terminal e código de saída 1."""
    print("Error: {}".format(error.message))
    if error.hint:
        print()
        print(error.hint)
    sys.exit(1)


def compress(input_file_path, output_file_path, power=0):
    """Comprime um PDF pela linha de comando do Ghostscript."""
    print("Compress PDF...")
    try:
        initial_size, final_size = service.compress_file(
            input_file_path, output_file_path, power)
    except PdfError as error:
        _die(error)

    ratio = 1 - (final_size / initial_size)
    print("Compression by {0:.0%}.".format(ratio))
    print("Final file size is {0:.1f}MB".format(final_size / 1000000))
    print("Done.")


def get_ghostscript_path():
    try:
        return service.find_ghostscript()
    except PdfError as error:
        raise FileNotFoundError(error.message) from error


def merge(input_file_paths, output_file_path):
    """Junta vários PDFs num só, na ordem recebida."""
    try:
        target = service.merge(list(input_file_paths), output_file_path)
    except PdfError as error:
        _die(error)

    print("Merged {} file(s) into '{}' ({:.1f}MB).".format(
        len(input_file_paths), target, target.stat().st_size / 1000000))


def rotate(pdf_file_path, degree=180):
    """Gira todas as páginas de um PDF, no lugar. Múltiplo de 90."""
    try:
        service.rotate(pdf_file_path, degree)
    except PdfError as error:
        _die(error)
    print("Rotated '{}' by {} degrees.".format(pdf_file_path, degree))


def iter_pdfs(root):
    """Todo PDF sob `root`, recursivamente, em ordem estável."""
    return iter(service.list_pdfs(root))


def _echo(step, data):
    """Traduz o andamento da rodada em linhas de terminal.

    Todo texto que o operador lê está aqui. O serviço só avisa o que aconteceu;
    como isso vira palavra é problema desta camada — que é o que permite à
    interface de navegador contar a mesma rodada de outro jeito.
    """
    if step == "found":
        if not data["count"]:
            print("No PDF found in '{}'. Nothing to do.".format(data["dir"]))
            return
        print("Found {} PDF file(s) in '{}'.".format(data["count"], data["dir"]))
        print()

    elif step == "compressing":
        print("-> {}".format(data["relative_path"]))
        print("Compress PDF...")

    elif step == "copying":
        print("-> {}".format(data["relative_path"]))

    elif step == "compressed":
        processed = data["file"]
        # "Compression by 0%" seria a leitura errada do que aconteceu: o
        # arquivo não resistiu à compressão, ele já estava otimizado, e o que
        # está na saída é o original — não uma versão recomprimida sem ganho.
        if processed.kept_original:
            print("Already optimized: compressing would make it bigger.")
            print("Kept the original ({0:.1f}MB).".format(processed.size_after / 1000000))
            print()
        else:
            print("Compression by {0:.0%}.".format(processed.savings))
            print("Final file size is {0:.1f}MB".format(processed.size_after / 1000000))
            print("Done.")
            print()

    elif step == "copied":
        print("Copied as is ({0:.1f}MB).".format(data["file"].size_after / 1000000))
        print()

    elif step == "rotated":
        print("Rotated '{}' by {} degrees.".format(data["file"].path, data["degrees"]))

    elif step == "merged":
        print()
        print("Merged {} file(s) into '{}' ({:.1f}MB).".format(
            data["count"], data["path"], data["size"] / 1000000))

    elif step == "done":
        result = data["result"]
        print()
        print("{} file(s) written.".format(len(result.files)))
        if result.compressed:
            print("Total: {0:.1f}MB -> {1:.1f}MB ({2:.0%}).".format(
                result.size_before / 1000000,
                result.size_after / 1000000,
                result.savings))
            kept = result.kept
            if kept:
                # Sem esta linha, o total de um lote ja otimizado seria "0%" e
                # pareceria falha do programa, quando na verdade e a resposta
                # certa: nao havia o que ganhar, e nada foi piorado.
                print("{} of them were already optimized and were kept as they "
                      "were.".format(len(kept)))
                # So niveis mais fortes do que o usado: mandar tentar -c 3 quem
                # acabou de rodar -c 3 e o jeito mais rapido de um conselho
                # perder a credibilidade.
                codes = [code for code, _, _ in service.LEVELS]
                stronger = codes[codes.index(result.level) + 1:] if result.level in codes else []
                if stronger:
                    print("To reduce them anyway, try {} (they lower image "
                          "resolution).".format(
                              " or ".join("-c {}".format(c) for c in stronger)))
                else:
                    print("You already used the strongest level: there is "
                          "nothing more to squeeze this way.")
        else:
            # Sem compressao um "Total: 2.0MB -> 2.0MB (0%)" so faria o leitor
            # procurar o que deu errado.
            print("Total: {0:.1f}MB (not compressed).".format(
                result.size_after / 1000000))


def compress_dir(input_dir=INPUT_DIR, output_dir=OUTPUT_DIR, power=2,
                 degree=0, merge_into=None, order=None):
    """Processa todo PDF de `input_dir` para `output_dir`.

    A estrutura de subpastas é espelhada: um PDF solto em `input` cai solto em
    `output`, e um PDF em `input/lote` cai em `output/lote`. Devolve a lista
    de arquivos escritos.
    """
    try:
        result = service.run(
            input_dir=input_dir,
            output_dir=output_dir,
            level=power,
            degrees=degree or 0,
            merge_into=merge_into,
            order=order,
            on_progress=_echo,
        )
    except PdfError as error:
        _die(error)

    return [str(f.path) for f in result.files]


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument('input', nargs='?',
                        help="Relative or absolute path of the input PDF file. "
                             "When omitted, every PDF in the '{}' folder is "
                             "compressed into '{}'.".format(INPUT_DIR, OUTPUT_DIR))
    parser.add_argument('-o', '--out', help='Relative or absolute path of the output PDF file '
                                            '(or of the output folder, in folder mode)')
    parser.add_argument('-c', '--compress', type=int, help='Compression level from 0 to 4')
    parser.add_argument('-n', '--no-compress', action='store_true',
                        help="Don't compress, only copy. Lets --merge and --rotate "
                             "run without Ghostscript installed")
    parser.add_argument('-b', '--backup', action='store_true', help="Backup the old PDF file")
    parser.add_argument('-m', '--merge', metavar='NAME',
                        help='Also join the compressed PDFs into a single file named NAME')
    parser.add_argument('-r', '--rotate', type=int, metavar='DEGREE',
                        help='Rotate every page of the result by DEGREE (multiple of 90)')
    parser.add_argument('--open', action='store_true', default=False,
                        help='Open PDF after compression')
    args = parser.parse_args()

    # `power is None` quer dizer "nao comprimir". Repare no teste `is None`:
    # com um `if not args.compress`, o nivel 0 ('/default') era falso e virava
    # 2 em silencio, entao o nivel que o README documenta nunca era alcancado.
    power = None if args.no_compress else (2 if args.compress is None else args.compress)

    # --merge junta VARIOS PDFs, entao nao significa nada para um arquivo so.
    # Antes era aceito ali e ignorado sem aviso.
    if args.input is not None and args.merge:
        print("Error: --merge joins several PDFs and only works in folder mode.")
        print()
        print("Drop the files in '{}' and run without the input argument.".format(INPUT_DIR))
        sys.exit(1)

    # Modo pasta: 'input' -> 'output', sem nunca tocar nos arquivos de origem
    if args.input is None:
        compress_dir(INPUT_DIR, args.out or OUTPUT_DIR, power=power,
                     degree=args.rotate or 0, merge_into=args.merge)
        return

    # Sem arquivo de saida declarado, escreve num temporario
    if not args.out:
        args.out = 'temp.pdf'

    if power is None:
        shutil.copyfile(args.input, args.out)
    else:
        compress(args.input, args.out, power=power)

    # Sem arquivo de saida declarado, o original e substituido
    if args.out == 'temp.pdf':
        if args.backup:
            shutil.copyfile(args.input, args.input.replace(".pdf", "_BACKUP.pdf"))
        shutil.copyfile(args.out, args.input)
        os.remove(args.out)

    # A rotacao se aplica ao resultado comprimido
    if args.rotate:
        rotate(args.input if args.out == 'temp.pdf' else args.out, args.rotate)

    if args.open:
        if args.out == 'temp.pdf' and args.backup:
            subprocess.call(['open', args.input])
        else:
            subprocess.call(['open', args.out])


if __name__ == '__main__':
    main()
