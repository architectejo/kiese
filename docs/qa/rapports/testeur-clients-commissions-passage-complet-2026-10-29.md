# Rapport — Passage de non-régression complet Clients/Commissions (2026-10-29)

Agent : testeur-clients-commissions
Contexte : BUG-083 (avertissement vente rétroactive en période de commission verrouillée) et
BUG-086 (validation de date partagée) — vérification qu'ils n'ont rien cassé sur le parcours
normal, et passage complet de la définition de « terminé » (CLAUDE.md §7) sur Clients/Commissions.

## 1. Suite de tests

`python manage.py test clients commissions` (backend) :
- Avant ajout de mes tests : **60 tests, 0 échec**.
- Après ajout (6 tests supplémentaires, dont 1 `@expectedFailure` nouveau) : **63 tests** (hors doublon
  de comptage), **1 échec flaky pré-existant** et **1 `expected failure` attendu** :
  - `clients.tests.test_verification_2026_10_22.BUG017RealConcurrencyStrictAssertionTests
    ::test_all_successful_concurrent_codes_are_unique_no_duplicate_in_db` — flaky connu (verrou SQLite
    sous vrais threads), **déjà documenté sous BUG-017 (OUVERT, non du périmètre de cette mission)** ;
    reproduit tantôt en échec (1/16, puis 7/16 réussites) tantôt en succès total sur 5 exécutions
    répétées en isolation — comportement intermittent inhérent à SQLite + threads réels, pas une
    régression liée à BUG-083/086 ni une anomalie nouvelle.
  - `clients.tests.test_api.ClientCreateResponseContractTests
    ::test_create_response_is_missing_id_and_code_bug_088` — `@expectedFailure` que j'ai ajouté pour
    prouver **BUG-088** (voir §3).
- Aucun échec lié à BUG-068/084/057 dans le périmètre clients/commissions (ces tickets concernent
  `treasury`, hors de ce module).

## 2. Couverture CLAUDE.md §5.1 (Clients) et §5.3 (Commissions)

Relecture complète des deux sections face aux tests existants (`backend/clients/tests/`,
`backend/commissions/tests/`) : toutes les règles ont un test, sauf deux zones que j'ai complétées
moi-même cette session (fichier `commissions/tests/test_regression_complete_2026_10_29.py`) :

1. **Parcours normal de bout en bout, aucune date touchée** (demande explicite du coordinateur) :
   `NormalGerantClientAndOrderJourneyTests` — un GERANT crée un client via l'API (code
   auto-généré, nœud de rattachement, plafond par défaut 50 000 FC, catégorie NORMAL), un FACTURIER
   facture 20 pains à 500 FC (CRÉDIT), confirme la livraison, puis DIRECTION génère la période de
   commission — sans jamais fournir `invoice_date` ni `delivered_at`. Vérifie BP après = 10 000 FC,
   dette client mise à jour, CM brute = 10 000 × 0,25 = 2 500 FC. **Passe intégralement** — aucune
   régression de BUG-083/086 sur le chemin « aucune date demandée ».
2. **« Fiche individuelle des retenues » (CLAUDE.md §5.3)** : non couverte explicitement ailleurs.
   `ClientCommissionIndividualHistoryTests` prouve que le filtre standard `?client=<uuid>` de
   `ClientCommissionViewSet` renvoie bien l'historique chronologique des retenues d'un client à
   travers plusieurs `CommissionPeriod` (janvier : dette retenue 5 000 FC ; février : dette apurée,
   retenue 0 FC) — **passe**.

Formule BUG-058 (CARTE déduite, REMISE non déduite du Net à Payer, décision client 2026-10-23)
re-vérifiée intacte via la suite existante (`test_audit_comptable_2026_10_22.py`,
`test_bug058_independent_verification.py`, `test_formulas.py`) — aucune régression détectée après
BUG-083/086.

Point de vigilance non bloquant, signalé pour information (pas un bug) : `Client.ClientType`
(`DETAILLANT`/`GROSSISTE`/`REVENDEUR`) ne modélise pas littéralement les 4 catégories « régulier /
VENTE SOLDE / VENTE CASH / épargne » de CLAUDE.md §5.1 — ces catégories sont en réalité portées par
`Invoice.is_soldee`/`payment_type` (module Ventes, périmètre `testeur-ventes`) plutôt que par le
client lui-même. Le test `ClientSavingsAccountTests` couvre déjà le comportement BP négatif attendu
pour un client « épargne » générique. Pas d'anomalie nouvelle — contrat déjà cohérent avec
`adaptes.md` tel qu'implémenté dans `sales/models.py`.

## 3. Anomalie trouvée — BUG-088 (nouveau, OUVERT)

**`ClientCreateSerializer` (backend/clients/serializers.py) n'expose ni `id` ni `code` dans la
réponse de création d'un client.** `ClientViewSet.create()` (DRF standard) renvoie donc un `201` dont
le corps ne permet pas de retrouver le client créé.

Conséquence concrète et vérifiée par lecture de code : `frontend/src/pages/dashboard/Clients.tsx`
(flux de vente directe au comptoir, ~ligne 596-604) crée automatiquement un « Client Occasionnel » et
lit immédiatement `res.data.id` pour l'utiliser dans la facture suivante — cet `id` est toujours
`undefined`, le bloc de création de facture est silencieusement sauté, et la **première vente
occasionnelle** d'une boulangerie échoue sans aucun message d'erreur visible à l'écran.

Ticket détaillé : `docs/qa/REGISTRE_BUGS.md` → **BUG-088** (Majeur, backend/frontend, OUVERT).
Test de reproduction : `backend/clients/tests/test_api.py::ClientCreateResponseContractTests
::test_create_response_is_missing_id_and_code_bug_088` (`@expectedFailure`, garde la suite verte).

Non bloquant pour le parcours normal « gérant crée un client via le formulaire dédié puis le
sélectionne dans la recherche prédictive » (celui-ci ne dépend jamais de `res.data.id`) — bloquant
uniquement pour le raccourci « vente occasionnelle » décrit ci-dessus.

Je n'ai pas corrigé le code applicatif (hors mandat testeur) — correction suggérée dans la fiche
BUG-088 : ajouter `'id'` et `'code'` (read-only) à `ClientCreateSerializer.Meta.fields`.

## 4. Vérification manuelle navigateur

Les ports 8000 (backend) et 5173 (frontend) sont actifs avec une connexion déjà **établie**
(`netstat` : `ESTABLISHED`), signe qu'un autre agent utilise probablement l'application en ce
moment. Conformément à la prudence déjà appliquée par d'autres agents dans ce registre (risque de
collision sur `db.sqlite3` avec une session concurrente), je n'ai pas effectué de test manuel dans le
navigateur ni touché `backend/db.sqlite3` réel. La vérification du parcours normal a été faite par
test automatisé de bout en bout (API, §2.1) plutôt que manuellement.

## 5. Migrations

`python manage.py showmigrations` sur la vraie base (`backend/db.sqlite3`) : **aucune migration en
attente** (`[ ]` : 0 occurrence sur l'ensemble des apps). `clients` (jusqu'à `0006`), `commissions`
(jusqu'à `0003`), `sales` (jusqu'à `0006`), `treasury` (jusqu'à `0011`) toutes appliquées.

## 6. Verdict

**Clients et Commissions : prêts à présenter au client, avec une réserve mineure documentée.**
- Tous les scénarios des sections 5.1/5.3 de CLAUDE.md sont couverts par des tests automatisés qui
  passent (63 tests, le seul échec restant est un flaky pré-existant déjà documenté sous BUG-017,
  hors périmètre de cette mission).
- Aucun ticket **bloquant** ouvert sur le module.
- **Un ticket Majeur nouvellement ouvert (BUG-088)** : la création automatique du « Client
  Occasionnel » (vente directe au comptoir, première vente occasionnelle d'une boulangerie) échoue
  silencieusement. Ce n'est pas le parcours principal (facturation nominative d'un client existant ou
  nouveau via le formulaire dédié, qui fonctionne correctement), mais c'est un raccourci utilisé en
  pratique pour les ventes au comptoir sans client identifié — à corriger avant démonstration si ce
  flux est montré au client, ou à signaler explicitement comme connu sinon.
- BUG-083 et BUG-086 n'ont introduit **aucune régression** sur le chemin normal (aucune date
  rétroactive, réglage désactivé) ni sur la formule de commission (BUG-058 toujours respectée).

## Fichiers modifiés/ajoutés

- `backend/commissions/tests/test_regression_complete_2026_10_29.py` (nouveau)
- `backend/clients/tests/test_api.py` (ajout `ClientCreateResponseContractTests`)
- `docs/qa/REGISTRE_BUGS.md` (ajout BUG-088 — tableau de suivi + fiche détaillée)
- `docs/qa/rapports/testeur-clients-commissions-passage-complet-2026-10-29.md` (ce rapport)

Aucun fichier applicatif (`models.py`, `views.py`, `serializers.py`, pages React) n'a été modifié.
