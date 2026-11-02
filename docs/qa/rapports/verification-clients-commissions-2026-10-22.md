# Rapport de vérification — Clients et Commissions (phase 4)

Agent : `testeur-clients-commissions` · Date : 2026-10-22
Mission : revérifier de façon critique et indépendante les corrections apportées par `dev-backend` aux tickets `BUG-017` à `BUG-021` (ouverts par moi-même en phase 2), conformément à CLAUDE.md §7 règle 3 (« celui qui corrige ne valide jamais sa propre correction »).

## Méthode

1. Relecture du code actuel (pas du diff, ni du rapport de `dev-backend`, ni de mon propre rapport de phase 2) :
   - `backend/clients/models.py` (nouveau modèle `ClientCodeSequence`, `_generate_client_code`, `Client.save()`, `SocialDistributionLine.compute()`).
   - `backend/commissions/views.py::CommissionPeriodViewSet.generate()`.
   - `backend/sales/models.py::Invoice` (pour BUG-021/BUG-052).
2. Relance de `python manage.py test clients commissions` (`DJANGO_DEBUG=True DJANGO_SECRET_KEY=...` requis en local, `backend/.env` restant un venv — note déjà connue, BUG-007).
3. Écriture de scénarios supplémentaires indépendants (pas une simple relecture) :
   - `backend/clients/tests/test_verification_2026_10_22.py` (nouveau fichier) :
     - `BUG017RealConcurrencyStrictAssertionTests` — 16 threads concurrents (contre 8 en phase 2), avec une assertion **strictement plus exigeante** que le test existant : le test de phase 2 ne vérifiait que l'absence de plantage total (`len(errors) + len(codes) == n_threads`), ce qui aurait laissé passer une collision de code masquée par des erreurs de verrou SQLite. Mon test vérifie en plus l'unicité stricte des codes produits, en mémoire **et** relue depuis la base.
     - `BUG018ComputeDirectCallTests` — appel direct de `compute()` sur une instance non sauvegardée avec un `merite` non nul assigné comme chaîne (reproduction exacte du scénario de bug), pour prouver non seulement l'absence de `TypeError` mais l'exactitude Decimal du résultat (le test existant laisse `merite` à 0 par défaut, donc ne prouve pas que l'addition est correcte quand `merite` compte réellement).
   - `backend/commissions/tests/test_verification_2026_10_22.py` (nouveau fichier) :
     - `CombinedOccasionalAndSoldeeSaleTests` — un même client avec, dans le même mois/nœud, une facture normale, une facture VENTE SOLDE et une facture occasionnelle (`client=None`) coexistant : vérifie que `generate()` ne plante pas, que `generated == 1`, et que `order_value`/`commission_gross` restent exacts au FC près (calcul manuel en `Decimal`). Ce scénario combiné n'était pas testé en phase 2 (chaque bug testé séparément) et aurait pu révéler une interaction parasite entre les deux filtres ajoutés pour BUG-019/BUG-020.
4. Mise à jour du registre (`docs/qa/REGISTRE_BUGS.md`) : statuts, sections « Vérification » détaillées par ticket, et ouverture d'un ticket de suivi précisé pour BUG-021.

## Résultats par ticket

### BUG-017 — `_generate_client_code` sans verrou → **VÉRIFIÉ**
- Code actuel : `ClientCodeSequence` (nouveau modèle, compteur persistant par préfixe de boulangerie) + `select_for_update()` + `transaction.atomic()` dans `_generate_client_code`, avec garde-fou qui avance la séquence si le code calculé est déjà pris. `Client.save()` retente jusqu'à 10 fois sur `IntegrityError`.
- Le décorateur `@expectedFailure` a bien été retiré définitivement du test de phase 2 (confirmé en lisant `clients/tests/test_models.py`, pas seulement en faisant confiance au registre).
- Mon test de concurrence renforcé (16 threads, assertion stricte d'unicité en mémoire et en base) passe : **0 doublon**.
- Aucune faille trouvée.

### BUG-018 — `SocialDistributionLine.compute()` plante (`TypeError`) → **VÉRIFIÉ**
- `compute()` convertit désormais explicitement `tarif`, `total_social` et `merite` via `Decimal(str(...))`, à la source (pas de contournement par relecture en base).
- Mon test d'appel direct avec `merite` non nul confirme l'exactitude du calcul (`remise = indice × tarif`, `total_payer = total_social + remise + merite`), pas seulement l'absence de plantage.
- Aucune faille trouvée.

### BUG-019 — `generate()` plante sur une vente occasionnelle (`client=None`) → **VÉRIFIÉ**
- Filtre `client__isnull=False` ajouté au queryset `invoices` de `generate()`, confirmé en lecture directe du code.
- Mon test combiné (facture normale + soldée + occasionnelle sur le même client/nœud/mois) confirme l'absence de plantage **et** l'exactitude du calcul malgré la coexistence des trois cas.
- Aucune faille trouvée.

### BUG-020 — Les ventes VENTE SOLDE restent dans la base de calcul de la CM → **VÉRIFIÉ**
- Filtre `is_soldee=False` ajouté au même queryset combiné que BUG-019, confirmé en lecture directe du code.
- Point de vigilance noté mais non bloquant (déjà couvert par la proposition BUG-021/BUG-052 ci-dessous) : ce filtre ne couvre que `is_soldee` ; aucun champ `Invoice` ne représente aujourd'hui une « VENTE CASH » distincte au sens strict de CLAUDE.md §5.1. Je ne rouvre pas ce ticket pour ce point, qui est hors de son périmètre strict (il concernait uniquement `is_soldee`).
- Aucune faille trouvée dans le périmètre du ticket.

### BUG-021 — Aucune case « vente sans commission de 25 % » → **confirmé comme ticket de suivi, périmètre précisé et transféré en BUG-052**
- La proposition documentée par `dev-backend` (champ `Invoice.commission_exempt`, défaut `False`, filtre ajouté dans `generate()`, case UI dans `Sales.tsx`) est **solide sur le fond** : elle distingue correctement le besoin réel (CM=0 sur une facture normale, sans changer le prix ni la BP) de `is_soldee` (qui change le prix à 75 % et gèle la BP).
- Précision ajoutée en phase 4, absente de la proposition initiale : `commission_exempt=True` ne doit **pas** modifier `compute_debt_after()` — la BP doit continuer à suivre `order_total` normalement. Sans cette précision, un développeur pressé pourrait copier le traitement de `is_soldee` et introduire une régression sur la BP pour une facture qui n'est pourtant pas une vente soldée.
- Décision : ouverture de **BUG-052** (module Ventes, backend+frontend) reprenant la proposition avec ce point de vigilance explicite. BUG-021 reste tracé (`CONFIRMÉ — PÉRIMÈTRE TRANSFÉRÉ EN BUG-052`) pour l'historique de l'analyse, mais toute implémentation/vérification future se fait sur BUG-052.
- Cohérence avec le périmètre de l'agent : je n'implémente rien (`sales/models.py`, `Sales.tsx` sont hors de mon périmètre backend `clients`/`commissions`) — je me limite à confirmer/préciser la proposition et à ouvrir le ticket de suivi, comme demandé par la mission.

## Tests

- Fichiers ajoutés (vérification uniquement, aucun code applicatif modifié) :
  - `backend/clients/tests/test_verification_2026_10_22.py`
  - `backend/commissions/tests/test_verification_2026_10_22.py`
- `python manage.py test clients commissions` : **53/53 OK** (50 tests de phase 2 + 3 tests de vérification ajoutés), aucune régression.
- Aucune démonstration manuelle contre `backend/db.sqlite3` n'a été jugée nécessaire pour cette vérification (les scénarios sont entièrement couverts par les tests automatisés ci-dessus) ; aucune donnée DEMO/TEST n'a donc été laissée dans la base réelle.

## Fichiers modifiés/ajoutés par cette session

- `docs/qa/REGISTRE_BUGS.md` : statuts BUG-017/018/019/020 → `VÉRIFIÉ` (sections « Vérification » ajoutées) ; BUG-021 → `CONFIRMÉ — PÉRIMÈTRE TRANSFÉRÉ EN BUG-052` ; nouveau ticket `BUG-052` (table + fiche détaillée).
- `backend/clients/tests/test_verification_2026_10_22.py` (nouveau)
- `backend/commissions/tests/test_verification_2026_10_22.py` (nouveau)
- Aucun fichier de code applicatif modifié (conforme à la mission).

## Tickets ouverts à l'issue de cette session

- `BUG-052` (Ventes, backend/frontend, Mineur, `OUVERT`) — à traiter par `dev-backend`/`dev-frontend` lors d'un prochain round sur le module Ventes, puis à vérifier par `testeur-ventes` (et recoupement commissions par moi-même si la génération de période est affectée).
