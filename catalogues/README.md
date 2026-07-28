# Catalogues de sections GSA

CSV de référence extraits de la base de catalogues installée avec GSA
(`C:\Program Files\Oasys\GSA 10.2\sectlib.db3`, SQLite). C'est cette base que
GSA consulte quand un profil est désigné par `CAT <type> <section> <date>`.

Régénérer (après une mise à jour de GSA par exemple) :

```powershell
venv\Scripts\python.exe catalogues\extract_catalogues.py
```

## Contenu

| Fichier | Contenu |
|---|---|
| `Catalogues.csv` | Les 17 catalogues (British, Europrofile, AISC, ArcelorMittal…). |
| `Types.csv` | Les 272 types de sections, avec leur catalogue et leur **abréviation** (la clé des désignations : `IPE-AM`, `HE-AM`, `UB`, …). |
| `IPE-AM.csv` | Poutrelles IPE ArcelorMittal (68 : IPE80→IPE750, variantes A/AA/O/V incluses). |
| `HE-AM.csv` | Poutrelles HE ArcelorMittal (124 : HEA/HEB/HEM/HEC/HEAA). |
| `UPE-AM.csv` | Profilés U à ailes parallèles (14). |
| `UPN-AM.csv` | Profilés U à ailes inclinées (18). |
| `IPN-AM.csv` | Poutrelles I à ailes inclinées (21). |

Pour exporter d'autres types : ajouter leur abréviation (colonne `abreviation`
de `Types.csv`) à `TYPES_EXPORTES` dans `extract_catalogues.py` et relancer.

## Colonnes des CSV de sections

Unités SI (m, kg). Convention d'axes du modèle GSA (poutre le long de x
local) : **Iyy = axe fort** (`SECT_I_XX` de la base), **Izz = axe faible** —
cohérent avec la table `Sections.csv` des exports de `test/main.py`.

- `nom`, `masse_kg_m`, `h_m`, `b_m`, `tw_m`, `tf_m`, `r_m` : désignation et géométrie ;
- `aire_m2`, `Iyy_m4`, `Izz_m4`, `iy_m`, `iz_m` : aire, inerties, rayons de giration ;
- `Wel_y_m3`, `Wel_z_m3`, `Wpl_y_m3`, `Wpl_z_m3` : modules élastiques et plastiques ;
- `J_m4`, `Iw_m6` : torsion et gauchissement ;
- `obsolete` : TRUE si la section est retirée du catalogue courant ;
- `profil_gsa` : **désignation exacte à passer à GSA** (champ `Profile` d'une
  section, ex. `CAT IPE-AM IPE200 20170912`). La date est facultative : GSA
  normalise `CAT IPE-AM IPE200` en y ajoutant la date du catalogue.
