# gsa_bridge — lecteur générique de modèles Oasys GSA

Pont Python ↔ GSA 10.2 fondé sur l'**API .NET** (`GsaAPI.dll`) chargée
**dans le processus Python** (in-process). Aucune fenêtre GSA, aucun serveur
externe, aucun processus à nettoyer : le moteur de calcul GSA est appelé
directement comme une bibliothèque.

`GsaModel` ouvre **n'importe quel fichier `.gwb`** et en extrait les tables
brutes (les mêmes que celles de la vue *Output* de GSA), sans mise en forme
métier. Il ne présuppose rien du modèle (pas seulement une poutre isostatique).

## Contenu du dossier

| Fichier | Rôle |
|---|---|
| `bridge.py` | La classe `GsaModel` : ouverture d'un modèle + méthodes d'extraction brute (données du modèle et résultats). C'est le cœur du dossier. |
| `dotnet_runtime.py` | Amorçage du runtime .NET pour pouvoir charger `GsaAPI.dll`. **Indispensable** et non trivial — voir ci-dessous. |
| `__init__.py` | Fait de `gsa_bridge` un package importable (`from commun.gsa_bridge.bridge import GsaModel`). |
| `runtime/working.gwb` | Copie de travail regénérée à chaque ouverture. Le modèle source n'est **jamais** modifié. Contenu jetable. |

## À quoi sert `dotnet_runtime.py` ?

`GsaAPI.dll` est une bibliothèque **.NET Framework 4.8**. Pour l'appeler depuis
Python on passe par `pythonnet` (`import clr`), mais deux réglages doivent être
faits **avant** le premier `import clr`, sinon rien ne marche :

1. **Choix du runtime** — `pythonnet.load("netfx")`. Par défaut pythonnet peut
   démarrer le runtime **.NET Core (CoreCLR)** ; le moteur natif de GSA, lui,
   attend le **.NET Framework de bureau (netfx)**. Le mauvais runtime ne lève
   pas d'erreur claire : le programme plante en `AccessViolationException`
   (corruption mémoire) au premier `Analyse`. `load("netfx")` force le bon.
2. **Résolution des DLL natives** — `os.add_dll_directory(...)` +
   ajout au `PATH`. `GsaAPI.dll` dépend d'une cascade de DLL natives (solveur,
   sections, etc.) situées dans le dossier d'installation de GSA
   (`C:\Program Files\Oasys\GSA 10.2`). Sans ce dossier dans le chemin de
   recherche, le chargement de l'assembly échoue.

`dotnet_runtime.ensure()` fait ces deux choses **une seule fois** (idempotent)
et est appelé automatiquement par `GsaModel.__init__`. En résumé : c'est la
« rampe de lancement » qui rend `GsaAPI` chargeable ; sans lui, `import GsaAPI`
échoue ou le calcul corrompt la mémoire.

> Si GSA est installé ailleurs qu'en `C:\Program Files\Oasys\GSA 10.2`, adapter
> `GSA_DIR` dans `dotnet_runtime.py`.

## Utilisation

```python
from commun.gsa_bridge.bridge import GsaModel

with GsaModel(r"chemin\vers\mon_modele.gwb") as m:
    sections = m.sections()          # tables du modèle (aucune analyse requise)
    charges  = m.beam_loads()
    m.analyse()                      # lance les tâches d'analyse
    efforts  = m.beam_forces("C1")   # résultats : combinaison 1
    fleche   = m.node_displacements("A2")
```

Chaque méthode renvoie une **liste de `dict`** (une ligne = une entité),
directement convertible en CSV / DataFrame. Rien n'est reformaté : les valeurs
sont celles que renvoie GSA, en **unités SI du modèle** (N, m, Pa…), y compris
les `NaN` là où une composante n'existe pas (ex. réaction en moment sur une
rotule).

### Méthodes d'extraction

**Données du modèle** (sans analyse) :
`nodes()`, `elements()`, `members()`, `sections()`, `materials()`,
`load_cases()`, `beam_loads()`, `gravity_loads()`,
`analysis_tasks()`, `analysis_cases()`, `combination_cases()`.

**Résultats** (après `analyse()`) :
`result_cases()` (liste les cas disponibles), puis
`beam_forces(cas, positions=3)`, `beam_displacements(cas, positions=3)`,
`node_displacements(cas)`, `node_reactions(cas)`.

**Vérification** : `check_analysis_setup()` — lève `ConfigurationAnalyseError`
(sans rien modifier) si le modèle n'a pas de quoi être analysé : pas de cas de
charge, pas de tâche d'analyse, ou pas de cas d'analyse. Une analyse GSA exige
au moins une **tâche** contenant des **cas d'analyse** (des combinaisons seules
ne suffisent pas). À appeler avant `analyse()`.

Le **cas** est désigné à la manière de GSA : `"A1"` = cas d'analyse n°1,
`"C1"` = combinaison n°1. Pour une combinaison à permutations **multiples**
(enveloppe type `ENVELOPPE ELU`), **toutes** les permutations sont prises en
compte : chaque table renvoie alors **deux lignes par position** (`perm:
"max"` / `perm: "min"` — extrêmes signés de chaque composante sur l'ensemble
des permutations), au lieu d'une ligne de valeurs directes. Les max/min
calculés en aval balaient ainsi l'enveloppe complète. Les méthodes 1D
acceptent un `progress(fait, total)` optionnel, appelé après chaque
élément extrait (l'extraction des permutations est l'étape longue).

## Exporter / vérifier

Le script [`scripts/export_model.py`](../scripts/export_model.py) ouvre un
modèle, (re)lance l'analyse et écrit toutes ces tables en CSV dans
`result/export/<modèle>/` :

```powershell
venv\Scripts\python.exe scripts\export_model.py                     # menu interactif
venv\Scripts\python.exe scripts\export_model.py "GSA_model\Canopée - Modèle de Vent.gwb" --cases C1,C3
```

> Perf : extraire les résultats de GSA (surtout les **combinaisons**,
> recalculées à la volée) est de loin l'étape la plus coûteuse — pas l'écriture
> CSV. `--cases` limite l'extraction aux cas voulus.

## Contraintes

- **Windows uniquement**, avec GSA 10.2 installé et licencié.
- **Mono-thread** : Oasys documente que `GsaAPI` n'est pas utilisable en
  multi-thread. Un `GsaModel` doit vivre dans un seul thread. Pour du calcul
  parallèle, utiliser plusieurs **processus**.
- `pip install pythonnet` requis (cf. `requirements.txt`).
