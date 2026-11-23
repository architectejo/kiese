# Rapport dev-backend (Dev B) d28 - 2026-11-23

BUG-919 a 928 : CORRIGES (les `@expectedFailure` de `production/tests/test_verif_production_a9_v9.py` sont retires, assertions inchangees ; les 15 tests passent). Verification par le testeur d'origine.

## Nouveau contrat d'identifiant des lignes poussees (BUG-919)

L'`id` envoye par un poste pour une ligne (PK entiere locale) n'est plus jamais une cle cloud. Pas de migration.

- `ProductionSessionLine` : cle naturelle `(session, bread_price, source)` (unique en base). `id` ignore. Absente `source` = `DECLARED`.
- `BreadTransferLine` : cle naturelle `(transfer, bread_price)` (unique en base). `id` ignore.
- `InvoiceLine` (pas de contrainte d'unicite possible) : l'`id` est un indice. Il designe la ligne cloud de meme PK seulement si elle appartient a la facture indiquee. Id libre : la ligne est creee avec cet id (compatibilite). Id deja pris par la ligne d'une autre facture (collision entre postes) : ligne cherchee par `(facture, categorie)`, sinon creee avec une PK auto-attribuee.
- Rejeu idempotent, aucune collision entre deux postes. Lignes deja synchronisees (id legacy) retrouvees par cle naturelle : pas de doublon au premier envoi apres correctif.
- Limite connue : deux lignes de meme categorie sur une meme facture ET collision d'id avec un autre poste sont indiscernables au rejeu (cas tres rare). Une vraie cle stable (UUID de ligne) demanderait une migration + une evolution du poste : a ouvrir si le client veut ce cas.
- `sync_now.py` : envoie maintenant `source` pour les lignes de fournee (sans cela une ligne CARRYOVER aurait ecrase la ligne DECLARED). Un poste non mis a jour envoie sans `source` : traite comme DECLARED.

## Corrections (fichier : `backend/sync/services.py`)
- 920 : ligne en double. Fournee : meme cle avec une autre quantite = mise a jour si la fournee est ouverte (utile aux incrementes de livraison), REJECTED si cloturee. Transfert : l'emettrice qui renvoie une autre `quantity_sent` est REJECTED. Plus de `IntegrityError` avalee.
- 921 : transfert CONFIRMED/CANCELLED : ajout de ligne REJECTED ; `quantity_received` deja renseignee non reecrivable (premier remplissage permis). Exception : le lot qui termine le transfert (transfert ajoute a `_batch_terminal_parents`).
- 922 : `from_node == to_node` refuse. 928 : `quantity_sent`/`quantity_received` de transfert et de ligne bornes 0..2e9 (`_sync_int`).
- 923 : `closed_at` futur refuse (creation et transition).
- 924 : les totaux de fournee ne sont plus copies ; `compute_totals()` apres creation et a chaque ligne poussee/modifiee. `sac_value_fc_used` borne a 100 000 000. Une fournee sans ligne declare 0 FC.
- 925 : `BreadDisposal` quantite <= 1 000 000, valeur totale <= 9 999 999 999 (bornes REST).
- 926 : `consumable_type` bien forme (`[A-Za-z0-9_-]{1,10}`), `unit` str <= 20. Pas d'obligation d'appartenir a `ConsumableType` : `test_sync_bug004_extension` pousse `SEL` (non seede) et BUG-729 couvre ce point (`@expectedFailure` existant). A trancher avec le coordinateur.
- 927 : `Invoice.team` dans `{'', 'A', 'B'}` (vide conserve pour les anciennes factures).

## Tests
`production.tests.test_verif_production_a9_v9`, `test_verif_production_a8_v8`, tout `sync`, `test_sync_inventaire_v2_a3` : 309 tests, 2 echecs `sync.tests.test_sync_social` (total_payer 7400 vs 1400), identiques avant mes modifications (verifie par `git stash`) : hors perimetre, a ouvrir cote clients. `makemigrations --check` : aucun changement. Log : `$TEMP/d28.log`.

## Risques
- Contrat d'API sync : changement de comportement des lignes (voir plus haut) ; aucun changement de schema. Pas de ticket frontend.
- Mise a jour d'une ligne de fournee ouverte par un rejeu perime : ecrase par la derniere valeur recue (chaque push porte l'etat complet du poste).
