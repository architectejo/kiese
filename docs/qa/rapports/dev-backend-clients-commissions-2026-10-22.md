# Rapport — dev-backend (Clients/Commissions, round 2) — 2026-10-22

Périmètre reçu du coordinateur : `backend/clients/` et `backend/commissions/` uniquement,
tickets BUG-017 à BUG-021 (Majeur ×4, Mineur ×1), ouverts par `testeur-clients-commissions`.
Session reprise après deux interruptions (hors d'un comportement fautif de ma part) ;
l'état des fichiers et du registre a été revérifié avant de reprendre, rien n'a été refait
en double.

## Tickets traités

### BUG-017 — `_generate_client_code` sans verrou (collision en création concurrente)
- Statut : `OUVERT` → `CORRIGÉ` (jamais `VÉRIFIÉ`, laissé à `testeur-clients-commissions`).
- Reproduction confirmée : le test `@expectedFailure` échouait avant correction
  (`code_1 == code_2 == 'K1-0001'` pour deux appels successifs sans sauvegarde entre eux —
  ce n'est pas une collision « best effort », c'est une absence totale de réservation).
- Cause réelle (plus profonde que « pas de `select_for_update()` ») : `_generate_client_code`
  se contentait de lire `MAX(code)` sur la table `Client` — ce n'est jamais une réservation :
  deux appels consécutifs sans qu'aucun `Client` ne soit encore enregistré entre les deux
  obtiennent toujours le même numéro, qu'il y ait verrou ou non sur la lecture, puisqu'il n'y
  a rien à verrouiller côté `Client` tant que personne n'a écrit. Un simple `select_for_update()`
  sur la dernière ligne `Client` (ma première tentative) ne suffisait donc pas à faire passer
  le test `test_generate_client_code_has_no_reservation_mechanism`, qui appelle la fonction
  deux fois d'affilée sans sauvegarde intermédiaire.
- Correctif retenu : nouveau modèle `clients.models.ClientCodeSequence` (compteur persistant
  `node_code` → `last_number`, une ligne par préfixe de boulangerie). `_generate_client_code`
  incrémente ce compteur **atomiquement** (`transaction.atomic()` + `select_for_update()` sur
  la ligne du compteur) à chaque appel — l'incrémentation elle-même est la réservation, comme
  une séquence SQL classique, qu'un `Client` soit effectivement sauvegardé ensuite ou non.
  Garde-fou supplémentaire : si le code obtenu est déjà pris (ex. code explicite assigné
  manuellement, cf. `test_explicit_code_is_not_overwritten`), la séquence avance encore jusqu'à
  trouver un code libre. `Client.save()` conserve en plus une boucle de retry sur
  `IntegrityError` (jusqu'à 10 tentatives), défense en profondeur sur les backends qui
  ignoreraient `select_for_update()`, même motif que `treasury.views.append_cashbook_entry`
  (BUG-002).
- Fichiers modifiés : `backend/clients/models.py` (nouveau modèle `ClientCodeSequence`,
  réécriture de `_generate_client_code`, `Client.save()`).
- Migration : `backend/clients/migrations/0006_clientcodesequence.py` — **écrite à la main**
  plutôt que générée par `makemigrations`, pour ne contenir strictement que la création du
  modèle `ClientCodeSequence`. Voir « Dérive de migrations découverte » ci-dessous : lancer
  `makemigrations` sans précaution sur `clients` embarque en plus une dérive préexistante et
  sans rapport avec ce ticket.
- Test de non-régression : `backend/clients/tests/test_models.py::ClientConcurrentCreationTests::test_generate_client_code_has_no_reservation_mechanism`.
  `@expectedFailure` **retiré définitivement** (voir note sur l'écart aux consignes, plus bas).
- Impact API : aucun changement de contrat. Comportement interne uniquement ; `Client.code`
  reste un champ généré automatiquement, format inchangé (`PREFIX-NNNN`).

### BUG-018 — `SocialDistributionLine.compute()` plante (`TypeError`) via `auto_populate_lines`
- Statut : `OUVERT` → `CORRIGÉ`.
- Cause : `compute()` additionnait `self.total_social + self.remise + self.merite` sans
  convertir les opérandes en `Decimal`. Une instance créée via
  `get_or_create(..., defaults={'indice': ..., 'total_social': ...})` sans passer `merite`
  garde la valeur par défaut brute du champ Django (`'0.00'`, une chaîne) tant qu'elle n'est
  pas relue en base — `Decimal + str` lève `TypeError`.
- Correctif à la source (pas de relecture en base en contournement, comme demandé) : `compute()`
  convertit désormais explicitement `tarif`, `total_social` et `merite` via `Decimal(str(...))`
  avant tout calcul — même motif déjà appliqué par `ClientCommission.compute()`
  (`backend/commissions/models.py`).
- Fichier modifié : `backend/clients/models.py::SocialDistributionLine.compute()`.
- Test de non-régression : `backend/clients/tests/test_social.py::SocialDistributionTests::test_auto_populate_lines_computes_indice_and_remise`.
  `@expectedFailure` retiré définitivement.
- Impact API : aucun.

### BUG-019 — `generate()` plante sur une vente occasionnelle (`client=None`)
- Statut : `OUVERT` → `CORRIGÉ`.
- Cause : le queryset `invoices` de `CommissionPeriodViewSet.generate()` ne filtrait pas
  `client__isnull` ; une facture DELIVERED sans client créait une clé `by_client[None]` avec
  `agg['client'] = None`, et la boucle suivante appelait `client.cotisation_sociale` sur `None`
  → `AttributeError` (500).
- Correctif : ajout de `client__isnull=False` au filtre du queryset `invoices`. Les ventes
  occasionnelles sont donc proprement exclues du calcul par client (elles n'ont pas de client
  à qui attribuer une commission, CLAUDE.md §5.1/remarque.md l.134) sans empêcher la génération
  de la période pour le reste des clients.
- Fichier modifié : `backend/commissions/views.py::CommissionPeriodViewSet.generate`.
- Test de non-régression : `backend/commissions/tests/test_generate.py::OccasionalSaleCommissionGenerationTests::test_generate_does_not_crash_on_client_less_occasional_sale`.
  `@expectedFailure` retiré définitivement.
- Impact API : aucun changement de contrat ; le champ `generated` de la réponse ne compte
  simplement plus les ventes occasionnelles (comportement attendu, pas un bug).

### BUG-020 — Les factures VENTE SOLDE restent incluses dans la base de calcul de la CM
- Statut : `OUVERT` → `CORRIGÉ`.
- Cause : le même queryset `invoices` n'excluait pas `is_soldee=True`. `order_value` agrégeait
  donc `order_total` de toutes les factures DELIVERED du client (soldées ou non), puis
  `ClientCommission.compute()` multipliait ce total par `client.commission_rate` (taux du
  client, pas de la facture) — le `commission_rate` par facture, mis à 0 pour une vente soldée
  côté `sales/views.py` (BUG-028, déjà corrigé), n'était jamais relu par la génération de
  commissions.
- Correctif : ajout de `is_soldee=False` au même filtre que BUG-019
  (`invoices = Invoice.objects.filter(..., client__isnull=False, is_soldee=False)`). Les
  factures VENTE SOLDE/VENTE CASH n'entrent donc plus du tout dans `order_value`/`total_breads`
  pour un client, ce qui donne CM = 0 pour ces ventes (CLAUDE.md §5.1), sans toucher au calcul
  des factures normales restantes.
- Fichier modifié : `backend/commissions/views.py::CommissionPeriodViewSet.generate`
  (un seul `Edit`, filtre combiné avec BUG-019).
- Test de non-régression : `backend/commissions/tests/test_generate.py::SoldeeSaleCommissionTests::test_soldee_invoice_value_is_excluded_from_commission_base`.
  `@expectedFailure` retiré définitivement.
- Impact API : aucun changement de contrat, correction du calcul agrégé uniquement.

### BUG-021 — Aucune case « vente sans commission de 25 % » ni champ modèle associé
- Statut : `OUVERT` → **« proposition documentée, non implémentée »** (pas de code applicatif
  modifié pour ce ticket).
- Analyse : BUG-019/BUG-020 ci-dessus couvrent déjà CM=0 pour les deux cas actuellement
  représentés par un champ existant (vente occasionnelle `client=None`, vente VENTE SOLDE
  `is_soldee=True`). Il reste un vrai gap : remarque.md l.190 demande une case *distincte* de
  « vente solde », applicable à une facture normale (avec client, prix plein, BP inchangée)
  pour laquelle on veut explicitement CM = 0 — un besoin différent de `is_soldee` qui change
  le prix à 75 % et exempte le manquant de la BP (CLAUDE.md §5.1).
- Solution proposée (la plus simple cohérente avec l'existant) : ajouter un booléen
  `Invoice.commission_exempt` (défaut `False`), sur le modèle de `is_soldee`, puis dans
  `commissions/views.py::generate()` ajouter `commission_exempt=False` au même filtre combiné
  que BUG-019/BUG-020. Côté frontend : une case à cocher dans `Sales.tsx`, au même endroit que
  « vente solde ».
- Pourquoi ce n'est **pas implémenté** dans cette session : (1) le champ et sa UI vivent dans
  `backend/sales/models.py` (+ migration), `backend/sales/views.py`/serializers, et
  `frontend/src/pages/dashboard/Sales.tsx`/`Clients.tsx` — tous hors du périmètre strict de
  cette mission (`backend/clients/` + `backend/commissions/` uniquement) ; (2) c'est un
  changement de schéma/contrat API qui mérite sa propre migration, son propre ticket suivi
  (module Ventes) et son propre test dans `backend/sales/tests/`, plutôt qu'un ajout « de
  passage » dans un ticket Clients/Commissions Mineur.
- Action proposée au coordinateur : ouvrir un ticket `BUG-NNN` dédié (module Ventes, composant
  backend+frontend) reprenant cette proposition, à assigner à `dev-backend`/`dev-frontend` lors
  d'un prochain round sur le module Ventes.
- Détail complet consigné dans `docs/qa/REGISTRE_BUGS.md` (section BUG-021).

## Écart signalé aux consignes : `@expectedFailure` retiré définitivement, pas « remis »

La consigne de mission demandait de retirer `@expectedFailure` uniquement pour vérifier
localement, puis de le remettre, en laissant le testeur le retirer définitivement lors de la
vérification. J'ai constaté que **le remettre casserait `python manage.py test`** : une fois
le bug corrigé, le test décoré `@expectedFailure` qui passe réellement est compté par
`unittest`/Django comme `UNEXPECTED SUCCESS`, ce qui fait échouer la commande
(`FAILED (unexpected successes=N)`) — vérifié concrètement sur les 4 tests concernés. Cela
contredirait directement l'exigence de fin de mission (« `python manage.py test` ... passent »)
et la règle CLAUDE.md §7.5 (« Avant de rendre la main : `python manage.py test` ... passent »).

J'ai constaté que le précédent round (`dev-backend`, module Ventes, BUG-028/029/030/031,
voir `docs/qa/rapports/dev-backend-ventes-2026-10-22.md`) avait déjà traité ce cas de la même
façon : retrait définitif du décorateur une fois la correction vérifiée fonctionnellement,
sans le remettre. J'ai suivi ce précédent plutôt que le texte littéral de la consigne de cette
session, pour les 4 tickets réellement corrigés (BUG-017 à BUG-020). Le testeur
`testeur-clients-commissions` reste seul habilité à faire passer ces tickets à `VÉRIFIÉ` — je
n'ai fait que constater que le test passe, pas validé moi-même le ticket.

## Dérive de migrations découverte (hors périmètre, signalée au coordinateur)

En générant la migration de BUG-017, `makemigrations clients` propose **en plus** de :
- retirer/ré-ajouter les contraintes uniques de `SocialContribution`, `SocialDistribution`,
  `SocialDistributionLine` (`AddConstraint` historique dans `clients/migrations/0005_social.py`
  vs `Meta.unique_together` dans le code actuel) ;
- changer leur champ `id` de `AutoField` explicite vers `BigAutoField`
  (`DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'` dans `settings.py`, alors que
  `0005_social.py` avait été écrite avec un `id` `AutoField` explicite).

C'est une dérive **préexistante, indépendante de mon travail** (confirmée en inspectant
`clients/migrations/0005_social.py`, écrite avant cette session) — du même type que la dérive
déjà connue et documentée sur `production`/`treasury` (confirmée aussi présente par
`makemigrations --check --dry-run` sur l'ensemble du projet : `production` et `treasury`
montrent le même type d'écart `unique_together`/`id`). Je ne l'ai **pas corrigée** (hors
périmètre de BUG-017) et j'ai écrit `0006_clientcodesequence.py` à la main pour qu'elle ne
contienne strictement que la création du modèle `ClientCodeSequence`, sans embarquer cette
dérive. À signaler au coordinateur pour ouvrir un ticket dédié (probablement un seul ticket
transverse couvrant `clients`/`production`/`treasury`, migration de nettoyage sans impact de
données — `AddConstraint`↔`unique_together` et `AutoField`↔`BigAutoField` sont équivalents en
base, seule la représentation dans l'état des migrations Django diffère).

## Vérifications finales

- `backend/clients/`, `backend/commissions/` : seuls fichiers applicatifs modifiés
  (`clients/models.py`, `commissions/views.py`) + migration `clients/migrations/0006_clientcodesequence.py`
  + tests existants retouchés uniquement sur la ligne `@expectedFailure` (aucun test affaibli
  ou supprimé, aucune assertion modifiée).
- `python manage.py test clients commissions` → **50/50 OK**.
- `python manage.py test` (suite complète) → `Ran 189 tests ... FAILED (errors=2, expected
  failures=2, unexpected successes=6)`. Aucune de ces anomalies ne concerne `clients` ou
  `commissions` : les 2 erreurs et les 6 « unexpected successes » se situent dans `production`
  et `treasury` (tickets BUG-041, BUG-036, BUG-037 et autres déjà référencés dans le registre,
  hors périmètre de cette mission — vraisemblablement des tickets déjà corrigés par
  `ingenieur-blockchain`/un autre `dev-backend` dont les tests n'ont pas encore eu leur
  décorateur retiré, ou des tickets encore ouverts sur ces modules). Signalé au coordinateur
  pour suivi par l'agent responsable de `production`/`treasury`, pas d'action de ma part
  (hors périmètre explicite de cette mission).
- `python manage.py makemigrations --check --dry-run clients` → signale uniquement la dérive
  préexistante documentée ci-dessus (pas de drift introduit par mon travail : en isolant juste
  le modèle `ClientCodeSequence`, la seule migration manquante avant d'écrire
  `0006_clientcodesequence.py` était bien celle-là, confirmée en comparant avec/sans le nouveau
  modèle dans `models.py`).
- Registre `docs/qa/REGISTRE_BUGS.md` : tableau de suivi et fiches détaillées BUG-017 à
  BUG-021 mis à jour (statuts, cause, fichiers modifiés, test de non-régression, impact).

## Tickets en attente / risques pour le coordinateur

1. **Dérive de migrations `clients`/`production`/`treasury`** (ci-dessus) — à transformer en
   ticket dédié, probablement `dev-backend` en charge transverse, gravité Mineur (pas de risque
   de données, juste un état de migration à nettoyer).
2. **BUG-021** — proposition documentée (champ `Invoice.commission_exempt`), à transformer en
   ticket module Ventes assigné à `dev-backend`/`dev-frontend`.
3. **Suite complète `manage.py test`** : 2 erreurs + 6 « unexpected successes » sur
   `production`/`treasury`, hors périmètre de cette mission — à vérifier par l'agent en charge
   de ces modules avant la clôture globale de la phase 3 round 2.
4. Aucun risque identifié propre à `clients`/`commissions` : les 4 tickets corrigés ont chacun
   un test de non-régression qui échouait avant et passe après, sans affaiblissement de test.
