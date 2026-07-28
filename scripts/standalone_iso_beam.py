# -*- coding: utf-8 -*-
"""
Script standalone (demo) : accede directement aux resultats du modele Poutre
ISO via GsaModel, sans passer par les fonctions d'export.
"""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from gsa_bridge.bridge import GsaModel

# Chemin du modele Poutre ISO
model_path = ROOT / "GSA_model" / "Poutre ISO.gwb"

print(f"Ouverture du modele : {model_path}")
print("-" * 60)

with GsaModel(model_path) as model:
    # Verification que le modele est analysable
    model.check_analysis_setup()
    print("[OK] Modele analysable\n")

    # === DONNEES DU MODELE ===
    print("=== DONNEES DU MODELE ===\n")

    # Noeuds
    nodes = model.nodes()
    print(f"Noeuds ({len(nodes)}) :")
    for n in nodes[:3]:
        print(f"  Noeud {n['node']:3d} : ({n['x']:8.3f}, {n['y']:8.3f}, {n['z']:8.3f})")
    if len(nodes) > 3:
        print(f"  ... ({len(nodes) - 3} autres noeuds)")
    print()

    # Elements
    elements = model.elements()
    print(f"Elements ({len(elements)}) :")
    for e in elements[:3]:
        print(f"  Element {e['element']:3d} : type={e['type']}, topologie={e['topologie']}")
    if len(elements) > 3:
        print(f"  ... ({len(elements) - 3} autres elements)")
    print()

    # Sections
    sections = model.sections()
    print(f"Sections ({len(sections)}) :")
    for s in sections:
        print(f"  Section {s['section']:3d} ({s['nom']}) : A={s['aire_m2']:.6f} m², Iyy={s['Iyy_m4']:.8f} m⁴")
    print()

    # Cas de charge
    load_cases = model.load_cases()
    print(f"Cas de charge ({len(load_cases)}) :")
    for lc in load_cases:
        print(f"  Cas {lc['cas']:3d} ({lc['nom']}) : type={lc['type']}")
    print()

    # === LANCER L'ANALYSE ===
    print("=== ANALYSE ===\n")
    print("Lancement de l'analyse...")
    timings = model.analyse()
    for t in timings:
        status = "[OK]" if t['ok'] else "[KO]"
        print(f"  {status} Tache {t['tache']:2d} ({t['nom']:20s}) : {t['duree_s']:.2f} s")
    print()

    # === RESULTATS ===
    print("=== RESULTATS ===\n")

    # Lister les cas de resultats disponibles
    available = model.result_cases()
    print(available)
    print(f"Cas d'analyse disponibles (A) : {available['A']}")
    print(f"Combinaisons disponibles (C)  : {available['C']}")
    print()

    # Prendre le premier cas d'analyse disponible
    if available['A']:
        case = f"A{available['A'][0]}"
        print(f"Resultats pour le cas {case} :\n")

        # Efforts dans les elements
        forces = model.beam_forces(case, positions=3)
        print(f"Efforts dans les elements ({len(forces)} valeurs) :")
        for f in forces[:5]:
            print(f"  Element {f['element']:3d} @ pos {f['pos']:.2f} : "
                  f"Fx={f['Fx']:10.2f} N, Fy={f['Fy']:10.2f} N, Fz={f['Fz']:10.2f} N, "
                  f"Myy={f['Myy']:12.4f} N·m")
        if len(forces) > 5:
            print(f"  ... ({len(forces) - 5} autres valeurs)")
        print()

        # Deplacements des noeuds
        displacements = model.node_displacements(case)
        print(f"Deplacements nodaux ({len(displacements)}) :")
        for d in displacements[:5]:
            print(f"  Noeud {d['node']:3d} : Ux={d['Ux']:12.6f} m, Uy={d['Uy']:12.6f} m, Uz={d['Uz']:12.6f} m")
        if len(displacements) > 5:
            print(f"  ... ({len(displacements) - 5} autres noeuds)")
        print()

        # Reactions d'appui
        reactions = model.node_reactions(case)
        print(f"Reactions d'appui ({len(reactions)}) :")
        for r in reactions:
            if abs(r['Fx']) > 0.1 or abs(r['Fy']) > 0.1 or abs(r['Fz']) > 0.1:  # Appuis actifs
                print(f"  Noeud {r['node']:3d} : Fx={r['Fx']:10.2f} N, Fy={r['Fy']:10.2f} N, Fz={r['Fz']:10.2f} N")
        print()

    # Deplacements le long des elements
    if available['A']:
        case = f"A{available['A'][0]}"
        elem_displ = model.beam_displacements(case, positions=3)
        print(f"Deplacements le long des elements ({len(elem_displ)} valeurs) :")
        for d in elem_displ[:5]:
            print(f"  Element {d['element']:3d} @ pos {d['pos']:.2f} : "
                  f"Ux={d['Ux']:12.6f} m, Uy={d['Uy']:12.6f} m")
        if len(elem_displ) > 5:
            print(f"  ... ({len(elem_displ) - 5} autres valeurs)")

print("\n" + "=" * 60)
print("Fin du script standalone.")
