# Rapport testeur Clients et Commissions (dev-b), 2026-11-21 : tâche B-8

Objet : préparer les questions client pour BUG-266, 267, 268 (Commissions, « À CLARIFIER »), sans modifier le code applicatif.

## Méthode
- Lecture des fiches du registre, de `commissions/models.py` (`compute`, `_compute_carried_debt_in`), `commissions/views.py` (`generate`, `mark_paid`) et de QUESTIONS_CLIENT*.md. Dernier numéro existant : Q-021, donc Q-022 à Q-024.
- Chiffres vérifiés en exécutant le vrai code (test jetable dans `backend/commissions/tests/`, données fictives, supprimé après exécution). Commande : `DJANGO_DEBUG=True .venv/Scripts/python.exe manage.py test commissions.tests.test_jetable_b8`. Résultats du code identiques aux calculs à la main. Les alternatives B/C ne sont pas implémentées : elles sont calculées à la main.
- Paramètres : pain 500 FC, taux 25 %, cotisation 3 000 FC, imprimés 0.

## Questions (ajoutées en fin de `docs/qa/QUESTIONS_CLIENT_SIMPLIFIE.md`)
| Q | Ticket | Exemple | Application aujourd'hui | Alternatives |
|---|---|---|---|---|
| Q-022 | BUG-266 | commande 20 000, CM 5 000, dette 6 000, cotisation 3 000 : net -4 000 | non payable, reporté ; mars (CM 15 000, dette payée) : 8 000 | B oublier : 12 000 ; C client paie 4 000 en espèces : 12 000 |
| Q-023 | BUG-267 | épargne 7 000, commande 4 000, CM 1 000, cotisation 3 000 | net 5 000 (épargne ajoutée, comme l'Excel) | B épargne exclue : -2 000 (reporté) |
| Q-024 | BUG-268 | dette 10 000, CM 5 000 : fév. -8 000 ; mars dette inchangée | -8 000 (dette comptée une fois) | ancien comportement : -16 000 |

## Constats à signaler au coordinateur
1. Le registre indique pour ces trois tickets « Décision client » (corrigés et VÉRIFIÉS le 2026-11-13), mais aucune réponse correspondante n'existe dans QUESTIONS_CLIENT*.md (seule Q-002 couvre le report). Les questions servent donc à confirmer ces décisions. Le statut `CORRIGÉ` des tickets n'a pas été modifié.
2. BUG-267 a été partiellement renversé par BUG-293 (Q-012) : l'épargne créditrice s'ajoute au net pour un client qui achète. Q-023 confirme ce choix.
3. Cas non tranché : quand le client paie sa dette de BP après un net négatif, le report reste intégralement déduit (exemple Q-022 : 8 000 au lieu de 12 000). Traité par Q-022 ; si la réponse est B ou C, un ticket sera nécessaire.

## Fichiers modifiés
- `docs/qa/QUESTIONS_CLIENT_SIMPLIFIE.md` : section ajoutée en fin de fichier (CRLF conservé).
- `docs/qa/REGISTRE_BUGS.md` : lignes BUG-266, 267, 268, mention « Question Q-NNN préparée le 2026-11-21 ».
- Aucun code applicatif, aucun test conservé, aucun commit.
