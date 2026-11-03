# Rapport auditeur-comptable — 2026-11-03 — Vérification de BUG-126 (et déblocage de BUG-123)

Mission : vérification indépendante du correctif de **BUG-126** apporté par le coordinateur
(`backend/production/migrations/0018_bug123_backfill_average_unit_cost.py`, migration inverse
`reset_average_unit_cost` mise à jour en miroir, nouveau test
`backend/production/tests/test_bug126_backfill_exit_unit_price.py`), afin de décider si **BUG-123**
(laissé à `CORRIGÉ` le 2026-11-02 à cause de BUG-126, voir
`docs/qa/rapports/auditeur-comptable-2026-11-02-verif-bug123.md`) peut être repassé à `VÉRIFIÉ`.

## Méthode

Comme pour la vérification précédente (CLAUDE.md §4) : aucune donnée réelle de `data_kiese/` dans ce
scénario, uniquement des données fictives rejouées contre une base de test SQLite jetable
(`python manage.py test`). Reproduction **indépendante**, pas une simple relecture : un scénario à
valeurs et enchaînement différents de celui du coordinateur, exécuté dans un test temporaire
(`backend/production/tests/test_zzz_scratch_verif_bug126.py`), écrit puis supprimé après vérification
— non committé, ce n'est pas un test de régression permanent (celui du coordinateur l'est déjà).

## 1. Relecture de la migration 0018 corrigée

`backfill_average_unit_cost` rejoue l'historique de chaque `ConsumableStock` par
`ConsumableMovement.objects.filter(stock=stock).order_by('created_at', 'pk')` et, pour chaque `EXIT`,
fige désormais `mv.unit_price = running_avg` (le CUMP **tel qu'il était à cet instant précis du
rejeu**, avant d'être modifié par une éventuelle `ENTRY` suivante) puis sauvegarde la ligne
(`mv.save(update_fields=['unit_price'])`) — au lieu de jeter cette valeur comme avant (BUG-126). Seul
le `ConsumableStock.average_unit_cost` final est sauvegardé en fin de boucle, comme avant.

Comparé directement à `ConsumableMovement.save()` (`backend/production/models.py` ~l.410-433), qui
fige `self.unit_price = stock.average_unit_cost` **au moment réel** d'une sortie : **même principe
exactement reconstitué**, aucune divergence entre la logique que la migration rejoue et la logique
réelle qu'elle cherche à reconstituer pour l'historique. La migration inverse
(`reset_average_unit_cost`) a été étendue en miroir :
`ConsumableMovement.objects.filter(movement_type='EXIT').update(unit_price=Decimal('0.00'))`, en plus
de `ConsumableStock.objects.update(average_unit_cost=Decimal('0.0000'))`.

**Conforme.**

## 2. Reproduction indépendante (scénario différent de celui du coordinateur)

Scénario volontairement plus exigeant que `test_bug126_backfill_exit_unit_price.py` : 3 `ENTRY`
encadrant 2 `EXIT` historiques (dégradés à `unit_price=0.00` par `.update()`, en contournant `save()`,
pour simuler exactement l'état d'une ligne créée avant le correctif BUG-123), avec une **troisième**
`ENTRY` placée **après** le second `EXIT` — pour que même ce second `EXIT` ait un CUMP chronologique
différent du CUMP final du stock (dans le test du coordinateur, rien ne suit le second EXIT, donc son
CUMP chronologique coïncide avec le CUMP final — moins discriminant).

Calcul à la main (consommable fictif, valeurs choisies sans rapport avec `data_kiese/`) :

| Mouvement | Quantité | Prix saisi | CUMP résultant | `unit_price` attendu après backfill |
|---|---|---|---|---|
| ENTRY #1 | 10 | 100 000 FC | 100 000,0000 | — |
| EXIT #1 (historique, dégradé à 0) | 3 | — | inchangé (100 000,0000) | **100 000,00** |
| ENTRY #2 | 5 | 130 000 FC | (7×100 000+5×130 000)/12 = **112 500,0000** | — |
| EXIT #2 (historique, dégradé à 0) | 4 | — | inchangé (112 500,0000) | **112 500,0000** |
| ENTRY #3 | 2 | 50 000 FC | (8×112 500+2×50 000)/10 = **100 000,0000** (final) | — |

Exécution : `backend/.venv/Scripts/python.exe manage.py test
production.tests.test_zzz_scratch_verif_bug126 -v 2` → **2 tests, OK** du premier coup. Assertions
clés confirmées :
- `exit_1.unit_price == Decimal('100000.00')` (CUMP à l'instant de EXIT#1, ni 0 ni le CUMP final).
- `exit_2.unit_price == Decimal('112500.0000')` **et** `!= final_cump (100000.0000)` — preuve directe
  que le backfill restampe le CUMP **chronologique** de l'instant précis de chaque sortie, pas le CUMP
  final du stock recalculé en fin de boucle (c'était exactement le défaut que BUG-126 décrivait).
- `stock.average_unit_cost == Decimal('100000.0000')` (CUMP final, inchangé par rapport à avant le
  backfill — seul le comportement sur les EXIT historiques a changé).
- Migration inverse : `average_unit_cost` remis à `0.0000` **et** `unit_price` de l'EXIT remis à
  `0.00` — les deux champs sont bien réinitialisés, pas seulement le CUMP du stock.

**Conforme, confirmé indépendamment.**

## 3. Non-régression

- Suite permanente `backend/production/tests/test_bug126_backfill_exit_unit_price.py` (2 tests, écrite
  par le coordinateur) : relancée isolément, **OK**.
- Suite `production` complète, `finance` complète, `commissions` complète : **OK** (voir point 4).
- Aucun code applicatif modifié par cette mission — uniquement `docs/qa/REGISTRE_BUGS.md`, ce rapport,
  et un test temporaire supprimé avant la fin de la mission (jamais committé).

## 4. Suite de tests complète

Première tentative : `python manage.py test` s'est retrouvé **bloqué** (process quasi inactif,
~0 s de temps CPU consommé sur plus d'une heure). Diagnostic via `tasklist`/`wmic process` :
**4 process Python `manage.py test` tournaient simultanément** sur la machine au même moment
(au moins un autre agent exécutait également des tests en parallèle sur la même base SQLite
partagée) — pattern de contention déjà identifié sous **BUG-112**. Process bloqué arrêté
(`Stop-Process -Force`), confirmé qu'aucun autre process Python ne restait actif
(`tasklist` vide), puis **relance isolée** :

```
Ran 490 tests in 1122.024s

OK
```

**490 tests, 0 échec.** Les 3 échecs `treasury` observés lors de la vérification du 2026-11-02/03
(`test_blocked_delivery_still_leaves_client_bread_counter_incremented`,
`test_normal_sale_delivery_still_blocked_after_report_generated`,
`test_no_new_invoice_affects_an_already_generated_report`) **ne se reproduisent plus** une fois la
contention inter-process éliminée — confirmé qu'il s'agissait bien d'un artefact de contention
partagée (BUG-112), pas d'une régression réelle du verrou de vacation (BUG-036, toujours intact).
Aucun nouveau ticket ouvert sur ce point : conforme à la consigne de la mission (reconfirmer en
isolation avant de qualifier un défaut réel).

## Conclusion et statut des tickets

- **BUG-126** : `VÉRIFIÉ` (auditeur-comptable, 2026-11-03). Le backfill restampe désormais chaque
  `ConsumableMovement` EXIT historique avec son CUMP chronologique exact, jamais le CUMP final ni 0 ;
  la migration inverse réinitialise les deux champs concernés. Confirmé par reproduction indépendante
  avec un scénario distinct de celui du coordinateur.
- **BUG-123** : `VÉRIFIÉ` (auditeur-comptable, 2026-11-03). La seule réserve qui le bloquait
  (incomplétude du backfill sur l'historique, BUG-126) est levée ; tous les autres points déjà validés
  le 2026-11-02 (formule CUMP, figement sur EXIT, non-régression bilan/cash-flow/N-1, performance)
  restent valides sans changement.
- `docs/qa/REGISTRE_BUGS.md` mis à jour : tableau de suivi (lignes BUG-123 et BUG-126 passées à
  `VÉRIFIÉ`) + fiches détaillées complétées avec les notes de vérification datées du 2026-11-03.
- `python manage.py test` complet : **OK, 490 tests, 0 échec** (après élimination de la contention
  inter-process, conformément à la consigne de la mission sur BUG-112).
- Aucune ambiguïté ni contradiction entre documents de référence rencontrée. Aucun code applicatif
  modifié. Aucune donnée réelle `data_kiese/` utilisée ou copiée dans cette mission.

## Fichiers mis à jour par cette mission

- `docs/qa/REGISTRE_BUGS.md` : tableau de suivi (BUG-123, BUG-126 → `VÉRIFIÉ`) + fiches détaillées
  complétées (notes de vérification 2026-11-03).
- `docs/qa/rapports/auditeur-comptable-2026-11-03-verif-bug123-bug126.md` : ce rapport.
- Aucun fichier de code applicatif modifié. Test temporaire de reproduction
  (`backend/production/tests/test_zzz_scratch_verif_bug126.py`) créé puis supprimé avant la fin de la
  mission, jamais committé.
