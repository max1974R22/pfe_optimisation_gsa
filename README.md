# PFE V0 — Automatisation GSA / Excel (vérification de poutres acier)

Croiser le modèle Oasys GSA et le classeur Excel de prédimensionnement pour
automatiser la vérification de poutres acier (EC3). Le pont GSA travaille
**in-process** (API .NET `GsaAPI.dll` via pythonnet) et **toujours sur une
copie** : les fichiers `.gwb` maîtres ne sont jamais modifiés.

## Arborescence

| Dossier | Rôle |
|---|---|
| `GSA_model/` | Modèles GSA maîtres (`.gwb`). |
| `app/` | **Interface web** du dimensionneur (`venv\Scripts\python.exe app\server.py` → http://localhost:8765). |
| `algo_opti/` | **Algorithmes d'optimisation de la structure globale** (une section par famille de barres). Un module par algorithme (`LIBELLE`, `DESCRIPTION`, `optimiser(modele, cfg)`), enregistré dans `ALGOS` (`__init__.py`) et proposé automatiquement dans le menu déroulant de la page. Premier algo : `brut_force.py` (force brute + passes, ex-`optimiser_global`). |
| `gsa_bridge/` | Pont GSA : `GsaModel` (lecture des tables + résultats, swap de section). |
| `excel_bridge/` | Pont Excel (classeur Predim, xlwings/COM). |
| `catalogues/` | Catalogues de sections extraits de la base GSA (`sectlib.db3`) + extracteur. |
| `config/` | Critères modifiables (`dimensionnement.json` : 90 % fy, L/300…). |
| `scripts/` | **Tous les points d'entrée** (voir ci-dessous). |
| `tests/` | Scripts de vérification et de benchmark (chrono GSA, calcul manuel) + **étude des 668 permutations de l'ENVELOPPE ELU** de la Canopée (efforts par barre acier et par combinaison). Voir `tests/README.md`. |
| `comparaison_modele/` | Étude de sensibilité de l'algorithme escalade (treillis Pratt). Voir `comparaison_modele/README.md`. |
| `result/` | Toutes les sorties : `export/<modèle>/`, `sections/`, `calcul_manuel/`, `dimensionnement/`. |
| `optimisations/` | Journaux (`.txt`) des runs d'optimisation (horodatés par modèle et algorithme). |
| `reference/` | Documents de référence (Eurocode, classeur Excel, identité graphique…). |
| `suivi_build/` | Journal des sessions de build (à lire pour l'historique). |

## Scripts (`venv\Scripts\python.exe scripts\<script>.py`)

| Script | Ce qu'il fait |
|---|---|
| `export_model.py` | Exporte un modèle `.gwb` en CSV (tables + résultats) → `result/export/<modèle>/`. Menu interactif sans argument. |
| `etude_sections.py` | Recalcule la Poutre ISO avec N sections IPE → `result/sections/<SECTION>/` + `_Comparatif.csv`. |
| `comparer_sections.py` | Post-traitement : tableau large 1 ligne/section (max et position par cas) → `result/sections/_Comparaison.csv`. |
| `calcul_manuel.py` | Mêmes grandeurs par les formules (pL²/8, pL/2, 5pL⁴/384EI) + écart vs GSA → `result/calcul_manuel/`. |
| `dimensionner.py` | **Dimensionnement** : parcourt la série de sections en décroissant, critère ELU sur les **contraintes calculées par GSA** — enveloppe **signée min/max de toutes les mesures** (combinées C1/C2, axiale A, flexion By/Bz, von Mises, cisaillements…), la plus grande amplitude gouverne ; restriction possible via une clé `mesures` dans `config/dimensionnement.json` —, critère ELS (f ≤ L/300), suppose des combinaisons nommées `ELU`/`ELS` → tableau des taux (avec mesure gouvernante) + section retenue → `result/dimensionnement/`. Logique réutilisée par l'interface `app/` et par les algorithmes de `algo_opti/`. |
| `../app/server.py` | **Interface web** : dépôt/choix du `.gwb`, résumé du modèle (charges nodales et **listes GSA** comprises) avec **vue 3D interactive**, **performances du modèle actuel** (volet dépliable : poids d'acier, contraintes extrêmes C1/C2 à l'ELU, déplacement max à l'ELS, détail barre par barre + efforts d'extrémité par membre « 1D member results ») (canvas maison `app/static/viewer3d.js`, cible surlignée), **cible d'optimisation** (barre seule ou groupe = liste GSA ; en groupe, le critère ELU suit la barre la plus sollicitée), choix de la famille (cf. `config/familles.json`) et des contraintes GSA vérifiées à l'ELU, critères éditables, tableau des taux avec mesure/barre gouvernantes et section retenue, **« Charger dans le modèle »** (applique la section à la cible — propriété dédiée au besoin — et enregistre le `.gwb`, écrase directement le fichier chargé), puis **ouverture du classeur Predim pré-rempli en mode torseur** dans Excel (enveloppe ELU des efforts de la barre gouvernante à 0/25/50/75/100 % — jamais les chargements extérieurs ; copie horodatée dans `%LOCALAPPDATA%\PredimGSA\`, le maître Predim n'est jamais touché). Serveur stdlib multi-thread ; tous les appels GsaAPI passent par un thread travailleur unique (contrainte GsaAPI). |
| `standalone_iso_beam.py` | Démo minimale d'accès direct aux résultats via `GsaModel`. |
| `../catalogues/extract_catalogues.py` | Regénère les CSV de catalogues depuis `sectlib.db3`. |

## Prérequis

- GSA 10.2 installé (licence utilisée par le moteur in-process).
- `venv` Python avec `requirements.txt` (pythonnet ≥ 3.1 notamment).
- Un seul script GSA à la fois (copie de travail partagée `gsa_bridge/runtime/`).
