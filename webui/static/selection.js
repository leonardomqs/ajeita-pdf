/* Os arquivos escolhidos: escolher, soltar, remover, reordenar.
 *
 * Vive num arquivo só porque duas telas usam a mesma lista — a de comprimir e
 * a de juntar. Duplicá-la em dois <script> de template seria repetir a mesma
 * decisão de interface em dois lugares, e é essa a divergência que o resto do
 * projeto evita desde a extração do `service.py`.
 *
 * O que ela resolve: **uma FileList é somente leitura**. Não dá para reordenar
 * nem remover arquivos dentro de um <input type="file">, e uma segunda escolha
 * substitui a primeira em vez de somar. Então a seleção de verdade vive aqui,
 * nesta lista em JavaScript, e quem a envia é o `upload.js` — que monta o
 * formulário a partir dela, não dos inputs.
 *
 * Enquanto o `upload.js` não assumir (`own()`), os inputs continuam donos dos
 * arquivos: a lista só manda a ordem, e remover não tiraria nada do envio. Por
 * isso o botão de remover só aparece depois que ele assume. Sem JavaScript
 * nenhum a página volta a ser um formulário comum, com a ordem alfabética do
 * servidor — perde o recurso, não a função.
 *
 * O que a página precisa ter:
 *   - um ou mais <input type="file" data-files>
 *   - #list, #list-block, #count, #total, #order
 * O que ela ganha:
 *   - window.SelectedFiles
 */

(function () {
  const list = document.getElementById("list");
  if (!list) return;

  const block = document.getElementById("list-block");
  const count = document.getElementById("count");
  const total = document.getElementById("total");
  const overNote = document.getElementById("over-limit");
  const orderField = document.getElementById("order");
  const clear = document.getElementById("clear");
  const inputs = Array.from(document.querySelectorAll("[data-files]"));
  const zones = Array.from(document.querySelectorAll("[data-drop]"));

  //: O teto de envio do servidor, em bytes, vindo do template. Compará-lo com
  //: o total aqui evita o pior caminho possível: esperar o envio de 600 MB
  //: inteiro para receber um erro que já se sabia no momento da escolha.
  const limit = Number(block.dataset.limit || 0);

  let items = [];
  let owned = false;

  function humanSize(bytes) {
    if (bytes >= 1048576) return (bytes / 1048576).toFixed(1).replace(".", ",") + " MB";
    if (bytes >= 1024) return Math.round(bytes / 1024) + " KB";
    return bytes + " B";
  }

  function totalBytes() {
    return items.reduce((sum, item) => sum + item.bytes, 0);
  }

  // --------------------------------------------------------------- a lista

  function add(found) {
    for (const entry of found) {
      const file = entry.file;
      const path = entry.name || file.webkitRelativePath || file.name;
      if (!path.toLowerCase().endsWith(".pdf")) continue;
      // Agora que a seleção se acumula, escolher duas vezes os mesmos
      // arquivos é engano comum. Mesmo caminho, mesmo tamanho e mesma data de
      // modificação é o mesmo arquivo: entra uma vez só.
      const repeated = items.some(
        (item) =>
          item.name === path && item.bytes === file.size && item.stamp === file.lastModified
      );
      if (repeated) continue;
      items.push({ file: file, name: path, bytes: file.size, stamp: file.lastModified });
    }
    render();
  }

  function move(from, to) {
    if (to < 0 || to >= items.length || from === to) return;
    const [item] = items.splice(from, 1);
    items.splice(to, 0, item);
    render();
  }

  function render() {
    block.hidden = items.length === 0;
    count.textContent = items.length
      ? "— " + items.length + (items.length === 1 ? " arquivo" : " arquivos")
      : "";

    const size = totalBytes();
    const over = limit > 0 && size > limit;
    total.textContent = humanSize(size);
    total.classList.toggle("over", over);
    if (overNote) overNote.hidden = !over;
    if (clear) clear.hidden = !owned;

    list.replaceChildren();
    items.forEach((item, i) => list.appendChild(row(item, i)));

    orderField.value = items.map((item) => item.name).join("\n");
  }

  function row(item, i) {
    const li = document.createElement("li");
    li.className = "item";
    li.draggable = true;
    li.dataset.index = i;

    const grip = document.createElement("span");
    grip.className = "item-grip";
    grip.setAttribute("aria-hidden", "true");
    grip.textContent = "⣿";

    // textContent, nunca innerHTML: o nome vem do arquivo que a pessoa
    // escolheu, e um nome pode conter < e >.
    const name = document.createElement("span");
    name.className = "item-name";
    name.textContent = item.name;

    const size = document.createElement("span");
    size.className = "item-size";
    size.textContent = humanSize(item.bytes);

    const buttons = document.createElement("span");
    buttons.className = "item-buttons";
    for (const step of [-1, 1]) {
      const button = control(step === -1 ? "↑" : "↓", (step === -1 ? "subir " : "descer ") + item.name);
      button.classList.add("move");
      button.dataset.step = step;
      button.disabled = (step === -1 && i === 0) || (step === 1 && i === items.length - 1);
      buttons.appendChild(button);
    }
    // Remover só faz sentido quando é esta lista que vai ser enviada. Sem o
    // `upload.js`, o arquivo subiria do mesmo jeito e o botão seria mentira.
    if (owned) {
      const remove = control("✕", "tirar " + item.name + " da lista");
      remove.classList.add("remove");
      buttons.appendChild(remove);
    }

    li.append(grip, name, size, buttons);
    return li;
  }

  function control(glyph, label) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "item-button";
    button.textContent = glyph;
    button.title = label;
    button.setAttribute("aria-label", label);
    return button;
  }

  // ------------------------------------------------- de onde vêm os arquivos

  function collect(event) {
    const input = event.target;
    add(Array.from(input.files).map((file) => ({ file: file, name: "" })));
    // Esvaziar o input serve a duas coisas: escolher o MESMO arquivo de novo
    // volta a disparar `change` (senão a segunda escolha seria silenciosa), e
    // o formulário não manda uma segunda cópia por baixo. Só depois que o
    // `upload.js` assumiu, porque sem ele o input ainda é quem carrega tudo.
    if (owned) input.value = "";
  }

  for (const input of inputs) input.addEventListener("change", collect);

  /* Arrastar de fora: do Explorer para a página.
   *
   * O alvo é a janela inteira, não só a área tracejada. Quem arrasta mira no
   * que está vendo, e um PDF solto dois centímetros fora não deveria virar
   * "o navegador abriu o arquivo, e a página com tudo o que já estava
   * escolhido se perdeu" — que é o que acontece sem `preventDefault`.
   */
  function draggingFiles(event) {
    // O arrasto interno da lista não carrega "Files". Sem esta pergunta,
    // reordenar acenderia a área de soltar a cada item movido.
    const types = event.dataTransfer ? event.dataTransfer.types : null;
    return !!types && Array.from(types).indexOf("Files") !== -1;
  }

  function highlight(on) {
    for (const zone of zones) zone.classList.toggle("drop--over", on);
  }

  let depth = 0;
  window.addEventListener("dragenter", (event) => {
    if (!draggingFiles(event)) return;
    depth += 1;
    highlight(true);
  });
  window.addEventListener("dragleave", () => {
    // dragleave dispara também ao passar de um elemento para outro dentro da
    // página. Contar entradas e saídas é o que distingue "saiu de um filho"
    // de "saiu da janela" — sem isso a área pisca durante o arrasto.
    depth = Math.max(0, depth - 1);
    if (!depth) highlight(false);
  });
  window.addEventListener("dragover", (event) => {
    if (!draggingFiles(event)) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
  });
  window.addEventListener("drop", (event) => {
    if (!draggingFiles(event)) return;
    event.preventDefault();
    depth = 0;
    highlight(false);
    accept(event.dataTransfer);
  });

  function accept(transfer) {
    // webkitGetAsEntry tem de ser lido AGORA: a lista de itens do arrasto é
    // esvaziada assim que este handler retorna, e ler uma pasta é assíncrono.
    const entries = [];
    for (const item of transfer.items || []) {
      const entry = item.webkitGetAsEntry ? item.webkitGetAsEntry() : null;
      if (entry) entries.push(entry);
    }
    if (!entries.length) {
      add(Array.from(transfer.files || []).map((file) => ({ file: file, name: file.name })));
      return;
    }
    Promise.all(entries.map((entry) => walk(entry, ""))).then((lists) => add(lists.flat()));
  }

  /* Uma pasta arrastada chega como diretório, e dá para percorrê-la. É o que
   * mantém, no arrasto, a mesma promessa que a pasta `input/` cumpre na linha
   * de comando: a saída espelha a estrutura que entrou. */
  function walk(entry, prefix) {
    if (entry.isFile) {
      return new Promise((resolve) => {
        entry.file(
          (file) => resolve([{ file: file, name: prefix + entry.name }]),
          () => resolve([])
        );
      });
    }
    if (!entry.isDirectory) return Promise.resolve([]);

    const reader = entry.createReader();
    const folder = prefix + entry.name + "/";
    const found = [];
    return new Promise((resolve) => {
      // readEntries entrega a pasta em levas e sinaliza o fim com uma leva
      // vazia. Uma chamada só traria as primeiras ~100 entradas, e nada na
      // resposta diria que faltou o resto.
      const step = () =>
        reader.readEntries((batch) => {
          if (!batch.length) {
            Promise.all(found.map((child) => walk(child, folder))).then((lists) =>
              resolve(lists.flat())
            );
            return;
          }
          for (const child of batch) found.push(child);
          step();
        }, () => resolve([]));
      step();
    });
  }

  // ---------------------------------------------------------- mexer na lista

  list.addEventListener("click", (event) => {
    const button = event.target.closest(".item-button");
    if (!button) return;
    const i = Number(button.closest(".item").dataset.index);
    if (button.classList.contains("remove")) {
      items.splice(i, 1);
      render();
      return;
    }
    move(i, i + Number(button.dataset.step));
  });

  const sortByName = document.getElementById("sort-name");
  if (sortByName) {
    sortByName.addEventListener("click", () => {
      items.sort((a, b) => a.name.localeCompare(b.name, "pt-BR", { numeric: true }));
      render();
    });
  }
  const reverse = document.getElementById("reverse");
  if (reverse) {
    reverse.addEventListener("click", () => {
      items.reverse();
      render();
    });
  }
  if (clear) {
    clear.addEventListener("click", () => {
      items = [];
      for (const input of inputs) input.value = "";
      render();
    });
  }

  // Arrastar dentro da lista: o movimento acontece no drop, não no dragover.
  // Reordenar durante o dragover redesenha a lista embaixo do cursor e o
  // arrasto se perde.
  let dragging = null;
  list.addEventListener("dragstart", (event) => {
    const li = event.target.closest(".item");
    if (!li) return;
    dragging = Number(li.dataset.index);
    li.classList.add("dragging");
    event.dataTransfer.effectAllowed = "move";
  });
  list.addEventListener("dragover", (event) => {
    event.preventDefault();
    const li = event.target.closest(".item");
    if (li && dragging !== null) li.classList.add("drop-target");
  });
  list.addEventListener("dragleave", (event) => {
    const li = event.target.closest(".item");
    if (li) li.classList.remove("drop-target");
  });
  list.addEventListener("drop", (event) => {
    const li = event.target.closest(".item");
    if (!li || dragging === null) return;
    // O `drop` da janela também veria este evento e trataria o arrasto interno
    // como arquivo chegando de fora.
    event.preventDefault();
    event.stopPropagation();
    move(dragging, Number(li.dataset.index));
    dragging = null;
  });
  list.addEventListener("dragend", () => {
    dragging = null;
    render();
  });

  window.SelectedFiles = {
    count: () => items.length,
    bytes: totalBytes,
    limit: () => limit,
    overLimit: () => limit > 0 && totalBytes() > limit,
    chosen: () => items.map((item) => ({ file: item.file, name: item.name })),
    //: Exposto porque o `upload.js` escreve o mesmo tamanho na barra de
    //: progresso. Dois formatadores divergiriam na primeira mudança.
    humanSize: humanSize,
    //: O `upload.js` avisa que passou a ser ele quem envia. Daqui em diante os
    //: inputs são só uma porta de entrada, e esta lista é a seleção.
    own() {
      owned = true;
      render();
    },
  };
})();
