# Vérification Trésorerie — ronde 2 — 2026-10-22

Agent : `testeur-tresorerie` (vérificateur indépendant des correctifs de
`dev-backend`, CLAUDE.md §7 règle 3).

## Périmètre vérifié

- **BUG-053** — `Invoice.deliver()` non-atomique : une livraison bloquée par
  le signal `pre_save` de BUG-036 (vacation déjà rapportée) laissait une
  mise à jour fantôme et durable de `client.total_breads_received`/
  `category`, alors qu'aucune livraison n'avait réellement eu lieu.

Correctif relu : `docs/qa/rapports/dev-backend-residuel-phase4-2026-10-22.md`
et la section « Correction » sous BUG-053 dans
`docs/qa/REGISTRE_BUGS.md`.

## Méthode

1. Relecture indépendante du code actuel :
   - `backend/sales/models.py::Invoice.deliver()` : confirmé que tout le
     corps de la méthode (affectation de `livreur`/`status`/`delivered_at`,
     incrément de `client.total_breads_received`, `client.refresh_category()`,
     `client.save(...)`, et enfin `self.save()` — l'étape que le signal
     `pre_save` de BUG-036 peut bloquer) est désormais à l'intérieur d'un
     seul `with transaction.atomic():`. Un rollback déclenché par le signal
     au moment de `self.save()` annule donc aussi la mise à jour du client
     exécutée plus haut dans la même méthode.
   - `backend/sales/views.py::InvoiceViewSet.deliver` : confirmé décorée
     `@transaction.atomic` (symétrique à `InvoiceViewSet.create`, déjà
     atomique). `log_activity`/`create_notification` appelés après
     `invoice.deliver(...)` dans la vue font désormais partie de la même
     unité atomique.
2. Relance ciblée du test de preuve existant :
   `python manage.py test treasury.tests.test_bug053_signal_side_effects -v 2`
   → **6/6 tests `OK`**, y compris
   `DeliveryBlockedSideEffectTests::test_blocked_delivery_still_leaves_client_bread_counter_incremented`,
   qui passe désormais sans `@unittest.expectedFailure` (décorateur retiré
   par `dev-backend`, assertion de fond inchangée — pas d'affaiblissement
   du test). Les 5 tests `SignalDoesNotAffectNormalFlowsTests` (création
   normale, livraison normale, annulation, resauvegarde d'une facture déjà
   livrée, remboursement direct `DELIVERED`) continuent de passer sans
   régression.
3. **Reproduction indépendante du scénario de bout en bout** demandé par la
   mission, dans un fichier temporaire
   `backend/treasury/tests/test_verif_tmp_bug053_e2e.py` (créé, exécuté,
   puis supprimé après confirmation — jamais versionné, aucun fichier
   applicatif ni fichier de test permanent modifié) :
   1. Facture 1 (client X, équipe A) livrée normalement via
      `invoice.deliver(livreur)` → `client.total_breads_received` passe
      de 0 à 5.
   2. Gérant génère le rapport Niveau 1 pour (nœud, équipe A, aujourd'hui)
      via `POST /api/treasury/reports/generate/` → `FacturierReport` créé.
   3. Facture 2 (même client, même vacation) créée puis sa livraison est
      tentée → `ValidationError` levée par le signal BUG-036, facture
      reste `PENDING`.
   4. `client.total_breads_received` et `client.category` relus en base :
      **strictement inchangés** par rapport à l'état avant la tentative
      bloquée (contrairement au comportement avant correction, où
      `total_breads_received` serait passé à 14 malgré le refus de la
      livraison).
   5. Facture 3 (même client, équipe B, vacation différente et pas encore
      rapportée) livrée normalement → `ValidationError` non levée,
      `client.total_breads_received` correctement incrémenté de 11
      (passe à `before + 11`) — confirme que le correctif ne casse pas le
      flux normal de livraison.
   - Résultat : **1/1 test `OK`** avant suppression du fichier temporaire.
4. Suite complète relancée : `python manage.py test treasury sales -v 2`
   → **67 tests, `OK`, 0 échec, 0 succès inattendu**. Quelques tracebacks
   `OperationalError: database table is locked: core_config` visibles dans
   la sortie verbeuse proviennent du test de concurrence à plusieurs
   threads déjà existant sur le livre de caisse (retry SQLite attendu dans
   ce mécanisme) — sans incidence sur le résultat final `OK`, aucun test en
   échec.

## Points vérifiés spécifiquement

- La transaction englobe bien **les deux écritures** (mise à jour du
  client ET sauvegarde de la facture) — ce n'était pas garanti avant
  correction puisque la mise à jour du client était commise en base avant
  d'atteindre `self.save()`.
- Aucune régression sur le flux normal de livraison : une livraison qui
  réussit continue d'incrémenter correctement `total_breads_received` et de
  recalculer `category` (`client.refresh_category()`), que ce soit via la
  méthode `Invoice.deliver()` directement ou via l'action API
  `POST /api/sales/invoices/<id>/deliver/`.
- Aucun changement de contrat d'API observé (codes HTTP et format
  `{"detail": "..."}` inchangés pour le cas de blocage, déjà vérifié sous
  BUG-036).
- Aucun fichier applicatif modifié pendant cette vérification. Le seul
  fichier créé pour la reproduction indépendante
  (`test_verif_tmp_bug053_e2e.py`) a été supprimé après usage et n'apparaît
  plus dans le dépôt.

## Conclusion

**BUG-053 : VÉRIFIÉ.** Le correctif de `dev-backend` (encapsulation
complète d'`Invoice.deliver()` dans `transaction.atomic()` + action
`InvoiceViewSet.deliver` décorée `@transaction.atomic`) résout bien
l'anomalie : une livraison bloquée par le verrouillage de vacation
(BUG-036) ne laisse plus aucune trace fantôme sur le compteur de pains ou
la catégorie du client, et le flux normal de livraison n'est pas affecté.
Le registre (`docs/qa/REGISTRE_BUGS.md`) a été mis à jour : tableau de
suivi (ligne BUG-053 → `VÉRIFIÉ`) et section « Vérification » ajoutée sous
la fiche détaillée BUG-053.

## Commandes exécutées

```
cd backend
python manage.py test treasury.tests.test_bug053_signal_side_effects -v 2   # 6 tests, OK
python manage.py test treasury sales                                        # 67 tests, OK
```

## Fichiers consultés / modifiés

- Consultés (sans modification) : `backend/sales/models.py`,
  `backend/sales/views.py`, `backend/treasury/signals.py`,
  `backend/treasury/tests/test_bug053_signal_side_effects.py`.
- Créé puis supprimé (vérification, non versionné) :
  `backend/treasury/tests/test_verif_tmp_bug053_e2e.py`.
- Modifié : `docs/qa/REGISTRE_BUGS.md` (statut BUG-053 → `VÉRIFIÉ` dans le
  tableau de suivi + section « Vérification » ajoutée sous la fiche
  détaillée).
