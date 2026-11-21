// Baut ein Blatt aus den Daten eines Posts (posts/<name>.json).
function render(post, nr) {
  const sl = post.slides[nr - 1];
  const zwei = n => String(n).padStart(2, '0');
  // Das Feld des Diagramms kommt zuerst leer aufs Blatt. Gezeichnet wird ganz unten, wenn feststeht,
  // wie groß das Feld ist; so behalten die Beschriftungen ihre Größe in Pixeln (siehe charts.js).
  const figur = sl.figur ? '<div class="figur"></div>' : '';
  const absaetze = (sl.text || []).map(p => `<p>${p}</p>`).join('');
  const kicker = sl.kicker ? `<div class="kicker">${sl.kicker}</div>` : '';
  const kopf = `${kicker}<h2>${sl.headline}</h2>${absaetze}`;
  const fuss = sl.fuss ? `<div class="fuss">${sl.fuss}</div>` : '';
  let inhalt;

  if (sl.typ === 'cover') {
    inhalt = `${kicker}<div class="zahl">${sl.zahl}</div><h1>${sl.headline}</h1>${absaetze}${figur}`;
  } else if (sl.typ === 'balken') {
    // Die Länge richtet sich nach dem größten Wert.
    const max = Math.max(...sl.balken.map(b => b.wert));
    const reihen = sl.balken.map(b =>
      `<div class="reihe${b.akzent ? ' akz' : ''}"><div class="kopf"><span class="wert">${b.anzeige}</span><span class="wer">${b.name}</span></div>` +
      `<div class="bahn"><i style="width:${(b.wert / max) * 100}%"></i></div></div>`).join('');
    inhalt = `${kopf}<div class="balkenfeld">${reihen}</div>${fuss}`;
  } else if (sl.typ === 'punkte') {
    const punkte = sl.punkte.map(p =>
      `<div class="punkt"><div class="wert">${p.wert}</div><div><div class="wer">${p.name}</div><div class="zusatz">${p.zusatz || ''}</div></div></div>`).join('');
    inhalt = `${kopf}<div class="kennzahlen">${punkte}</div>${fuss}`;
  } else if (sl.typ === 'outro') {
    inhalt = `${Diagramm.marke()}<h2>${sl.headline}</h2>${absaetze}<div class="konto">Folgen: ${post.konto}</div>` +
      `<div class="quellen">Quellen: ${post.quellen.join(' · ')}</div>`;
  } else {
    // "diagramm": Überschrift, Text, Diagramm, Fußzeile
    inhalt = `${kopf}${figur}${fuss}`;
  }

  // Die Leiste zeigt den Titel des Posts und die Blattnummer. Die Nummer des Posts steht dort nicht mehr:
  // In der Mindestschrift von 30 px passt sonst nicht alles in eine Zeile.
  document.getElementById('sheet').innerHTML =
    `<div class="inhalt ${sl.typ}">${inhalt}</div>` +
    `<div class="leiste"><div>${Diagramm.marke()}<span class="name">Schaubild</span></div>` +
    `<div class="thema">${post.titel}</div><div class="blatt">${zwei(nr)}/${zwei(post.slides.length)}</div></div>`;

  if (sl.figur) {
    const feld = document.querySelector('#sheet .figur');
    feld.innerHTML = Diagramm[sl.figur.fn]({ ...sl.figur, breite: feld.clientWidth, hoehe: feld.clientHeight });
  }
  window.bereit = true;   // tools/pruefen.py wartet darauf
}
