# Catalogues de sections GSA

Depuis la base de catalogues installée avec GSA
(`C:\Program Files\Oasys\GSA 10.2\sectlib.db3`, SQLite — c'est cette base que
GSA consulte quand un profil est désigné par `CAT <type> <section> <date>`) :

```powershell
venv\Scripts\python.exe catalogues\scripts\extract_catalogues.py   # sectlib.db3 -> catalogues_sections.xlsx (brut)
venv\Scripts\python.exe catalogues\scripts\exporter_csv.py          # catalogues_sections_GSA.xlsx -> *.csv
```

`extract_catalogues.py` régénère un `catalogues_sections.xlsx` **brut** (rien
que ce qui vient de GSA). `catalogues_sections_GSA.xlsx` est la copie de
**travail** — reprise à la main dans un tableur (ex. profils UB/UC ajoutés à
l'onglet HE, cf. plus bas) — qui fait référence : c'est elle qu'`exporter_csv.py`
lit. Après une extraction, reporter les évolutions dans `catalogues_sections_GSA.xlsx`
à la main plutôt que l'écraser, sous peine de perdre les retouches.

À relancer `exporter_csv.py` après toute modification de
`catalogues_sections_GSA.xlsx` (le fichier doit être fermé dans Excel).

## Contenu

| Fichier | Contenu |
|---|---|
| `catalogues_sections_GSA.xlsx` | Référence **consultable et modifiable à la main** : une feuille par catégorie (IPE, IPN, HD, HE, CHS, RHS, W — RHS regroupe les RHS et les SHS de GSA), colonnes de géométrie/section (g, h, b, tw, tf, A, Iy, Wy, Wply, iy, Iz, Wz, Wplz, iz, It, r) + `profil_gsa` (désignation exacte à passer à GSA). Peut contenir d'autres colonnes (h/b, Avz, Ss, Iw, Avy...) issues de retouches manuelles : `exporter_csv.py` les ignore. |
| `IPE.csv`, `IPN.csv`, `HD.csv`, `HE.csv`, `CHS.csv`, `RHS.csv`, `W.csv` | Copie rapide à charger de chaque feuille du xlsx (unités SI, m/kg — `nom`, `masse_kg_m`, `h_m`, `b_m`, `tw_m`, `tf_m`, `aire_m2`, `Iyy_m4`, `Wel_y_m3`, `Wpl_y_m3`, `iy_m`, `Izz_m4`, `Wel_z_m3`, `Wpl_z_m3`, `iz_m`, `J_m4`, `r_m`, `profil_gsa`) : ce sont ces fichiers que lit le code (`commun/catalogues.py::charger_catalogue`, utilisé par `commun/dimensionner.py`, `commun/stabilite_ec3/section_catalogue.py`, `commun/algo_opti/*`, `commun/excel_bridge/scripts/injecter_sections_gsa.py`) — ouvrir le xlsx à chaque appel serait trop lent. |

Pour ajouter une catégorie : l'ajouter à `CATEGORIES` dans
`scripts/extract_catalogues.py` (avec le ou les catalogues GSA — `TYPE_ABR` —
à regrouper dans la feuille) et à `FEUILLES` dans `scripts/exporter_csv.py`,
puis relancer les deux scripts (reporter la nouvelle feuille dans
`catalogues_sections_GSA.xlsx` avant de relancer `exporter_csv.py`).

## Compléter une feuille modifiée à la main

`scripts/completer_ub.py` est un script ponctuel : dans une copie retravaillée
à la main du xlsx (`catalogues_sections_GSA.xlsx`, onglet HE, avec un bloc de
lignes ajoutées manuellement à la suite des HE-AM, sans `profil_gsa`), il
repère ce bloc et le remplace intégralement par le catalogue GSA complet
choisi (`UB-AM`, ArcelorMittal Universal Beams — 137 sections) : noms ET
géométrie extraits directement de GSA, colonnes formule (h/b, Avz, Iw, Avy)
réécrites à l'identique (recalées à la ligne), `Ss` laissée vide (pas
d'équivalent GSA). Il ne modifie jamais le fichier source, seulement une
copie (`..._complete.xlsx`). À adapter (`TYPE_ABR`, chemins) si une autre
famille est ajoutée à la main de la même façon.

## Famille W (AISC, 02/09/2026)

Profils en I américains, catalogue GSA `W-AM` (`TYPE_NUM=273`, "AM American
wide flange beams(W)" — variante **métrique** de dimensions, cohérente avec
HD-AM/HE-AM/IPE-AM/IPN-AM ci-dessus ; à ne pas confondre avec le catalogue
`W` brut de sectlib, impérial et dupliqué entre deux `TYPE_NUM` obsolètes).
252 sections, désignations `W<h>x<b>x<masse>` (ex. `W250x100x28.4`).

Contrairement à SHS/UB/UC (qui n'ont pas de feuille dédiée et sont rangés
tels quels dans RHS/HE/HD, cf. `commun/stabilite_ec3/section_catalogue.py::
ONGLET_PREDIM`), W a sa **propre** feuille/CSV : une section W reste "W" de
bout en bout, l'optimisation et la stabilité cherchent dans `catalogues/W.csv`,
jamais dans HE. C'est un profil en I/H laminé ordinaire au sens EC3 (mêmes
formules que HE/HD — courbes de flambement, gauchissement, Tableau B.1 "H I")
: `commun/stabilite_ec3/_commun.py::FAMILLES_I_H` en tient compte.

**Pas d'onglet dans `reference/excels/Predim_poutre acier_v3_GSA.xlsm`** (le
classeur ne connaît que IPE/IPN/HE/HD/CHS/RHS/Custom, `AB2` 1 à 7) : une barre
en W ne peut donc être vérifiée que par le moteur Python
(`commun/stabilite_ec3`, le moteur par défaut depuis le 01/09/2026, cf.
`appv2/README.md`) — le bouton « Ouvrir dans Excel » d'appv2 n'a pas
d'équivalent pour cette famille.
