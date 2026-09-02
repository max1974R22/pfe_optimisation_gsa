/* ==== Vue3D — visionneuse filaire du modèle GSA (canvas, aucune dépendance) ====
   Projection orthographique + caméra orbitale (Z vertical, convention GSA).
   API : Vue3D.attacher(canvas) puis Vue3D.charger(noeuds, elements) ;
   Vue3D.surligner([ids]) met en évidence des éléments (cible d'optimisation).
   (noeuds/elements = lignes de /api/resume).

   Vue3D.chargerSections(geometrie) / Vue3D.basculerSections(actif) : rendu
   SOLIDE (sections des barres réellement extrudées, cf. GsaAPI Model.Draw
   côté serveur — /api/vue-sections) plutôt que le simple trait d'axe. Ce
   rendu est BEAUCOUP plus lourd (des milliers de triangles) : pour ne jamais
   ralentir l'orbite filaire habituelle, il n'est dessiné que « au repos »
   (pas pendant un glisser/zoom actif, cf. enMouvement) — l'interaction reste
   sur le rendu filaire rapide et le solide se substitue une fois le geste
   terminé (cf. `programmerReglage`). */
"use strict";

const Vue3D = (() => {
  let canvas = null, ctx = null;
  let noeuds = [], elements = [], parId = new Map();
  let surlignes = new Set();          // ids d'éléments mis en évidence
  let centre = [0, 0, 0], rayon = 1;
  let bbox = null;                    // {x0,x1,y0,y1,z0,z1} du modèle

  /* rendu « sections » (solide, coûteux — cf. entête du module) */
  let sectionsData = null;            // {triangles:{positions,couleurs}, lignes:{...}}
  let sectionsActives = false;
  let enMouvement = false;            // vrai pendant un glisser/zoom : bascule sur le filaire rapide
  let minuterieReglage = null;

  /* caméra orbitale */
  let theta, phi, zoom, panX, panY;
  const reinitialiser = () => { theta = -1.05; phi = 0.42; zoom = 1; panX = 0; panY = 0; };
  reinitialiser();

  const couleurs = () => {
    const s = getComputedStyle(document.documentElement);
    const v = (nom, defaut) => s.getPropertyValue(nom).trim() || defaut;
    return {
      element: v("--v3d-element", "#0a5e73"),
      noeud: v("--v3d-noeud", "#0b1f33"),
      appui: v("--v3d-appui", "#6f8500"),
      texte: v("--v3d-texte", "#61828a"),
      accent: v("--accent", "#e6007e"),
    };
  };

  /* code des mouvements bloqués d'un nœud, convention GSA (translations
     x/y/z puis rotations xx/yy/zz autour de ces axes) — ex. 3 translations
     + rotation autour de x bloquées -> "xyzxx" */
  function codeAppui(n) {
    const codes = [];
    if (n.res_x) codes.push("x");
    if (n.res_y) codes.push("y");
    if (n.res_z) codes.push("z");
    if (n.res_xx) codes.push("xx");
    if (n.res_yy) codes.push("yy");
    if (n.res_zz) codes.push("zz");
    return codes;
  }

  /* ---- projection ------------------------------------------------------ */
  function base() {
    // repère caméra : "droite", "haut" et profondeur, Z monde vers le haut
    const ct = Math.cos(theta), st = Math.sin(theta);
    const cp = Math.cos(phi), sp = Math.sin(phi);
    return {
      droite: [ct, st, 0],
      haut: [-st * sp, ct * sp, cp],
      prof: [-st * cp, ct * cp, -sp],
    };
  }
  function projeter(p, b, echelle, l, h) {
    const d = [p[0] - centre[0], p[1] - centre[1], p[2] - centre[2]];
    const dot = (u, v) => u[0] * v[0] + u[1] * v[1] + u[2] * v[2];
    return [
      l / 2 + panX + dot(d, b.droite) * echelle,
      h / 2 + panY - dot(d, b.haut) * echelle,
      dot(d, b.prof),
    ];
  }

  /* ---- dessin ---------------------------------------------------------- */
  function dessiner() {
    if (!ctx) return;
    const dpr = window.devicePixelRatio || 1;
    const l = canvas.clientWidth, h = canvas.clientHeight;
    if (canvas.width !== l * dpr || canvas.height !== h * dpr) {
      canvas.width = l * dpr; canvas.height = h * dpr;
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, l, h);
    if (!noeuds.length) return;

    const c = couleurs();
    const b = base();
    const echelle = (Math.min(l, h) * 0.42 / rayon) * zoom;

    /* rendu solide (sections réelles) : seulement au repos, cf. entête du
       module — pendant un glisser/zoom on reste sur le filaire ci-dessous,
       bien moins coûteux à redessiner à chaque mouvement de souris */
    if (sectionsActives && sectionsData && !enMouvement) {
      dessinerSolide(b, echelle, l, h);
      dessinerTriedre(b, h, c);
      return;
    }

    const pts = new Map();
    noeuds.forEach((n) => pts.set(n.node, projeter([n.x, n.y, n.z], b, echelle, l, h)));

    /* sol : plan z = 0 esquissé (quad très clair + ombre portée de la
       structure, projection verticale des barres), dessiné en premier */
    if (bbox) {
      const mrg = Math.max(rayon * 0.18, 0.5);
      const coins = [
        [bbox.x0 - mrg, bbox.y0 - mrg, 0], [bbox.x1 + mrg, bbox.y0 - mrg, 0],
        [bbox.x1 + mrg, bbox.y1 + mrg, 0], [bbox.x0 - mrg, bbox.y1 + mrg, 0],
      ].map((p) => projeter(p, b, echelle, l, h));
      ctx.beginPath();
      coins.forEach((p, i) => i === 0 ? ctx.moveTo(p[0], p[1]) : ctx.lineTo(p[0], p[1]));
      ctx.closePath();
      ctx.fillStyle = "rgba(120, 130, 140, 0.07)";
      ctx.fill();
      ctx.strokeStyle = "rgba(120, 130, 140, 0.22)";
      ctx.lineWidth = 1;
      ctx.stroke();

      const sol = new Map();
      noeuds.forEach((n) => sol.set(n.node, projeter([n.x, n.y, 0], b, echelle, l, h)));
      ctx.lineCap = "round";
      ctx.lineWidth = 3;
      ctx.strokeStyle = "rgba(60, 70, 80, 0.10)";
      elements.forEach((e) => {
        const topo = (e.topologie || []).filter((id) => sol.has(id));
        if (topo.length < 2) return;
        ctx.beginPath();
        topo.forEach((id, i) => {
          const p = sol.get(id);
          i === 0 ? ctx.moveTo(p[0], p[1]) : ctx.lineTo(p[0], p[1]);
        });
        ctx.stroke();
      });
    }

    /* éléments (polyligne sur la topologie) ; les surlignés en dernier,
       plus épais et en magenta, pour rester lisibles par-dessus le reste */
    ctx.lineCap = "round";
    const tracer = (e) => {
      const topo = (e.topologie || []).filter((id) => pts.has(id));
      if (topo.length < 2) return;
      ctx.beginPath();
      topo.forEach((id, i) => {
        const p = pts.get(id);
        i === 0 ? ctx.moveTo(p[0], p[1]) : ctx.lineTo(p[0], p[1]);
      });
      ctx.stroke();
    };
    ctx.lineWidth = 2;
    ctx.strokeStyle = c.element;
    elements.forEach((e) => { if (!surlignes.has(e.element)) tracer(e); });
    if (surlignes.size) {
      ctx.lineWidth = 4.5;
      ctx.strokeStyle = c.accent;
      elements.forEach((e) => { if (surlignes.has(e.element)) tracer(e); });
    }

    /* nœuds : point ; appui rotule pure (3 translations, aucune rotation) :
       triangle plein comme d'habitude ; tout autre encastrement partiel ou
       mixte (une seule translation, translations + rotation(s)...) : petit
       point + code des mouvements bloqués (convention GSA x/y/z/xx/yy/zz),
       en vert, pour ne pas laisser croire à une rotule alors que ce n'en est
       pas une (cf. codeAppui) */
    noeuds.forEach((n) => {
      const p = pts.get(n.node);
      const codes = codeAppui(n);
      const rotule = n.res_x && n.res_y && n.res_z && !n.res_xx && !n.res_yy && !n.res_zz;
      if (rotule) {
        ctx.fillStyle = c.appui;
        ctx.beginPath();
        ctx.moveTo(p[0], p[1]);
        ctx.lineTo(p[0] - 6, p[1] + 10);
        ctx.lineTo(p[0] + 6, p[1] + 10);
        ctx.closePath();
        ctx.fill();
      } else if (codes.length) {
        ctx.fillStyle = c.appui;
        ctx.beginPath();
        ctx.arc(p[0], p[1], 2.5, 0, Math.PI * 2);
        ctx.fill();
        ctx.font = "9px Consolas, monospace";
        ctx.textAlign = "center";
        ctx.fillText(codes.join(""), p[0], p[1] + 13);
        ctx.textAlign = "start";
      } else if (noeuds.length <= 400) {
        ctx.fillStyle = c.noeud;
        ctx.beginPath();
        ctx.arc(p[0], p[1], noeuds.length > 100 ? 1.2 : 2.5, 0, Math.PI * 2);
        ctx.fill();
      }
    });

    /* numéros de barres, au milieu de chaque élément (modèles peu denses) */
    if (elements.length <= 120) {
      ctx.font = "11px Consolas, monospace";
      ctx.textAlign = "center";
      elements.forEach((e) => {
        const topo = (e.topologie || []).filter((id) => pts.has(id));
        if (topo.length < 2) return;
        const a = pts.get(topo[0]), z = pts.get(topo[topo.length - 1]);
        ctx.fillStyle = surlignes.has(e.element) ? c.accent : c.texte;
        ctx.fillText(String(e.element), (a[0] + z[0]) / 2, (a[1] + z[1]) / 2 - 5);
      });
      ctx.textAlign = "start";
    }

    dessinerTriedre(b, h, c);
  }

  /* trièdre X/Y/Z en bas à gauche — repère commun aux deux rendus (filaire
     et solide), factorisé pour ne pas le dupliquer */
  function dessinerTriedre(b, h, c) {
    const o = [34, h - 34], la = 22;
    [["X", [1, 0, 0]], ["Y", [0, 1, 0]], ["Z", [0, 0, 1]]].forEach(([nom, v]) => {
      const dot = (u, w) => u[0] * w[0] + u[1] * w[1] + u[2] * w[2];
      const x = o[0] + dot(v, b.droite) * la, y = o[1] - dot(v, b.haut) * la;
      ctx.strokeStyle = c.texte; ctx.lineWidth = 1.2;
      ctx.beginPath(); ctx.moveTo(o[0], o[1]); ctx.lineTo(x, y); ctx.stroke();
      ctx.fillStyle = c.texte; ctx.font = "10px Consolas, monospace";
      ctx.fillText(nom, x + 3, y);
    });
  }

  /* rendu SOLIDE (sections extrudées) : peint les triangles GSA en
     algorithme du peintre (tri par profondeur, du plus loin au plus proche),
     puis les arêtes par-dessus pour la netteté — cf. entête du module pour
     le compromis fluidité (uniquement « au repos »). */
  function dessinerSolide(b, echelle, l, h) {
    const { positions: posT, couleurs: colT } = sectionsData.triangles;
    const nTri = colT.length;
    const tris = new Array(nTri);
    for (let i = 0; i < nTri; i++) {
      const o = i * 9;
      const p0 = projeter([posT[o], posT[o + 1], posT[o + 2]], b, echelle, l, h);
      const p1 = projeter([posT[o + 3], posT[o + 4], posT[o + 5]], b, echelle, l, h);
      const p2 = projeter([posT[o + 6], posT[o + 7], posT[o + 8]], b, echelle, l, h);
      tris[i] = { z: (p0[2] + p1[2] + p2[2]) / 3, p0, p1, p2, couleur: colT[i] };
    }
    // profondeur croissante = plus loin de la caméra (cf. base()/projeter()) :
    // on peint du plus loin au plus proche pour que le proche masque le loin
    tris.sort((a, b2) => b2.z - a.z);
    tris.forEach((t) => {
      ctx.beginPath();
      ctx.moveTo(t.p0[0], t.p0[1]);
      ctx.lineTo(t.p1[0], t.p1[1]);
      ctx.lineTo(t.p2[0], t.p2[1]);
      ctx.closePath();
      ctx.fillStyle = t.couleur;
      ctx.fill();
    });

    const { positions: posL, couleurs: colL } = sectionsData.lignes;
    ctx.lineWidth = 1;
    for (let i = 0; i < colL.length; i++) {
      const o = i * 6;
      const p0 = projeter([posL[o], posL[o + 1], posL[o + 2]], b, echelle, l, h);
      const p1 = projeter([posL[o + 3], posL[o + 4], posL[o + 5]], b, echelle, l, h);
      ctx.strokeStyle = colL[i];
      ctx.beginPath();
      ctx.moveTo(p0[0], p0[1]);
      ctx.lineTo(p1[0], p1[1]);
      ctx.stroke();
    }
  }

  /* ---- interactions ---------------------------------------------------- */
  function attacherEvenements() {
    let bouton = -1, dernierX = 0, dernierY = 0;
    canvas.addEventListener("pointerdown", (e) => {
      bouton = e.shiftKey ? 2 : e.button;
      dernierX = e.clientX; dernierY = e.clientY;
      canvas.setPointerCapture(e.pointerId);
      demarrerMouvement();
    });
    canvas.addEventListener("pointermove", (e) => {
      if (bouton < 0) return;
      const dx = e.clientX - dernierX, dy = e.clientY - dernierY;
      dernierX = e.clientX; dernierY = e.clientY;
      if (bouton === 2) { panX += dx; panY += dy; }
      else {
        theta -= dx * 0.008;
        phi = Math.max(-1.5, Math.min(1.5, phi + dy * 0.008));
      }
      dessiner();
    });
    canvas.addEventListener("pointerup", () => { bouton = -1; programmerReglage(); });
    canvas.addEventListener("wheel", (e) => {
      e.preventDefault();
      zoom *= e.deltaY < 0 ? 1.12 : 1 / 1.12;
      zoom = Math.max(0.05, Math.min(80, zoom));
      demarrerMouvement();
      dessiner();
      programmerReglage();
    }, { passive: false });
    canvas.addEventListener("dblclick", () => { reinitialiser(); dessiner(); });
    canvas.addEventListener("contextmenu", (e) => e.preventDefault());
    new ResizeObserver(dessiner).observe(canvas);
  }

  /* bascule sur le filaire rapide pour la durée du geste (glisser/zoom) —
     cf. entête du module : le rendu solide ne redessine qu'« au repos » */
  function demarrerMouvement() {
    if (!sectionsActives) return;
    clearTimeout(minuterieReglage);
    enMouvement = true;
  }
  /* geste terminé : laisse un court délai (au cas où un autre geste
     s'enchaîne aussitôt) puis « règle » le rendu solide une seule fois */
  function programmerReglage() {
    if (!sectionsActives) return;
    clearTimeout(minuterieReglage);
    minuterieReglage = setTimeout(() => { enMouvement = false; dessiner(); }, 120);
  }

  /* ---- API ------------------------------------------------------------- */
  return {
    attacher(el) {
      canvas = el;
      ctx = canvas.getContext("2d");
      attacherEvenements();
      /* le canvas remplit desormais une demi-page souple (colonne de sortie),
         plus une hauteur fixe : sa taille change au redimensionnement de la
         fenetre ET au retour sur l'onglet « Vue 3D ». Sans ce redessin, la
         taille de rendu (canvas.width/height, fixee au dernier dessin) reste
         celle d'avant et l'image apparait etiree. */
      if (typeof ResizeObserver === "function") {
        new ResizeObserver(() => dessiner()).observe(canvas);
      } else {
        window.addEventListener("resize", dessiner);
      }
    },
    surligner(ids) {
      surlignes = new Set(ids || []);
      dessiner();
    },
    charger(listeNoeuds, listeElements) {
      noeuds = listeNoeuds || [];
      elements = (listeElements || []).filter((e) => !e.factice);
      surlignes = new Set();
      parId = new Map(noeuds.map((n) => [n.node, n]));
      // geometrie « sections » d'un AUTRE modele : jamais reutilisee sur
      // celui qu'on vient de charger (cf. Vue3D.chargerSections)
      sectionsData = null;
      sectionsActives = false;
      enMouvement = false;
      clearTimeout(minuterieReglage);

      /* recadrage : centre + rayon englobant */
      if (noeuds.length) {
        const xs = noeuds.map((n) => n.x), ys = noeuds.map((n) => n.y), zs = noeuds.map((n) => n.z);
        bbox = { x0: Math.min(...xs), x1: Math.max(...xs),
                 y0: Math.min(...ys), y1: Math.max(...ys),
                 z0: Math.min(...zs), z1: Math.max(...zs) };
        centre = [(bbox.x0 + bbox.x1) / 2, (bbox.y0 + bbox.y1) / 2,
                  (bbox.z0 + bbox.z1) / 2];
        rayon = Math.max(1e-6, ...noeuds.map((n) =>
          Math.hypot(n.x - centre[0], n.y - centre[1], n.z - centre[2])));
      } else {
        bbox = null;
      }
      reinitialiser();
      dessiner();
    },
    /* mémorise la géométrie « sections » (réponse de /api/vue-sections) sans
       l'activer — cf. basculerSections */
    chargerSections(geometrie) {
      sectionsData = geometrie || null;
    },
    /* bascule le rendu filaire <-> solide (sections réelles) ; sans effet si
       aucune géométrie n'a été chargée (cf. chargerSections) */
    basculerSections(actif) {
      sectionsActives = !!actif && !!sectionsData;
      enMouvement = false;
      dessiner();
      return sectionsActives;
    },
    sectionsChargees() { return !!sectionsData; },
    /* redessine sans rien changer a l'etat. Utile quand le canvas a ete
       MASQUE (onglet de sortie « Detail optimisation » actif) puis reaffiche :
       tant qu'il est masque, clientWidth/clientHeight valent 0 et un
       redimensionnement de la fenetre passe inapercu — au retour, la taille de
       rendu ne correspond plus a la taille affichee. `dessiner()` recale
       canvas.width/height sur clientWidth/clientHeight a chaque appel. */
    redessiner() { dessiner(); },
    /* capture l'état actuel du canvas en PNG (pour le téléchargement,
       cf. app.js) */
    exporterImage() { return canvas ? canvas.toDataURL("image/png") : null; },
  };
})();
