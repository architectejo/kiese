# Rapport dev-backend — 2026-11-15

Reprise d'un lot laissé inachevé (arbre de travail non commité : clients, commissions, core, sync, migrations core/0020, clients/0010, commissions/0005). Décisions client du 2026-11-14 appliquées : signe « − » accepté pour un paiement ; carte client supprimée ; période de paie = mois civil (inchangé) ; conformité aux fichiers `data_kiese/` (lecture seule, aucune donnée réelle copiée).

## Résultats de test

| Run | Commande (DB_NAME isolé, `db.sqlite3` non touché) | Résultat |
|---|---|---|
| Étape 1 (avant étapes 2 et 3) | `manage.py test commissions clients core` | `Ran 328 tests in 850.673s` — `OK (skipped=1)` |
| Final | `manage.py test` (suite complète) | `Ran 1304 tests in 2949.122s` — `OK (skipped=1, expected failures=1)` |
| Migrations | `manage.py makemigrations --check --dry-run` | `No changes detected` |

Aucun test supprimé ni affaibli. Les tests réécrits l'ont été parce que la règle qu'ils figeaient a été remplacée par une décision client (liste ci-dessous, valeurs recalculées à la main en Decimal).

## Étape 1 — BUG-289, 291, 292, 293 : CORRIGÉ
Relecture du code existant : cohérent.
- Net = CM − (dette + sociale + imprimés + autre + report) ; `deduction_carte` fixée à 0 dans `ClientCommission.compute`, `net_carte == net_ordi`, colonnes conservées dans serializers/listing/payroll (valeur 0, aucun calcul de carte restant : vérifié par recherche dans `commissions`, `clients`, `core`, `sales`, `treasury`, `finance`).
- BUG-289 : `Node.monthly_social_contribution` (0 par défaut, B2 = 2 000), `Client.cotisation_sociale` nullable, `effective_cotisation_sociale`.
- BUG-292 : remise = 0,25 % de la commande, non déduite. BUG-293 : BP créditrice ajoutée au net.
- Test de non-régression « net sans carte » : `commissions/tests/test_bug289_292_293_2026_11_14.py::Bug291SansCarte` (déjà présent, vérifié, vert).
- Registre mis à jour ; impact frontend consolidé dans le nouveau ticket **BUG-301** (masquer CARTE, réglage cotisation par boulangerie, cotisation client optionnelle, dette négative affichée comme crédit, motif, remise annuelle).

## Étape 2 — BUG-290 (paiements négatifs) : CORRIGÉ
- `sales/serializers.py` : `payment_amount` sans borne basse (BUG-209 levé) ; champ facultatif `motif`.
- `sales/views.py` : versement sans commande (`is_debt_repayment`) accepte un montant négatif ; seul 0 est refusé (BUG-213 réduit à « nul »). BP après = BP avant + commande − paiement. Blocage de crédit extrait en `InvoiceViewSet._credit_block_response` et appliqué aussi au versement négatif : un paiement négatif ne contourne pas le blocage (403 + notification) ; un client sous le plafond reste libre de sortir de la caisse jusqu'au plafond.
- `sales/models.py` : `Invoice.motif` (`RETRAIT_EPARGNE`, `EMPRUNT_BOULANGER`, `MANQUANT_EQUIPE`, `AUTRE`, vide par défaut), migration `sales/0009_bug290_invoice_motif` (AddField simple, réversible).
- Cohérences vérifiées par test : `daily_summary` (CASH −5 000, CREDIT +5 000), rapport facturier (cash signé), clôture (`net_cash` négatif) et livre de caisse (écriture en SORTIE), commissions (lignes sans commande exclues, vente avec paiement négatif conservée), épargne (−10 000 → −6 000 pour −4 000), reçu (champs de la facture).
- Tests : `sales/tests/test_bug290_paiements_negatifs_2026_11_15.py` (nouveaux, verts). Réécrits (refus → acceptation) : `test_vague1_corrections_ventes::test_versement_negatif_accepte`, `test_vague1_db_ventes_2026_11_12::test_versement_negatif_accepte_sur_facture` et `..._sur_remboursement`.
- Point ouvert (non bloquant) : nature de la ligne K3 n° 54 du 13/08 (−13 000 FC).

## Étape 3 — BUG-295 (remise annuelle) : CORRIGÉ
- Constat : INDICE × TARIF + MÉRITE existait déjà dans `SocialDistribution` / `SocialDistributionLine` ; le défaut était `ClientCommission.annual_bonus = pains × 0,025` ajouté au net si « incorporée ». `finance` n'utilise pas `annual_bonus`.
- `commissions/models.py::compute` : `annual_bonus = 0`, net sans remise annuelle (colonnes et flag conservés pour l'API).
- Caisse sociale : nouvelle action `POST /api/clients/distributions/<id>/refresh_indices/` (INDICE = cotisations payées de l'année, TOTAL SOCIAL, MÉRITE conservé) ; changement de `tarif` recalcule les lignes d'une distribution ouverte ; tarif d'une distribution clôturée figé (400). Aucune migration.
- Tests : `clients/tests/test_bug295_remise_annuelle_2026_11_15.py` (6 tests, ex. 10 × 700 + 1 500 = 28 500 ; tarif 600 → 27 500 ; INDICE 11 → 31 200). Réécrits car ils figeaient l'ancienne règle : `commissions/tests/test_formulas.py` (3 tests `DeductionAndAnnualBonusTests`), `test_bug058_independent_verification::test_annual_bonus_untouched_by_bug058_fix`, `test_vague2_db_commissions_2026_11_12` (assertions de remise annuelle). BUG-263 à 268 : tests inchangés et verts.

## Fichiers modifiés par cette session
`backend/sales/{models,serializers,views}.py`, `backend/sales/migrations/0009_bug290_invoice_motif.py` (nouveau), `backend/commissions/models.py`, `backend/clients/{serializers,views}.py`, tests listés ci-dessus, `docs/qa/REGISTRE_BUGS.md` (BUG-290, 295 CORRIGÉ ; BUG-301 ouvert). En plus du lot précédent (non revu ligne à ligne hors étape 1) : `clients/models`, `core/models`, `sync/services`, migrations `core/0020`, `clients/0010`, `commissions/0005`.

## Risques et points à valider
1. `clients/0010_bug289` : les clients restés à 3 000,00 passent à NULL (suit la boulangerie) ; une personnalisation volontaire à 3 000 est indiscernable.
2. Commissions déjà générées : `annual_bonus` / net restent ceux d'avant tant qu'elles ne sont pas régénérées (payées/clôturées jamais modifiées).
3. `total_credit_sales` du rapport facturier compte un retrait comme variation de BP (+ montant), aligné sur `daily_summary` et les Excel ; à confirmer par testeur-tresorerie si le client préfère l'exclure.
4. TARIF : valeur par défaut 700 FC à la création d'une distribution (reste de K2 2023) ; la direction doit le saisir chaque année.
5. `Config.annual_bonus_rate` inutilisé (champ conservé, pas de migration).
6. Données : `backend/db.sqlite3` non modifié (mtime inchangé).
7. Incident de procédure, corrigé : un ancien script de scratchpad (`patch_reg.py`, mêmes nom que mon script) a été lancé par erreur et a dupliqué 8 notes sur BUG-200 à 207 dans le registre ; doublons retirés (`git diff` du registre revenu à l'état antérieur, hors mes ajouts).

## Tickets
- Passés à CORRIGÉ : BUG-289, 290 (volet backend), 291, 292, 293, 295. Aucun passé à VÉRIFIÉ.
- Ouvert : BUG-301 (dev-frontend).
- Inchangés : BUG-285, 294, 296 (À CLARIFIER).
