/* O andamento da rodada, perguntado de tempos em tempos.
 *
 * A página já nasce com o andamento inteiro desenhado pelo servidor — barra e
 * lista. Este arquivo só troca esse pedaço pela versão mais nova, e por isso
 * não monta nada: o HTML das linhas vive no `_progress.html`, num lugar só,
 * e é o mesmo que quem não tem JavaScript recebe a cada <meta refresh>.
 *
 * Perguntar de novo, e não um fluxo aberto do servidor: é o servidor de
 * desenvolvimento do Flask rodando na máquina da própria pessoa, e segurar uma
 * conexão por rodada custaria mais do que uma pergunta contra 127.0.0.1.
 */

(function () {
  const box = document.getElementById("running");
  if (!box) return;

  const url = box.dataset.progress;

  //: Quantas perguntas seguidas falharam. O servidor local não costuma cair no
  //: meio de uma rodada, mas fechar a janela preta é como o programa termina —
  //: e aí a página precisa dizer isso em vez de girar para sempre.
  let failures = 0;

  //: O último pedaço recebido. Enquanto um arquivo grande é comprimido, a
  //: resposta é igual à anterior: comparar evita redesenhar a lista inteira
  //: duas vezes por segundo sem nada ter mudado.
  let last = "";

  //: Acompanhar a linha em curso enquanto a pessoa não rolar a lista. Num lote
  //: de oitenta arquivos, a linha de agora sai de vista em poucos segundos; se
  //: alguém foi olhar outra parte, ficar puxando a rolagem de volta seria pior
  //: do que não acompanhar.
  let following = true;

  function stopFollowing() {
    following = false;
  }

  function swap(html) {
    const before = box.querySelector(".scroll--andamento");
    const top = before ? before.scrollTop : 0;

    box.innerHTML = html;

    const after = box.querySelector(".scroll--andamento");
    if (!after) return;
    after.scrollTop = top;
    // Gestos de rolagem, e não o evento `scroll`: este dispara também quando
    // somos nós que mexemos, e não dá para distinguir um do outro.
    for (const gesture of ["wheel", "touchstart", "keydown", "mousedown"]) {
      after.addEventListener(gesture, stopFollowing, { passive: true });
    }
    if (following) keepInView(after);
  }

  function keepInView(scroller) {
    const current = scroller.querySelector(".row--working");
    if (!current) return;
    const above = current.offsetTop < scroller.scrollTop;
    const below =
      current.offsetTop + current.offsetHeight > scroller.scrollTop + scroller.clientHeight;
    if (above || below) {
      scroller.scrollTop = current.offsetTop - scroller.clientHeight / 2;
    }
  }

  /* De quanto em quanto perguntar.
   *
   * A resposta é a lista inteira: num lote de duzentos arquivos ela passa de
   * 80 KB, e perguntar três vezes por segundo faria o servidor gastar mais
   * tempo desenhando a lista do que comprimindo PDF. Num lote grande cada
   * arquivo também leva menos tempo do que o intervalo, então espaçar não
   * esconde nada — e num lote pequeno, onde cada arquivo demora, a pergunta
   * continua rápida. */
  function delay(marker) {
    const many = marker && Number(marker.dataset.files) > 60;
    return many ? 1200 : 400;
  }

  function lost() {
    const note = box.querySelector(".progress-note");
    if (note) {
      note.textContent =
        "Perdi o contato com o servidor. A janela preta do ajeita-pdf pode ter " +
        "sido fechada; se ela ainda estiver aberta, recarregue esta página.";
    }
  }

  function ask() {
    fetch(url, { headers: { Accept: "text/html" }, cache: "no-store" })
      .then((response) => {
        if (!response.ok) throw new Error(response.status);
        return response.text();
      })
      .then((html) => {
        failures = 0;
        if (html !== last) {
          last = html;
          swap(html);
        }
        const marker = box.querySelector("[data-state]");
        const state = marker ? marker.dataset.state : "running";
        if (state === "done" || state === "error") {
          // A página desta rodada sabe desenhar os três estados. Recarregá-la é
          // mais honesto do que montar o resultado aqui: é o servidor que
          // decide o que a rodada virou.
          window.location.reload();
          return;
        }
        setTimeout(ask, delay(marker));
      })
      .catch(() => {
        failures += 1;
        if (failures < 5) {
          setTimeout(ask, 1000);
          return;
        }
        lost();
      });
  }

  setTimeout(ask, 300);
})();
