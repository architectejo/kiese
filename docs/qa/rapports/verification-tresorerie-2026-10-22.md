# Vérification Trésorerie — phase 4 — 2026-10-22

Agent : `testeur-tresorerie` (vérificateur indépendant des correctifs de
`ingenieur-blockchain`/`dev-backend`/`dev-frontend`, CLAUDE.md §7 règle 3).

## Périmètre vérifié

- **BUG-033** — `FacturierReport` Niveau 1 : détail par catégorie de pain.
- **BUG-034** — Clôture confirmée non modifiable (400 sur `PATCH`).
- **BUG-035** — Double clôture → 400 propre au lieu de 500.
- **BUG-036** — Verrouillage de vacation après génération du rapport Niveau 1
  (signal `pre_save` sur `sales.Invoice`, `backend/treasury/signals.py`).
- **BUG-037** — Clôture bloquée si transfert entrant en écart non résolu.
- **BUG-044** — `Treasury.tsx` masque le Livre de Caisse Direction pour les
  rôles non-HQ.
- **BUG-045** — Affichage du détail par catégorie de pain (Niveau 1).
- **BUG-046** — Formulaire de clôture gère le refus `PATCH` sur une clôture
  confirmée.
- **BUG-048** — Message + lien vers les transferts si clôture bloquée par
  BUG-037.

(BUG-047 avait déjà été vérifié par `testeur-ventes` ; BUG-049/050/051
relèvent de `testeur-production`.)

## Méthode

1. Relecture critique indépendante de `backend/treasury/views.py`,
   `models.py`, `signals.py`, `apps.py`, `migrations/0009_...py`, et de
   `frontend/src/pages/dashboard/Treasury.tsx` / `src/api/services.ts`.
2. Scénario de bout en bout dédié à BUG-036 (facture PENDING → livraison →
   rapport Niveau 1 de sa vacation → nouvelle livraison bloquée).
3. Nouveaux tests indépendants écrits dans
   `backend/treasury/tests/test_bug036_signal_side_effects.py` :
   - 5 tests confirmant que le signal `pre_save` de BUG-036 ne casse aucun
     autre flux de sauvegarde de `sales.Invoice` (création normale,
     livraison normale sans rapport existant, annulation d'une facture
     PENDING, resauvegarde anodine d'une facture déjà DELIVERED,
     remboursement créé directement DELIVERED) — **tous passent**.
   - 1 test (`DeliveryBlockedSideEffectTests`) qui a révélé une anomalie
     réelle — voir ci-dessous (**BUG-052**, nouveau ticket ouvert).
4. `python manage.py test treasury production blockchain` relancé en
   intégralité : **62 tests, `OK (expected failures=1)`** — le seul échec
   attendu est le nouveau test de BUG-052.
5. `npx tsc --noEmit` : 0 erreur. `npm run build` (frontend) : build réussi,
   seul avertissement préexistant (chunk JS > 500 kB, sans rapport avec ce
   périmètre).

## Résultats

| Ticket | Verdict |
|---|---|
| BUG-033 | **VÉRIFIÉ** |
| BUG-034 | **VÉRIFIÉ** |
| BUG-035 | **VÉRIFIÉ** |
| BUG-036 | **VÉRIFIÉ pour son périmètre strict** (voir BUG-052 ci-dessous) |
| BUG-037 | **VÉRIFIÉ** (une observation non bloquante signalée, voir ci-dessous) |
| BUG-044 | **VÉRIFIÉ** |
| BUG-045 | **VÉRIFIÉ** |
| BUG-046 | **VÉRIFIÉ** |
| BUG-048 | **VÉRIFIÉ** |

Toutes les fiches détaillées (méthode précise, points vérifiés point par
point) sont consignées dans `docs/qa/REGISTRE_BUGS.md` sous « Vérification
de phase 4 — BUG-033 à BUG-037 » et « ... BUG-044, BUG-045, BUG-046,
BUG-048 ».

## Anomalie trouvée pendant la vérification : BUG-052 (nouveau, OUVERT)

En vérifiant explicitement que le signal `pre_save` de BUG-036 « ne casse
aucun autre flux de sauvegarde de facture », j'ai trouvé un effet de bord
réel et reproductible, **conséquence directe de BUG-036** (pas un défaut
indépendant préexistant — voir justification dans le ticket) :

`Invoice.deliver()` (`backend/sales/models.py`) exécute, dans cet ordre :
1. mise à jour **immédiatement sauvegardée** de
   `client.total_breads_received`/`category` (`client.save(...)`) ;
2. `self.save()` — c'est exactement cette étape que le signal BUG-036
   bloque (`ValidationError`) quand la vacation est déjà rapportée.

Ni `Invoice.deliver()` ni l'action `InvoiceViewSet.deliver`
(`backend/sales/views.py`, contrairement à `InvoiceViewSet.create`, qui est
`@transaction.atomic`) n'entourent cette séquence d'une transaction. Une
livraison bloquée laisse donc le compteur de pains du client durablement
incrémenté (et sa catégorie potentiellement changée) **alors qu'aucune
livraison n'a réellement eu lieu** — la facture, elle, reste bien `PENDING`
en base.

Reproduit par test (échoue avant toute correction, comme attendu) :
`backend/treasury/tests/test_bug036_signal_side_effects.py::DeliveryBlockedSideEffectTests::test_blocked_delivery_still_leaves_client_bread_counter_incremented`
— marqué `@expectedFailure # BUG-052`.

Piste de correction suggérée (non appliquée — je ne corrige pas le code
applicatif) : encapsuler tout le corps de `Invoice.deliver()` dans
`transaction.atomic()`, plutôt que de réordonner les deux écritures (plus
robuste contre toute future exception entre les deux `save()`).

Ticket ajouté au registre : **BUG-052**, Majeur, module Trésorerie/Ventes,
composant backend, statut `OUVERT`, assigné à aucun dev pour l'instant.

## Observation non bloquante (BUG-037 / BUG-048)

Les instructions de vérification manuelle rédigées par `dev-frontend` pour
BUG-048 suggèrent de « résoudre l'écart du transfert (confirmer la
réception avec la quantité correcte), retenter la clôture ». En relisant
`production/views.py::BreadTransferViewSet.confirm_reception`, j'ai constaté
que cette action n'est appelable qu'au statut `RESPONDED` — une fois le
transfert passé à `DISPUTED`, il n'existe aucune action backend pour le
« corriger » : le seul chemin qui lève le blocage de clôture est
l'annulation du transfert (`CANCELLED`, explicitement exclu du calcul de
l'écart par `_unresolved_incoming_transfer_gap`). Cela n'invalide ni
BUG-037 ni BUG-048 (l'objet réel — bloquer la clôture tant que l'écart
existe, et afficher clairement le message — est bien rempli), mais la
démonstration précise suggérée dans les notes de BUG-048 n'est pas
réalisable telle que décrite avec les actions actuellement exposées par
l'API `production`. Signalé pour information du coordinateur, périmètre
`production` (pas `treasury`), pas de ticket supplémentaire ouvert sur ce
point précis.

## Fichiers créés par cette vérification

- `backend/treasury/tests/test_bug036_signal_side_effects.py` (nouveau) —
  6 tests (5 verts, 1 `@expectedFailure` référençant BUG-052).

## Fichiers modifiés

- `docs/qa/REGISTRE_BUGS.md` — passage de BUG-033 à BUG-037 à `VÉRIFIÉ`
  avec méthode détaillée ; passage de BUG-044/045/046/048 à `VÉRIFIÉ` avec
  méthode détaillée ; ouverture de **BUG-052** (OUVERT, Majeur).

Aucun fichier de code applicatif modifié (CLAUDE.md §7 règle 2).
