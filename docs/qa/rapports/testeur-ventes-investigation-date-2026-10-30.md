# Investigation — écart constant d'un jour, 4 tests `sales` (2026-10-30)

## Contexte
testeur-clients-commissions a signalé que 4 tests dans `backend/sales/tests/` échouent de façon
reproductible même en relance isolée (quelques secondes) bien après minuit, avec un écart constant
d'un jour — infirmant l'hypothèse initiale de dev-backend (rapport BUG-088) d'une simple flakiness
de traversée de minuit pendant l'exécution d'une suite longue (~14 min).

Fichiers concernés :
- `backend/sales/tests/test_bug083_backdated_sales.py`
- `backend/sales/tests/test_bug083_verification_2026_10_29.py`
- `backend/sales/tests/test_e2e_normal_flow_2026_10_29.py`

## Reproduction
```
cd backend
python manage.py test sales.tests.test_bug083_backdated_sales \
  sales.tests.test_bug083_verification_2026_10_29 \
  sales.tests.test_e2e_normal_flow_2026_10_29 -v 2
```
4 échecs, tous de la même forme (`attendu` = date locale demandée, `obtenu` = date locale − 1 jour) :
- `test_backdated_delivery_date_accepted_on_deliver_action` : `2026-10-24 != 2026-10-25`
- `test_omitting_delivered_at_keeps_default_now_behaviour` : `2026-10-29 != 2026-10-30`
- `test_backdated_invoice_and_delivery_store_exact_requested_dates` : `2026-10-26 != 2026-10-27`
- `test_full_invoice_delivery_receipt_cycle_without_any_date_field` : `2026-10-29 != 2026-10-30`

Dans les 4 cas, la valeur obtenue est systématiquement exactement **1 jour en retard** sur la valeur
attendue — et uniquement sur des assertions portant sur `invoice.delivered_at` (jamais
`invoice.invoice_date`).

## Cause racine
`settings.TIME_ZONE = 'Africa/Kinshasa'` (UTC+1), `USE_TZ = True`. À l'heure où l'investigation a été
menée (~00h49 heure locale, le 2026-10-30) :
```
python date.today()      -> 2026-10-30   (local, Africa/Kinshasa)
python datetime.utcnow() -> 2026-10-29 23:49  (UTC)
```
`delivered_at` est un `DateTimeField` *aware*, stocké en UTC. Les 4 assertions en échec appelaient
`.date()` **directement** sur cet objet aware — ce qui renvoie la date dans le fuseau porté par
l'objet, c'est-à-dire **UTC**, jamais reconvertie vers l'heure locale. Entre 00h00 et 01h00 heure
locale (Kinshasa = UTC+1), la date locale a déjà basculé au jour suivant alors que la date UTC ne
l'a pas encore fait : `.date()` nu renvoie donc systématiquement « hier » par rapport à la date
locale attendue par le test, pour toute heure comprise dans cette fenêtre d'une heure — peu importe
la durée d'exécution de la suite. Ce n'est donc ni une traversée de minuit en cours d'exécution
(hypothèse de dev-backend), ni une date codée en dur mal calculée : c'est une confusion entre
« date calendaire locale » (ce que le test veut vérifier) et « date dans le fuseau UTC de l'objet
aware » (ce que `.date()` nu renvoie réellement).

Ceci correspond précisément à l'hypothèse (b)/(c) du mandat : confusion entre
`timezone.now().date()` (UTC) et `timezone.localdate()`/`timezone.localtime(...).date()` (local).

## Défaut de test ou défaut applicatif ?
**Défaut de test**, confirmé par relecture du code applicatif :
- `sales/views.py::_combine_date_with_now_time()` construit déjà le `datetime` aware correctement, à
  partir de `timezone.localtime(timezone.now())` (heure locale), puis `timezone.make_aware(combined,
  now.tzinfo)` avec le tzinfo local.
- `Invoice.deliver()` (`sales/models.py`) utilise `timezone.now()` (instant UTC correct, comme il se
  doit pour un horodatage technique) quand `delivered_at` n'est pas fourni.
- `core/utils.py::validate_requested_date` et tous les usages dans `sales/views.py` pour les champs
  `DateField` (`invoice_date`) utilisent `timezone.localdate()`, pas `timezone.now().date()`.

Aucune confusion `now().date()` vs `localdate()` n'a été trouvée côté application. Le problème était
uniquement dans les 4 assertions de test, qui appelaient `.date()` sur un `datetime` aware sans le
reconvertir à l'heure locale au préalable — alors que c'est bien la date **locale** que les
scénarios métier (BUG-083, « ventes passées ») cherchent à vérifier.

## Correction appliquée
Remplacement de `invoice.delivered_at.date()` par `timezone.localtime(invoice.delivered_at).date()`
dans les 4 assertions concernées (import `from django.utils import timezone` ajouté dans les 3
fichiers) :
- `backend/sales/tests/test_bug083_backdated_sales.py`
- `backend/sales/tests/test_bug083_verification_2026_10_29.py`
- `backend/sales/tests/test_e2e_normal_flow_2026_10_29.py`

Aucun code applicatif modifié (conformément à CLAUDE.md §7, règle 2).

## Vérification
- Les 3 fichiers relancés isolément : **16/16 tests OK**.
- `python manage.py test sales` (suite complète) : **58/58 tests OK**, aucun échec résiduel.

## Registre
Note ajoutée dans `docs/qa/REGISTRE_BUGS.md`, section « Investigation complémentaire —
testeur-ventes (2026-10-30) », juste après la conclusion de BUG-088 (pas de nouveau ticket ouvert :
aucun défaut applicatif identifié ; corrige explicitement l'hypothèse erronée de dev-backend sur la
traversée de minuit).

## Fichiers touchés
- `d:\Projects\kiesse\backend\sales\tests\test_bug083_backdated_sales.py`
- `d:\Projects\kiesse\backend\sales\tests\test_bug083_verification_2026_10_29.py`
- `d:\Projects\kiesse\backend\sales\tests\test_e2e_normal_flow_2026_10_29.py`
- `d:\Projects\kiesse\docs\qa\REGISTRE_BUGS.md`
