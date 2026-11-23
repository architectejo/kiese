# Testeur trésorerie, cycle 17 partie C (2026-11-23)

Fichier de tests : `backend/treasury/tests/test_verif_tresorerie_c17_v16.py` (10 tests, verts) ; c16 relancé (23 verts).

## BUG-996 : VÉRIFIÉ
- Éditions non infirmées : compteur reste 0 (3 PUT). Une infirmation puis une resoumission : +1 exactement ; édition suivante non infirmée : inchangé (3 cycles).
- Resoumission refusée (400) : ni compteur ni infirmation modifiés.
- Rejeu d'un lot antérieur à l'infirmation (compteur 0) : l'infirmation n'est jamais levée (3 rejeux).
- Les 2 tests c16 adaptés (`test_payload_exporte_le_compteur`, `test_rejeu_d_un_enregistrement_anterieur_a_l_infirmation`) testent toujours l'essentiel : le premier vérifie le compteur exporté après vraie resoumission (1), le second reproduit exactement le scénario du défaut (édition, infirmation, rejeu) et exige que l'infirmation tienne. Défaut d'origine fermé.
- Cycle complet poste/cloud : push, infirmation, resoumission (1), rejeu ignoré, 2e infirmation, 2e resoumission, confirmation, versement, chaîne valide.

## Balayage final : aucun nouveau défaut
- Verrou de vente BUG-973 : bloqué sans clôture, en attente, infirmée, resoumise ; débloqué à la confirmation seule (BUG-986 reste À CLARIFIER) ; la confirmation d'un autre poste ne débloque pas.
- Finance : lecture réservée Direction/Comptable/Admin (gérant, facturier, livreur 403, anonyme 401) sur les 4 états, la liste et `summary` ; POST sur les états 405 ; N-1 sans données et années hors plage (400 à la création) sans 500. Observation : une année 1 créée directement en base donnerait un 500 (N-1 = année 0), non atteignable par l'API.
- Blockchain/treasury : après 2 versements et un bon, soldes 20 000, 40 000, 30 000 ; les deux vérifications concordent ; altération en base détectée par les deux (alerte ouverte).
- Bon de décaissement : solde exact à 0, bon supérieur au solde refusé sans résidu.

## Nouveaux tickets : 0
