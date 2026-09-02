# -*- coding: utf-8 -*-
"""Verification de la stabilite EC3 (EN 1993-1-1 §6.3) — SANS Excel.

Reimplementation Python des 4 taux calcules par le classeur Predim
(`commun/excel_bridge/stabilite.py`, onglet `Calcul`, cellules X35:X38) :
verifier la stabilite d'une barre sans ouvrir Excel, sans COM, sans verrou
de classeur — et environ 4 ordres de grandeur plus vite (cf. plus bas).

Repartition des fichiers (correspondance avec le classeur) :

  flambement.py               §6.3.1   Calcul!X35 (= P67)
  deversement.py              §6.3.2   Calcul!X36 (= Q86), Mcr en Annexe MCR
  flexion_compression_yy.py   [6.61]   Calcul!X37 (= V96)
  flexion_compression_zz.py   [6.62]   Calcul!X38 (= V100)
  coefficients_c1_c2.py       C1/C2 de Mcr, formules analytiques du §3.5 de
                               l'Annexe MCR (NF EN 1993-1-1/NA)
  coefficients_cm_b3.py       Cmy/Cmz, Tableau B.3 (Calcul!AL51 / AL64)
  _commun.py                  briques partagees (types, coefficient chi §6.49,
                               tableau des courbes de flambement §6.1, kzz)
  verification.py             assemble les 4 taux, cas dimensionnant (= MAX),
                               equivalent de Calcul!L4

ETAT : les formules sont ECRITES ET VERIFIEES. Chaque fonction cite la clause
EC3 et la cellule du classeur dont elle est la traduction ; les cellules ont
ete relues une a une (openpyxl, formules et non valeurs) sur le classeur
courant `reference/excels/Predim_poutre acier_v3_GSA.xlsm`.

CE QUI DIFFERE VOLONTAIREMENT DU CLASSEUR — une seule chose :

  C1 et C2 (facteurs de moment du Mcr de deversement) sont CALCULES ici, par
  les formules analytiques du §3.5 de l'Annexe MCR, des lors que le diagramme
  de moment a 3 points est fourni (`Torseur.My_debut/milieu/fin_kNm`). Le
  classeur, lui, les prend dans deux cellules SAISIES A LA MAIN (P32/P33,
  lecture d'abaque — appv2 y envoie les valeurs de l'encadre Instabilite,
  1,13 / 0,46 par defaut, les memes pour TOUTES les barres). Les deux taux
  de deversement ne peuvent donc pas coincider en general : c'est l'objet de
  `tests/scripts/comparaison_stabilite_excel_python.py`, et c'est documente
  dans README.md a cote de ce fichier.

  Domaine de validite a garder en tete : le §3.5 donne C1/C2 pour k_z = k_w = 1
  ("Les valeurs de C1 et C2 ont ete determinees pour kz = 1 et kw = 1"). Avec
  le k = 0,5 propose par defaut dans l'encadre Instabilite d'appv2, C1/C2
  calcules sortent de ce domaine — cf. README.md, section « Ce qu'il reste a
  trancher ».

TOUT LE RESTE SUIT LE CLASSEUR A L'IDENTIQUE, y compris ses deux
particularites de section creuse, longtemps absentes d'ici (corrigees le
01/09/2026, cf. README.md) :
  - kzz/kyz suivent la ligne « Creux » du Tableau B.1 pour un tube
    (Calcul!AB81 = IF(AH76="h i", AE80, AF80), AH76 = "H I" pour les onglets
    IPE/IPN/HE/HD seulement) ;
  - le deversement est SANS OBJET pour un CHS (Calcul!S80 = IF(AB2=5, 1, ...)
    : chi_LT force a 1, un tube circulaire ne deverse pas).

Ces correspondances de cellules ont ete verifiees par lecture directe du
classeur — s'y referer en cas de doute plutot que de re-deriver.
"""
