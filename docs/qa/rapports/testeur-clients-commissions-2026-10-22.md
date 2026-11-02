# Rapport — testeur-clients-commissions — 2026-10-22

## Mission

Audit BUG-012 (`docs/qa/REGISTRE_BUGS.md`) : lignes 34-50, 85-97, 108, 130,
148, 172-192, 202, 210 de `remarque.md`, + scénarios CLAUDE.md §5.1
(Clients) et §5.3 (Commissions). Tests automatisés uniquement, aucune
modification de code applicatif.

## Résultat global

`python manage.py test clients commissions` → **50 tests, OK (4 expected
failures)**. Suite verte avec `@expectedFailure` référençant les tickets
ouverts (règle CLAUDE.md §7).

Fichiers créés :
- `backend/core/testing.py` — **non créé par moi** : un autre agent
  (vraisemblablement `testeur-ventes`, en parallèle) l'a créé avant que mon
  propre brouillon ne soit écrit ; j'ai adopté sa version (`make_node`,
  `make_user`, `make_bread_price`, `make_client`, `get_config`) sans la
  dupliquer, conformément à CLAUDE.md §7 règle 1.
- `backend/clients/tests/__init__.py`, `test_models.py`, `test_api.py`,
  `test_imports.py`, `test_social.py` (49 tests côté clients cumulés avec
  commissions → 50 au total avec commissions/tests).
- `backend/commissions/tests/__init__.py`, `test_formulas.py`, `test_generate.py`.
- Suppression des `clients/tests.py` et `commissions/tests.py` vides
  (remplacés par les paquets `tests/`).

## Scénarios couverts et vérifiés conformes (marqués `[c]` dans `remarque.md`)

| remarque.md | Constat |
|---|---|
| l.38 | Plafond crédit par défaut = 50 000 FC (`Client.credit_limit`). |
| l.48, l.50 | `Commissions.tsx` est bien branché sur l'API (`commissionsApi.commissions.list/generate`), avec recherche + filtres (statut, boulangerie). |
| l.94, l.96 | Les montants ne restent plus à 0 après génération de période ; formule de « Déductions » documentée et testée. |
| l.130 | `deduction_debt` est bien alimentée depuis `client.current_debt` à la génération. |
| l.172 | Un `credit_limit` personnalisé saisi à la création (ORM et API) n'est jamais écrasé par le défaut, même s'il est supérieur. |
| l.188 | `Config.default_commission_rate` et `Client.commission_rate` valent `0.25` par défaut (pas 0.30), partout. |
| l.202 | `Client.ClientType` ne propose que DÉTAILLANT/GROSSISTE/REVENDEUR. |

Autres scénarios CLAUDE.md §5.1/§5.3 couverts et conformes (tests verts,
pas de ticket) :
- Génération de code client unique avec préfixe boulangerie, incrémentation séquentielle, code explicite non écrasé.
- Facturier K1 retrouve par recherche prédictive (nom partiel ou code) un client de K3 ; un gérant K1, lui, ne le voit pas (contrôle de contraste de la règle remarque.md « facturier/livreur voient toutes les boulangeries »).
- Modification du plafond crédit : autorisée pour gérant et direction, refusée (HTTP 403) pour facturier et livreur.
- Catégorisation automatique : Meilleur Client au seuil `Config.best_client_threshold`, À Risque dès `current_debt >= credit_limit` (y compris égalité stricte), priorité de « À Risque » sur « Meilleur Client ».
- BP négatif accepté (client épargne) sans déclenchement de la catégorie à risque.
- Photo client : un fichier qui n'est pas une image réelle est rejeté (validation native `ImageField`).
- Import Excel (`clients/imports.py`) avec classeurs **fictifs** générés en mémoire (jamais `data_kiese/`) : parsing multi-boulangeries, feuille sans code boulangerie reconnu (ignorée et reportée), arrêt au premier nom vide, dry-run sans écriture, ré-import idempotent (doublons détectés par nom), code boulangerie inconnu reporté sans planter.
- Caisse sociale : génération mensuelle de cotisations idempotente, bascule payé/impayé horodatée, auto-remplissage des lignes de distribution annuelle avec indice = nombre de cotisations payées et `remise = indice × tarif`, distribution clôturée qui refuse un nouveau remplissage.
- Formules de commission, valeurs calculées à la main en `Decimal` exact (aucun `float`) :
  - CM brute = valeur commande × taux, testé à 0,25 et 0,30, et avec une valeur non ronde (333 333,33 FC) pour vérifier l'absence d'erreur flottante.
  - Remise annuelle = 0,025 × volume livré, avec et sans incorporation au net.
  - `Total retenues` = dette + sociale + imprimés + autre **+ CARTE (1 %) + REMISE (0,1 %)** — le modèle réel (`ClientCommission.compute()`, docstring citant adaptes.md §3.2) ajoute deux retenues non mentionnées dans la formule simplifiée de CLAUDE.md §5.3. **Point signalé plutôt que tranché** : CLAUDE.md §5.3 cite une formule à 4 termes, le code (et son commentaire explicite) s'appuie sur adaptes.md, document prioritaire sur cahierDesCharges.md mais dont la priorité par rapport au texte de CLAUDE.md lui-même n'est pas définie formellement par CLAUDE.md §1 (qui ordonne les documents métier entre eux, pas vis-à-vis de lui-même). Je n'ai pas ouvert de ticket : le calcul réel est cohérent et testé, juste plus riche que le résumé de CLAUDE.md.
  - Net à payer = (CM + remise incorporée) − retenues, avec ajustement manuel qui écrase le calcul.
  - Net à payer négatif : l'application ne bloque pas, ne lève pas d'erreur, calcule un négatif tel quel. **Déjà suivi comme question ouverte** `Q-002` dans `docs/qa/QUESTIONS_CLIENT.md` — je n'ai pas dupliqué de ticket, juste écrit un test qui documente le comportement actuel (`test_net_payable_can_go_negative_when_deductions_exceed_cm`).
  - Listing de paie (`payroll_listing`) : totaux verticaux exacts, recoupés par somme manuelle sur deux clients à taux différents (0,25 et 0,30).

## Anomalies confirmées — 5 tickets ouverts

| Ticket | Gravité | Résumé | Preuve (test `@expectedFailure`) |
|---|---|---|---|
| **BUG-017** | Majeur | `_generate_client_code()` n'a aucun verrou/réservation : deux créations concurrentes de client pour la même boulangerie obtiennent le même « prochain code » ; la seconde création échoue avec une `IntegrityError` au lieu de produire un code unique suivant. | `backend/clients/tests/test_models.py::ClientConcurrentCreationTests::test_generate_client_code_has_no_reservation_mechanism` (déterministe) + test complémentaire sous vrais threads (non bloquant, flaky par nature). |
| **BUG-018** | Majeur | `SocialDistributionLine.compute()` plante (`TypeError: Decimal + str`) dans `auto_populate_lines` : le champ `merite` garde sa valeur par défaut `'0.00'` (chaîne) au lieu d'un `Decimal`, contrairement à `ClientCommission.compute()` qui convertit systématiquement chaque opérande. | `backend/clients/tests/test_social.py::SocialDistributionTests::test_auto_populate_lines_computes_indice_and_remise` |
| **BUG-019** | Majeur | `CommissionPeriodViewSet.generate()` plante (HTTP 500, `AttributeError`) dès qu'une vente occasionnelle DELIVERED (`Invoice.client=None`, légitime depuis `sales/views.py`) existe dans le mois de la période — `client.cotisation_sociale` est appelé sur `client=None`. | `backend/commissions/tests/test_generate.py::OccasionalSaleCommissionGenerationTests::test_generate_does_not_crash_on_client_less_occasional_sale` |
| **BUG-020** | Majeur | Les factures VENTE SOLDE (`is_soldee=True`) restent incluses dans la base de calcul de la CM : `generate()` additionne `order_total` de **toutes** les factures DELIVERED du client (soldées ou non) puis multiplie par `client.commission_rate` — le `commission_rate=0` mis par le frontend sur la facture soldée (`Sales.tsx` l.193) n'est jamais relu par la génération de période. Contraire à CLAUDE.md §5.1 (« VENTE SOLDE... CM = 0 »). | `backend/commissions/tests/test_generate.py::SoldeeSaleCommissionTests::test_soldee_invoice_value_is_excluded_from_commission_base` |
| **BUG-021** | Mineur | Aucune case « vente sans commission de 25 % » distincte de « vente solde » (remarque.md l.190), ni champ modèle associé ; les ventes occasionnelles ne sont pas davantage garanties CM=0 par une règle explicite. | Pas de test Django possible sans ajouter de code — constat de lecture de code uniquement, consigné dans le ticket. |

BUG-012 passé à `REJETÉ` (remplacé par les tickets individuels ci-dessus +
lignes `[c]` dans `remarque.md`), conformément à la règle « ne pas garder
BUG-012..016 comme fourre-tout ».

## Points non vérifiés (hors portée d'un test Django)

Certains points de remarque.md dans le périmètre BUG-012 sont purement
visuels/front-end (modales de détail client avec onglets, libellé « BP »
au lieu de « Dette », colonnes retirées du tableau clients l.42/44/46/108)
: je ne les ai ni testés ni marqués `[c]`, faute de pouvoir le prouver par
un test automatisé backend. Ils restent à la charge d'un passage
`testeur-e2e` ou d'une vérification manuelle ultérieure — je ne les
qualifie pas de bug par prudence (absence de preuve, pas preuve
d'absence).

La ligne 210 (doublons de clients dans « Rapport Mensuel par Client » des
États Financiers N/N-1) relève du module `finance`, hors de mon périmètre
de fichiers (`backend/finance/`) ; je ne l'ai pas auditée — à confirmer par
`testeur-permissions`/`auditeur-comptable` (déjà cités dans BUG-016 pour
la partie Finance).

## Données laissées en base réelle

Aucune — toutes les vérifications ont été faites via `manage.py test` sur
la base de test éphémère Django (règle PLAN_2026-10-22.md §0.1 point 1),
jamais contre `backend/db.sqlite3`. Aucune donnée DEMO/TEST n'a été laissée
dans la base réelle.

## Fichiers livrés

- `backend/core/testing.py` (adopté, non modifié par moi — voir ci-dessus)
- `backend/clients/tests/__init__.py`
- `backend/clients/tests/test_models.py`
- `backend/clients/tests/test_api.py`
- `backend/clients/tests/test_imports.py`
- `backend/clients/tests/test_social.py`
- `backend/commissions/tests/__init__.py`
- `backend/commissions/tests/test_formulas.py`
- `backend/commissions/tests/test_generate.py`
- `docs/qa/REGISTRE_BUGS.md` (BUG-012 clos, BUG-017 à BUG-021 ouverts)
- `remarque.md` (lignes 38, 48, 50, 94, 96, 130, 172, 188, 202 marquées `[c]`)
