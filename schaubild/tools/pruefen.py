"""Prüft einen Post gegen die Regeln aus AUTOMATIK.md. Ein Post mit Fehlern gilt nicht als fertig.

Aufruf:  python tools/pruefen.py 015-beispiel          ein Post (mehrere möglich)
         python tools/pruefen.py --vorrat              alle Posts aus plan.json ab morgen, die noch nicht erschienen sind
         python tools/pruefen.py --alt 006-pkw         ältere Posts ohne die neuen Felder: nur Bild und Schrift, nicht das Format
         python tools/pruefen.py --ohne-reel <post>    nur die Blätter

Geprüft wird in zwei Teilen:
  Format  Pflichtfelder und Längen: Titelblatt mit Thema, Aussage, amtlicher Zahl und großem Anfangs- und Endwert,
          die Felder des Reels, Hinweis und Beschriftung bei einer Achse, die nicht bei null beginnt.
  Bild    Die Blätter und fünf Bilder des Reels werden in Chrome aufgebaut und vermessen: kleinste Schrift
          (30 px im Blatt, 40 px im Reel), nichts läuft aus dem Blatt, über die Leiste oder in die Bedienbereiche
          von Instagram, die Kernzahl steht in einer Zeile, keine Beschriftung im Diagramm liegt auf einer anderen.

Das Skript ändert nichts und ruft keine Schnittstelle auf. Endet es mit "in Ordnung", ist der Rückgabewert 0, sonst 1.
"""
import argparse
import datetime as dt
import json
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from render import CONFIG, ROOT, finde_chrome, starte_server  # noqa: E402
from reel import starte_chrome  # noqa: E402

BLATT = (1080, 1350)
REEL = (1080, 1920)
SCHRIFT_BLATT = 30      # px, Mindestschrift im Blatt
SCHRIFT_REEL = 40       # px, Mindestschrift im Reel
RAND = 60               # px, Rand links und rechts
REEL_OBEN, REEL_UNTEN, REEL_RECHTS = 160, 1536, 920   # frei für Instagram: oben, die unteren 20 %, rechts neben Diagramm und Bühne
REEL_ZEITEN = (0.0, 3.0, 6.0, 10.5)
DIAGRAMM_MIN = 300      # px, kleinste Höhe eines Diagrammfelds
SCHRUMPFEN = 0.85       # Texte des Reels dürfen höchstens um 15 % kleiner werden, damit sie passen
FRAGE_ENDE = 'Welche Zahl sollen wir als Nächstes zeichnen?'
FESTE_HASHTAGS = ('deutschland', 'statistik', 'datenvisualisierung', 'infografik', 'zahlen', 'wissen')
OUTRO = {'typ': 'outro', 'headline': 'Deutschland in Grafiken', 'text': ['Eine Zahl, ein Schaubild, eine Quelle. Jeden Tag.']}

# Läuft in der Seite: misst alle Texte und Blöcke des Blatts.
MESSEN = r"""
(() => {
  const sheet = document.getElementById('sheet');
  const rund = v => Math.round(v * 10) / 10;
  const deckkraft = e => { let a = 1; for (let x = e; x && x !== document.body; x = x.parentElement) a *= parseFloat(getComputedStyle(x).opacity); return rund(a); };
  const rolle = e => { const t = []; for (let x = e; x && x !== sheet; x = x.parentElement) {
    const c = (x.getAttribute('class') || '').trim().split(/\s+/).filter(Boolean).join('.'); t.unshift(x.tagName.toLowerCase() + (c ? '.' + c : '')); } return t.join(' > '); };
  const texte = [], gesehen = new Set();
  const lauf = document.createTreeWalker(sheet, NodeFilter.SHOW_TEXT);
  for (let n; (n = lauf.nextNode());) {
    if (!n.textContent.trim()) continue;
    const e = n.parentElement, svg = !!e.ownerSVGElement;
    let px = parseFloat(getComputedStyle(e).fontSize), box;
    if (svg) {
      if (gesehen.has(e)) continue;
      gesehen.add(e);
      const m = e.getScreenCTM(), r = e.getBoundingClientRect();
      px *= m.a;
      const p = e.ownerSVGElement.createSVGPoint(); p.x = 0; p.y = +e.getAttribute('y');
      const g = p.matrixTransform(m).y;                       // Grundlinie
      box = [r.left, g - 0.76 * px, r.right, g + 0.16 * px];
    } else {
      const bereich = document.createRange(); bereich.selectNodeContents(n);
      const rs = [...bereich.getClientRects()].filter(r => r.width > 0);
      if (!rs.length) continue;
      const unten = Math.max(...rs.map(r => r.bottom)), oben = Math.min(...rs.map(r => r.top));
      box = [Math.min(...rs.map(r => r.left)), oben + (rs[0].height - 0.95 * px), Math.max(...rs.map(r => r.right)), unten - 0.05 * px];
    }
    texte.push({ text: n.textContent.trim().slice(0, 44), rolle: rolle(e), px: rund(px), box: box.map(rund), svg, deckkraft: deckkraft(e) });
  }
  const bloecke = [...sheet.querySelectorAll('div, h1, h2, p, span')].map(e => {
    const r = e.getBoundingClientRect(), cs = getComputedStyle(e);
    return { rolle: rolle(e), box: [r.left, r.top, r.right, r.bottom].map(rund), sw: e.scrollWidth, cw: e.clientWidth,
      zeilen: Math.round(e.offsetHeight / (parseFloat(cs.lineHeight) || e.offsetHeight || 1)), deckkraft: deckkraft(e),
      geschrumpft: e.dataset.geschrumpft || '', umbruch: cs.whiteSpace };
  });
  const figuren = [...sheet.querySelectorAll('svg.fig')].map(s => {
    const r = s.getBoundingClientRect();
    return { box: [r.left, r.top, r.right, r.bottom].map(rund), entfallen: s.dataset.entfallen || '', fern: s.dataset.fern || '' };
  });
  return JSON.stringify({ texte, bloecke, figuren });
})()
"""


def lies(pfad):
    return json.loads(Path(pfad).read_text(encoding='utf-8'))


def klar(text):
    """Text ohne Auszeichnung, so lang wie auf dem Blatt."""
    return re.sub(r'<[^>]+>', '', str(text or ''))


# ---------------------------------------------------------------- Format

def pruefe_format(name, post):
    f = []

    def laenge(wo, text, hoechstens, mindestens=1):
        n = len(klar(text))
        if n < mindestens:
            f.append(f'{wo} fehlt.')
        elif n > hoechstens:
            f.append(f'{wo} hat {n} Zeichen, erlaubt sind {hoechstens}: „{klar(text)}“')

    if not re.fullmatch(r'\d{3}-[a-z0-9-]+', name) or post.get('nr') != name[:3]:
        f.append('Dateiname und Feld nr passen nicht zusammen (<nr>-<kurzname>, Kurzname aus a–z, 0–9, Bindestrich).')
    laenge('titel', post.get('titel'), 26)
    slides = post.get('slides') or []
    typen = [s.get('typ') for s in slides]
    if not 5 <= len(slides) <= 6 or typen[:1] != ['cover'] or typen[-1:] != ['outro']:
        f.append(f'slides: 5 oder 6 Blätter, zuerst cover, zuletzt outro (ist: {", ".join(map(str, typen))}).')
        return f
    if slides[-1] != OUTRO:
        f.append('Das Schlussblatt weicht von der festen Vorgabe ab.')

    # Titelblatt
    t = slides[0]
    laenge('Titelblatt kicker (Thema)', t.get('kicker'), 30)
    if re.match(r'\s*Schaubild Nr', t.get('kicker') or ''):
        f.append('Titelblatt kicker nennt das Thema, nicht „Schaubild Nr. …“.')
    laenge('Titelblatt zahl (Kernzahl)', t.get('zahl'), 9)
    laenge('Titelblatt headline', t.get('headline'), 40, 8)
    if len(klar(t.get('headline')).split()) > 6:
        f.append('Titelblatt headline hat mehr als 6 Wörter.')
    absatz = t.get('text') or []
    if len(absatz) != 1:
        f.append('Titelblatt text: genau ein Absatz.')
    else:
        laenge('Titelblatt text', absatz[0], 110, 20)
        if not re.search(r'\d', klar(absatz[0])) or '<em>' not in absatz[0]:
            f.append('Titelblatt text nennt die amtliche Zahl mit Jahr (in <em>) und die Grundlage der Aussage.')
    fig = t.get('figur') or {}
    if fig.get('fn') != 'linie' or not fig.get('reihen'):
        f.append('Titelblatt braucht figur mit fn linie.')
    else:
        r0 = fig['reihen'][0]
        von, bis = r0['von'], r0['von'] + len(r0['werte']) - 1
        gross = {m.get('jahr') for m in fig.get('marken') or [] if m.get('gross') and klar(m.get('text'))}
        if not {von, bis} <= gross:
            f.append(f'Titelblatt: Anfangs- und Endwert fehlen als Marken mit "gross": true und text (Jahre {von} und {bis}).')

    # Zweites Blatt trägt das Diagramm des Reels
    if typen[1] != 'diagramm' or (slides[1].get('figur') or {}).get('fn') != 'linie':
        f.append('Blatt 2 muss ein diagramm mit fn linie sein (das Reel zeichnet es).')

    for nr, s in enumerate(slides, 1):
        wo = f'Blatt {nr}'
        if s['typ'] in ('diagramm', 'balken', 'punkte'):
            laenge(f'{wo} kicker', s.get('kicker'), 44)
            laenge(f'{wo} headline', s.get('headline'), 32)
        if s['typ'] == 'diagramm':
            if len(s.get('text') or []) != 1:
                f.append(f'{wo} text: genau ein Absatz.')
            else:
                laenge(f'{wo} text', s['text'][0], 160)
            laenge(f'{wo} fuss', s.get('fuss'), 100)
        elif s.get('fuss'):
            laenge(f'{wo} fuss', s.get('fuss'), 100)
        for absatz in s.get('text') or []:
            if absatz.count('<em>') > 1:
                f.append(f'{wo}: mehr als eine Hervorhebung mit <em>.')
        if s['typ'] == 'punkte':
            if len(s.get('punkte') or []) != 3:
                f.append(f'{wo}: genau drei Kennzahlen.')
            for p in s.get('punkte') or []:
                laenge(f'{wo} wert', p.get('wert'), 8)
                laenge(f'{wo} name', p.get('name'), 26)
                laenge(f'{wo} zusatz', p.get('zusatz'), 60, 0)
        figur = s.get('figur') or {}
        if figur.get('fn') == 'linie':
            for m in figur.get('marken') or []:
                r = figur['reihen'][m.get('reihe', 0)]
                if not r['von'] <= m.get('jahr', -1) < r['von'] + len(r['werte']):
                    f.append(f'{wo}: Marke im Jahr {m.get("jahr")} liegt außerhalb der Reihe.')
            f += [f'{wo}: {x}' for x in pruefe_achse(figur, s.get('fuss'))]

    # Reel
    reel = post.get('reel') or {}
    frage = reel.get('frage') or ''
    laenge('reel.frage', frage, 48, 10)
    if not frage.endswith('?'):
        f.append('reel.frage endet mit einem Fragezeichen.')
    laenge('reel.unter (Zeile unter der Kernzahl)', reel.get('unter'), 16, 3)
    lauf = reel.get('lauf') or {}
    laenge('reel.lauf.was (was der laufende Wert zählt)', lauf.get('was'), 30, 3)
    if lauf.get('teiler') and 'stellen' not in lauf:
        f.append('reel.lauf: Zu teiler gehört stellen (Nachkommastellen der Anzeige).')
    if reel.get('stimmung', 'neutral') not in ('neutral', 'ernst'):
        f.append('reel.stimmung: nur "ernst" oder weglassen.')
    if 'zahl' in reel:
        laenge('reel.zahl', reel.get('zahl'), 9)
    if typen[1] == 'diagramm' and (slides[1].get('figur') or {}).get('fn') == 'linie':
        figur = {**slides[1]['figur'], **(reel.get('figur') or {})}
        if figur.get('ymin') and not any(a.get('wert') == figur['ymin'] and klar(a.get('text')) for a in figur.get('achse') or []):
            f.append('Reel: Die Achse beginnt nicht bei null, also braucht die Grundlinie eine Beschriftung (achse mit wert = ymin und text).')

    # Bildunterschrift, Hashtags, Quellen
    caption = post.get('caption') or []
    if not caption or caption[-1] != FRAGE_ENDE:
        f.append(f'caption endet mit genau der Frage „{FRAGE_ENDE}“')
    n = sum(len(c) for c in caption)
    if not 200 <= n <= 320:
        f.append(f'caption hat zusammen {n} Zeichen, erlaubt sind 200 bis 320.')
    tags = post.get('hashtags') or []
    if len(tags) != 10 or any(h not in tags for h in FESTE_HASHTAGS) or any(h != h.lower() or '#' in h for h in tags):
        f.append('hashtags: genau 10, klein, ohne #, darunter die sechs festen.')
    quellen = post.get('quellen') or []
    if len(quellen) < 2 or not quellen[-1].startswith('Abruf '):
        f.append('quellen: mindestens eine Quelle und zuletzt „Abruf MM/JJJJ“.')
    return f


def pruefe_achse(figur, fuss):
    """Beginnt die Achse nicht bei null, braucht das Blatt den Hinweis und die Grundlinie ihre Beschriftung."""
    if not figur.get('ymin'):
        return []
    f = []
    if 'achse' not in klar(fuss).lower():
        f.append('Die Achse beginnt nicht bei null (ymin). Dann steht im fuss dieses Blatts der Hinweis, z. B. „Die Achse beginnt bei 35 Millionen.“')
    if not any(a.get('wert') == figur['ymin'] and klar(a.get('text')) for a in figur.get('achse') or []):
        f.append('Die Achse beginnt nicht bei null: Die Grundlinie braucht eine Beschriftung (achse mit wert = ymin und text).')
    return f


# ---------------------------------------------------------------- Bild

def schneidet(a, b, luft=0.0):
    return a[0] + luft < b[2] and a[2] - luft > b[0] and a[1] + luft < b[3] and a[3] - luft > b[1]


def block(messung, ende):
    """Erster Block, dessen Rolle mit ende aufhört."""
    return next((b for b in messung['bloecke'] if b['rolle'].endswith(ende)), None)


def pruefe_blatt(messung, typ, alt):
    f = []
    sichtbar = [t for t in messung['texte'] if t['deckkraft'] > 0.05]
    if not sichtbar:
        return ['Das Blatt ist leer (Fehler im Post?).'], None
    kleinste = min(t['px'] for t in sichtbar)
    for t in sichtbar:
        if t['px'] < SCHRIFT_BLATT - 0.05:
            f.append(f'Schrift {t["px"]:g} px, Mindestschrift ist {SCHRIFT_BLATT} px: „{t["text"]}“')
    inhalt, leiste = block(messung, 'div.inhalt.' + typ), block(messung, 'div.leiste')
    for t in sichtbar:
        b, in_leiste = t['box'], t['rolle'].startswith('div.leiste')
        grenze = leiste['box'] if in_leiste else inhalt['box']
        if b[0] < RAND - 8 or b[2] > BLATT[0] - RAND + 2:      # die Kernzahl steht 6 px weiter links
            f.append(f'Text läuft seitlich aus dem Blatt: „{t["text"]}“')
        elif b[1] < grenze[1] - 6 or b[3] > grenze[3] + 3:
            f.append(f'Text läuft {"aus der Leiste" if in_leiste else "aus dem Inhalt oder über die Leiste"}: „{t["text"]}“')
    for b in messung['bloecke']:
        if b['sw'] > b['cw'] + 1 and (b['umbruch'] == 'nowrap' or b['rolle'].endswith('div.thema')):
            f.append(f'Zeile ist zu lang und wird abgeschnitten: {b["rolle"].split(" > ")[-1]}')
    for fig in messung['figuren']:
        if fig['box'][3] - fig['box'][1] < DIAGRAMM_MIN:
            f.append(f'Das Diagramm ist nur {fig["box"][3] - fig["box"][1]:.0f} px hoch (mindestens {DIAGRAMM_MIN}): Text kürzen.')
        if fig['entfallen']:
            f.append(f'Marke ohne Platz, ihr Text entfällt: {fig["entfallen"]}. Seite, Anker oder Zahl der Marken ändern.')
        if fig['fern'] and not alt:
            f.append(f'Marke steht weit von ihrem Punkt: {fig["fern"]}. Seite oder Anker ändern oder die Marke streichen.')
        f += [f'Im Diagramm: {x}' for x in pruefe_svg_texte([t for t in sichtbar if t['svg']], fig['box'])]
    if typ == 'cover':
        zahl, h1 = block(messung, 'div.zahl'), block(messung, 'h1')
        if zahl and (zahl['zeilen'] > 1 or zahl['sw'] > zahl['cw'] + 1):
            f.append('Die Kernzahl passt nicht in eine Zeile.')
        if h1 and h1['zeilen'] > 2:
            f.append(f'Die Überschrift des Titelblatts hat {h1["zeilen"]} Zeilen, erlaubt sind 2.')
    elif not alt:
        h2 = block(messung, 'h2')
        if h2 and h2['zeilen'] > 2:
            f.append(f'Die Überschrift hat {h2["zeilen"]} Zeilen, erlaubt sind 2.')
    if not alt:
        for b in messung['bloecke']:
            if b['rolle'].endswith(('div.fuss', 'div.zusatz')) and b['zeilen'] > 2:
                f.append(f'{"Die Fußzeile" if b["rolle"].endswith("fuss") else "Ein Zusatz"} hat {b["zeilen"]} Zeilen, erlaubt sind 2: kürzen.')
    return f, kleinste


def pruefe_svg_texte(texte, feld):
    f = []
    for t in texte:
        b = t['box']
        if b[0] < feld[0] - 3 or b[2] > feld[2] + 3 or b[1] < feld[1] - 3 or b[3] > feld[3] + 3:
            f.append(f'Beschriftung ragt aus dem Feld: „{t["text"]}“')
    for i, a in enumerate(texte):
        for b in texte[i + 1:]:
            if schneidet(a['box'], b['box'], 2):
                f.append(f'Beschriftungen liegen aufeinander: „{a["text"]}“ und „{b["text"]}“')
    return f


def pruefe_reel(messung, wann, alt):
    f, immer = [], []      # immer: gilt für das ganze Reel, nicht nur für dieses Bild
    sichtbar = [t for t in messung['texte'] if t['deckkraft'] > 0.05]
    if not sichtbar:
        return ['Das Bild ist leer (Fehler im Post?).'], None
    kleinste = min(t['px'] for t in sichtbar)
    for t in sichtbar:
        if t['px'] < SCHRIFT_REEL - 0.05:
            f.append(f'Schrift {t["px"]:g} px, Mindestschrift im Reel ist {SCHRIFT_REEL} px: „{t["text"]}“')
    figur = block(messung, 'div.figur')
    for t in sichtbar:
        b, marke = t['box'], t['rolle'].startswith('div.reel-marke')
        if b[0] < RAND - 8 or b[2] > REEL[0] - RAND + 2:
            f.append(f'Text läuft seitlich aus dem Bild: „{t["text"]}“')
        if marke:
            continue
        if b[1] < REEL_OBEN - 4 or b[3] > REEL_UNTEN + 3:
            f.append(f'Text liegt im Bedienbereich von Instagram (oben {REEL_OBEN} px, unten ab {REEL_UNTEN} px): „{t["text"]}“')
        im_kopf = 'div.kopf' in t['rolle'] or t['rolle'].endswith('div.kicker')
        if im_kopf and b[3] > figur['box'][1] + 3:
            f.append(f'Kopf läuft in das Diagramm: „{t["text"]}“')
        if not im_kopf and b[2] > REEL_RECHTS + 3:
            f.append(f'Text liegt im rechten Bedienbereich von Instagram (ab {REEL_RECHTS} px): „{t["text"]}“')
        if 'div.buehne' in t['rolle'] and b[1] < figur['box'][3] - 6:
            f.append(f'Bühne läuft in das Diagramm: „{t["text"]}“')
    for b in messung['bloecke']:
        if b['deckkraft'] > 0.05 and b['sw'] > b['cw'] + 1 and b['umbruch'] == 'nowrap':
            f.append(f'Zeile ist zu lang und wird abgeschnitten: {b["rolle"].split(" > ")[-1]}')
        if b['geschrumpft'] and not alt:
            ist, soll = (float(x) for x in b['geschrumpft'].split('/'))
            if ist < SCHRUMPFEN * soll:      # ein paar Pixel weniger sind in Ordnung
                immer.append(f'{b["rolle"].split(" > ")[-1]} passt nicht und wurde von {soll:g} auf {ist:g} px verkleinert: Text kürzen.')
    frage = block(messung, 'div.frage')
    if frage and frage['deckkraft'] > 0.05 and frage['zeilen'] > 3:
        f.append(f'Die Frage hat {frage["zeilen"]} Zeilen, erlaubt sind 3.')
    for fig in messung['figuren']:
        if fig['entfallen']:
            immer.append(f'Marke ohne Platz, ihr Text entfällt: {fig["entfallen"]}.')
        if fig['fern'] and not alt:
            immer.append(f'Marke steht weit von ihrem Punkt: {fig["fern"]}. Unter reel.figur.marken andere Marken vorgeben.')
        f += [f'Im Diagramm: {x}' for x in pruefe_svg_texte([t for t in sichtbar if t['svg']], fig['box'])]
    return [f'Reel: {x}' for x in immer] + [f'{wann}: {x}' for x in f], kleinste


class Seite:
    def __init__(self):
        self.server = starte_server()
        self.server.handle_error = lambda *a: None     # Chrome bricht Verbindungen beim Beenden ab; das ist kein Fehler
        self.basis = f'http://127.0.0.1:{self.server.server_address[1]}/render'
        self.profil = tempfile.mkdtemp(prefix='schaubild-pruefen-')
        self.prozess, self.seite = starte_chrome(finde_chrome(), self.profil)

    def lade(self, url, groesse):
        self.seite.befehl('Emulation.setDeviceMetricsOverride', width=groesse[0], height=groesse[1], deviceScaleFactor=1, mobile=False)
        self.seite.befehl('Page.navigate', url=url)
        for _ in range(100):
            if self.seite.werte('window.bereit === true'):
                return True
            time.sleep(0.1)
        return False

    def miss(self):
        return json.loads(self.seite.werte(MESSEN))

    def schliesse(self):
        self.prozess.kill()
        self.server.shutdown()
        time.sleep(0.3)
        shutil.rmtree(self.profil, ignore_errors=True)


def pruefe_dateien(name, post):
    """Liegen die gerenderten Bilder vor?"""
    ordner = ROOT / 'out' / name
    namen = [f'{nr:02d}.jpg' for nr in range(1, len(post.get('slides') or []) + 1)] + ['uebersicht.jpg', 'reel-vorschau.jpg', 'story.jpg']
    fehlt = [n for n in namen if not (ordner / n).exists()]
    return [f'Bilder fehlen in out/{name}: {", ".join(fehlt)}. Erst tools/render.py und tools/reel.py ausführen.'] if fehlt else []


def pruefe_bild(seite, name, post, alt, ohne_reel):
    f, werte = [], {}
    konto = CONFIG['konto']
    blatt_min = []
    for nr, s in enumerate(post['slides'], 1):
        if not seite.lade(f'{seite.basis}/slide.html?post={name}&konto={konto}&slide={nr}', BLATT):
            f.append(f'Blatt {nr}: Die Seite wurde nicht fertig (Fehler im Post, z. B. eine Marke außerhalb der Reihe).')
            continue
        fehler, kleinste = pruefe_blatt(seite.miss(), s['typ'], alt)
        f += [f'Blatt {nr}: {x}' for x in fehler]
        if kleinste:
            blatt_min.append(kleinste)
    werte['blatt'] = min(blatt_min) if blatt_min else None
    if ohne_reel:
        return f, werte
    if not seite.lade(f'{seite.basis}/reel.html?post={name}&konto={konto}', REEL):
        return f + ['Reel: Die Seite wurde nicht fertig (Fehler im Post?).'], werte
    reel_min = []
    for t in REEL_ZEITEN:
        seite.seite.werte(f'window.zeige({t})')
        fehler, kleinste = pruefe_reel(seite.miss(), f'Reel bei {t:g} s', alt)
        f += fehler
        reel_min.append(kleinste or 0)
    seite.seite.werte('document.getElementById("sheet").classList.add("story"); window.zeige(window.dauer)')
    fehler, kleinste = pruefe_reel(seite.miss(), 'Story', alt)
    f += fehler
    reel_min.append(kleinste or 0)
    seite.seite.werte('document.getElementById("sheet").classList.remove("story")')
    # Jedes Bild des Videos einmal aufbauen: Ein Fehler in der Zeitsteuerung fiele sonst erst auf GitHub auf.
    lauf = seite.seite.werte('(() => { try { for (let i = 0; i <= Math.round(window.dauer * 30); i++) window.zeige(i / 30); return "ok"; } catch (e) { return String(e); } })()')
    if lauf != 'ok':
        f.append(f'Reel: Fehler beim Durchlauf aller Bilder: {lauf}')
    werte['reel'] = min(reel_min)
    return list(dict.fromkeys(f)), werte


def vorrat():
    """Posts aus plan.json ab morgen, die noch nicht erschienen sind."""
    import publish
    heute = publish.berlin_jetzt().date().isoformat()
    erschienen = {e['post'] for e in lies(ROOT / 'veroeffentlicht.json')}
    return [e['post'] for e in lies(ROOT / 'plan.json')['posts'] if e['datum'] > heute and e['post'] not in erschienen]


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('posts', nargs='*')
    parser.add_argument('--vorrat', action='store_true', help='alle noch nicht erschienenen Posts aus plan.json ab morgen')
    parser.add_argument('--alt', action='store_true', help='ältere Posts ohne die neuen Felder: nur Bild und Schrift prüfen')
    parser.add_argument('--ohne-reel', action='store_true', help='nur die Blätter prüfen')
    args = parser.parse_args()
    posts = list(args.posts) + (vorrat() if args.vorrat else [])
    if not posts:
        sys.exit('Kein Post angegeben. Aufruf: python tools/pruefen.py <post>  oder  --vorrat')

    seite = Seite()
    schlecht = 0
    try:
        for name in posts:
            pfad = ROOT / 'posts' / f'{name}.json'
            if not pfad.exists():
                print(f'{name}: posts/{name}.json fehlt.')
                schlecht += 1
                continue
            post = lies(pfad)
            fehler = [] if args.alt else [f'Format: {x}' for x in pruefe_format(name, post)] + pruefe_dateien(name, post)
            bild, werte = pruefe_bild(seite, name, post, args.alt, args.ohne_reel)
            fehler += bild
            schrift = f'kleinste Schrift im Blatt {werte.get("blatt"):g} px' if werte.get('blatt') else 'Blätter nicht messbar'
            if werte.get('reel'):
                schrift += f', im Reel {werte["reel"]:g} px'
            if fehler:
                schlecht += 1
                print(f'{name}: NICHT FERTIG, {len(fehler)} Fehler ({schrift})')
                for x in fehler:
                    print(f'  - {x}')
            else:
                print(f'{name}: in Ordnung ({schrift})')
    finally:
        seite.schliesse()
    if schlecht:
        sys.exit(1)


if __name__ == '__main__':
    main()
