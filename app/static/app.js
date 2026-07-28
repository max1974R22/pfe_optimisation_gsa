/* ==== Dimensionneur GSA — logique de la page ==== */
"use strict";

const $ = (id) => document.getElementById(id);
let familleActive = "HE";   // repli si absente des familles reçues, cf. remplirFamilles
let dernierResume = null;   // dernière réponse /api/resume (éléments, listes…)
let dernierRun = null;      // {modele, famille, section, cible} du dernier dimensionnement réussi
let dernierExcel = null;    // {libelle, nuance, barre} pour l'export Predim (mode torseur)

/* ---------------------------------------------------------------- utils */
async function api(chemin, options) {
  const rep = await fetch(chemin, options);
  const data = await rep.json().catch(() => ({ erreur: `HTTP ${rep.status}` }));
  if (!rep.ok) throw new Error(data.erreur || `HTTP ${rep.status}`);
  return data;
}
function message(id, texte, classe = "") {
  const el = $(id);
  el.textContent = texte;
  el.className = "message " + classe;
}
const fmt = (v, dec = 2) =>
  v === null || v === undefined ? "—" : Number(v).toLocaleString("fr-FR", {
    minimumFractionDigits: dec, maximumFractionDigits: dec });
const echapperXml = (s) => String(s).replace(/[&<>]/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));

/* suivi d'avancement d'un calcul long : polle GET /api/progression pendant
   qu'on attend la réponse, et affiche « étape — fait/total » dans le message.
   Renvoie une fonction stop() à appeler AVANT d'écrire le message final
   (elle coupe le timer et neutralise un poll encore en vol). */
function suivreProgression(canal, msgId) {
  let actif = true;
  const tick = async () => {
    if (!actif) return;
    try {
      const p = (await api("/api/progression"))[canal];
      if (!actif || !p || !p.etape || p.etape === "terminé") return;
      const avancement = p.total ? ` — ${p.fait ?? 0}/${p.total}` : "…";
      message(msgId, `${p.etape}${avancement}`);
    } catch (e) { /* le poll ne doit jamais perturber le calcul */ }
  };
  const timer = setInterval(tick, 600);
  return () => { actif = false; clearInterval(timer); };
}

/* récapitulatif du torseur ELU transmis au classeur Predim (réponse des
   endpoints /api/excel-barre et /api/excel-famille) */
function recapTorseur(res) {
  const t = res.torseur;
  const ligne = (nom, c, u) => `<tr><th>${nom}</th>
    <td>${fmt(c.max, 2)} ${u}</td><td>${fmt(c.min, 2)} ${u}</td>
    <td><b>${fmt(c.enveloppe, 2)} ${u}</b></td></tr>`;
  return `<h4>Torseur ELU transmis — ${res.profil} · ${res.nuance} · L = ${fmt(res.longueur_m, 2)} m</h4>
     <table><tr><th></th><th>max</th><th>min</th><th>saisi</th></tr>
     ${ligne("N", t.N, "kN")}${ligne("Vz", t.Vz, "kN")}${ligne("Vy", t.Vy, "kN")}
     ${ligne("My", t.My, "kNm")}${ligne("Mz", t.Mz, "kNm")}</table>`;
}

/* ---------------------------------------------------------- initialisation */
async function init() {
  try {
    const etat = await api("/api/etat");
    remplirModeles(etat.modeles);
    remplirFamilles(etat.familles);
    remplirAlgos(etat.algos, etat.algo_defaut);
    remplirMesuresPerf(etat.mesures_elu);
    $("in-fy").value = etat.criteres.fy_MPa;
    $("in-coef").value = etat.criteres.coefficient;
    $("in-denom").value = etat.criteres.denominateur;
    majSigma();
    majFleche();
  } catch (e) {
    message("msg-modele", "serveur injoignable", "erreur");
  }
}

/* ------------------------------------------------------- onglets principaux */
let vueActive = "modele";
function choisirVue(vue) {
  vueActive = vue;
  $("onglets-vues").querySelectorAll(".onglet").forEach((o) =>
    o.classList.toggle("actif", o.dataset.vue === vue));
  ["modele", "perf", "optim"].forEach((v) => { $("vue-" + v).hidden = v !== vue; });
  if (vue === "perf" && dernierResume && !perfChargee) {
    // pas de combinaisons ELU/ELS nommées : on attend le choix + « Lancer »
    if (refsManuelles)
      message("msg-perf", "choisir les combinaisons ELU et ELS puis « Lancer l'analyse ».");
    else
      chargerPerf();
  }
}
$("onglets-vues").addEventListener("click", (ev) => {
  const btn = ev.target.closest(".onglet");
  if (btn && !btn.disabled && btn.dataset.vue !== vueActive) choisirVue(btn.dataset.vue);
});
function activerVues(actives) {
  $("onglets-vues").querySelectorAll(".onglet").forEach((o) => {
    if (o.dataset.vue !== "modele") o.disabled = !actives;
  });
}
function remplirModeles(modeles, selection) {
  const sel = $("sel-modele");
  sel.innerHTML = "";
  modeles.forEach((m) => sel.add(new Option(m, m)));
  if (selection) sel.value = selection;
}
function remplirFamilles(familles) {
  const zone = $("familles");
  zone.innerHTML = "";
  // la famille active peut ne plus exister (ex. valeur par défaut du script,
  // ou familles.json modifié) : repli sur la première proposée
  if (familles.length && !familles.includes(familleActive)) familleActive = familles[0];
  familles.forEach((f) => {
    const b = document.createElement("button");
    b.className = "chip" + (f === familleActive ? " actif" : "");
    b.textContent = f;
    b.onclick = () => {
      familleActive = f;
      zone.querySelectorAll(".chip").forEach((c) => c.classList.toggle("actif", c === b));
      majUIAlgo();
    };
    zone.appendChild(b);
  });
}
function remplirAlgos(algos, defaut) {
  /* menu déroulant des algorithmes d'optimisation globale (dossier algo_opti/) */
  const sel = $("sel-algo");
  sel.innerHTML = "";
  (algos || []).forEach((a) => {
    const o = new Option(a.libelle, a.id);
    o.title = a.description || "";
    sel.add(o);
  });
  if (defaut) sel.value = defaut;
}
function majSigma() {
  const lim = ($("in-coef").value * $("in-fy").value) || 0;
  $("lbl-sigma").textContent = `soit σ ≤ ${fmt(lim, 1)} MPa`;
}
["in-coef", "in-fy"].forEach((id) => $(id).addEventListener("input", majSigma));

/* flèche limite = portée GLOBALE du modèle chargé / dénominateur (cf. server.py
   ::_perf_extraire — même critère que l'onglet Performances/Optimisation) ;
   n'affiche rien tant qu'aucun modèle n'est chargé (portée inconnue) */
function majFleche() {
  const denom = parseFloat($("in-denom").value) || 0;
  const L = dernierResume && dernierResume.portee_m;
  const lim = (L && denom) ? (L * 1000 / denom) : null;
  $("lbl-fleche").textContent = lim
    ? `soit f ≤ ${fmt(lim, 1)} mm (L = ${fmt(L, 2)} m)` : "";
}
$("in-denom").addEventListener("input", majFleche);

/* ------------------------------------------------------------------ dépôt */
const zone = $("zone-depot");
zone.addEventListener("dragover", (e) => { e.preventDefault(); zone.classList.add("survol"); });
zone.addEventListener("dragleave", () => zone.classList.remove("survol"));
zone.addEventListener("drop", (e) => {
  e.preventDefault(); zone.classList.remove("survol");
  if (e.dataTransfer.files.length) deposer(e.dataTransfer.files[0]);
});
$("input-fichier").addEventListener("change", (e) => {
  if (e.target.files.length) deposer(e.target.files[0]);
});
async function deposer(fichier) {
  try {
    message("msg-modele", `dépôt de ${fichier.name}…`);
    const data = await api(`/api/upload?nom=${encodeURIComponent(fichier.name)}`,
                           { method: "POST", body: fichier });
    remplirModeles(data.modeles, data.modele);
    message("msg-modele", `${data.modele} ajouté à GSA_model/`, "ok");
  } catch (e) {
    message("msg-modele", e.message, "erreur");
  }
}

/* ------------------------------------------------------------------ résumé */
$("btn-resume").addEventListener("click", chargerResume);
$("sel-modele").addEventListener("change", () => {
  dernierResume = null;
  choisirVue("modele");
  activerVues(false);
  $("carte-resume").hidden = true; $("carte-res").hidden = true;
  majFleche();                     // portée inconnue tant que le résumé n'est pas rechargé
});
async function chargerResume(garderResultats = false) {
  const btn = $("btn-resume");
  btn.disabled = true;
  message("msg-modele", "lecture du modèle (GsaAPI)…");
  const stop = suivreProgression("resume", "msg-modele");
  try {
    const r = await api(`/api/resume?modele=${encodeURIComponent($("sel-modele").value)}`);
    stop();
    dernierResume = r;
    afficherResume(r);
    message("msg-modele", "");
    $("carte-resume").hidden = false;
    majFleche();                     // portée du modèle chargé -> flèche limite (cf. lbl-fleche)
    resetPerf();                     // le modèle (re)chargé invalide les perfs
    configurerCombosPerf(r);         // combinaisons ELU/ELS (auto ou au choix)
    activerVues(true);
    if (!garderResultats) $("carte-res").hidden = true;
    $("titre-3d").textContent = r.modele;
    $("titre-3d").hidden = false;
    $("vide-3d").hidden = true;
    Vue3D.charger(r.noeuds, r.elements);
    reinitialiserOutils3D();
    majCible();
    if (!garderResultats)
      $("carte-resume").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (e) {
    stop();
    message("msg-modele", e.message, "erreur");
  } finally {
    stop();
    btn.disabled = false;
  }
}

/* tuile repliable : au-delà de `max` lignes, le reste se déplie avec un petit + */
const MAX_LIGNES_TUILE = 6;
function tuile(titre, lignes, max = MAX_LIGNES_TUILE) {
  const tr = (arr, cls) => arr.map(([k, v]) =>
    `<tr${cls ? ` class="${cls}"` : ""}><th>${k}</th><td>${v}</td></tr>`).join("");
  const visibles = lignes.slice(0, max);
  const cachees = lignes.slice(max);
  const bascule = cachees.length
    ? `<tr class="ligne-plus"><td colspan="2"><button class="btn-plus"
         data-plus="+ ${cachees.length} autre(s)" data-moins="− réduire">
         + ${cachees.length} autre(s)</button></td></tr>`
    : "";
  return `<div class="tuile"><h3>${titre}</h3>
    <table>${tr(visibles)}${tr(cachees, "cachee")}${bascule}</table></div>`;
}
/* délégation : un seul écouteur pour tous les + / − des tuiles */
$("grille-resume").addEventListener("click", (ev) => {
  const btn = ev.target.closest(".btn-plus");
  if (!btn) return;
  const table = btn.closest("table");
  const deplie = btn.classList.toggle("deplie");
  table.querySelectorAll("tr.cachee").forEach((tr) => tr.classList.toggle("visible", deplie));
  btn.textContent = deplie ? btn.dataset.moins : btn.dataset.plus;
});
function afficherResume(r) {
  $("resume-nom").textContent = r.modele;
  const dr = [];
  dr.push(r.analysable
    ? `<span class="pill ok">modèle analysable</span>`
    : `<span class="pill ko">non analysable — ${r.probleme}</span>`);
  dr.push(r.combinaisons_trouvees
    ? `<span class="pill ok">combinaisons ELU (${r.combinaisons_trouvees.ELU}) et ELS (${r.combinaisons_trouvees.ELS}) trouvées</span>`
    : `<span class="pill ko">combinaisons ELU/ELS introuvables</span>`);
  if (r.portee_m) dr.push(`<span class="pill">portée L = ${fmt(r.portee_m, 2)} m</span>`);
  $("drapeaux").innerHTML = dr.join("");

  const g = [];
  g.push(tuile(`Nœuds (${r.noeuds.length})`, r.noeuds.map((n) =>
    [`n°${n.node}`, `(${fmt(n.x, 1)}; ${fmt(n.y, 1)}; ${fmt(n.z, 1)})`
      + (n.res_x || n.res_y || n.res_z ? " <span class=\"appui\">appui</span>" : "")])));
  g.push(tuile(`Éléments 1D (${r.elements.length})`, r.elements.map((e) =>
    [`n°${e.element}`, `${e.type} — nœuds ${e.topologie.join("→")}`
      + (e.longueur_m ? ` — ${fmt(e.longueur_m, 2)} m` : "")])));
  g.push(tuile("Section actuelle", r.sections.map((s) => ["n°" + s.section,
    `<span class="mono">${s.profil}</span><br>A = ${s.aire_m2} m² · Iyy = ${s.Iyy_m4} m⁴ · Wel,y = ${s.Zy_m3} m³`])));
  g.push(tuile("Matériaux", r.materiaux.map((m) => [m.nom || m.type,
    `E = ${fmt(m.E_Pa / 1e9, 0)} GPa · ρ = ${fmt(m.densite_kg_m3, 0)} kg/m³ · ν = ${m.nu}`])));
  g.push(tuile("Cas de charge", r.cas_de_charge.map((c) => [`L${c.cas}`, `${c.nom} <span class="mono">(${c.type})</span>`])));
  const charges = [];
  r.charges_poutre.forEach((b) => charges.push([`cas ${b.cas}`,
    `${b.type} ${b.direction} = <b>${b.valeur} N/m</b> sur ${b.cible} ${b.liste}`]));
  (r.charges_nodales || []).forEach((nl) => charges.push([`cas ${nl.cas}`,
    `nodale ${nl.direction} = <b>${nl.valeur} N</b> sur nœuds ${nl.noeuds}`
    + (nl.type !== "NODE_LOAD" ? ` <span class="mono">(${nl.type})</span>` : "")]));
  r.charges_gravite.forEach((gr) => charges.push([`cas ${gr.cas}`,
    `gravité (${gr.facteur_x}; ${gr.facteur_y}; ${gr.facteur_z}) sur ${gr.liste ?? "tout"}`]));
  g.push(tuile("Charges", charges.length ? charges : [["—", "aucune"]]));
  const listes = listesBarres(r);
  if (listes.length)
    g.push(tuile("Groupes (listes GSA)", listes.map((l) =>
      [l.nom, `${l.ids.length} barre(s) — <span class="mono">${l.definition}</span>`])));
  g.push(tuile("Combinaisons", r.combinaisons.map((c) =>
    [`C${c.combinaison}`, `<b>${c.nom}</b> = <span class="mono">${c.definition}</span>`])));
  $("grille-resume").innerHTML = g.join("");

  $("btn-lancer").disabled = !(r.analysable && r.combinaisons_trouvees);
}

/* -------------------------------------------- performances du modèle actuel */
let perfChargee = false;
let dernierPerf = null;         // { barres: [...], meta: {refs, rho_kg_m3, total} }
let jobPerf = null;             // { id, timer } du calcul de performances EN FLUX
let mesuresPerf = new Set();    // mesures prises en compte dans σ max / σ min
let refsManuelles = false;      // le modèle n'a pas de combinaisons nommées ELU/ELS
let avecStressActif = false;    // options du calcul EN COURS (figées au lancement,
let enveloppeMembresActif = false; // cf. bouton « Relancer l'analyse » pour les changer

/* colonnes efforts/moments — toujours extraites (rapide, cf. server.py::_perf_ligne) ;
   C1/C2 = contraintes combinées (A±B) déduites de N/My/Mz, PAS les coefficients
   de déversement C1/C2 de l'encadré stabilité (même nom, notion différente) */
const COLS_EFFORTS = [
  ["N", "N", "kN"], ["Vy", "Vy", "kN"], ["Vz", "Vz", "kN"],
  ["My", "My", "kNm"], ["Mz", "Mz", "kNm"],
];
const profilCourt = (p) => (p || "").replace(/^CAT \S+ /, "").replace(/ \d{8}$/, "");

/* combinaisons ELU/ELS transmises aux calculs : celles choisies dans la page
   quand le modèle n'en nomme aucune ainsi, sinon {} (détection par nom côté
   serveur) */
function refsChoisies() {
  return refsManuelles ? { elu: $("sel-elu").value, els: $("sel-els").value } : {};
}

function configurerCombosPerf(r) {
  /* le serveur n'a pas trouvé de combinaisons nommées ELU/ELS -> l'utilisateur
     les désigne dans deux listes déroulantes (bloc affiché) ; sinon on masque
     le bloc et on garde la détection automatique */
  refsManuelles = !r.combinaisons_trouvees;
  $("bloc-combos").hidden = !refsManuelles;
  if (!refsManuelles) return;
  const combos = r.combinaisons || [];
  [["sel-elu", "ELU"], ["sel-els", "ELS"]].forEach(([id, mot]) => {
    const sel = $(id);
    sel.innerHTML = "";
    combos.forEach((c) => sel.add(new Option(`C${c.combinaison} — ${c.nom}`, `C${c.combinaison}`)));
    // pré-sélection : une combinaison « ENVELOPPE <mot> », sinon « <mot> »
    const trouve = (pred) => combos.find((c) => pred((c.nom || "").toUpperCase()));
    const c = trouve((n) => n.includes("ENVELOPPE") && n.includes(mot))
           || trouve((n) => n.includes(mot));
    if (c) sel.value = `C${c.combinaison}`;
  });
}
$("btn-perf").addEventListener("click", () => { if (dernierResume) chargerPerf(); });

function remplirMesuresPerf(mesures) {
  /* chips de filtrage des contraintes du tableau de performances : toutes
     sélectionnées au départ ; en décocher une (ex. von Mises) fait remonter
     la mesure dimensionnante suivante dans σ max / σ min */
  const zone = $("mesures-perf");
  zone.innerHTML = "";
  mesuresPerf = new Set((mesures || []).map((m) => m.id));
  (mesures || []).forEach((m) => {
    const b = document.createElement("button");
    b.className = "chip petite actif";
    b.textContent = m.id;
    b.title = `${m.libelle} (${m.groupe})`;
    b.onclick = () => {
      if (mesuresPerf.has(m.id)) {
        if (mesuresPerf.size === 1) return;   // au moins une mesure
        mesuresPerf.delete(m.id);
      } else {
        mesuresPerf.add(m.id);
      }
      b.classList.toggle("actif", mesuresPerf.has(m.id));
      majSigmasPerf();
    };
    zone.appendChild(b);
  });
}

function extremesBarre(b) {
  /* max/min signés d'une barre sur les seules mesures cochées */
  let vmax = null, mmax = null, vmin = null, mmin = null;
  mesuresPerf.forEach((mid) => {
    const s = (b.sigmas || {})[mid];
    if (!s) return;
    if (vmax === null || s.max > vmax) { vmax = s.max; mmax = mid; }
    if (vmin === null || s.min < vmin) { vmin = s.min; mmin = mid; }
  });
  return { vmax, mmax, vmin, mmin };
}

function majSigmasPerf() {
  /* réactualise les tuiles (poids, σ, flèche) et les colonnes σ / |Uz| du
     tableau à partir des barres accumulées (calcul progressif en flux), sans
     toucher aux colonnes de stabilité remplies en parallèle */
  const p = dernierPerf;
  if (!p) return;
  const exb = new Map(p.barres.map((b) => [b.element, extremesBarre(b)]));
  let gmax = null, gmin = null, gfle = null;    // extrêmes globaux
  let gc1 = null, gc2 = null;                   // contrainte combinée (efforts) globale
  let poids = 0;
  p.barres.forEach((b) => {
    poids += b.masse_kg || 0;
    if (b.Uz_max_mm != null && (!gfle || b.Uz_max_mm > gfle.valeur))
      gfle = { valeur: b.Uz_max_mm, element: b.element };
    if (b.C1_MPa != null && (!gc1 || b.C1_MPa > gc1.valeur))
      gc1 = { valeur: b.C1_MPa, element: b.element };
    if (b.C2_MPa != null && (!gc2 || b.C2_MPa < gc2.valeur))
      gc2 = { valeur: b.C2_MPa, element: b.element };
  });
  exb.forEach((e, eid) => {
    if (e.vmax !== null && (!gmax || e.vmax > gmax.valeur))
      gmax = { valeur: e.vmax, element: eid, mesure: e.mmax };
    if (e.vmin !== null && (!gmin || e.vmin < gmin.valeur))
      gmin = { valeur: e.vmin, element: eid, mesure: e.mmin };
  });

  const rho = (p.meta && p.meta.rho_kg_m3) || 0;
  const mixte = p.meta && p.meta.materiaux_mixtes;
  const stat = (titre, valeur, detail) => `
    <div class="stat"><span class="stat-titre">${titre}</span>
      <span class="stat-valeur">${valeur}</span>
      <span class="stat-detail">${detail}</span></div>`;
  $("perf-stats").innerHTML =
    // modèle à matériau unique (cas courant, acier) : densité affichée ;
    // modèle mixte (ex. acier + bois) : chaque barre a SA densité réelle
    // (cf. _densites_sections côté serveur), pas de ρ unique à afficher
    stat(mixte ? "Poids total" : "Poids d'acier", `${fmt(poids, 1)} kg`,
         mixte ? "Σ L·A·ρ (densité par matériau)" : `Σ L·A·ρ, ρ = ${fmt(rho, 0)} kg/m³`)
    + (gmax
       ? stat("σ max — ELU", `${fmt(gmax.valeur, 1)} MPa`,
              `barre n°${gmax.element} · ${gmax.mesure}`) : "")
    + (gmin
       ? stat("σ min — ELU", `${fmt(gmin.valeur, 1)} MPa`,
              `barre n°${gmin.element} · ${gmin.mesure}`) : "")
    + (gc1
       ? stat("C1 max (A+B) — ELU", `${fmt(gc1.valeur, 1)} MPa`,
              `barre n°${gc1.element} · déduit de N/My/Mz`) : "")
    + (gc2
       ? stat("C2 min (A-B) — ELU", `${fmt(gc2.valeur, 1)} MPa`,
              `barre n°${gc2.element} · déduit de N/My/Mz`) : "")
    + (gfle
       ? stat("Déplacement max — ELS", `${fmt(gfle.valeur, 2)} mm`,
              `barre n°${gfle.element} · |Uz|`) : "");

  const corps = $("table-perf").querySelector("tbody");
  p.barres.forEach((b) => {
    const tr = corps.querySelector(`tr[data-element="${b.element}"]`);
    if (!tr) return;
    const e = exb.get(b.element);
    const cel = (cls, txt, pire) => {
      const c = tr.querySelector(cls);
      if (!c) return;   // colonnes σ absentes du tableau (avecStressActif = false)
      c.textContent = txt;
      if (pire !== undefined) c.classList.toggle("pire", pire);
    };
    cel(".cel-smax", e.vmax === null ? "—" : fmt(e.vmax, 1),
        gmax && b.element === gmax.element && e.vmax === gmax.valeur);
    cel(".cel-mmax", e.mmax ?? "—");
    cel(".cel-smin", e.vmin === null ? "—" : fmt(e.vmin, 1),
        gmin && b.element === gmin.element && e.vmin === gmin.valeur);
    cel(".cel-mmin", e.mmin ?? "—");
    cel(".cel-uz", fmt(b.Uz_max_mm, 2),
        gfle && b.element === gfle.element && b.Uz_max_mm === gfle.valeur);
    cel(".cel-c1", fmt(b.C1_MPa, 1),
        gc1 && b.element === gc1.element && b.C1_MPa === gc1.valeur);
    cel(".cel-c2", fmt(b.C2_MPa, 1),
        gc2 && b.element === gc2.element && b.C2_MPa === gc2.valeur);
  });
}

function resetPerf() {
  arreterPerf();                   // coupe un calcul en flux encore en cours
  perfChargee = false;
  dernierPerf = null;
  barreChoisie = null;
  $("perf-contenu").hidden = true;
  $("perf-detail").open = false;
  $("zone-excel-barre").hidden = true;
  $("recap-excel-barre").hidden = true;
  $("btn-perf-stop").hidden = true;
  message("msg-perf", "");
  message("msg-stab", "");
  message("msg-excel-barre", "");
}

/* l'analyse se lance à l'ouverture de l'onglet Performances (cf. choisirVue) */
/* visible dès que la case est cochée (indépendant du calcul en cours : montre
   ce qui SERA affiché après avoir cliqué « Relancer l'analyse ») */
$("chk-stress").addEventListener("change", () =>
  $("bloc-mesures-perf").hidden = !$("chk-stress").checked);

const colsEntetesEfforts = () => COLS_EFFORTS.map(([id, lbl, unite]) =>
  `<th>${lbl} max<br>${unite}</th><th>${lbl} min<br>${unite}</th>`).join("");
const colsCellulesEfforts = (source) => COLS_EFFORTS.map(([id]) => {
  const v = (source && source[id]) || {};
  return `<td>${fmt(v.max, id.startsWith("M") ? 2 : 1)}</td><td>${fmt(v.min, id.startsWith("M") ? 2 : 1)}</td>`;
}).join("");

/* en-tête du tableau, reconstruite au lancement selon les options ACTIVES
   (avecStressActif/enveloppeMembresActif, figées pour la durée du calcul) */
function entetePerfHTML() {
  const colsC1C2 = `<th title="Contrainte combinée A+B max (déduite de N/My/Mz — sans rapport avec les coefficients de déversement C1/C2 de l'encadré stabilité)">C1<br>MPa</th>
                     <th title="Contrainte combinée A-B min">C2<br>MPa</th>`;
  const colsStress = avecStressActif ? `
    <th>σ max ELU<br>MPa</th><th>Stress<br>max</th>
    <th>σ min ELU<br>MPa</th><th>Stress<br>min</th>` : "";
  return `<tr>
    <th>${enveloppeMembresActif ? "Barre / position" : "Barre"}</th><th>Profil</th><th>L<br>m</th><th>Masse<br>kg</th>
    ${colsEntetesEfforts()}${colsC1C2}${colsStress}
    <th>|Uz| max<br>mm</th>
    <th title="amplitude C1/C2 (max(C1,-C2)) / fy — limite = coefficient du critère (ex. 0.9)">Taux<br>ELU</th>
    <th title="|Uz| max / flèche limite (portée globale de l'ouvrage / denominateur)">Taux<br>ELS</th>
    <th>Taux<br>stabilité</th><th>OK</th><th>Cas<br>dimensionnant</th>
  </tr>`;
}

/* ligne(s) de tableau d'une barre : la ligne de synthèse (colonnes σ / |Uz| /
   stabilité remplies ensuite par majSigmasPerf et appliquerStabPerf, au fur
   et à mesure du flux), suivie — si l'enveloppe sur les éléments est active —
   des 5 lignes de détail par position (0/25/50/75/100 %), directement dans
   le même tableau (pas de panneau séparé à ouvrir). */
/* libellé + classe d'une cellule OK/KO — `ok` : true/false/null (indisponible) */
const okHTML = (ok) => ok === null || ok === undefined
  ? `<td class="cel-ok">…</td>`
  : `<td class="cel-ok ${ok ? "verdict-ok" : "verdict-ko"}">${ok ? "OK" : "KO"}</td>`;

/* verdict global d'une barre : KO si l'un des trois (ELU/ELS, stabilité) est
   dépassé, OK si les trois sont connus et tiennent, sinon null (incomplet) */
const okCombine = (eluEls, stabOk) => (eluEls === false || stabOk === false) ? false
  : (eluEls === null || eluEls === undefined || stabOk === null || stabOk === undefined) ? null : true;

function lignePerfHTML(b) {
  const colsC1C2 = `<td class="cel-c1">${fmt(b.C1_MPa, 1)}</td><td class="cel-c2">${fmt(b.C2_MPa, 1)}</td>`;
  const colsStress = avecStressActif ? `
    <td class="cel-smax">…</td><td class="mono cel-mmax">…</td>
    <td class="cel-smin">…</td><td class="mono cel-mmin">…</td>` : "";
  const ligneBarre = `
    <tr data-element="${b.element}" class="${b.ok === false ? "depassee" : ""}">
      <td>n°${b.element}</td>
      <td class="mono">${profilCourt(b.profil) || "—"}</td>
      <td>${fmt(b.longueur_m, 2)}</td>
      <td>${fmt(b.masse_kg, 1)}</td>
      ${colsCellulesEfforts(b.efforts)}${colsC1C2}${colsStress}
      <td class="cel-uz">${fmt(b.Uz_max_mm, 2)}</td>
      <td class="cel-elu">${b.taux_ELU == null ? "—" : barreTaux(b.taux_ELU, (dernierPerf.meta && dernierPerf.meta.coefficient) || 1)}</td>
      <td class="cel-els">${b.taux_ELS == null ? "—" : barreTaux(b.taux_ELS)}</td>
      <td class="cel-stab">…</td>
      ${okHTML(b.ok)}
      <td class="cel-cas">…</td>
    </tr>`;
  if (!enveloppeMembresActif || !b.positions || !b.positions.length) return ligneBarre;
  const colsVidesStress = avecStressActif ? "<td></td><td></td><td></td><td></td>" : "";
  const lignesPosition = b.positions.map((p) => `
    <tr class="ligne-position">
      <td>↳ ${Math.round(p.pos * 100)} %</td><td></td><td></td><td></td>
      ${colsCellulesEfforts(p)}<td>${fmt(p.C1_MPa, 1)}</td><td>${fmt(p.C2_MPa, 1)}</td>${colsVidesStress}
      <td></td><td></td><td></td><td></td><td></td><td></td>
    </tr>`).join("");
  return ligneBarre + lignesPosition;
}

/* export CSV du tableau de performances affiché (s'ouvre nativement dans
   Excel) — construit depuis les DONNÉES accumulées (dernierPerf), pas en
   lisant le DOM, pour garder la pleine précision numérique */
function exporterPerfCSV() {
  const p = dernierPerf;
  if (!p || !p.barres.length) return;
  const entetes = ["element", "position", "profil", "longueur_m", "masse_kg",
    ...COLS_EFFORTS.flatMap(([id, lbl, u]) => [`${lbl}_max_${u}`, `${lbl}_min_${u}`]),
    "C1_MPa", "C2_MPa"];
  if (avecStressActif) entetes.push("sigma_max_MPa", "mesure_max", "sigma_min_MPa", "mesure_min");
  entetes.push("Uz_max_mm", "taux_ELU", "taux_ELS", "taux_stabilite", "ok", "cas_stabilite");
  const stabMap = p.stab || {};
  const auCsv = (vals) => vals.map((v) =>
    (v === null || v === undefined) ? "" : String(v).replace(/;/g, ",")).join(";");
  const lignes = [];
  p.barres.forEach((b) => {
    const s = stabMap[b.element] || stabMap[String(b.element)] || {};
    const stabOk = s.erreur ? null : (s.taux_stabilite === undefined ? null : s.taux_stabilite <= 1);
    const ok = okCombine(b.ok, stabOk);
    lignes.push(auCsv([b.element, "", profilCourt(b.profil), b.longueur_m, b.masse_kg,
      ...COLS_EFFORTS.flatMap(([id]) => [(b.efforts || {})[id]?.max, (b.efforts || {})[id]?.min]),
      b.C1_MPa, b.C2_MPa,
      ...(avecStressActif ? [b.sigma_max_MPa, b.mesure_max, b.sigma_min_MPa, b.mesure_min] : []),
      b.Uz_max_mm, b.taux_ELU, b.taux_ELS, s.taux_stabilite,
      ok === null ? "" : (ok ? "OK" : "KO"), s.cas]));
    if (enveloppeMembresActif && b.positions) {
      b.positions.forEach((pos) => lignes.push(auCsv([b.element, `${Math.round(pos.pos * 100)}%`, "", "", "",
        ...COLS_EFFORTS.flatMap(([id]) => [pos[id]?.max, pos[id]?.min]), pos.C1_MPa, pos.C2_MPa,
        ...(avecStressActif ? ["", "", "", ""] : []), "", "", "", "", "", ""])));
    }
  });
  const csv = "﻿" + [entetes.join(";"), ...lignes].join("\r\n");
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `performances_${($("sel-modele").value || "modele").replace(/\.gwb$/i, "")}.csv`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(a.href);
}
$("btn-perf-export").addEventListener("click", exporterPerfCSV);

/* remplit les colonnes stabilité + OK des barres dont le résultat EC3 est
   arrivé (calculé en parallèle de l'extraction GSA, il peut arriver après la
   ligne) : OK combine le verdict ELU/ELS déjà connu (b.ok, cf. lignePerfHTML)
   et le nouveau verdict de stabilité — KO si l'un des trois est dépassé,
   sinon OK si les trois sont connus, sinon « … » (encore incomplet). Le taux
   de stabilité est affiché avec la même jauge colorée (barreTaux) que les
   colonnes ELU/ELS et que le tableau d'optimisation globale — pas de case
   surlignée : la couleur de la jauge suffit à repérer un dépassement. Une
   ligne KO est surlignée en rouge sur toute la ligne (même logique que
   #table-global tr.depassee) */
function appliquerStabPerf(stab) {
  if (!stab) return;
  const p = dernierPerf;
  const corps = $("table-perf").querySelector("tbody");
  Object.entries(stab).forEach(([eid, b]) => {
    const tr = corps.querySelector(`tr[data-element="${eid}"]`);
    if (!tr) return;
    const celTaux = tr.querySelector(".cel-stab");
    const celCas = tr.querySelector(".cel-cas");
    const celOk = tr.querySelector(".cel-ok");
    let stabOk = null;
    if (b.erreur) {
      celTaux.textContent = "—";
      celCas.textContent = "—";
      celCas.title = b.erreur;
    } else {
      celTaux.innerHTML = barreTaux(b.taux_stabilite);
      celCas.textContent = b.taux_stabilite > 0 ? b.cas : "—";
      celCas.title = Object.entries(b.taux || {})
        .map(([k, v]) => `${k} : ${v === null ? "—" : fmt(v, 3)}`).join("\n");
      stabOk = b.taux_stabilite <= 1;
    }
    const ligne = p && p.barres.find((x) => String(x.element) === String(eid));
    const ok = okCombine(ligne ? ligne.ok : null, stabOk);
    celOk.className = `cel-ok ${ok === null ? "" : ok ? "verdict-ok" : "verdict-ko"}`;
    celOk.textContent = ok === null ? "…" : (ok ? "OK" : "KO");
    tr.classList.toggle("depassee", ok === false);
  });
}

/* démarre le calcul de performances EN FLUX (barre par barre côté serveur) :
   le tableau se remplit au fur et à mesure, la stabilité EC3 arrive en
   parallèle, et le bouton Arrêter coupe la boucle */
async function chargerPerf() {
  await arreterPerf();                 // stoppe un job précédent éventuel
  perfChargee = true;
  // options figées pour la durée de ce calcul (cf. entetePerfHTML/lignePerfHTML)
  avecStressActif = $("chk-stress").checked;
  enveloppeMembresActif = $("chk-enveloppe-pos").checked;
  dernierPerf = { barres: [], meta: {} };
  barreChoisie = null;
  $("table-perf").querySelector("thead").innerHTML = entetePerfHTML();
  $("table-perf").querySelector("tbody").innerHTML = "";
  $("perf-stats").innerHTML = "";
  $("perf-contenu").hidden = false;
  message("msg-stab", "");
  message("msg-perf", avecStressActif
    ? "démarrage du calcul barre par barre (efforts + contraintes)…"
    : "démarrage du calcul barre par barre (efforts/moments)…");
  try {
    const r = await api("/api/performance/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ modele: $("sel-modele").value,
                             coefs: coefsStabilite(), avec_stress: avecStressActif,
                             enveloppe_membres: enveloppeMembresActif, ...refsChoisies() }),
    });
    jobPerf = { id: r.job, timer: null };
    $("btn-perf-stop").hidden = false;
    $("btn-perf-stop").disabled = false;
    sonderPerf();
  } catch (e) {
    message("msg-perf", e.message, "erreur");
    $("btn-perf-stop").hidden = true;
    jobPerf = null;
  }
}

/* une itération de poll : récupère les nouvelles barres + stabilités, remplit
   le tableau, et se replanifie tant que le job tourne */
async function sonderPerf() {
  if (!jobPerf) return;
  const jobId = jobPerf.id;
  try {
    const depuis = dernierPerf.barres.length;
    const s = await api(`/api/performance/poll?job=${jobId}&depuis=${depuis}`);
    if (!jobPerf || jobPerf.id !== jobId) return;   // job remplacé/arrêté entre-temps
    if (s.meta && s.meta.total != null) dernierPerf.meta = s.meta;
    if (s.lignes && s.lignes.length) {
      $("table-perf").querySelector("tbody")
        .insertAdjacentHTML("beforeend", s.lignes.map(lignePerfHTML).join(""));
      dernierPerf.barres.push(...s.lignes);
    }
    if (s.stab) dernierPerf.stab = s.stab;   // export CSV (cf. exporterPerfCSV)
    appliquerStabPerf(s.stab);
    majSigmasPerf();

    const total = (s.meta && s.meta.total) || "?";
    const refs = s.meta && s.meta.refs;
    const infoRefs = refs ? ` — ${refs.ELU} (ELU) / ${refs.ELS} (ELS)` : "";
    const nbStab = s.stab ? Object.keys(s.stab).length : 0;
    const extractionEnCours = s.etat === "en_cours";
    // la stabilité (Excel) tourne EN PARALLÈLE et finit après l'extraction :
    // on continue de poller tant qu'elle n'est pas terminée
    const encoreActif = s.etat !== "erreur" && (extractionEnCours || !s.stab_fini);

    if (encoreActif) {
      if (extractionEnCours)
        message("msg-perf", `contraintes barre par barre : ${s.recus}/${total}${infoRefs}`);
      else
        message("msg-perf",
          `contraintes OK (${s.recus}/${total}) — stabilités EC3 : ${nbStab}/${s.recus}${infoRefs}`);
      jobPerf.timer = setTimeout(sonderPerf, 500);
    } else {
      $("btn-perf-stop").hidden = true;
      jobPerf = null;
      if (s.etat === "erreur") {
        message("msg-perf", `calcul interrompu : ${s.erreur || "erreur inconnue"}`, "erreur");
      } else {
        const arrete = s.etat === "arrete";
        message("msg-perf",
          `${arrete ? "arrêté" : "terminé"} — ${s.recus}/${total} barre(s), `
          + `${nbStab} stabilité(s)${infoRefs}`, arrete ? "" : "ok");
      }
      if (s.stab_erreur)
        message("msg-stab", `stabilités partielles : ${s.stab_erreur}`, "erreur");
    }
  } catch (e) {
    if (jobPerf && jobPerf.id === jobId) {
      message("msg-perf", e.message, "erreur");
      $("btn-perf-stop").hidden = true;
      jobPerf = null;
    }
  }
}

/* arrête le job en cours (bouton Arrêter, changement de modèle, relance) :
   le serveur coupe entre deux barres, la boucle de poll cesse */
async function arreterPerf() {
  if (!jobPerf) return;
  const id = jobPerf.id;
  if (jobPerf.timer) clearTimeout(jobPerf.timer);
  jobPerf = null;
  $("btn-perf-stop").hidden = true;
  try {
    await api("/api/performance/stop", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ job: id }),
    });
  } catch (e) { /* arrêt best-effort */ }
}

$("btn-perf-stop").addEventListener("click", async () => {
  $("btn-perf-stop").disabled = true;
  message("msg-perf", "arrêt demandé — fin de la barre en cours…");
  await arreterPerf();
});

/* ------------------------- stabilité EC3 des barres (classeur Predim) */
let barreChoisie = null;

function coefsStabilite() {
  /* coefficients de déversement (annexe F) + type de répartition de charge
     (tableau B.3, facteurs Cmy/Cmz/CmLT) saisis dans l'encadré */
  return { k: $("in-coef-k").value, kw: $("in-coef-kw").value,
           C1: $("in-coef-c1").value, C2: $("in-coef-c2").value,
           repartition: $("sel-repartition").value };
}

/* « Relancer l'analyse de stabilité » : la stabilité EC3 dépend du torseur ELU
   extrait de GSA, donc changer les coefficients de déversement impose de
   relancer le calcul en flux (perf + stabilité) avec les coefficients courants */
$("btn-stab").addEventListener("click", () => { if (dernierResume) chargerPerf(); });

/* sélection d'une barre dans le tableau -> bouton Excel */
$("table-perf").addEventListener("click", (ev) => {
  const tr = ev.target.closest("tbody tr[data-element]");
  if (!tr) return;
  const id = Number(tr.dataset.element);
  const corps = $("table-perf").querySelector("tbody");
  if (barreChoisie === id) {          // re-clic : désélection
    barreChoisie = null;
    tr.classList.remove("selectionnee");
    $("zone-excel-barre").hidden = true;
    return;
  }
  barreChoisie = id;
  corps.querySelectorAll("tr").forEach((r) => r.classList.toggle("selectionnee", r === tr));
  Vue3D.surligner([id]);
  $("lbl-barre-excel").textContent = `barre n°${id}`;
  $("btn-excel-barre").textContent = `Ouvrir la barre n°${id} dans Excel`;
  $("zone-excel-barre").hidden = false;
  $("recap-excel-barre").hidden = true;
  message("msg-excel-barre", "");
});

$("btn-excel-barre").addEventListener("click", async () => {
  if (barreChoisie === null) return;
  const btn = $("btn-excel-barre");
  btn.disabled = true;
  message("msg-excel-barre", "préparation du classeur Predim — copie, torseur, ouverture d'Excel…");
  try {
    const res = await api("/api/excel-barre", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ modele: $("sel-modele").value, element: barreChoisie, ...refsChoisies() }),
    });
    message("msg-excel-barre", `classeur ouvert dans Excel : ${res.fichier}`, "ok");
    $("recap-excel-barre").innerHTML = recapTorseur(res);
    $("recap-excel-barre").hidden = false;
  } catch (e) {
    message("msg-excel-barre", e.message, "erreur");
  } finally {
    btn.disabled = false;
  }
});

/* --------------------------------------------------- cible de l'optimisation */
function listesBarres(r) {
  /* listes GSA de barres (Member/Element) ; à défaut, pseudo-groupes construits
     depuis le champ "groupe" des éléments (maillage : 1 membre = 1 élément) */
  const listes = (r.listes || []).filter(
    (l) => (l.type === "Member" || l.type === "Element") && l.ids.length);
  if (listes.length) return listes;
  const parGroupe = new Map();
  r.elements.forEach((e) => {
    if (!parGroupe.has(e.groupe)) parGroupe.set(e.groupe, []);
    parGroupe.get(e.groupe).push(e.element);
  });
  if (parGroupe.size < 2) return [];
  return [...parGroupe.entries()].sort((a, b) => a[0] - b[0]).map(([grp, ids]) =>
    ({ nom: `Groupe ${grp}`, definition: ids.join(" "), ids }));
}

let modeCible = "barre";        // "barre" | "groupe" | "global"

$("onglets-cible").addEventListener("click", (ev) => {
  const btn = ev.target.closest(".onglet");
  if (!btn || btn.dataset.mode === modeCible) return;
  modeCible = btn.dataset.mode;
  $("onglets-cible").querySelectorAll(".onglet").forEach((o) =>
    o.classList.toggle("actif", o === btn));
  majCible();
});

function majCible() {
  /* repeuple le sélecteur selon le mode d'optimisation */
  if (!dernierResume) return;
  const sel = $("sel-cible");
  sel.innerHTML = "";
  sel.hidden = modeCible === "global";
  $("sel-algo").hidden = modeCible !== "global";
  $("opt-continuite").hidden = modeCible !== "global";
  if (modeCible === "global") {
    // ordre d'optimisation des familles (réordonnable par glisser-déposer) :
    // indices dans listesBarres, réinitialisés à chaque (re)construction
    ordreFamilles = listesBarres(dernierResume).map((_, i) => i);
  }
  // visibilité des options dépendant de l'algo (stabilité, départ, params, ordre)
  majUIAlgo();
  if (modeCible === "groupe") {
    listesBarres(dernierResume).forEach((l, i) =>
      sel.add(new Option(`${l.nom} — ${l.ids.length} barre(s)`, `g${i}`)));
    if (!sel.options.length)
      sel.add(new Option("aucun groupe dans le modèle", "", true, true));
  } else if (modeCible === "barre") {
    const sections = new Map(dernierResume.sections.map((s) => [s.section, s.profil]));
    dernierResume.elements.forEach((e) => {
      const profil = (sections.get(e.propriete) || "").replace(/^CAT \S+ /, "").replace(/ \d{8}$/, "");
      const L = e.longueur_m ? ` — ${fmt(e.longueur_m, 2)} m` : "";
      sel.add(new Option(`barre n°${e.element}${L} — ${profil || "prop. " + e.propriete}`, e.element));
    });
  }
  cibleChoisie();
}

function cibleCourante() {
  /* {elements, libelle} de la sélection (barre/groupe), ou null */
  if (!dernierResume) return null;
  const v = $("sel-cible").value;
  if (modeCible === "groupe") {
    const l = listesBarres(dernierResume)[Number(v.slice(1))];
    return l ? { elements: l.ids, libelle: l.nom } : null;
  }
  const id = Number(v);
  return Number.isInteger(id) && id > 0
    ? { elements: [id], libelle: `barre n°${id}` } : null;
}

let ordreFamilles = [];   // ordre d'optimisation (indices dans listesBarres)

function groupesGlobaux() {
  /* toutes les familles de barres, DANS L'ORDRE choisi (glisser-déposer) —
     l'ordre est transmis tel quel à l'algorithme (il change le résultat) */
  if (!dernierResume) return [];
  const listes = listesBarres(dernierResume);
  const ordre = ordreFamilles.length === listes.length
    ? ordreFamilles : listes.map((_, i) => i);
  return ordre.map((i) => ({ elements: listes[i].ids, libelle: listes[i].nom }));
}

function rendreOrdreFamilles() {
  /* liste réordonnable des familles (mode global) ; glisser-déposer HTML5.
     Inutile pour l'algo génétique (l'ordre des familles n'influence pas la
     recherche, contrairement à la descente par coordonnées) : on la masque. */
  const ol = $("ordre-familles");
  const listes = listesBarres(dernierResume);
  ol.hidden = modeCible !== "global" || listes.length < 2
           || $("sel-algo").value === "genetique";
  if (ol.hidden) { ol.innerHTML = ""; return; }
  ol.innerHTML = ordreFamilles.map((idx, rang) => {
    const l = listes[idx];
    return `<li draggable="true" data-idx="${idx}">
      <span class="rang">${rang + 1}</span>
      <span>${l.nom}</span>
      <span class="fam-nb">${l.ids.length} barre(s)</span>
      <span class="poignee" aria-hidden="true">⠿</span>
    </li>`;
  }).join("");
}

let ordreSource = null;   // indice (dans ordreFamilles) de l'élément glissé

$("ordre-familles").addEventListener("dragstart", (ev) => {
  const li = ev.target.closest("li");
  if (!li) return;
  ordreSource = [...li.parentNode.children].indexOf(li);
  li.classList.add("glisse");
  ev.dataTransfer.effectAllowed = "move";
});
$("ordre-familles").addEventListener("dragover", (ev) => {
  ev.preventDefault();                         // autorise le drop
  const li = ev.target.closest("li");
  if (!li) return;
  $("ordre-familles").querySelectorAll("li").forEach((r) =>
    r.classList.toggle("cible-drop", r === li));
});
$("ordre-familles").addEventListener("dragend", () => {
  $("ordre-familles").querySelectorAll("li").forEach((r) =>
    r.classList.remove("glisse", "cible-drop"));
});
$("ordre-familles").addEventListener("drop", (ev) => {
  ev.preventDefault();
  const li = ev.target.closest("li");
  if (!li || ordreSource === null) return;
  const cible = [...li.parentNode.children].indexOf(li);
  if (cible !== ordreSource) {
    const [dep] = ordreFamilles.splice(ordreSource, 1);   // déplace dans l'ordre
    ordreFamilles.splice(cible, 0, dep);
    rendreOrdreFamilles();
    cibleChoisie();
  }
  ordreSource = null;
});

function longueursCible(elements) {
  /* longueurs des barres de la cible (mode barre = elle-même, groupe = les
     siennes), ou de chaque famille (mode global) — pour l'indication du
     départ de l'algorithme escalade (h0 = L_barre/ratio, PAS la portée) */
  if (!dernierResume) return [];
  if (elements && elements.length) {
    const parId = new Map(dernierResume.elements.map((e) => [e.element, e.longueur_m]));
    return elements.map((id) => parId.get(id)).filter((l) => l != null);
  }
  return [];
}

function majIndicationDepart(elements) {
  /* exemple de gabarit de depart de l'escalade (h0 = L/ratio_hauteur, b0 =
     h0/ratio_largeur), calcule sur la PLUS COURTE et la PLUS LONGUE barre de
     la cible — jamais sur la portee globale du modele (une famille de
     barres courtes demarre petit, meme dans une grande structure) */
  const zone = $("indication-depart");
  if (!zone) return;
  const global = modeCible === "global";
  const longueurs = global
    ? groupesGlobaux().flatMap((g) => longueursCible(g.elements))
    : longueursCible(elements);
  const ratioH = parseFloat($("in-ratio-hauteur").value) || 20;
  const ratioB = parseFloat($("in-ratio-largeur").value) || 3;
  if (!longueurs.length) { zone.textContent = ""; return; }
  const h0cm = (L) => (L / ratioH) * 100;
  const b0cm = (L) => (h0cm(L) / ratioB);
  const avecLargeur = familleActive === "RHS";
  const exemple = (L) => `${fmt(L, 2)} m → h0 ${fmt(h0cm(L), 1)} cm`
    + (avecLargeur ? `, b0 ${fmt(b0cm(L), 1)} cm` : "");
  const lmin = Math.min(...longueurs), lmax = Math.max(...longueurs);
  zone.textContent = lmin === lmax
    ? `ex. barre ${exemple(lmin)}`
    : `ex. barres ${fmt(lmin, 2)}–${fmt(lmax, 2)} m → h0 ${fmt(h0cm(lmin), 1)}–${fmt(h0cm(lmax), 1)} cm`
      + (avecLargeur ? `, b0 ${fmt(b0cm(lmin), 1)}–${fmt(b0cm(lmax), 1)} cm` : "");
}

function cibleChoisie() {
  const pret = dernierResume && dernierResume.analysable
            && dernierResume.combinaisons_trouvees;
  if (modeCible === "global") {
    const gr = groupesGlobaux();
    Vue3D.surligner(gr.flatMap((g) => g.elements));
    const algo = $("sel-algo").selectedOptions[0];
    $("info-cible").textContent = gr.length
      ? `${algo ? algo.textContent : "algorithme"} sur les ${gr.length} familles de barres`
      : "aucune famille de barres dans le modèle";
    $("btn-lancer").disabled = !gr.length || !pret;
    majIndicationDepart(null);
    return;
  }
  const c = cibleCourante();
  Vue3D.surligner(c ? c.elements : []);
  $("info-cible").textContent = c && modeCible === "groupe"
    ? `critère ELU sur la barre la plus sollicitée des ${c.elements.length} barres du groupe`
    : "";
  $("btn-lancer").disabled = !c || !pret;
  majIndicationDepart(c ? c.elements : null);
}
function majUIAlgo() {
  /* affichage des options dépendant de l'algorithme choisi (mode global) :
       - génétique : panneau de paramètres ; PAS de classement des familles
         (sans effet), ni contrainte de stabilité (non gérée par le GA), ni
         continuité/départ (son propre boost initial en tient lieu) ;
       - force brute : case « départ sections max » et continuité (fenêtre
         d'espace de recherche entre familles mitoyennes) ;
       - escalade : classement des familles (ordre du parcours des passes),
         stabilité (boucle externe) comme force brute, et regles de depart
         (h0/b0, cf. params-escalade) — pas de continuité (pas géré). */
  const global = modeCible === "global";
  const algo = $("sel-algo").value;
  const genetique = algo === "genetique";
  const bruteForce = algo === "brut_force";
  const escalade = algo === "escalade";
  $("params-genetique").hidden = !(global && genetique);
  $("params-escalade").hidden = !(global && escalade);
  $("opt-ratio-largeur").hidden = familleActive !== "RHS";
  $("opt-stabilite").hidden = !(global && !genetique);
  $("opt-depart-max").hidden = !(global && bruteForce);
  $("opt-continuite").hidden = !(global && bruteForce);
  rendreOrdreFamilles();
  cibleChoisie();
}

$("sel-cible").addEventListener("change", cibleChoisie);
$("sel-algo").addEventListener("change", majUIAlgo);
$("chk-continuite").addEventListener("change", cibleChoisie);
$("chk-stabilite").addEventListener("change", cibleChoisie);
$("chk-depart-max").addEventListener("change", cibleChoisie);
$("in-ratio-hauteur").addEventListener("input", () => majIndicationDepart(cibleCourante()?.elements));
$("in-ratio-largeur").addEventListener("input", () => majIndicationDepart(cibleCourante()?.elements));

/* --------------------------------------------------------- dimensionnement */
$("btn-lancer").addEventListener("click", lancer);
function criteresCourants() {
  /* toutes les contraintes GSA sont toujours évaluées (max/min signés) */
  const hauteurMax = parseFloat($("in-hauteur-max").value);
  const epaisseurMax = parseFloat($("in-epaisseur-max").value);
  return {
    fy_Pa: $("in-fy").value * 1e6,
    coefficient: parseFloat($("in-coef").value),
    denominateur: parseFloat($("in-denom").value),
    hauteur_max_m: hauteurMax > 0 ? hauteurMax : undefined,
    epaisseur_max_mm: epaisseurMax > 0 ? epaisseurMax : undefined,
    ratio_hauteur_depart: parseFloat($("in-ratio-hauteur").value) || undefined,
    ratio_largeur_depart: parseFloat($("in-ratio-largeur").value) || undefined,
  };
}

function paramsGenetique() {
  /* paramètres de l'algo génétique (undefined si un autre algo est choisi) —
     les % sont convertis en fractions ; le serveur/module borne les valeurs */
  if ($("sel-algo").value !== "genetique") return undefined;
  const pct = (id, def) => {
    const v = parseFloat($(id).value);
    return (Number.isFinite(v) ? v : def) / 100;
  };
  const ent = (id, def) => {
    const v = parseInt($(id).value, 10);
    return Number.isFinite(v) ? v : def;
  };
  return {
    population: ent("ga-population", 50),
    generations: ent("ga-generations", 30),
    taux_mutation: pct("ga-mutation", 10),
    pourcentage_gagnants: pct("ga-gagnants", 30),
    boost_initial: pct("ga-boost", 20),
    taux_croisement: pct("ga-croisement", 90),
    elitisme: ent("ga-elitisme", 2),
    arret_stagnation: ent("ga-stagnation", 0),
  };
}

async function lancer() {
  const btn = $("btn-lancer");
  btn.disabled = true;
  const stop = suivreProgression(modeCible === "global" ? "global" : "dimensionner",
                                 "msg-dim");
  try {
    let res;
    if (modeCible === "global") {
      const groupes = groupesGlobaux();
      message("msg-dim", `optimisation globale (${groupes.length} familles × série ${familleActive})…`);
      res = await api("/api/global", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          modele: $("sel-modele").value,
          famille: familleActive,
          algo: $("sel-algo").value || undefined,
          groupes,
          continuite: $("chk-continuite").checked,
          stabilite: $("chk-stabilite").checked,
          depart_max: $("chk-depart-max").checked,
          genetique: paramsGenetique(),
          criteres: criteresCourants(),
        }),
      });
      stop();
      afficherResultatsGlobal(res);
      const boucles = res.stabilite
        ? ` · ${res.boucles_stabilite} boucle(s) stabilité EC3` : "";
      const unite = res.algo === "genetique"
        ? `${res.generations_faites} génération(s)` : `${res.passes} passe(s)`;
      message("msg-dim",
        `${res.analyses} analyse(s) GSA en ${unite} et ${res.duree_s} s${boucles}`
        + (res.converge ? ""
           : res.algo === "genetique" ? " — aucune configuration faisable trouvée"
           : " — NON convergé (affectations encore instables)"),
        res.converge ? "ok" : "erreur");
    } else {
      const cible = cibleCourante();
      if (!cible) { message("msg-dim", "aucune cible sélectionnée", "erreur"); return; }
      message("msg-dim", `analyse GSA de la série ${familleActive} sur ${cible.libelle}…`);
      res = await api("/api/dimensionner", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          modele: $("sel-modele").value,
          famille: familleActive,
          cible,
          criteres: criteresCourants(),
        }),
      });
      stop();
      afficherResultats(res);
      message("msg-dim", `${res.lignes.length} section(s) essayée(s) en ${res.duree_s} s`, "ok");
    }
    $("carte-res").hidden = false;
    $("carte-res").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (e) {
    stop();
    message("msg-dim", e.message, "erreur");
  } finally {
    stop();
    btn.disabled = false;
  }
}

function barreTaux(taux, limite = 1) {
  // limite : valeur de taux au-dela de laquelle le critere est depasse —
  // 1 pour l'ELS (fleche) ; le coefficient du critere (ex. 0.9) pour l'ELU,
  // desormais exprime par rapport a fy (235 MPa...) et non plus normalise a 1
  const pct = Math.min((taux / limite) * 100, 100);
  const couleur = taux > limite ? "var(--ko)" : taux > 0.85 * limite ? "var(--avert)" : "var(--vert-egis)";
  return `<span class="taux">${fmt(taux, 3)}
    <span class="barre"><i style="width:${pct}%;background:${couleur}"></i></span></span>`;
}
/* trio σ / mesure / barre d'un côté (traction = max > 0 sur les contraintes
   normales signées, compression = min < 0) ; tout le trio passe en GRAS quand
   c'est LUI qui est pris pour le taux ELU. Le côté absent (cible ne
   travaillant que dans l'autre sens) affiche des tirets. */
const gras = (txt, gouverne) => gouverne ? `<b>${txt}</b>` : txt;
const trioSigma = (v, mesure, elem, gouverne) => v == null
  ? `<td>—</td><td class="mono">—</td><td class="mono">—</td>`
  : `<td>${gras(fmt(v, 1), gouverne)}</td>
     <td class="mono">${gras(mesure ?? "—", gouverne)}</td>
     <td class="mono">${gras(elem != null ? "n°" + elem : "—", gouverne)}</td>`;
/* le trio gouverne-t-il le taux ELU ? (même mesure, même barre, même
   amplitude — sinon le gouvernant est p. ex. von Mises, hors trios) */
const gouvTrio = (l, cote) =>
  l[`sigma_${cote}_MPa`] != null
  && l[`mesure_${cote}`] === l.mesure
  && l[`element_${cote}`] === l.element_gouvernant
  && Math.abs(l[`sigma_${cote}_MPa`]) === l.sigma_MPa;
/* cellule Taux ELU : barre de taux (relatif a fy, limite = coefficient du
   critere, ex. 0.9) + mesure/barre prises pour le calcul */
const celTauxELU = (l, coefficient = 1) => `
  <td title="σ = ${fmt(l.sigma_MPa, 1)} MPa">${barreTaux(l.taux_ELU, coefficient)}
    <span class="note-gouv">${l.mesure ?? "—"} · n°${l.element_gouvernant ?? "—"}</span></td>`;
function afficherResultats(res) {
  $("defil-res").hidden = false;
  $("defil-global").hidden = true;
  $("graphe-global").hidden = true;      // graphe réservé à l'optimisation globale
  dernierRun = res.retenue
    ? { modele: $("sel-modele").value, famille: res.famille,
        section: res.retenue.section, cible: res.cible }
    : null;
  /* export Predim en mode torseur : la barre gouvernante de la section
     retenue, dans l'état analysé AVEC cette section (jamais les chargements
     extérieurs — l'outil doit marcher pour tout modèle) */
  dernierExcel = res.retenue && res.retenue.barre_gouvernante
    ? { libelle: (res.cible && res.cible.libelle) || `section ${res.retenue.section}`,
        nuance: res.nuance, barre: res.retenue.barre_gouvernante,
        section: res.retenue.section }
    : null;
  $("zone-excel").hidden = !dernierExcel;
  $("zone-appliquer").hidden = !res.retenue;
  $("recap-excel").hidden = true;
  message("msg-excel", "");
  message("msg-appliquer", "");
  $("btn-excel").textContent = dernierExcel
    ? `Ouvrir la barre n°${dernierExcel.barre.element} (${dernierExcel.section}) dans Excel`
    : "Ouvrir dans Excel";
  $("btn-appliquer").textContent = res.retenue
    ? `Charger ${res.retenue.section} dans le modèle` : "Charger dans le modèle";

  const surCible = res.cible ? ` pour ${res.cible.libelle}` : "";
  const gouvernant = res.retenue && res.cible && res.cible.elements.length > 1
    ? ` · barre la plus sollicitée : n°${res.retenue.element_gouvernant}` : "";
  $("banniere").innerHTML = res.retenue
    ? `<div class="banniere-ok">Section retenue${surCible} : <b>${res.retenue.section}</b>
       — taux ELU ${fmt(res.retenue.taux_ELU, 3)} · taux ELS ${fmt(res.retenue.taux_ELS, 3)}
       (${fmt(res.retenue.masse_kg_m, 1)} kg/m)${gouvernant}</div>`
    : `<div class="banniere-ko">Aucune section de la famille ${res.famille} ne satisfait les critères${surCible}.</div>`;
  $("rappel-criteres").textContent =
    (res.cible ? `Cible ${res.cible.libelle} (${res.cible.elements.length} barre(s)) · ` : "")
    + `Famille ${res.famille} · σ ≤ ${fmt(res.criteres.sigma_limite_MPa, 1)} MPa `
    + `(${Math.round(res.criteres.coefficient * 100)} % de ${res.criteres.fy_MPa} MPa) `
    + `sur l'enveloppe max/min de toutes les contraintes GSA · `
    + `flèche ≤ L/${res.criteres.denominateur} = ${fmt(res.criteres.fleche_limite_mm, 1)} mm `
    + `(L = ${fmt(res.portee_m, 2)} m) `
    + (res.criteres.hauteur_max_m ? `· h ≤ ${fmt(res.criteres.hauteur_max_m, 2)} m ` : "")
    + `· combinaisons ${res.refs.ELU} / ${res.refs.ELS}`;

  const corps = $("table-res").querySelector("tbody");
  corps.innerHTML = res.lignes.map((l, i) => `
    <tr class="${res.retenue && l.section === res.retenue.section ? "retenue" : ""}" data-ligne="${i}">
      <td>${l.section}</td>
      <td>${fmt(l.masse_kg_m, 1)}</td>
      ${trioSigma(l.sigma_max_MPa, l.mesure_max, l.element_max, gouvTrio(l, "max"))}
      ${trioSigma(l.sigma_min_MPa, l.mesure_min, l.element_min, gouvTrio(l, "min"))}
      ${celTauxELU(l, res.criteres.coefficient)}
      <td>${fmt(l.fleche_ELS_mm, 2)}</td>
      <td>${barreTaux(l.taux_ELS)}</td>
      <td class="cel-stab">…</td>
      <td class="cel-cas">…</td>
      <td class="${l.verdict === "OK" ? "verdict-ok" : "verdict-ko"}">${l.verdict}</td>
    </tr>`).join("");
  chargerStabilitesLignes(res);
}

/* ---- stabilité EC3 des lignes du dimensionnement barre/groupe (différé) ---- */
let jetonStabRes = 0;     // invalide les remplissages d'un run précédent

async function chargerStabilitesLignes(res) {
  const jeton = ++jetonStabRes;
  const corps = $("table-res").querySelector("tbody");
  const barres = res.lignes.map((l) => l.barre_gouvernante || null);
  if (!barres.some(Boolean)) {
    corps.querySelectorAll(".cel-stab, .cel-cas").forEach((c) => (c.textContent = "—"));
    message("msg-stab-res", "");
    return;
  }
  message("msg-stab-res",
    "vérification des stabilités EC3 de chaque section essayée (classeur Predim — Excel travaille en arrière-plan)…");
  const stop = suivreProgression("stabilite-lignes", "msg-stab-res");
  try {
    const s = await api("/api/stabilite-lignes", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ nuance: res.nuance, barres }),
    });
    stop();
    if (jeton !== jetonStabRes) return;      // un autre run a remplacé le tableau
    res.lignes.forEach((l, i) => {
      const tr = corps.querySelector(`tr[data-ligne="${i}"]`);
      if (!tr) return;
      const celTaux = tr.querySelector(".cel-stab");
      const celCas = tr.querySelector(".cel-cas");
      const r = s.resultats[i];
      if (r) {
        celTaux.textContent = fmt(r.taux_stabilite, 3);
        celTaux.classList.toggle("pire", r.taux_stabilite > 1);
        celCas.textContent = r.taux_stabilite > 0 ? r.cas : "—";
        celCas.title = Object.entries(r.taux || {})
          .map(([k, v]) => `${k} : ${v === null ? "—" : fmt(v, 3)}`).join("\n");
      } else {
        celTaux.textContent = "—";
        celCas.textContent = "—";
        celCas.title = s.erreurs[i] || "";
      }
    });
    message("msg-stab-res",
      `stabilités vérifiées en ${s.duree_s} s — classeur Predim, barre gouvernante à la section essayée, torseur ELU`, "ok");
  } catch (e) {
    stop();
    if (jeton !== jetonStabRes) return;
    corps.querySelectorAll(".cel-stab, .cel-cas").forEach((c) => (c.textContent = "—"));
    message("msg-stab-res", `stabilités indisponibles : ${e.message}`, "erreur");
  } finally {
    stop();
  }
}

function afficherResultatsGlobal(res) {
  $("defil-res").hidden = true;
  $("defil-global").hidden = false;
  dernierGlobal = res;                 // reference FIXE (graphe, historique, criteres)
  pointSelectionne = null;             // vue par defaut : le resultat retenu
  jetonPoint++;                        // invalide une eval de point en vol

  const bilanEls = `flèche ELS ${fmt(res.fleche_ELS_mm, 2)} mm (taux ${fmt(res.taux_ELS, 3)})`;
  const ko = res.groupes.filter((g) => g.verdict !== "OK");
  $("banniere").innerHTML = ko.length
    ? `<div class="banniere-ko">Famille(s) sans solution dans la série ${res.famille} :
       ${ko.map((g) => g.libelle).join(", ")} — même la plus grosse section dépasse.</div>`
    : `<div class="banniere-ok">Optimisation globale : <b>${fmt(res.masse_totale_kg, 1)} kg</b>
       d'acier pour les ${res.groupes.length} familles — ${bilanEls}</div>`;
  $("rappel-criteres").textContent =
    `${res.groupes.length} familles · série ${res.famille}`
    + (res.algo ? ` · algorithme ${res.algo}` : "")
    + (res.depart_max === false ? " · départ : config existante" : "")
    + (res.continuite ? " · continuité : barres mitoyennes à ±1 section" : "")
    + (res.stabilite ? ` · stabilité EC3 ≤ 1 (${res.boucles_stabilite} boucle(s))` : "")
    + ` · σ ≤ ${fmt(res.criteres.sigma_limite_MPa, 1)} MPa `
    + `(${Math.round(res.criteres.coefficient * 100)} % de ${res.criteres.fy_MPa} MPa) `
    + `sur l'enveloppe max/min de toutes les contraintes GSA · `
    + `flèche ≤ L/${res.criteres.denominateur} = ${fmt(res.criteres.fleche_limite_mm, 1)} mm `
    + `(L = ${fmt(res.portee_m, 2)} m) `
    + (res.criteres.hauteur_max_m ? `· h ≤ ${fmt(res.criteres.hauteur_max_m, 2)} m ` : "")
    + `· combinaisons ${res.refs.ELU} / ${res.refs.ELS}`;

  remplirTableGlobal(res);
  $("point-info").hidden = true;
  message("msg-point", "");
  afficherProgression(res);
}

/* remplit #table-global + les zones Excel/appliquer à partir d'un résultat
   (soit le résultat RETENU par l'algo, soit — cf. selectionnerPoint — la
   ré-évaluation d'un point précis du graphe de progression) ; source commune
   du clic sur une ligne (surlignage 3D + bouton Excel famille, cf. plus bas) */
let resTableActive = null;
function remplirTableGlobal(res, { point = false } = {}) {
  resTableActive = res;
  jetonStabRes++;                      // invalide un remplissage différé en cours
  message("msg-stab-res", "");
  dernierExcel = null;                 // l'export Predim passe par zone-excel-fam
  familleChoisie = null;
  $("zone-excel-fam").hidden = true;
  $("recap-excel-fam").hidden = true;
  message("msg-excel-fam", "");

  const ok = res.groupes.filter((g) => g.verdict === "OK");
  dernierRun = ok.length
    ? { modele: $("sel-modele").value, famille: res.famille,
        applications: ok.map((g) => ({ elements: g.elements,
                                       libelle: g.libelle, section: g.section })) }
    : null;
  $("zone-appliquer").hidden = !ok.length;
  $("zone-excel").hidden = true;          // pas d'export Predim en mode global
  $("recap-excel").hidden = true;
  message("msg-appliquer", "");
  $("btn-appliquer").textContent = point
    ? `Charger cette configuration (${ok.length} famille(s)) dans le modèle`
    : `Charger ${ok.length} famille(s) dans le modèle`;

  const celStab = (g) => {
    if (g.taux_stabilite == null)
      return `<td class="cel-stab-glob" title="${g.stabilite_erreur || res.stabilite_erreur || ""}">—</td>`;
    const detail = Object.entries(g.stabilite_detail || {})
      .map(([k, v]) => `${k} : ${v === null ? "—" : fmt(v, 3)}`).join("\n");
    return `<td class="cel-stab-glob ${g.taux_stabilite > 1 ? "pire" : ""}"
      title="${g.cas_stabilite || ""}\n${detail}">${fmt(g.taux_stabilite, 3)}</td>`;
  };
  // C1 (A+B max) / C2 (A-B min) : contrainte combinée déduite de N/My/Mz
  // (rapide, cf. algo_opti/_commun.py::_c1_c2_famille — même principe que
  // l'onglet Performances), pas les tables de contraintes GSA
  const celC1C2 = (v, elem) => v == null
    ? `<td>—</td><td class="mono">—</td>`
    : `<td>${fmt(v, 1)}</td><td class="mono">${elem != null ? "n°" + elem : "—"}</td>`;
  $("table-global").querySelector("tbody").innerHTML = res.groupes.map((g, i) => `
    <tr class="${g.verdict === "OK" ? "" : "depassee"}" data-groupe="${i}">
      <td>${g.libelle}</td>
      <td>${g.n_barres}</td>
      <td><b>${g.section}</b></td>
      ${celC1C2(g.C1_MPa, g.element_c1)}
      ${celC1C2(g.C2_MPa, g.element_c2)}
      <td>${barreTaux(g.taux_ELU, res.criteres.coefficient)}</td>
      <td>${barreTaux(g.taux_ELS)}</td>
      ${celStab(g)}
      <td>${fmt(g.masse_kg, 1)}</td>
      <td class="${g.verdict === "OK" ? "verdict-ok" : "verdict-ko"}">${g.verdict}</td>
    </tr>`).join("");
}

/* calcul de la stabilité EC3 (classeur Predim, une passe Excel par famille)
   pour la configuration ACTUELLEMENT AFFICHÉE (resTableActive : résultat
   retenu, ou point du graphe sélectionné, cf. remplirTableGlobal). Bouton
   manuel plutôt qu'automatique : la config d'un point survolé n'a pas de
   stabilité calculée par défaut (coûteux — une passe Excel par famille et
   par point — cf. app/server.py::evaluer_configuration_globale). */
$("btn-stab-global").addEventListener("click", async () => {
  if (!resTableActive) return;
  const btn = $("btn-stab-global");
  btn.disabled = true;
  message("msg-stab-global", "vérification EC3 (classeur Predim, Excel invisible)…");
  try {
    const barres = resTableActive.groupes.map((g) => g.barre_gouvernante || null);
    const rep = await api("/api/stabilite-lignes", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ nuance: resTableActive.nuance, barres }),
    });
    const lignes = $("table-global").querySelectorAll("tbody tr[data-groupe]");
    resTableActive.groupes.forEach((g, i) => {
      const r = rep.resultats[i];
      if (r) {
        g.taux_stabilite = r.taux_stabilite;
        g.cas_stabilite = r.cas;
        g.stabilite_detail = r.taux;
        delete g.stabilite_erreur;
      } else {
        g.stabilite_erreur = rep.erreurs[i] || "indisponible";
      }
      const cel = lignes[i] && lignes[i].querySelector(".cel-stab-glob");
      if (!cel) return;
      if (r) {
        cel.textContent = fmt(r.taux_stabilite, 3);
        cel.classList.toggle("pire", r.taux_stabilite > 1);
        cel.title = `${r.cas || ""}\n${Object.entries(r.taux || {})
          .map(([k, v]) => `${k} : ${v === null ? "—" : fmt(v, 3)}`).join("\n")}`;
      } else {
        cel.textContent = "—";
        cel.title = g.stabilite_erreur;
      }
    });
    message("msg-stab-global",
      `stabilités vérifiées en ${rep.duree_s} s — classeur Predim, barre gouvernante, torseur ELU`, "ok");
  } catch (e) {
    message("msg-stab-global", e.message, "erreur");
  } finally {
    btn.disabled = false;
  }
});

/* graphe de progression : masse totale (kg) de chaque configuration essayée */
function afficherProgression(res) {
  const hist = res.historique || [];
  if (!hist.length) { $("graphe-global").hidden = true; return; }
  redessinerGraphe();
  const nOk = hist.filter((p) => p.ok).length;
  const uniteAlgo = res.algo === "genetique"
    ? `${res.generations_faites} génération(s), population ${res.population}`
    : `${res.passes} passe(s)`;
  $("graphe-legende").innerHTML =
    `Progression — masse totale par configuration essayée : <b>${hist.length}</b> config. `
    + `(${nOk} faisable(s)) · ${res.analyses} analyse(s) GSA · ${uniteAlgo}. `
    + `Points <span style="color:var(--accent)">roses</span> = faisables, `
    + `gris = hors critères ; courbe <span style="color:var(--ok)">verte</span> = `
    + `meilleure masse faisable atteinte. Cliquer un point (ou naviguer au clavier `
    + `← →, une fois le graphe cliqué) affiche le détail de cette configuration `
    + `dans le tableau ci-dessous.`;
  $("graphe-global").hidden = false;
}

/* redessine le graphe à partir de dernierGlobal.historique + pointSelectionne
   (extrait pour être rappelable seul lors d'une sélection, sans reconstruire
   la légende ni rien d'autre) */
function redessinerGraphe() {
  const hist = (dernierGlobal && dernierGlobal.historique) || [];
  $("graphe-svg").innerHTML = dessinerProgression(hist, pointSelectionne);
}

// dimensions du graphe SVG, partagées avec le clic de sélection (cf.
// selectionnerPointDepuisClic) qui doit inverser X(i) -> i
const GRAPHE_DIMS = { W: 720, H: 240, mL: 58, mR: 14, mT: 14, mB: 28 };

function dessinerProgression(hist, selection = null) {
  /* SVG simple, sans dépendance : X = indice de configuration, Y = masse (kg).
     Points colorés selon faisabilité + courbe de la meilleure masse faisable. */
  const { W, H, mL, mR, mT, mB } = GRAPHE_DIMS;
  const N = hist.length;
  const masses = hist.map((p) => p.masse);
  const dmn = Math.min(...masses), dmx = Math.max(...masses);
  let lo = dmn, hi = dmx;
  if (lo === hi) { lo -= 1; hi += 1; }
  const pad = (hi - lo) * 0.08; lo -= pad; hi += pad;
  const X = (i) => mL + (N <= 1 ? 0 : (i / (N - 1)) * (W - mL - mR));
  const Y = (m) => H - mB - ((m - lo) / (hi - lo)) * (H - mT - mB);

  // meilleure masse faisable atteinte (min courant) -> courbe de progression
  let best = Infinity;
  const bestPts = [];
  hist.forEach((p, i) => {
    if (p.ok && p.masse < best) best = p.masse;
    if (best < Infinity) bestPts.push([i, best]);
  });

  // sous-échantillonnage des points pour ne pas surcharger le rendu
  const step = Math.max(1, Math.ceil(N / 600));
  let dots = "";
  for (let i = 0; i < N; i += step) {
    const p = hist[i];
    // infobulle native (survol) : sections essayées par famille à ce point,
    // telles que renvoyées par l'algo (cf. algo_opti/*.py, champ "config")
    const detailConfig = p.config
      ? Object.entries(p.config).map(([lib, sec]) => `${lib} = ${sec}`).join("\n")
      : "";
    const infobulle = `config. ${i + 1}/${N} · ${fmt(p.masse, 1)} kg · `
      + `${p.ok ? "faisable" : "hors critères"}`
      + (detailConfig ? `\n${detailConfig}` : "");
    dots += `<circle class="${p.ok ? "pt-ok" : "pt-ko"}" data-i="${i}" cx="${X(i).toFixed(1)}" `
          + `cy="${Y(p.masse).toFixed(1)}" r="2"><title>${echapperXml(infobulle)}</title></circle>`;
  }
  // marqueur du point sélectionné (indépendant du sous-échantillonnage
  // ci-dessus : toujours positionné sur l'index exact, même si celui-ci n'a
  // pas de <circle> propre, cf. selectionnerPoint)
  const marqueur = (selection != null && hist[selection])
    ? `<circle class="pt-selection" cx="${X(selection).toFixed(1)}" `
      + `cy="${Y(hist[selection].masse).toFixed(1)}" r="5"/>`
    : "";
  const bestPath = bestPts.length >= 2
    ? `<path class="ligne-best" d="M${bestPts.map(([i, m]) =>
        `${X(i).toFixed(1)},${Y(m).toFixed(1)}`).join(" L")}"/>`
    : "";

  let grille = "";
  [dmx, (dmn + dmx) / 2, dmn].forEach((t) => {
    const y = Y(t).toFixed(1);
    grille += `<line class="grille" x1="${mL}" y1="${y}" x2="${W - mR}" y2="${y}"/>`
            + `<text class="etiquette" x="${mL - 6}" y="${(+y + 3).toFixed(1)}" `
            + `text-anchor="end">${Math.round(t)}</text>`;
  });
  const axes = `<line class="axe" x1="${mL}" y1="${mT}" x2="${mL}" y2="${H - mB}"/>`
             + `<line class="axe" x1="${mL}" y1="${H - mB}" x2="${W - mR}" y2="${H - mB}"/>`;
  const xlab = `<text class="etiquette" x="${mL}" y="${H - 8}">0</text>`
             + `<text class="etiquette" x="${W - mR}" y="${H - 8}" text-anchor="end">${N - 1}</text>`
             + `<text class="etiquette" x="${(mL + W - mR) / 2}" y="${H - 8}" `
             + `text-anchor="middle">configuration essayée</text>`;
  return `<svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg" role="img" `
       + `aria-label="progression de la masse totale par configuration — `
       + `cliquer un point pour voir son détail">`
       + `${grille}${axes}${dots}${bestPath}${marqueur}${xlab}</svg>`;
}

/* sélection d'une famille dans le tableau global -> 3D + bouton Excel
   (résultat retenu OU configuration du graphe en cours de consultation,
   cf. resTableActive alimenté par remplirTableGlobal) */
let dernierGlobal = null;      // dernière réponse /api/global (référence FIXE : graphe/historique/critères)
let familleChoisie = null;     // indice dans resTableActive.groupes

$("table-global").addEventListener("click", (ev) => {
  const tr = ev.target.closest("tbody tr[data-groupe]");
  if (!tr || !resTableActive) return;
  const i = Number(tr.dataset.groupe);
  const corps = $("table-global").querySelector("tbody");
  if (familleChoisie === i) {          // re-clic : désélection
    familleChoisie = null;
    tr.classList.remove("selectionnee");
    $("zone-excel-fam").hidden = true;
    Vue3D.surligner(resTableActive.groupes.flatMap((g) => g.elements));
    return;
  }
  familleChoisie = i;
  corps.querySelectorAll("tr").forEach((r) => r.classList.toggle("selectionnee", r === tr));
  const g = resTableActive.groupes[i];
  Vue3D.surligner(g.elements);
  const b = g.barre_gouvernante;
  $("lbl-fam-excel").textContent = `${g.libelle} — barre n°${g.element_gouvernant ?? "?"}`;
  $("btn-excel-fam").textContent = b
    ? `Ouvrir la barre n°${b.element} (${g.section}) dans Excel` : "Ouvrir dans Excel";
  $("btn-excel-fam").disabled = !b;
  $("zone-excel-fam").hidden = false;
  $("recap-excel-fam").hidden = true;
  message("msg-excel-fam", b ? "" : "torseur de la barre gouvernante indisponible");
});

$("btn-excel-fam").addEventListener("click", async () => {
  if (familleChoisie === null || !resTableActive) return;
  const g = resTableActive.groupes[familleChoisie];
  if (!g.barre_gouvernante) return;
  const btn = $("btn-excel-fam");
  btn.disabled = true;
  message("msg-excel-fam", "préparation du classeur Predim — copie, torseur, ouverture d'Excel…");
  try {
    const res = await api("/api/excel-famille", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ libelle: g.libelle, nuance: resTableActive.nuance,
                             barre: g.barre_gouvernante }),
    });
    message("msg-excel-fam", `classeur ouvert dans Excel : ${res.fichier}`, "ok");
    $("recap-excel-fam").innerHTML = recapTorseur(res);
    $("recap-excel-fam").hidden = false;
  } catch (e) {
    message("msg-excel-fam", e.message, "erreur");
  } finally {
    btn.disabled = false;
  }
});

/* --------------------------- navigation dans le graphe de progression ---
   clic sur un point (ou flèches ← → une fois le graphe cliqué) : affiche le
   détail de CETTE configuration (section par famille) dans #table-global —
   aperçu immédiat depuis l'historique déjà connu côté page, puis, après un
   court débounce (évite de bombarder GSA pendant une navigation rapide au
   clavier), une ré-évaluation complète via /api/global/config (contraintes,
   taux, barre gouvernante -> boutons Charger/Excel adaptés à ce point). */
let pointSelectionne = null;   // indice dans dernierGlobal.historique, ou null = résultat retenu
let jetonPoint = 0;            // invalide une éval de point en vol si la sélection change
let timerPoint = null;

function selectionnerPoint(i) {
  const hist = (dernierGlobal && dernierGlobal.historique) || [];
  if (!hist.length) return;
  pointSelectionne = Math.max(0, Math.min(hist.length - 1, i));
  redessinerGraphe();
  afficherApercuPoint();
  clearTimeout(timerPoint);
  timerPoint = setTimeout(chargerConfigPoint, 250);
}

function deselectionnerPoint() {
  if (pointSelectionne === null) return;
  pointSelectionne = null;
  jetonPoint++;                      // invalide une éval de point en vol
  clearTimeout(timerPoint);
  redessinerGraphe();
  $("point-info").hidden = true;
  message("msg-point", "");
  remplirTableGlobal(dernierGlobal);   // retour au résultat retenu
}

/* aperçu instantané (avant même la ré-évaluation GSA) à partir des données
   déjà connues côté page : masse, faisabilité globale et section par famille
   (cf. champ "config" de l'historique, alimenté par algo_opti/*.py) */
function afficherApercuPoint() {
  const hist = dernierGlobal.historique;
  const p = hist[pointSelectionne];
  const detail = Object.entries(p.config || {}).map(([lib, sec]) => `${lib} = ${sec}`).join(" · ");
  $("point-info").hidden = false;
  $("point-info").innerHTML =
    `Configuration <b>#${pointSelectionne + 1}/${hist.length}</b> — ${fmt(p.masse, 1)} kg — `
    + `${p.ok ? "faisable" : "hors critères"}${detail ? " — " + detail : ""} `
    + `<button id="btn-point-retour" type="button">↩ résultat retenu</button>`;
  $("btn-point-retour").addEventListener("click", deselectionnerPoint);
  message("msg-point", "calcul détaillé de cette configuration (analyse GSA)…");
}

/* ré-évaluation complète (contraintes, taux, barre gouvernante) du point
   actuellement sélectionné, via une seule analyse GSA (/api/global/config) */
async function chargerConfigPoint() {
  if (pointSelectionne === null || !dernierGlobal) return;
  const p = dernierGlobal.historique[pointSelectionne];
  const jeton = ++jetonPoint;
  try {
    const res = await api("/api/global/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        modele: $("sel-modele").value,
        famille: dernierGlobal.famille,
        criteres: {
          fy_Pa: dernierGlobal.criteres.fy_MPa * 1e6,
          coefficient: dernierGlobal.criteres.coefficient,
          denominateur: dernierGlobal.criteres.denominateur,
          hauteur_max_m: dernierGlobal.criteres.hauteur_max_m,
        },
        groupes: dernierGlobal.groupes.map((g) => ({ elements: g.elements, libelle: g.libelle })),
        config: p.config,
      }),
    });
    if (jeton !== jetonPoint) return;   // sélection changée entre-temps
    remplirTableGlobal(res, { point: true });
    message("msg-point", "");
  } catch (e) {
    if (jeton !== jetonPoint) return;
    message("msg-point", e.message, "erreur");
  }
}

// clic sur un point du graphe : sélectionne le point le plus proche en X
// (marche même sur les graphes sous-échantillonnés, où tous les points
// n'ont pas leur propre <circle>, cf. dessinerProgression)
$("graphe-svg").addEventListener("click", (ev) => {
  const hist = (dernierGlobal && dernierGlobal.historique) || [];
  if (!hist.length) return;
  const svg = ev.currentTarget.querySelector("svg");
  if (!svg) return;
  const pt = svg.createSVGPoint();
  pt.x = ev.clientX; pt.y = ev.clientY;
  const { x } = pt.matrixTransform(svg.getScreenCTM().inverse());
  const { W, mL, mR } = GRAPHE_DIMS;
  const N = hist.length;
  const ratio = (x - mL) / (W - mL - mR);
  selectionnerPoint(Math.round(ratio * (N - 1)));
});

// navigation clavier ← → une fois le graphe focalisé (clic ou tabulation) ;
// démarre sur le premier point si aucune sélection en cours
$("graphe-global").addEventListener("keydown", (ev) => {
  if (ev.key !== "ArrowLeft" && ev.key !== "ArrowRight") return;
  const hist = (dernierGlobal && dernierGlobal.historique) || [];
  if (!hist.length) return;
  ev.preventDefault();
  const base = pointSelectionne ?? 0;
  selectionnerPoint(base + (ev.key === "ArrowRight" ? 1 : -1));
});

/* ------------------------------------------------- application au modèle */
$("btn-appliquer").addEventListener("click", appliquer);
async function appliquer() {
  if (!dernierRun) return;
  const btn = $("btn-appliquer");
  btn.disabled = true;
  message("msg-appliquer", `application de ${dernierRun.section} au modèle…`);
  try {
    const res = await api("/api/appliquer", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(dernierRun),
    });
    const detail = res.applications.map((a) =>
      `${a.libelle} → ${a.section}`).join(" · ");
    message("msg-appliquer", `${detail} — modèle ${res.modele} enregistré`, "ok");
    await chargerResume(true);       // reflète les nouvelles sections, garde les résultats
  } catch (e) {
    message("msg-appliquer", e.message, "erreur");
  } finally {
    btn.disabled = false;
  }
}

/* --------------------------------------------- vérification Predim (Excel) */
/* mode torseur UNIQUEMENT : le classeur reçoit l'enveloppe ELU des efforts de
   la barre gouvernante à 0/25/50/75/100 % (comme l'onglet Performances),
   jamais les chargements extérieurs du modèle */
$("btn-excel").addEventListener("click", ouvrirExcel);
async function ouvrirExcel() {
  if (!dernierExcel) return;
  const btn = $("btn-excel");
  btn.disabled = true;
  $("recap-excel").hidden = true;
  message("msg-excel", "préparation du classeur Predim — copie, torseur, ouverture d'Excel…");
  try {
    const res = await api("/api/excel-famille", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(dernierExcel),
    });
    message("msg-excel", `classeur ouvert dans Excel : ${res.fichier}`, "ok");
    $("recap-excel").innerHTML = recapTorseur(res);
    $("recap-excel").hidden = false;
  } catch (e) {
    message("msg-excel", e.message, "erreur");
  } finally {
    btn.disabled = false;
  }
}

/* ------------------------------------------- vue 3D : sections + capture */
let sectionsAffichees = false;

function reinitialiserOutils3D() {
  sectionsAffichees = false;
  $("btn-sections-3d").disabled = false;
  $("btn-sections-3d").textContent = "Afficher les sections";
  $("btn-capture-3d").disabled = false;
  message("msg-sections-3d", "");
}

$("btn-sections-3d").addEventListener("click", async () => {
  const btn = $("btn-sections-3d");
  if (Vue3D.sectionsChargees()) {
    // géométrie déjà en mémoire : bascule instantanée, pas de nouvel appel
    sectionsAffichees = Vue3D.basculerSections(!sectionsAffichees);
    btn.textContent = sectionsAffichees ? "Masquer les sections" : "Afficher les sections";
    return;
  }
  btn.disabled = true;
  message("msg-sections-3d",
    "géométrie réelle du modèle (sections extrudées, calcul GSA sans ouvrir son interface)…");
  try {
    const geometrie = await api(`/api/vue-sections?modele=${encodeURIComponent($("sel-modele").value)}`);
    Vue3D.chargerSections(geometrie);
    sectionsAffichees = Vue3D.basculerSections(true);
    btn.textContent = "Masquer les sections";
    message("msg-sections-3d", "");
  } catch (e) {
    message("msg-sections-3d", e.message, "erreur");
  } finally {
    btn.disabled = false;
  }
});

$("btn-capture-3d").addEventListener("click", () => {
  const url = Vue3D.exporterImage();
  if (!url) return;
  const a = document.createElement("a");
  a.href = url;
  a.download = `${($("sel-modele").value || "modele").replace(/\.gwb$/i, "")}_vue3d.png`;
  document.body.appendChild(a);
  a.click();
  a.remove();
});

Vue3D.attacher($("vue3d"));
init();
