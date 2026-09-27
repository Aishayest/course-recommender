// Пересчёт итогового балла прямо в браузере.
//
// Слагаемые уже посчитаны сервером и лежат в разметке карточки: близость,
// шанс, нужность, оценки. Формула балла — их взвешенная сумма, так что
// подвинуть ползунок и увидеть новый порядок можно без обращения к серверу.
// Пересобрать сам список кандидатов — уже нельзя, для этого нужна кнопка.
(function () {
  "use strict";

  var PARTS = ["need", "access", "fit", "ease"];

  var form = document.getElementById("weights");
  var list = document.getElementById("courses");
  if (!form || !list) return;

  var cards = Array.prototype.slice.call(list.querySelectorAll(".course"));
  if (!cards.length) return;

  function weights() {
    var found = {};
    PARTS.forEach(function (name) {
      var input = form.elements[name];
      found[name] = input ? parseFloat(input.value) : 0;
    });
    return found;
  }

  function score(card, w) {
    var total = 0;
    var sum = 0;
    PARTS.forEach(function (name) {
      var value = parseFloat(card.dataset[name]);
      total += w[name] * (isNaN(value) ? 0 : value);
      sum += w[name];
    });
    // Сумма весов нормируется — как на сервере, иначе баллы несравнимы.
    return sum ? total / sum : 0;
  }

  function apply() {
    var w = weights();

    cards.forEach(function (card) {
      card.querySelector("[data-score]").textContent = score(card, w).toFixed(2);
      PARTS.forEach(function (name) {
        var part = card.querySelector('[data-part="' + name + '"]');
        if (!part) return;
        part.querySelector("[data-weight]").textContent = "×" + w[name].toFixed(1);
        part.classList.toggle("component--muted", !w[name]);
        var uncounted = part.querySelector("[data-uncounted]");
        if (uncounted) uncounted.hidden = w[name] > 0;
      });
    });

    cards
      .slice()
      .sort(function (a, b) { return score(b, w) - score(a, w); })
      .forEach(function (card, index) {
        card.querySelector("[data-rank]").textContent = "#" + (index + 1);
        list.appendChild(card);
      });
  }

  form.addEventListener("input", apply);
  // При загрузке ничего не пересчитываем: сервер уже отрисовал те же числа,
  // а округление слагаемых в разметке могло бы дёрнуть балл на сотую.
  var note = form.querySelector("[data-live-note]");
  if (note) note.hidden = false;
})();
