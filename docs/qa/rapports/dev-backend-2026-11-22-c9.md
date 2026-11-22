# Rapport dev-backend, 2026-11-22 (c9) : finance, BUG-850 à BUG-854

Périmètre : `backend/finance/` uniquement. Aucun commit ni push. Aucune migration.

## Tickets traités (tous CORRIGÉ, jamais VÉRIFIÉ)

| Ticket | Cause | Correction |
|---|---|---|
| BUG-851 (Majeur) | DOC 1 lisait `inv.client.code` avec `client=None` (CLIENT DIVERS) : 500 | Agrégat partagé `_doc1_aggregate` ; ligne « CLIENT DIVERS » (code vide, BP 0, taux CM 0) pour `report` et `export` |
| BUG-852 | `FinancialYear.year` sans borne : `year=0` puis états en 500 | `FinancialYearSerializer.validate_year` : 2000 à 2100, 400 en français (POST et PATCH) |
| BUG-853 | CSV DOC 1 : cellules texte écrites brutes | `_csv_safe` : apostrophe devant `= + - @ tab CR` sur code et client ; les nombres (BP négatif) restent intacts |
| BUG-854 | `debt_after` de la facture la plus récente par date : faux avec facture antidatée | BP fin mois = BP d'ouverture non tracée + somme des `debt_delta` (non annulées, date <= fin du mois), comme BUG-820 |
| BUG-850 | Bilan d'un exercice clos excluait `NOT_SERVED` alors que le versement conservé réduit `current_debt` | Seule `CANCELLED` est exclue ; pas de décision métier nécessaire (la règle BUG-318 est déjà tranchée) |

## Tests

- Nouveau : `backend/finance/tests/test_bug850_854.py` (10 tests). Avant correction : 6 échecs + 1 erreur ; après : OK.
- `manage.py test finance --noinput` : 142 tests, 0 échec, 6 succès inattendus (les marques à retirer, ci-dessous) et 6 échecs attendus restants (tests historiques hors périmètre).
- `manage.py check` OK ; `makemigrations --check` : aucun changement.

## Marques `@expectedFailure` à retirer (fichier `test_audit_c_cycle3_c.py`, non modifié)

1. `test_not_served_invoice_with_kept_payment_matches_current_debt` (BUG-850)
2. `test_expired_pending_invoice_matches_current_debt` (BUG-850)
3. `test_doc1_csv_cell_starting_with_equals_is_neutralised` (BUG-853)
4. `test_doc1_with_client_divers_invoice` (BUG-851)
5. `test_financial_year_create_rejects_absurd_year` (BUG-852)
6. `test_doc1_bp_end_of_month_with_backdated_invoice_equals_real_bp` (BUG-854)

À conserver : `test_financial_year_edge_values_do_not_crash` (BUG-852). Il crée `year=0` par l'ORM, en contournant le serializer, puis attend 200 sur les états. Il ne peut passer que si les fonctions d'états tolèrent N-1 hors bornes de `date()` ; non fait (hors du périmètre « validation à la saisie »). Le testeur peut soit le réécrire pour passer par l'API, soit demander de durcir les états.

## Risques et points d'attention

- BUG-854 : la BP d'ouverture est déduite (`current_debt` - somme de tous les `debt_delta` non annulés). Toute variation de `current_debt` sans facture (retenue hors facture, correction manuelle) est donc traitée comme ouverture et apparaît à tous les mois. Cohérent avec la limite déjà documentée pour BUG-820.
- BUG-854 : une requête de plus par appel DOC 1 (factures des clients du mois, sans N+1) ; le test de performance existant (`Verif3Performance`) reste vert.
- BUG-852 : les années déjà en base hors 2000-2100 ne sont pas migrées ; seule la saisie est contrôlée.
- Fins de ligne CRLF d'origine conservées dans `views.py` et `serializers.py`.

## Fichiers modifiés

- `backend/finance/views.py`, `backend/finance/serializers.py`
- `backend/finance/tests/test_bug850_854.py` (nouveau)
- `docs/qa/REGISTRE_BUGS.md` (lignes du tableau BUG-850 à 854 et note dans la fiche)
