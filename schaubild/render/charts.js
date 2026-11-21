// Diagramme für Schaubild. Jede Funktion liefert ein SVG als String.
// Alle Zahlen kommen aus dem Post (posts/<name>.json); hier wird nur gezeichnet.
//
// Ein Diagramm wird in den echten Pixeln seines Feldes gezeichnet (o.breite x o.hoehe; render.js und
// reel.html messen das Feld). Der viewBox ist genauso groß, also skaliert nichts: Eine Schrift von 30 px
// ist im Blatt 30 px, egal wie viel Platz Überschrift und Text dem Diagramm lassen.
// Mindestschrift des Kanals: 30 px im Blatt (knapp 11 px am Handy), 40 px im Reel.
(function () {
  const r = n => Math.round(n * 10) / 10;
  const svg = (w, h, body, attr = '') =>
    `<svg class="fig" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${r(w)} ${r(h)}" preserveAspectRatio="xMidYMid meet" ${attr}>${body}</svg>`;
  const text = (x, y, inhalt, cls, gr, attr = '') =>
    `<text x="${r(x)}" y="${r(y)}" class="${cls}" style="font-size:${gr}px" ${attr}>${inhalt}</text>`;

  // Schriftgrößen in Pixeln des Blatts. o.schrift überschreibt sie, z. B. im Reel { achse: 40, marke: 46 }.
  // achse: Achsen, Jahre, zweite Zeile einer Marke · marke: Marken und Namen der Reihen · wert: große Werte
  const SCHRIFT = { achse: 30, marke: 34, wert: 76 };
  const ART = {
    achse: { font: '400 {}px "IBM Plex Mono"', em: 0.6 },
    marke: { font: '600 {}px Barlow', em: 0.54 },
    wert: { font: '700 {}px "Barlow Condensed"', em: 0.47 },
  };
  // Breite eines Textes in Pixeln: gemessen mit der geladenen Schrift, sonst geschätzt.
  let stift = null;
  function breite(s, art, gr) {
    const klar = String(s).replace(/<[^>]+>/g, '');
    try {
      stift = stift || document.createElement('canvas').getContext('2d');
      stift.font = ART[art].font.replace('{}', gr);
      const b = stift.measureText(klar).width;
      if (b > 0) return b;
    } catch (e) { /* ohne Zeichenfläche: schätzen */ }
    return klar.length * ART[art].em * gr;
  }
  // Fläche eines Textes: [links, rechts, oben, unten] zur Grundlinie y
  const kasten = (x, y, b, gr, anker) => {
    const x0 = anker === 'end' ? x - b : anker === 'middle' ? x - b / 2 : x;
    return [x0, x0 + b, y - gr * 0.78, y + gr * 0.14];
  };
  const trifft = (a, b, luft = 8) => a[0] - luft < b[1] && a[1] + luft > b[0] && a[2] - luft < b[3] && a[3] + luft > b[2];

  // Maße und Abbildung eines Liniendiagramms; das Reel braucht sie für die wandernde Kante.
  function geo(o) {
    const W = o.breite || 900, H = o.hoehe || 700;
    const fs = { ...SCHRIFT, ...(o.schrift || {}) };
    const l = 12, rechts = 16;
    // oben so viel Rand, wie die höchste Beschriftung über einem Punkt braucht
    const oben = Math.max(16, ...(o.marken || []).filter(m => m.text)
      .map(m => (m.gross ? fs.wert : fs.marke) * 0.78 + 30 + (m.zeile2 ? fs.achse * 1.15 : 0)));
    const unten = (o.jahre || []).length ? fs.achse + 26 : 10;
    const von = Math.min(...o.reihen.map(s => s.von));
    const bis = Math.max(...o.reihen.map(s => s.von + s.werte.length - 1));
    const ymin = o.ymin ?? 0;
    const ymax = Math.max(o.ymax ?? -Infinity, ...o.reihen.flatMap(s => s.werte));   // nie unter dem Höchstwert
    const X = j => l + ((j - von) / ((bis - von) || 1)) * (W - l - rechts);
    const Y = v => H - unten - ((v - ymin) / ((ymax - ymin) || 1)) * (H - oben - unten);
    return { W, H, fs, l, rechts, oben, unten, von, bis, ymin, ymax, X, Y };
  }

  // Liniendiagramm über Jahre.
  // o.reihen:  [{ von, werte: [...], akzent, flaeche, name, nameBei: { jahr, dy } }]   ein Wert pro Jahr ab "von"
  // o.ymin, o.ymax: Bereich der Werteachse. ymax knapp über dem Höchstwert genügt; den Platz für Marken
  //            schafft die Zeichnung selbst. Mit ymin über null beginnt die Achse nicht bei null: Dann braucht
  //            das Blatt den Hinweis darauf (fuss) und die Achse eine Beschriftung auf der Grundlinie.
  // o.achse:   [{ wert, text }]        waagerechte Hilfslinien mit Beschriftung (text "" = nur Linie)
  // o.jahre:   [1950, 1970, ...]       Beschriftung der Zeitachse; erstes und letztes Jahr stehen immer,
  //                                    ein Jahr dazwischen entfällt, wenn es an ein anderes stoßen würde
  // o.marken:  [{ reihe, jahr, text, zeile2, seite: 'oben' | 'unten', anker: 'start' | 'middle' | 'end',
  //               gross: true, akzent: true }]   gross = Wert in großer Schrift (Titelblatt), akzent = golden
  //            Eine Marke bleibt im Feld und weicht der Kurve und anderen Texten aus (andere Seite); findet
  //            sie keinen Platz, entfällt ihr Text (am SVG steht dann data-entfallen, tools/pruefen.py meldet es).
  // o.breite, o.hoehe: Größe des Feldes in Pixeln (setzt render.js bzw. reel.html)
  // o.schrift: { achse, marke, wert }  Schriftgrößen in Pixeln
  function linie(o) {
    const { W, H, fs, l, rechts, unten, von, bis, ymin, X, Y } = geo(o);
    const grund = H - unten;
    let body = '', oben = '';
    const belegt = [];       // Flächen schon gesetzter Texte
    const entfallen = [];

    // Liegt eine Kurve in diesem Rechteck? Geprüft werden die Jahrespunkte und Zwischenpunkte der Strecken.
    const kurveIn = k => o.reihen.some(s => s.werte.some((v, i) => {
      const w = s.werte[Math.min(i + 1, s.werte.length - 1)];
      return [0, 0.25, 0.5, 0.75].some(f => {
        const x = X(s.von + i + f), y = Y(v + (w - v) * f);
        return x > k[0] - 12 && x < k[1] + 12 && y > k[2] - 12 && y < k[3] + 12;
      });
    }));
    const frei = k => !belegt.some(b => trifft(k, b));

    // Hilfslinien. Die Beschriftung kommt erst nach den Kurven aufs Blatt, mit Rand in Blattfarbe.
    for (const a of o.achse || []) {
      body += `<path class="${a.wert === ymin ? 'grund' : 'netz'}" d="M${l} ${r(Y(a.wert))}H${W - rechts}"/>`;
    }
    // Die Beschriftung der Grundlinie steht immer: Sie zeigt, wo die Achse beginnt.
    for (const a of (o.achse || []).filter(a => a.wert === ymin && a.text !== '' && a.text != null)) {
      const k = kasten(l, grund - 12, breite(a.text, 'achse', fs.achse), fs.achse, 'start');
      belegt.push(k);
      oben += text(l, grund - 12, a.text, 'achse y', fs.achse);
    }

    // Zeitachse
    const rand = j => j === von || j === bis;
    const platz = j => {
      const b = breite(j, 'achse', fs.achse), x = X(j);
      return j === von ? [x, x + b] : j === bis ? [x - b, x] : [x - b / 2, x + b / 2];
    };
    const jahre = (o.jahre || []).filter(rand).map(platz);
    for (const j of o.jahre || []) {
      const p = platz(j);
      if (!rand(j)) {
        if (jahre.some(a => p[0] - 16 < a[1] && p[1] + 16 > a[0])) continue;   // passt nicht: entfällt, wird nicht kleiner
        jahre.push(p);
      }
      body += `<path class="grund" d="M${r(X(j))} ${grund}v10"/>`;
      const anker = j === von ? 'start' : j === bis ? 'end' : 'middle';
      body += text(X(j), grund + 14 + fs.achse * 0.8, j, 'achse', fs.achse, `text-anchor="${anker}"`);
    }

    // Kurven
    for (const s of o.reihen) {
      const punkte = s.werte.map((v, i) => `${r(X(s.von + i))} ${r(Y(v))}`);
      if (s.flaeche) {
        body += `<path class="flaeche" d="M${punkte.join('L')}L${r(X(s.von + s.werte.length - 1))} ${r(Y(ymin))}L${r(X(s.von))} ${r(Y(ymin))}Z"/>`;
      }
      body += `<path class="${s.akzent ? 'kurve akz' : 'kurve'}" d="M${punkte.join('L')}"/>`;
      if (s.name && s.nameBei) {
        const j = s.nameBei.jahr, b = breite(s.name, 'marke', fs.marke);
        const x = Math.min(W - b / 2, Math.max(b / 2, X(j)));
        const y = Y(s.werte[j - s.von]) + (s.nameBei.dy || -22);
        belegt.push(kasten(x, y, b, fs.marke, 'middle'));
        oben += text(x, y, s.name, 'reihe' + (s.akzent ? ' akz' : ''), fs.marke, 'text-anchor="middle"');
      }
    }

    // Marken: Punkt auf der Kurve, Text darüber oder darunter
    let punkteSvg = '';
    for (const m of o.marken || []) {
      const s = o.reihen[m.reihe || 0];
      const x = X(m.jahr), y = Y(s.werte[m.jahr - s.von]);
      punkteSvg += `<circle class="punkt${s.akzent ? ' akz' : ''}" cx="${r(x)}" cy="${r(y)}" r="9"/>`;
      if (!m.text) continue;
      const art = m.gross ? 'wert' : 'marke', gr = fs[art];
      const cls = m.gross ? 'wert' + (m.akzent ? ' akz' : '') : 'marke';
      const b = Math.max(breite(m.text, art, gr), m.zeile2 ? breite(m.zeile2, 'achse', fs.achse) : 0);
      const z2 = m.zeile2 ? fs.achse * 1.15 : 0;
      // Anker: Vorgabe aus dem Post, sonst mittig; in jedem Fall bleibt der Text im Feld
      let anker = m.anker || 'middle';
      if (!m.anker && (x - b / 2 < 0 || x + b / 2 > W)) anker = x < W / 2 ? 'start' : 'end';
      let tx = anker === 'start' ? x - 6 : anker === 'end' ? x + 6 : x;
      tx = anker === 'start' ? Math.max(0, Math.min(tx, W - b)) : anker === 'end' ? Math.min(W, Math.max(tx, b)) : Math.min(W - b / 2, Math.max(b / 2, tx));
      // Der Text steht über (oder unter) dem Punkt und dabei über (unter) allem, was die Kurve in seiner Breite
      // erreicht; sonst läge er bei flachen Kurven auf der Linie.
      const [x0, x1] = kasten(tx, 0, b, gr, anker);
      const hoehen = s.werte.map((v, i) => [X(s.von + i), Y(v)]).filter(p => p[0] >= x0 - 14 && p[0] <= x1 + 14).map(p => p[1]);
      const lage = seite => {
        const y1 = seite === 'unten' ? Math.max(y, ...hoehen) + 24 + gr * 0.74 : Math.min(y, ...hoehen) - 24 - z2;
        const k = kasten(tx, y1, b, gr, anker);
        k[3] += z2;
        return { y1, k, passt: k[2] >= 0 && k[3] <= grund - 4 && frei(k) };
      };
      const wunsch = m.seite === 'unten' ? 'unten' : 'oben';
      let p = lage(wunsch);
      if (!p.passt) {
        const anders = lage(wunsch === 'unten' ? 'oben' : 'unten');
        // Kein freier Platz auf beiden Seiten: Ein großer Wert (Titelblatt) bleibt stehen, eine gewöhnliche Marke entfällt.
        if (anders.passt) p = anders;
        else if (!(m.gross && p.k[2] >= 0 && p.k[3] <= grund - 4)) { entfallen.push(m.text); continue; }
      }
      belegt.push(p.k);
      punkteSvg += text(tx, p.y1, m.text, cls, gr, `text-anchor="${anker}"`);
      if (m.zeile2) punkteSvg += text(tx, p.y1 + z2, m.zeile2, 'marke leise', fs.achse, `text-anchor="${anker}"`);
    }

    // Übrige Achsenbeschriftung: links unter ihrer Linie; läge sie dort auf der Kurve oder auf einem Text,
    // steht sie rechts; ist auch dort kein Platz, entfällt sie (die Linie bleibt).
    for (const a of (o.achse || []).filter(a => a.wert !== ymin && a.text !== '' && a.text != null)) {
      const b = breite(a.text, 'achse', fs.achse), y = Y(a.wert) + fs.achse + 2;
      if (y > grund - 4) continue;
      const li = kasten(l, y, b, fs.achse, 'start'), re = kasten(W - rechts, y, b, fs.achse, 'end');
      const nachRechts = (kurveIn(li) || !frei(li)) && !kurveIn(re) && frei(re);
      if (!nachRechts && !frei(li)) continue;
      belegt.push(nachRechts ? re : li);
      oben += nachRechts ? text(W - rechts, y, a.text, 'achse y', fs.achse, 'text-anchor="end"') : text(l, y, a.text, 'achse y', fs.achse);
    }
    return svg(W, H, body + oben + punkteSvg, entfallen.length ? `data-entfallen="${entfallen.join(' | ').replace(/"/g, '')}"` : '');
  }

  // Säulen nebeneinander. o.saeulen: [{ wert, anzeige, name, akzent }]
  // Höchstens so viele Säulen, dass anzeige und name (30 px) unter und über der Säule Platz haben:
  // bei 4 Säulen etwa 11 Zeichen je name, bei 6 Säulen etwa 7.
  function saeulen(o) {
    const W = o.breite || 900, H = o.hoehe || 640;
    const fs = { ...SCHRIFT, wert: 52, ...(o.schrift || {}) };
    const unten = fs.achse + 26, oben = fs.wert + 24;
    const n = o.saeulen.length, luecke = 34;
    const b = (W - (n - 1) * luecke) / n;
    const max = Math.max(...o.saeulen.map(s => s.wert)) || 1;
    let body = `<path class="grund" d="M0 ${H - unten}H${W}"/>`;
    o.saeulen.forEach((s, i) => {
      const x = i * (b + luecke), h = (s.wert / max) * (H - oben - unten);
      body += `<rect class="${s.akzent ? 'saeule akz' : 'saeule'}" x="${r(x)}" y="${r(H - unten - h)}" width="${r(b)}" height="${r(h)}"/>`;
      body += text(x + b / 2, H - unten - h - 16, s.anzeige, 'wert' + (s.akzent ? ' akz' : ''), fs.wert, 'text-anchor="middle"');
      body += text(x + b / 2, H - unten + 14 + fs.achse * 0.8, s.name, 'achse', fs.achse, 'text-anchor="middle"');
    });
    return svg(W, H, body);
  }

  // Marke: drei steigende Säulen in Schwarz, Rot, Gold auf einer Grundlinie
  function marke() {
    return '<svg class="marke" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">' +
      '<rect class="m1" x="13.5" y="57.5" width="19" height="27"/><rect class="m2" x="40" y="38" width="20" height="48"/>' +
      '<rect class="m3" x="68" y="14" width="20" height="72"/><path class="mb" d="M6 88.5H94"/></svg>';
  }

  window.Diagramm = { linie, saeulen, marke, geo };
})();
