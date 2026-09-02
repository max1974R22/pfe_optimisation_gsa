"""
Lecteur generique d'un modele Oasys GSA via l'API .NET (GsaAPI.dll, chargee
in-process par pythonnet — voir dotnet_runtime.py).

`GsaModel` ouvre N'IMPORTE QUEL fichier .gwb (pas seulement la poutre ISO) et
expose des methodes d'EXTRACTION BRUTE : chacune renvoie une liste de lignes
(des `dict`), une ligne par entite, sans mise en forme. C'est volontairement
le materiau brut des tables que GSA affiche dans sa vue Output ; la mise en
page (tableau aligne, CSV...) est laissee a l'appelant (cf. test/).

Trois familles de methodes :
  - donnees du modele (aucune analyse requise) : nodes, elements, members,
    sections, materials, load_cases, beam_loads, node_loads, gravity_loads,
    lists, analysis_tasks, analysis_cases, combination_cases ;
  - resultats (necessitent une analyse) : beam_forces, member_forces,
    beam_stresses, beam_derived_stresses, beam_displacements,
    node_displacements, node_reactions. Le cas est designe par une chaine
    facon GSA : "A1" (cas d'analyse) ou "C1" (combinaison) ;
  - ecriture (les seules qui modifient la copie de travail) : section_dediee
    (isole une propriete de section pour une cible), set_section_profile
    (change le profil d'une section) et save_to (SaveAs explicite).

Le travail se fait toujours sur une COPIE du fichier (jamais l'original) ;
seul `save_to` ecrit ailleurs, sur demande explicite de l'appelant.
Contrainte Oasys : GsaAPI n'est pas thread-safe — un seul thread par modele.
"""
from __future__ import annotations

import shutil
import time
import uuid
from pathlib import Path

from gsa_bridge import dotnet_runtime


class ConfigurationAnalyseError(RuntimeError):
    """Le modele ne contient pas de quoi lancer une analyse (tache / cas manquants)."""


# --------------------------------------------------------------------------- utils
def _vec(v) -> tuple[float, float, float]:
    return (v.X, v.Y, v.Z)



def _mat_analysis_props(mat) -> dict:
    """Proprietes d'analyse communes a tous les materiaux (E, nu, densite, alpha)."""
    am = getattr(mat, "AnalysisMaterial", None) or mat
    return {
        "E_Pa": getattr(am, "ElasticModulus", None),
        "nu": getattr(am, "PoissonsRatio", None),
        "densite_kg_m3": getattr(am, "Density", None),
        "alpha_1_K": getattr(am, "CoefficientOfThermalExpansion", None),
    }


class GsaModel:
    """Session GsaAPI in-process autour d'un fichier GSA quelconque."""

    def __init__(self, source_path: str | Path, work_dir: str | Path | None = None):
        dotnet_runtime.ensure()
        from GsaAPI import Model

        self.source_path = Path(source_path)
        if not self.source_path.exists():
            raise FileNotFoundError(self.source_path)
        work_dir = Path(work_dir) if work_dir else Path(__file__).resolve().parent / "runtime"
        work_dir.mkdir(parents=True, exist_ok=True)
        # nom UNIQUE par instance (jamais un nom fixe partage type "working.gwb") :
        # deux GsaModel ne peuvent jamais se marcher dessus (copie/lecture d'un
        # AUTRE fichier en cours), et aucune copie perimee ne peut trainer sous
        # un nom que quelqu'un pourrait rouvrir en pensant lire le bon modele —
        # chaque instance ne lit jamais que SA PROPRE copie fraiche de source_path
        self.work_path = work_dir / f"{self.source_path.stem}_{uuid.uuid4().hex[:8]}.gwb"
        shutil.copyfile(self.source_path, self.work_path)  # jamais l'original
        self.model = Model(str(self.work_path))

    # -- cycle de vie --------------------------------------------------------
    def analyse(self, task: int | None = None) -> list[dict]:
        """(Re)lance une tache d'analyse (ou toutes si task est None).

        Renvoie une ligne par tache : {tache, nom, ok, duree_s}.
        """
        d = self.model.AnalysisTasks()
        task_ids = [task] if task is not None else list(d.Keys)
        timings = []
        for t in task_ids:
            nom = d[t].Name if t in d.Keys else ""
            t0 = time.perf_counter()
            ok = self.model.Analyse(t)
            timings.append({
                "tache": t,
                "nom": nom,
                "ok": bool(ok),
                "duree_s": round(time.perf_counter() - t0, 2),
            })
        return timings

    def check_analysis_setup(self) -> None:
        """Verifie que le modele a de quoi etre analyse. NE MODIFIE RIEN.

        Leve `ConfigurationAnalyseError` en listant ce qui manque : cas de
        charge, tache d'analyse, cas d'analyse. (Une analyse GSA a besoin d'au
        moins une tache contenant des cas d'analyse, eux-memes bases sur des
        cas de charge ; des combinaisons seules ne suffisent pas.)
        """
        manquants = []
        if not list(self.model.LoadCases().Keys):
            manquants.append("aucun cas de charge (load case) n'est defini")
        if not list(self.model.AnalysisTasks().Keys):
            manquants.append("aucune tache d'analyse (analysis task) n'est definie")
        if not list(self.model.AnalysisCases().Keys):
            manquants.append("aucun cas d'analyse (analysis case) n'est defini")
        if manquants:
            raise ConfigurationAnalyseError(
                "Modele non analysable : " + " ; ".join(manquants)
                + ". Aucune analyse ne peut etre lancee (le fichier n'est pas modifie)."
            )

    def close(self) -> None:
        if self.model is not None:
            self.model.Close()
            self.model = None
        # supprime la copie de travail (best-effort : Windows peut encore
        # tenir le fichier verrouille juste apres Close()) — rien ne doit
        # trainer sous un nom qu'une lecture ulterieure pourrait confondre
        # avec le fichier source
        try:
            self.work_path.unlink(missing_ok=True)
        except OSError:
            pass

    def __enter__(self) -> "GsaModel":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ======================================================================
    #  DONNEES DU MODELE (pas besoin d'analyse)
    # ======================================================================
    def nodes(self) -> list[dict]:
        d = self.model.Nodes()
        rows = []
        for nid in d.Keys:
            n = d[nid]
            x, y, z = _vec(n.Position)
            r = n.Restraint
            rows.append({
                "node": nid, "x": x, "y": y, "z": z,
                "res_x": r.X, "res_y": r.Y, "res_z": r.Z,
                "res_xx": r.XX, "res_yy": r.YY, "res_zz": r.ZZ,
                "nom": n.Name,
            })
        return rows

    def elements(self) -> list[dict]:
        d = self.model.Elements()
        rows = []
        for eid in d.Keys:
            e = d[eid]
            rows.append({
                "element": eid,
                "type": e.TypeAsString(),
                "propriete": e.Property,
                "groupe": e.Group,
                "topologie": list(e.Topology),
                "longueur_m": self.model.ElementLength(eid),
                "angle_orientation": e.OrientationAngle,
                "noeud_orientation": e.OrientationNode,
                "factice": e.IsDummy,
                "nom": e.Name,
            })
        return rows

    def members(self) -> list[dict]:
        d = self.model.Members()
        rows = []
        for mid in d.Keys:
            m = d[mid]
            rows.append({
                "member": mid,
                "type": m.TypeAsString(),
                "type_1d": m.Type1DAsString(),
                "propriete": m.Property,
                "groupe": m.Group,
                "topologie": m.Topology,
                "angle_orientation": m.OrientationAngle,
                "nom": m.Name,
            })
        return rows

    def sections(self) -> list[dict]:
        d = self.model.Sections()
        rows = []
        for sid in d.Keys:
            s = d[sid]
            p = s.Properties()
            rows.append({
                "section": sid,
                "nom": s.Name,
                "profil": s.Profile,
                "materiau": s.MaterialTypeAsString(),
                # id du materiau DANS SA COLLECTION DE TYPE (ex. SteelMaterials
                # id 2), a associer a `materiau` pour retrouver la densite REELLE
                # de la section (cf. app/server.py::_densites_sections) — deux
                # sections de types differents peuvent partager le meme id.
                "materiau_grade": s.MaterialGradeProperty,
                "aire_m2": p.Area,
                "Iyy_m4": p.Iyy,
                "Izz_m4": p.Izz,
                "J_m4": p.J,
                "Zy_m3": p.Zy,       # module elastique Wel,y
                "Zz_m3": p.Zz,       # module elastique Wel,z
                "Zpy_m3": p.Zpy,     # module plastique Wpl,y
                "Zpz_m3": p.Zpz,     # module plastique Wpl,z
                "C_m3": p.C,         # module de torsion Wt (tau_t = Mt / C)
                # facteurs de cisaillement de Timoshenko (aire reduite de
                # DEFORMATION = K x A). A ne pas confondre avec l'aire de
                # cisaillement Av de l'EC3 6.2.6, qui est une aire de
                # RESISTANCE et vaut autre chose (ex. tube mince : K = 0.500
                # contre Av/A = 2/pi = 0.637).
                "Kyy": p.Kyy,
                "Kzz": p.Kzz,
                "Ry_m": p.Ry,
                "Rz_m": p.Rz,
            })
        return rows

    def materials(self) -> list[dict]:
        """Tous les materiaux du modele, quel que soit leur type."""
        collections = {
            "acier": self.model.SteelMaterials,
            "beton": self.model.ConcreteMaterials,
            "bois": self.model.TimberMaterials,
            "aluminium": self.model.AluminiumMaterials,
            "frp": self.model.FrpMaterials,
            "verre": self.model.GlassMaterials,
            "textile": self.model.FabricMaterials,
            "armature": self.model.ReinforcementMaterials,
            "analyse": self.model.AnalysisMaterials,
        }
        rows = []
        for type_nom, getter in collections.items():
            try:
                d = getter()
            except Exception:
                continue
            for mid in d.Keys:
                mat = d[mid]
                rows.append({
                    "type": type_nom,
                    "id": mid,
                    "nom": getattr(mat, "Name", None),
                    **_mat_analysis_props(mat),
                })
        return rows

    def load_cases(self) -> list[dict]:
        d = self.model.LoadCases()
        return [{
            "cas": cid,
            "type": str(d[cid].CaseType),
            "nom": d[cid].Name,
        } for cid in d.Keys]

    def beam_loads(self) -> list[dict]:
        rows = []
        for b in self.model.BeamLoads():
            try:
                valeur = b.Value(0)
            except Exception:
                valeur = None
            rows.append({
                "cas": b.Case,
                "cible": str(b.EntityType),
                "liste": b.EntityList,
                "type": b.TypeAsString(),
                "direction": b.DirectionAsString(),
                "projete": b.IsProjected,
                "valeur": valeur,
            })
        return rows

    def node_loads(self) -> list[dict]:
        """Charges nodales concentrees.

        L'API GsaAPI impose UN type par appel (`Model.NodeLoads(type)`) : on
        agrege les types porteurs de forces/deplacements imposes — NODE_LOAD,
        APPL_DISP, SETTLEMENT. GRAVITY leve « Unsupported » cote GSA (le poids
        propre passe par `gravity_loads`) et n'est pas interroge.

        `noeuds` est la liste GSA brute (ex. "2 to 6"), `direction` la
        composante ("X", "Y", "Z", "XX"...), `valeur` en unites SI du modele.
        """
        from GsaAPI import NodeLoadType

        rows = []
        for type_nom in ("NODE_LOAD", "APPL_DISP", "SETTLEMENT"):
            try:
                coll = self.model.NodeLoads(getattr(NodeLoadType, type_nom))
            except Exception:
                continue
            for nl in coll:
                rows.append({
                    "cas": nl.Case,
                    "type": type_nom,
                    "noeuds": nl.Nodes,
                    "direction": nl.Direction.ToString(),
                    "valeur": nl.Value,
                    "nom": nl.Name,
                })
        return rows

    def gravity_loads(self) -> list[dict]:
        rows = []
        for g in self.model.GravityLoads():
            fx, fy, fz = _vec(g.Factor)
            rows.append({
                "cas": g.Case,
                "cible": str(g.EntityType),
                "liste": g.EntityList,
                "facteur_x": fx, "facteur_y": fy, "facteur_z": fz,
            })
        return rows

    def lists(self) -> list[dict]:
        """Listes GSA nommees, avec leurs ids developpes par `ExpandList`.

        `type` est l'entite ciblee ("Member", "Element", "Node"...) et `ids`
        la definition ("1 to 6", "12 13 15 17"...) resolue en liste d'entiers.
        """
        d = self.model.Lists()
        rows = []
        for lid in d.Keys:
            lo = d[lid]
            try:
                ids = list(self.model.ExpandList(lo))
            except Exception:
                ids = []
            rows.append({
                "liste": lid,
                "nom": lo.Name,
                "type": lo.Type.ToString(),
                "definition": lo.Definition,
                "ids": ids,
            })
        return rows

    def analysis_tasks(self) -> list[dict]:
        d = self.model.AnalysisTasks()
        return [{
            "tache": tid,
            "nom": d[tid].Name,
            "cas": list(d[tid].Cases),
        } for tid in d.Keys]

    def analysis_cases(self) -> list[dict]:
        d = self.model.AnalysisCases()
        return [{
            "cas": cid,
            "nom": d[cid].Name,
            "description": d[cid].Description,
        } for cid in d.Keys]

    def combination_cases(self) -> list[dict]:
        d = self.model.CombinationCases()
        return [{
            "combinaison": cid,
            "nom": d[cid].Name,
            "definition": d[cid].Definition,
        } for cid in d.Keys]

    def rendu_geometrie(self, entites: str = "all") -> dict:
        """Geometrie 3D REELLE du modele telle que GSA la dessinerait dans sa
        propre vue (via `Model.Draw`, API de rendu headless — aucune fenetre
        GSA n'est ouverte), sections des barres 1D EXTRUDEES (pas de simple
        trait d'axe) : triangles pleins (facettes de la section le long de
        chaque barre) + lignes (aretes). Ne necessite PAS d'analyse prealable
        (geometrie non deformee).

        `entites` : selecteur GSA ("all" par defaut). Renvoie des tableaux
        PLATS (x,y,z,x,y,z,... par triangle/ligne) + une couleur hexa par
        primitive — format compact pour un gros modele (des dizaines de
        milliers de triangles ne sont pas rares, meme pour une structure de
        taille modeste : chaque barre est extrudee facette par facette)."""
        import GsaAPI

        liste = GsaAPI.EntityList()
        liste.Name = "rendu"
        liste.Type = GsaAPI.EntityType.Element
        liste.Definition = entites

        methode = GsaAPI.EntityDisplayMethod()
        methode.For1d = GsaAPI.DisplayMethodFor1d.OutLineFilled
        methode.For2d = GsaAPI.DisplayMethodFor2d.Solid
        methode.For3d = GsaAPI.DisplayMethodFor3d.Solid

        spec = GsaAPI.GraphicSpecification()
        spec.EntityDisplayMethod = methode
        spec.Entities = liste
        spec.DrawInitialState = True
        spec.DrawDeformedShape = False

        resultat = self.model.Draw(spec)

        def hexa(c) -> str:
            return f"#{c.R:02x}{c.G:02x}{c.B:02x}"

        tri_pos: list[float] = []
        tri_col: list[str] = []
        for t in resultat.Triangles:
            for v in t.Vertices:
                tri_pos.extend((round(v.X, 4), round(v.Y, 4), round(v.Z, 4)))
            tri_col.append(hexa(t.Colour))

        lig_pos: list[float] = []
        lig_col: list[str] = []
        for l in resultat.Lines:
            lig_pos.extend((round(l.Start.X, 4), round(l.Start.Y, 4), round(l.Start.Z, 4),
                            round(l.End.X, 4), round(l.End.Y, 4), round(l.End.Z, 4)))
            lig_col.append(hexa(l.Colour))

        return {
            "triangles": {"positions": tri_pos, "couleurs": tri_col},
            "lignes": {"positions": lig_pos, "couleurs": lig_col},
        }

    # ======================================================================
    #  RESULTATS (necessitent une analyse prealable)
    # ======================================================================
    def result_cases(self) -> dict[str, list[int]]:
        """Cas pour lesquels des resultats existent : {'A': [...], 'C': [...]}."""
        return {
            "A": list(self.model.Results().Keys),
            "C": list(self.model.CombinationCaseResults().Keys),
        }

    def _result(self, case: str):
        case = case.strip().upper()
        kind, num = case[0], int(case[1:])
        if kind == "A":
            res = self.model.Results()
        elif kind == "C":
            res = self.model.CombinationCaseResults()
        else:
            raise ValueError(f"Cas invalide : {case!r} (attendu 'A<n>' ou 'C<n>')")
        if num not in res.Keys:
            raise KeyError(f"Pas de resultat pour le cas {case}")
        return res[num]

    @staticmethod
    def _permutations(coll, marker="YY"):
        """Toutes les permutations d'un resultat le long d'un element.

        Un cas d'analyse renvoie une collection plate de valeurs (traitee comme
        une permutation unique) ; une combinaison renvoie une collection de
        permutations (chacune une collection de valeurs le long de l'element) —
        pour une combinaison enveloppe (type ENVELOPPE ELU), il peut y en avoir
        plusieurs centaines. On distingue les deux via un attribut-marqueur
        present sur la valeur unitaire mais absent d'une collection : "YY" pour
        un Double6 (efforts/deplacements), "AxialStressA" pour une contrainte,
        "VonMisesStress" pour une contrainte derivee.
        """
        if coll.Count == 0:
            return []
        if hasattr(coll[0], marker):
            return [list(coll)]
        return [list(p) for p in coll]

    def _table_1d(self, data, champs, marker="YY", id_key="element",
                  progress=None) -> list[dict]:
        """Table d'un resultat 1D, TOUTES permutations prises en compte.

        Cas d'analyse (ou combinaison a permutation unique) : une ligne par
        position, valeurs directes — schema historique. Combinaison a
        permutations MULTIPLES (enveloppe) : DEUX lignes par position,
        perm="max" (maximum signe de chaque composante sur toutes les
        permutations) et perm="min" (minimum signe), pour que les max/min
        calcules en aval portent sur l'enveloppe complete et plus sur la seule
        1re permutation. Les NaN sont ignores dans la reduction (une composante
        sans aucune valeur lisible reste NaN).

        `progress(fait, total)` est appele apres chaque element extrait (le
        gros du cout est l'interop .NET : permutations x positions x champs).
        """
        rows = []
        ids = list(data.Keys)
        for k, eid in enumerate(ids):
            perms = self._permutations(data[eid], marker)
            if not perms:
                continue
            npos = len(perms[0])
            for i in range(npos):
                pos = i / (npos - 1) if npos > 1 else 0.0
                if len(perms) == 1:
                    v = perms[0][i]
                    rows.append({id_key: eid, "pos": pos,
                                 **{col: getattr(v, attr) for col, attr in champs}})
                    continue
                maxs: dict = {}
                mins: dict = {}
                for perm in perms:
                    v = perm[i]
                    for col, attr in champs:
                        x = getattr(v, attr)
                        if x != x:                      # NaN
                            continue
                        if col not in maxs or x > maxs[col]:
                            maxs[col] = x
                        if col not in mins or x < mins[col]:
                            mins[col] = x
                nan = float("nan")
                rows.append({id_key: eid, "pos": pos, "perm": "max",
                             **{col: maxs.get(col, nan) for col, _ in champs}})
                rows.append({id_key: eid, "pos": pos, "perm": "min",
                             **{col: mins.get(col, nan) for col, _ in champs}})
            if progress:
                progress(k + 1, len(ids))
        return rows

    # colonnes de sortie -> attribut .NET de la valeur unitaire
    _CHAMPS_FORCES = (("Fx", "X"), ("Fy", "Y"), ("Fz", "Z"),
                      ("Mxx", "XX"), ("Myy", "YY"), ("Mzz", "ZZ"))
    _CHAMPS_DEPL = (("Ux", "X"), ("Uy", "Y"), ("Uz", "Z"),
                    ("Rxx", "XX"), ("Ryy", "YY"), ("Rzz", "ZZ"))
    _CHAMPS_STRESS = (("A", "AxialStressA"),
                      ("Sy", "ShearStressSy"), ("Sz", "ShearStressSz"),
                      ("By_pz", "BendingStressByPositiveZ"),
                      ("By_nz", "BendingStressByNegativeZ"),
                      ("Bz_py", "BendingStressBzPositiveY"),
                      ("Bz_ny", "BendingStressBzNegativeY"),
                      ("C1", "CombinedStressC1"), ("C2", "CombinedStressC2"))
    _CHAMPS_DERIVE = (("SEy", "ElasticShearStressSEy"),
                      ("SEz", "ElasticShearStressSEz"),
                      ("St", "TorsionalStressSt"), ("VM", "VonMisesStress"))

    def beam_forces(self, case: str, positions: int = 3, progress=None,
                    elements: str = "all") -> list[dict]:
        """Efforts internes des elements 1D (Fx,Fy,Fz,Mxx,Myy,Mzz), unites SI.

        `elements` : selecteur GSA ("all", "12", "1 2 3"...) pour n'extraire
        qu'une barre ou un sous-ensemble (extraction barre par barre).
        """
        data = self._result(case).Element1dForce(elements, positions, None)
        return self._table_1d(data, self._CHAMPS_FORCES, progress=progress)

    def member_forces(self, case: str, positions: int = 3, progress=None,
                      elements: str = "all") -> list[dict]:
        """Efforts internes par MEMBRE 1D (`Member1dForce`), unites SI.

        Contrairement a `beam_forces` (par element du maillage), le resultat
        court le long du membre ENTIER — la sortie « 1D member results » de
        GSA. Avec le maillage 1 membre = 1 element du projet, les ids
        coincident avec ceux des elements. `elements` : selecteur GSA.
        """
        data = self._result(case).Member1dForce(elements, positions, None)
        return self._table_1d(data, self._CHAMPS_FORCES, id_key="member",
                              progress=progress)

    def beam_stresses(self, case: str, positions: int = 3, progress=None,
                      elements: str = "all") -> list[dict]:
        """Contraintes des elements 1D (`Element1dStress`), unites Pa.

        Composantes : axiale A, cisaillements Sy/Sz, flexion By sur les fibres
        +z/-z (`By_pz`/`By_nz`), flexion Bz sur les fibres +y/-y
        (`Bz_py`/`Bz_ny`), combinees C1 (A+B max) et C2 (A+B min).
        `elements` : selecteur GSA (extraction barre par barre).
        """
        data = self._result(case).Element1dStress(elements, positions, None)
        return self._table_1d(data, self._CHAMPS_STRESS, marker="AxialStressA",
                              progress=progress)

    def beam_derived_stresses(self, case: str, positions: int = 3,
                              progress=None, elements: str = "all") -> list[dict]:
        """Contraintes derivees des elements 1D (`Element1dDerivedStress`), Pa.

        Cisaillements elastiques SEy/SEz, contrainte de torsion St et
        contrainte equivalente de von Mises (VM). `elements` : selecteur GSA.
        """
        data = self._result(case).Element1dDerivedStress(elements, positions, None)
        return self._table_1d(data, self._CHAMPS_DERIVE, marker="VonMisesStress",
                              progress=progress)

    def beam_displacements(self, case: str, positions: int = 3,
                           progress=None, elements: str = "all") -> list[dict]:
        """Deplacements le long des elements 1D (Ux,Uy,Uz,Rxx,Ryy,Rzz), unites SI.

        `elements` : selecteur GSA (extraction barre par barre)."""
        data = self._result(case).Element1dDisplacement(elements, positions, None)
        return self._table_1d(data, self._CHAMPS_DEPL, progress=progress)

    def _table_noeud(self, data, champs) -> list[dict]:
        """Table d'un resultat nodal, TOUTES permutations prises en compte.

        Meme logique que `_table_1d` : valeur directe pour un cas d'analyse
        (Double6) ou une permutation unique ; deux lignes perm="max"/"min"
        (extremes signes par composante) pour une combinaison enveloppe.
        """
        rows = []
        for nid in data.Keys:
            val = data[nid]
            perms = [val] if hasattr(val, "Z") else list(val)
            if len(perms) == 1:
                v = perms[0]
                rows.append({"node": nid,
                             **{col: getattr(v, attr) for col, attr in champs}})
                continue
            maxs: dict = {}
            mins: dict = {}
            for v in perms:
                for col, attr in champs:
                    x = getattr(v, attr)
                    if x != x:                          # NaN
                        continue
                    if col not in maxs or x > maxs[col]:
                        maxs[col] = x
                    if col not in mins or x < mins[col]:
                        mins[col] = x
            nan = float("nan")
            rows.append({"node": nid, "perm": "max",
                         **{col: maxs.get(col, nan) for col, _ in champs}})
            rows.append({"node": nid, "perm": "min",
                         **{col: mins.get(col, nan) for col, _ in champs}})
        return rows

    def node_displacements(self, case: str) -> list[dict]:
        """Deplacements nodaux (Ux,Uy,Uz,Rxx,Ryy,Rzz), unites SI."""
        data = self._result(case).NodeDisplacement("all", None)
        return self._table_noeud(data, self._CHAMPS_DEPL)

    def node_reactions(self, case: str) -> list[dict]:
        """Reactions d'appui (Fx,Fy,Fz,Mxx,Myy,Mzz), unites SI."""
        data = self._result(case).NodeReactionForce("all", None)
        return self._table_noeud(data, self._CHAMPS_FORCES)

    # ======================================================================
    #  ECRITURE (modifient la copie de travail — a utiliser sciemment)
    # ======================================================================
    def section_dediee(self, element_ids, nom: str = "") -> int:
        """Renvoie l'id d'une propriete de section COMMUNE et EXCLUSIVE aux
        `element_ids` donnes, afin d'optimiser une barre ou un groupe sans
        toucher au reste du modele.

        - si les cibles partagent une meme propriete qui ne sert QU'A elles,
          elle est reutilisee telle quelle (rien n'est clone) ;
        - sinon (propriete partagee avec d'autres barres, ou cibles portant
          PLUSIEURS proprietes — ex. groupe a cheval sur des familles deja
          optimisees), l'une des proprietes est clonee sous un id libre et le
          clone est affecte aux elements cibles (et a leurs membres homonymes —
          maillage 1 membre = 1 element), laissant les autres porteurs sur
          leur section d'origine. Les appelants ecrasent systematiquement le
          profil du clone juste apres, sa valeur initiale est donc sans effet.

        La section d'origine reste intacte (cf. `_cloner_section` pour le piege
        des references vives de l'API).
        """
        cibles = {int(e) for e in element_ids}
        if not cibles:
            raise ValueError("section_dediee : aucun element cible.")
        elements = self.model.Elements()
        connus = set(elements.Keys)
        manquants = cibles - connus
        if manquants:
            raise KeyError(f"section_dediee : elements inexistants {sorted(manquants)}.")

        props_cibles = {elements[eid].Property for eid in cibles}
        src = min(props_cibles)
        if len(props_cibles) == 1:
            porteurs = {eid for eid in connus if elements[eid].Property == src}
            if porteurs == cibles:
                return src  # deja dedie a la cible : rien a cloner

        new_id = max(self.model.Sections().Keys) + 1
        self._cloner_section(src, new_id, nom)
        self._affecter_section(cibles, new_id)
        return new_id

    def _cloner_section(self, src: int, new_id: int, nom: str) -> None:
        """Clone la section `src` vers `new_id` (id suppose libre).

        ⚠️ Les objets Section de GsaAPI sont des REFERENCES VIVES : muter
        l'objet renvoye par `Sections()` mute la section d'origine en memoire.
        On l'exploite — on ecrit l'objet (eventuellement renomme) sous `new_id`,
        puis on RESTAURE explicitement l'original.
        """
        secs = self.model.Sections()
        s = secs[src]
        nom_origine = s.Name
        if nom:
            s.Name = nom
        self.model.SetSection(new_id, s)   # cree new_id a partir de l'etat courant
        s.Name = nom_origine               # restaure l'objet mute en place
        self.model.SetSection(src, s)

    def _affecter_section(self, element_ids, prop_id: int) -> None:
        """Affecte la propriete `prop_id` aux elements donnes et a leurs
        membres homonymes (meme id — maillage 1 membre = 1 element)."""
        elements = self.model.Elements()
        for eid in element_ids:
            e = elements[eid]
            e.Property = prop_id
            self.model.SetElement(eid, e)
        membres = self.model.Members()
        connus = set(membres.Keys)
        for mid in element_ids:
            if mid in connus:
                m = membres[mid]
                m.Property = prop_id
                self.model.SetMember(mid, m)

    def set_section_profile(self, section_id: int, profile: str) -> dict:
        """Change le profil d'une section dans la COPIE DE TRAVAIL et renvoie la
        section relue (profil normalise par GSA + proprietes) pour controle.

        N'ecrit rien sur disque : seul `save_to` persiste la copie de travail.
        La re-analyse est a la charge de l'appelant (le swap invalide les
        resultats existants).
        """
        secs = self.model.Sections()
        if section_id not in secs.Keys:
            raise KeyError(f"set_section_profile : section {section_id} inexistante.")
        s = secs[section_id]
        s.Profile = profile
        self.model.SetSection(section_id, s)

        s2 = self.model.Sections()[section_id]
        p = s2.Properties()
        return {
            "section": section_id,
            "profil": s2.Profile,      # designation normalisee par GSA
            "aire_m2": p.Area,
            "Iyy_m4": p.Iyy,
            "Izz_m4": p.Izz,
            "J_m4": p.J,
            "Zy_m3": p.Zy,
            "Zz_m3": p.Zz,
            "Zpy_m3": p.Zpy,
            "Zpz_m3": p.Zpz,
        }

    def save_to(self, destination: str | Path) -> Path:
        """Enregistre la copie de travail vers `destination` (`SaveAs`).

        Seule ecriture hors de `runtime/`. Le retour de `SaveAs` n'etant pas
        fiable, on verifie l'existence du fichier produit.
        """
        destination = Path(destination)
        self.model.SaveAs(str(destination))
        if not destination.exists():
            raise RuntimeError(f"Echec de l'enregistrement GSA : {destination}")
        return destination
