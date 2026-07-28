# -*- coding: utf-8 -*-
"""
Cree une COPIE du classeur Predim dont les onglets HE et RHS sont remplis avec
les sections issues de GSA (catalogues/), garantissant que TOUTE section que
l'optimiseur essaie (extraite de GSA) est aussi verifiable en stabilite EC3
dans le classeur — sans le filtrage a l'intersection GSA∩Excel qui limitait
avant les tubulaires a ~20 % du catalogue GSA (cf. catalogues/CHS.csv, RHS.csv,
SHS.csv, devenus obsoletes pour HE/RHS des lors que ce script est utilise).

CHIRURGIE ZIP/XML, PAS D'AUTOMATISATION EXCEL : piloter Excel par COM pour
ECRIRE et ENREGISTRER un fichier echoue silencieusement sur ce poste (le
classeur s'ouvre toujours ReadOnly=True quels que soient les parametres
passes, meme un classeur neuf jamais lie a un fichier — restriction machine,
pas un bug de ce script ; SaveAs declenche une boite de dialogue qui bloque
en mode invisible). Ce script modifie donc directement les entrees XML des
onglets HE (sheet8.xml) et RHS (sheet10.xml) DANS L'ARCHIVE ZIP .xlsm, sans
lancer Excel — uniquement les <row> de donnees (colonnes A a AA), le reste du
fichier (VBA, images, styles, autres onglets, calcChain...) reste OCTET POUR
OCTET identique au maitre. C'est UNIQUEMENT ce script qui touche au fichier ;
la lecture/le calcul (excel_bridge/bridge.py, via COM) est INCHANGEE et
continue de fonctionner sur le resultat (deja verifie : taux EC3 identiques
au maitre a 10 decimales pres sur des sections communes).

STRUCTURE DECOUVERTE DANS LE MAITRE (a respecter) :
  - Onglet "HE" (libelle interne "HE + UB") : lignes 3-112 = HE, 113-137 = HL,
    138 = separateur vide, 139-206 = UB (poutrelles britanniques — FAMILLE A
    NE JAMAIS TOUCHER, non couverte par ce script). Les 72 sections HEA/HEB/HEM
    de GSA sont ecrites en lignes 3-74 ; les lignes 75-137 (ancien HE-AA/HL
    devenu obsolete) sont VIDEES (colonnes A/B seulement — cf. plus bas)
    SANS EMPIETER sur la ligne 138 ni le bloc UB.
  - Onglet "RHS" : lignes 3-273 = RHS/SHS (les carres y sont deja nommes
    "RHS...", pas "SHS..." — convention du classeur, reprise ici), 274+ deja
    vide. Les 572 sections RHS+SHS de GSA (dedoublonnees) sont ecrites en
    lignes 3-574 ; aucune famille tierce a menager sur cet onglet.

Colonnes ECRITES (A..AA) : A=index (cle du VLOOKUP par la feuille Calcul),
B=designation (cherchee par bridge.py resolve_profile_index), puis les
colonnes de GEOMETRIE/MODULES lues par Calcul (h, b, tw, tf, A, Iy, Wy, Wply,
iy, Iz, Wz, Wplz, iz, It, r). Les colonnes de CONCEPTION EC3 (h/b, aires de
cisaillement Avz/Avy, courbes de flambement, moments statiques, Iw, masse
RHS) sont des FORMULES du classeur qui se recalculent depuis la geometrie :
recopiees (repere ligne recalee) depuis la 1re ligne de donnees du gabarit,
jamais saisies en valeur. Colonne Ss (non lue par Calcul) laissee vide.

Sortie : reference/excels/Predim_poutre acier_v3_GSA.xlsm (le maitre v3 reste
intact). Mettre a jour excel_bridge/config/io_map.json (workbookRelativePath)
pour pointer dessus. A relancer si sectlib.db3 (catalogues) ou le maitre change.

Usage :
    venv\\Scripts\\python.exe excel_bridge\\scripts\\injecter_sections_gsa.py
"""
from __future__ import annotations

import csv
import re
import shutil
import sys
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from excel_bridge.bridge import _normaliser_designation, load_json

IO_MAP = ROOT / "excel_bridge" / "config" / "io_map.json"
CATALOGUES = ROOT / "catalogues"
SORTIE = ROOT / "reference" / "excels" / "Predim_poutre acier_v3_GSA.xlsm"

LIGNE_DATA = 3               # les donnees commencent a la ligne 3 (1-2 = entetes)
COL_MAX = 27                 # colonnes A..AA (au-dela : hors du perimetre ecrit)

# (fichier dans l'archive, plage a effacer [A:B seulement] APRES la zone
#  ecrite — bloc obsolete a ne pas confondre avec une autre famille voisine)
ONGLETS = {
    "HE":  {"fichier": "xl/worksheets/sheet8.xml",
           "effacer_jusqua": 137},     # 138 = separateur, 139+ = UB : intact
    "RHS": {"fichier": "xl/worksheets/sheet10.xml",
           "effacer_jusqua": None},    # pas de famille tierce sur cet onglet
}

# colonne Excel (1-based) -> (champ CSV, facteur SI -> unite classeur mm/mm²/...)
# n'est ecrit que si la colonne n'est PAS une formule dans le classeur (les
# colonnes formule — Avz, courbes, RHS: masse/rayon... — se recalculent seules)
COLONNES_DONNEES = {
    4:  ("masse_kg_m", 1.0),     # D  g   kg/m  (formule pour RHS -> ignoree)
    5:  ("h_m", 1e3),            # E  h   mm
    6:  ("b_m", 1e3),            # F  b   mm
    7:  ("tw_m", 1e3),           # G  tw  mm
    8:  ("tf_m", 1e3),           # H  tf  mm (RHS/SHS : tf vide -> = tw)
    9:  ("aire_m2", 1e6),        # I  A   mm²
    10: ("Iyy_m4", 1e12),        # J  Iy  mm⁴
    11: ("Wel_y_m3", 1e9),       # K  Wy  mm³
    12: ("Wpl_y_m3", 1e9),       # L  Wply mm³
    13: ("iy_m", 1e3),           # M  iy  mm
    15: ("Izz_m4", 1e12),        # O  Iz  mm⁴
    16: ("Wel_z_m3", 1e9),       # P  Wz  mm³
    17: ("Wpl_z_m3", 1e9),       # Q  Wplz mm³
    18: ("iz_m", 1e3),           # R  iz  mm
    20: ("J_m4", 1e12),          # T  It  mm⁴
    23: ("r_m", 1e3),            # W  r   mm
}


def _col_lettre(n: int) -> str:
    """1 -> 'A', 27 -> 'AA'."""
    lettres = ""
    while n:
        n, r = divmod(n - 1, 26)
        lettres = chr(65 + r) + lettres
    return lettres


def _charger(fichier: Path, regex: str | None = None) -> list[dict]:
    with fichier.open(encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    if regex:
        rows = [r for r in rows if re.fullmatch(regex, r["nom"])]
    return rows


def _sections_he() -> list[dict]:
    rows = _charger(CATALOGUES / "HE-AM.csv", r"HE\d+[ABM]")
    rows.sort(key=lambda r: float(r["masse_kg_m"]))
    return rows


def _sections_rhs() -> list[dict]:
    """EN-RHS + EN-SHS fusionnes, dedoublonnes par nom normalise (ex. 'x4' ==
    'x4.0'), tries par masse croissante. Les carres (SHS) sont RENOMMES avec
    le prefixe 'RHS' : c'est la convention du classeur (ex. 'RHS200x200x5,0'
    y designe deja un tube carre) — app/server.py::_profil_predim applique la
    meme traduction de prefixe cote lecture (SHS -> onglet/designation RHS)."""
    rows = _charger(CATALOGUES / "EN-RHS.csv") + [
        {**r, "nom": "RHS" + r["nom"][3:]} for r in _charger(CATALOGUES / "EN-SHS.csv")]
    vus, uniques = set(), []
    for r in sorted(rows, key=lambda r: float(r["masse_kg_m"])):
        cle = _normaliser_designation(r["nom"])
        if cle not in vus:
            vus.add(cle)
            uniques.append(r)
    return uniques


def _sections_rhs_app() -> list[dict]:
    """EN-RHS + EN-SHS fusionnes pour le catalogue COTE APPLICATION
    (config/familles.json "RHS", lu par scripts/dimensionner.py::serie_sections)
    — SANS renommage SHS->RHS (contrairement a `_sections_rhs`, specifique a
    l'ecriture Excel) : les designations SHS restent 'SHS...' (naming GSA
    natif) et c'est `app/server.py::_profil_predim` qui traduit le prefixe
    vers 'RHS' au moment de la verification Excel — deja en place et teste,
    aucun changement necessaire cote serveur. Pas de dedoublonnage ici (a la
    difference de `_sections_rhs`) : quelques carres EN-RHS et EN-SHS peuvent
    coexister sous deux noms pour la meme geometrie (~10 sur 580+), sans
    consequence — doublon inoffensif pour l'optimisation (deux essais
    identiques), chacun se resout correctement cote classeur."""
    rows = _charger(CATALOGUES / "EN-RHS.csv") + _charger(CATALOGUES / "EN-SHS.csv")
    rows.sort(key=lambda r: float(r["masse_kg_m"]))
    return rows


def _exporter_catalogue_app(nom: str, sections: list[dict]) -> None:
    """Ecrit catalogues/{nom}.csv (memes colonnes que les catalogues source),
    consomme par scripts/dimensionner.py::serie_sections (dimensionnement et
    algo_opti/) — TOUJOURS le meme jeu de sections que celui injecte dans le
    classeur Excel (cf. main()), pour que optimisation et verification EC3
    restent coherentes."""
    chemin = CATALOGUES / f"{nom}.csv"
    with chemin.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(sections[0].keys()))
        w.writeheader()
        w.writerows(sections)
    print(f"  {chemin.name} : {len(sections)} section(s) (catalogue application)")


def _valeur(sec: dict, col: int) -> float | None:
    champ, facteur = COLONNES_DONNEES[col]
    brut = sec.get(champ)
    if not brut and col == 8:            # tf vide (tube) -> paroi uniforme = tw
        brut = sec.get("tw_m")
    if not brut:
        return None
    return round(float(brut) * facteur, 6)


# reference de cellule dont la LIGNE est EXACTEMENT LIGNE_DATA (ex. E3, F3,
# C3...) : ces refs suivent la ligne quand on "recopie" une formule modele
# vers une autre ligne. Les refs a ligne fixe ($…$2) ou nommees (fy) ne
# doivent PAS bouger (la regex ne matche que la ligne LIGNE_DATA precisement).
_REF_LIGNE = re.compile(rf'(\$?[A-Z]{{1,3}})(\$?){LIGNE_DATA}\b')


def _decaler(formule: str, ligne: int) -> str:
    """Formule modele (references vers la ligne LIGNE_DATA) recalee vers
    `ligne` — equivalent d'une recopie Excel (refs relatives ajustees)."""
    return _REF_LIGNE.sub(lambda mo: f"{mo.group(1)}{mo.group(2)}{ligne}", formule)


# ------------------------------------------------------------ manipulation XML
def _lire_lignes(sheetdata_inner: str) -> dict[int, str]:
    """{numero_ligne: XML complet de la <row>} pour toutes les lignes presentes
    dans le fragment <sheetData>...</sheetData> (gere les <row .../> vides ET
    les <row ...>...</row> avec cellules, y compris des <c .../> auto-fermees
    a l'interieur — cf. commentaire dans le corps de la fonction)."""
    lignes = {}
    # le groupe alterne : soit la ligne s'auto-ferme ('/>' immediatement apres
    # les attributs de <row>), soit elle contient du texte jusqu'a </row> —
    # [^>]*? (sans '>') borne precisement la fin des ATTRIBUTS de <row>, donc
    # un </c ... /> a l'interieur du contenu (matche par .*? apres le '>' de
    # <row>) ne peut pas etre confondu avec la fin de <row> elle-meme.
    for m in re.finditer(r'<row\b[^>]*?(?:/>|>.*?</row>)', sheetdata_inner, re.S):
        r = int(re.search(r'\br="(\d+)"', m.group(0)).group(1))
        lignes[r] = m.group(0)
    return lignes


_REF_CELL_LIGNE = re.compile(r'(\$?[A-Z]{1,3})(\$?)(\d+)\b')


def _decaler_general(formule: str, ligne_source: int, ligne_cible: int) -> str:
    """Formule recalee de `ligne_source` vers `ligne_cible` : les references a
    ligne RELATIVE egale a `ligne_source` sont deplacees vers `ligne_cible`
    (references a ligne ABSOLUE $N ou vers une autre ligne : inchangees)."""
    def repl(mo):
        col, dollar, ligne = mo.group(1), mo.group(2), int(mo.group(3))
        if dollar or ligne != ligne_source:
            return mo.group(0)
        return f"{col}{ligne_cible}"
    return _REF_CELL_LIGNE.sub(repl, formule)


def _deplier_formules_partagees(sheetdata_inner: str) -> str:
    """Convertit TOUTES les formules partagees (<f t="shared" ref=... si=N>) en
    formules NORMALES independantes, sur toute la feuille — a faire EN PREMIER,
    avant toute autre modification. Une formule partagee factorise le texte
    d'une formule sur une plage (le "maitre" le porte, les "suiveuses" n'ont
    qu'un <f t="shared" si="N"/> vide qui s'y refere) : si le maitre est ensuite
    modifie ou supprime (ce que fait ce script), les suiveuses pointent dans le
    vide et le classeur devient illisible par Excel — deja rencontre lors de la
    mise au point de ce script."""
    # meme piege que dans le remplacement (cf. plus bas) : le [^>]* final DOIT
    # exclure '/' — sinon il matche aussi les cellules "suiveuses" auto-
    # fermantes (<f t="shared" si="N"/>, sans texte), en avalant le '/' puis en
    # capturant n'importe quel contenu jusqu'au PROCHAIN </f> trouve (parfois
    # tres loin, dans une cellule sans rapport) comme "formule" du maitre.
    maitres: dict[str, tuple[int, str]] = {}     # si -> (ligne_maitre, formule)
    for m in re.finditer(r'<c r="[A-Z]+(\d+)"[^>]*>\s*'
                         r'<f t="shared"[^>]*\bsi="(\d+)"[^/>]*>(.*?)</f>',
                         sheetdata_inner, re.S):
        ligne, si, texte = int(m.group(1)), m.group(2), m.group(3)
        maitres.setdefault(si, (ligne, texte))    # 1re occurrence = le maitre

    def remplacer(m: re.Match) -> str:
        ref, attrs, si = m.group("ref"), m.group("attrs"), m.group("si")
        ligne_cell = int(re.search(r"\d+", ref).group())
        ligne_maitre, texte = maitres[si]
        formule = _decaler_general(texte, ligne_maitre, ligne_cell)
        return f'<c r="{ref}"{attrs}><f>{formule}</f>'

    # toute cellule <c r=... ...><f t="shared" ...(/>|>...</f>) -> normale.
    # ATTENTION : le dernier [^>]* (juste avant l'alternation /> | >...</f>)
    # doit exclure '/' — sinon, glouton, il "mange" le '/' d'une balise
    # auto-fermante <f .../>, forçant la regex a choisir la branche >...</f>
    # et a chercher un </f> BEAUCOUP plus loin dans le texte (celui d'une tout
    # autre cellule) : match qui explose en taille et corrompt le fichier —
    # deja rencontre lors de la mise au point de ce script.
    return re.sub(
        r'<c r="(?P<ref>[A-Z]+\d+)"(?P<attrs>[^>]*)>\s*'
        r'<f t="shared"[^>]*\bsi="(?P<si>\d+)"[^/>]*(?:/>|>.*?</f>)',
        remplacer, sheetdata_inner, flags=re.S)


def _cellule(ref: str, contenu: str | float | None, formule: bool = False) -> str:
    if contenu is None:
        return ""
    if formule:
        # `contenu` est extrait TEL QUEL du XML brut (donc DEJA echappe — ex.
        # '&lt;' pour '<' dans 'C3<=1.2') : ne PAS reechapper (sinon double
        # echappement '&amp;lt;', formule corrompue et fichier illisible par
        # Excel — cf. investigation : Excel refusait le fichier pour cette
        # raison precise).
        return f"<c r={quoteattr(ref)}><f>{contenu}</f></c>"
    if isinstance(contenu, str):
        return f'<c r={quoteattr(ref)} t="inlineStr"><is><t>{escape(contenu)}</t></is></c>'
    return f"<c r={quoteattr(ref)}><v>{contenu}</v></c>"


def _construire_ligne(ligne_no: int, index: int, sec: dict,
                      formules: dict[int, str]) -> str:
    """XML complet d'une <row> de donnees (une section)."""
    cellules = [_cellule(f"A{ligne_no}", index),
               _cellule(f"B{ligne_no}", sec["nom"])]
    for col in range(3, COL_MAX + 1):
        ref = f"{_col_lettre(col)}{ligne_no}"
        if col in formules:
            cellules.append(_cellule(ref, _decaler(formules[col], ligne_no), formule=True))
        elif col in COLONNES_DONNEES:
            cellules.append(_cellule(ref, _valeur(sec, col)))
    return (f'<row r="{ligne_no}" spans="1:{COL_MAX}">' + "".join(cellules) + "</row>")


def _traiter_onglet(xml: str, sections: list[dict], effacer_jusqua: int | None,
                    nom_onglet: str) -> str:
    debut = xml.index("<sheetData>") + len("<sheetData>")
    fin = xml.index("</sheetData>")
    # deplier les formules partagees EN PREMIER (sur toute la feuille) : sinon
    # modifier/vider une ligne "maitre" laisse des lignes "suiveuses" orphelines
    # ailleurs dans la feuille (cf. commentaire de _deplier_formules_partagees)
    inner_deplie = _deplier_formules_partagees(xml[debut:fin])
    lignes = _lire_lignes(inner_deplie)

    # colonnes FORMULE : reperees sur la ligne modele LIGNE_DATA du fichier
    # MAITRE (avant toute modification), par leur cellule <f>...</f>
    modele = lignes.get(LIGNE_DATA, "")
    formules = {}
    for col in range(3, COL_MAX + 1):
        # <f> peut porter des attributs (formule PARTAGEE — t="shared" ref="U3:U8"
        # si="0" — Excel factorise les formules identiques sur une plage) : le
        # texte de la formule n'en reste pas moins dans le contenu de <f>...</f>,
        # qu'on reecrit ensuite en formule normale (non partagee) par ligne.
        m = re.search(rf'<c r="{_col_lettre(col)}{LIGNE_DATA}"[^>]*>\s*<f[^>]*>(.*?)</f>', modele, re.S)
        if m:
            formules[col] = m.group(1)

    n = len(sections)
    for i, sec in enumerate(sections):
        ligne_no = LIGNE_DATA + i
        lignes[ligne_no] = _construire_ligne(ligne_no, i + 1, sec, formules)

    # lignes obsoletes (ancien contenu du meme gabarit, au-dela du nouveau
    # total) : A/B vides seulement (empeche resolve_profile_index/VLOOKUP de
    # les retrouver), colonnes C+ intactes — jamais au-dela de effacer_jusqua
    # (frontiere d'une AUTRE famille partageant l'onglet, ex. UB dans HE)
    borne = effacer_jusqua if effacer_jusqua is not None else (LIGNE_DATA + n - 1)
    videes = 0
    for ligne_no in range(LIGNE_DATA + n, borne + 1):
        if ligne_no not in lignes:
            continue
        contenu = lignes[ligne_no]
        contenu = re.sub(r'<c r="A\d+"[^/]*?(?:/>|>.*?</c>)', "", contenu, count=1)
        contenu = re.sub(r'<c r="B\d+"[^/]*?(?:/>|>.*?</c>)', "", contenu, count=1)
        lignes[ligne_no] = contenu
        videes += 1

    nouveau_inner = "".join(lignes[r] for r in sorted(lignes))
    donnees_ecrites = len(set(COLONNES_DONNEES) - set(formules))
    print(f"  onglet {nom_onglet} : {n} section(s) ecrite(s) "
          f"({donnees_ecrites} colonnes donnees, {len(formules)} colonnes formule), "
          f"{videes} ancienne(s) ligne(s) videe(s) (A:B, lignes {LIGNE_DATA + n}-{borne})")
    return xml[:debut] + nouveau_inner + xml[fin:]


def main() -> None:
    io_map = load_json(IO_MAP)
    maitre = ROOT / io_map["workbookRelativePath"]
    if not maitre.exists():
        sys.exit(f"Classeur maitre introuvable : {maitre}")
    if maitre.resolve() == SORTIE.resolve():
        sys.exit("Le maitre pointe deja sur la sortie ; restaurer d'abord le v3 original.")

    sections = {"HE": _sections_he(), "RHS": _sections_rhs()}

    # catalogues COTE APPLICATION (config/familles.json -> scripts/dimensionner.py
    # ::serie_sections, algo_opti/*) : memes sections HE que celles injectees
    # dans le classeur (aucun renommage pour HE) ; pour RHS, jeu SANS le
    # renommage SHS->RHS specifique a l'ecriture Excel (cf. _sections_rhs_app).
    print("Catalogues application (config/familles.json) :")
    _exporter_catalogue_app("HE", sections["HE"])
    _exporter_catalogue_app("RHS", _sections_rhs_app())

    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(maitre, "r") as zin:
        entrees = zin.infolist()
        contenu = {i.filename: zin.read(i.filename) for i in entrees}

    for nom, cfg in ONGLETS.items():
        fichier = cfg["fichier"]
        xml = contenu[fichier].decode("utf-8")
        contenu[fichier] = _traiter_onglet(
            xml, sections[nom], cfg["effacer_jusqua"], nom).encode("utf-8")

    # calcChain.xml devient obsolete (ordre de recalcul) : on le retire plutot
    # que de le laisser incoherent — Excel accepte une absence de calcChain
    # (recalcul complet a l'ouverture, comportement standard/sans risque) et
    # met a jour references/[Content_Types].xml tout seul a la sauvegarde
    # suivante ; on retire aussi sa declaration de Content_Types pour eviter
    # une reference vers une partie absente.
    calc_chain = "xl/calcChain.xml"
    if calc_chain in contenu:
        del contenu[calc_chain]
        ct = contenu["[Content_Types].xml"].decode("utf-8")
        ct = re.sub(r'<Override PartName="/xl/calcChain\.xml"[^/]*/>', "", ct)
        contenu["[Content_Types].xml"] = ct.encode("utf-8")
        rels = contenu["xl/_rels/workbook.xml.rels"].decode("utf-8")
        rels = re.sub(r'<Relationship[^>]*Target="calcChain\.xml"[^/]*/>', "", rels)
        contenu["xl/_rels/workbook.xml.rels"] = rels.encode("utf-8")

    if SORTIE.exists():
        SORTIE.unlink()
    with zipfile.ZipFile(SORTIE, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in entrees:
            if info.filename == calc_chain:
                continue
            zout.writestr(info.filename, contenu[info.filename])

    print(f"-> {SORTIE.relative_to(ROOT)}")
    print("Pense a pointer excel_bridge/config/io_map.json (workbookRelativePath) dessus.")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print("Injection des sections GSA (HE, RHS+SHS) dans une copie du classeur Predim :")
    main()
