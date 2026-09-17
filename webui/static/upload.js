/* O envio, com sinal de vida.
 *
 * Por que não deixar o navegador enviar o formulário sozinho:
 *
 *   1. Os arquivos de verdade estão na lista do `selection.js` — que pode ter
 *      itens removidos, outra ordem, e arquivos que vieram de um arrasto.
 *      Nenhum <input type="file"> consegue representar isso, porque a FileList
 *      dele é somente leitura.
 *   2. Num lote de 200 MB o envio nativo deixa a página parada por minutos sem
 *      dizer nada, e "travou" é a conclusão natural de quem está olhando.
 *
 * A resposta é a mesma que o envio nativo receberia, e é ela que decide para
 * onde ir: rodada boa termina em redirecionamento — o navegador já o seguiu, e
 * `responseURL` é a página de resultado. Erro devolve a página pronta na
 * própria URL do POST, e ela é desenhada no lugar desta.
 *
 * Se este arquivo não carregar, `own()` nunca é chamado e o formulário volta a
 * ser um formulário: envia pelos inputs, sem barra e sem remoção, mas envia.
 */

(function () {
  const form = document.getElementById("form");
  const files = window.SelectedFiles;
  if (!form || !files) return;

  const button = document.getElementById("submit");
  const problem = document.getElementById("form-error");
  const progress = document.getElementById("progress");
  const fill = document.getElementById("progress-fill");
  const note = document.getElementById("progress-note");

  //: Há um envio a caminho. Desabilitar o botão não basta: um Enter num campo
  //: de texto ainda dispara `submit`, e o segundo envio subiria o lote inteiro
  //: outra vez e abriria uma segunda rodada com os mesmos arquivos.
  let flying = false;

  //: O que impede o envio, na ordem em que foi registrado. Cada tela
  //: acrescenta as suas (a de juntar exige dois arquivos; a de comprimir
  //: recusa a rodada que não faria nada), e a primeira que devolver texto
  //: interrompe. É registro explícito, e não mais um `addEventListener` de
  //: submit, porque a ordem entre dois ouvintes do mesmo evento depende de
  //: qual <script> o navegador leu primeiro — e a validação PRECISA vir
  //: antes do envio, não depois dele já ter começado.
  const guards = [
    () =>
      files.overLimit()
        ? "Os arquivos somam " +
          files.humanSize(files.bytes()) +
          ", acima do limite de " +
          files.humanSize(files.limit()) +
          " que o servidor aceita de uma vez. Tire alguns da lista e mande o resto numa segunda leva."
        : null,
  ];

  function complain(text) {
    problem.textContent = text;
    problem.hidden = false;
    problem.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }

  function sending(loaded, size) {
    progress.hidden = false;
    progress.classList.remove("progress--working");
    fill.style.width = Math.round((loaded / size) * 100) + "%";
    note.textContent =
      "Enviando… " + files.humanSize(loaded) + " de " + files.humanSize(size);
  }

  function working() {
    // Os bytes chegaram; agora é o Ghostscript. Daqui em diante não há
    // percentual nenhum a mostrar — fingir um seria pior do que assumir a
    // espera, então a barra passa a só dizer que ainda está vivo.
    progress.classList.add("progress--working");
    fill.style.width = "100%";
    note.textContent = "Arquivos recebidos. Processando — num lote grande isto demora.";
  }

  function failed(text) {
    flying = false;
    progress.hidden = true;
    button.disabled = false;
    button.textContent = button.dataset.label;
    complain(text);
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    if (flying) return;

    for (const guard of guards) {
      const text = guard();
      if (text) {
        complain(text);
        return;
      }
    }
    problem.hidden = true;

    const data = new FormData();
    for (const [name, value] of new FormData(form)) {
      // Os campos de arquivo do formulário ficam de fora: quem manda os
      // arquivos é a lista. Os inputs já foram esvaziados, mas depender disso
      // seria depender de um efeito colateral de outro arquivo.
      if (!(value instanceof File)) data.append(name, value);
    }
    for (const chosen of files.chosen()) {
      // O terceiro argumento é o nome que viaja no envio. Num arrasto de pasta
      // ele carrega o caminho relativo ("lote/ata_01.pdf"), que é o que faz a
      // saída espelhar a entrada — e é o mesmo nome que está no campo `order`.
      data.append("pdfs", chosen.file, chosen.name);
    }

    const size = files.bytes();
    flying = true;
    button.dataset.label = button.textContent;
    button.disabled = true;
    button.textContent = button.dataset.busy || "Processando…";
    sending(0, size || 1);

    const xhr = new XMLHttpRequest();
    xhr.open("POST", form.action);
    xhr.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable) sending(event.loaded, event.total);
    });
    xhr.upload.addEventListener("load", working);
    xhr.addEventListener("load", () => {
      if (xhr.responseURL && xhr.responseURL !== form.action) {
        window.location.href = xhr.responseURL;
        return;
      }
      // Sem redirecionamento, a resposta É a página de erro, já pronta e já
      // explicada pelo servidor. Desenhá-la aqui evita reescrever na tela uma
      // mensagem que o `service.py` sabe dar melhor.
      document.open();
      document.write(xhr.responseText);
      document.close();
    });
    xhr.addEventListener("error", () =>
      failed(
        "O envio foi interrompido. Se o servidor ainda estiver aberto, tente de novo; " +
          "num lote muito grande, mande os arquivos em duas levas."
      )
    );
    xhr.addEventListener("abort", () => failed("O envio foi cancelado."));
    xhr.send(data);
  });

  window.Upload = {
    //: Cada tela registra aqui o que a impede de enviar. A função devolve o
    //: texto a mostrar, ou null se estiver tudo bem.
    check: (fn) => guards.push(fn),
  };

  files.own();
})();
