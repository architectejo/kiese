# Rapport — testeur-production — 2026-10-22

## Mission

Audit du périmètre Production & Stocks assigné par le ticket `BUG-014`
(`docs/qa/REGISTRE_BUGS.md`) : remarque.md lignes 1-6, 14-32, 90, 118-127,
142-146, 158, 169-170, 194-198 + CLAUDE.md §5.4 dans son ensemble (valeur du
sac, écart manquant/excédent, catégories de pains configurables,
consommables décimaux, transferts inter-boulangeries en 3 temps, somme nulle
au niveau groupe, pains non valorisés, réconciliation).

Consigne respectée : aucune modification de code applicatif. Tout le travail
est dans `backend/production/tests/` (+ `backend/core/testing.py`, fabriques
partagées — déjà en partie écrit par un autre agent en parallèle, j'ai
réutilisé sa version sans la modifier).

## Méthode

1. Lecture du code réel : `backend/production/{models,views,serializers,urls}.py`,
   `backend/core/models.py` (`Node`, `Config`, `BreadPrice`), `backend/core/permissions.py`,
   `frontend/src/pages/dashboard/Production.tsx`.
2. Écriture de 24 tests Django dans `backend/production/tests/` :
   - `test_fournees.py` — valeur/sac, manquant/excédent, historique vs changement de valeur du sac, catégories de pains configurables, consommables décimaux décrémentés.
   - `test_consumables.py` — stock restant = initial+entrées−utilisé, liste des consommables à l'approvisionnement, inventaire physique, alerte de surconsommation, stock négatif.
   - `test_transfers.py` — workflow en 3 temps, somme groupe inchangée, contrôle de nœud, double confirmation, transfert multi-lignes.
   - `test_disposal_reconciliation.py` — catégorisation des pains non valorisés, réconciliation production/ventes.
3. `python manage.py test production` → **OK, 24 tests, 9 `expectedFailure` (anomalies confirmées), 15 passants (comportements conformes)**.
4. Mise à jour de `remarque.md` (marques `[c]`) et de `docs/qa/REGISTRE_BUGS.md` (clôture de BUG-014, ouverture de BUG-038 à BUG-043).
5. Vérification qu'aucun doublon n'est créé avec les tickets déjà ouverts par les autres testeurs qui tournaient en parallèle sur la même session (`BUG-023` testeur-permissions, `BUG-037` testeur-tresorerie) : 3 de mes constats recoupent exactement leur périmètre — je n'ai pas ouvert de nouveau ticket pour ceux-là, j'ai ajouté des tests de non-régression côté `production` référençant leur ticket.
6. `python manage.py test` (suite complète) exécuté pour information : 166 tests, 12 échecs/2 erreurs hors de mon module (clients/core/sales, travaux en cours d'autres agents dans la même session), **aucun dans `production`**. Je n'ai pas touché à ces modules (hors mandat).

## Résultat détaillé

### Conforme (marqué `[c]` dans remarque.md)

- **Calcul en valeur** : `theoretical_yield = sacs × Node.sac_value_fc` (ou `Config.sac_value_fc` par défaut), écart signé manquant (négatif) / excédent (positif) correct.
- **Liste des consommables disponible à l'approvisionnement** : `ConsumableStockViewSet._ensure_stock_accounts()` auto-crée les comptes manquants pour chaque `ConsumableType` actif dès le premier `GET /stocks/`, y compris pour un type ajouté après coup — confirme que la correction récente de cette session (sur ce même viewset) fonctionne bien de bout en bout pour l'utilisateur.
- **Décrément des consommables à la fournée** : `ProductionSessionViewSet.perform_create` → `_record_consumable_exits` crée un `ConsumableMovement` EXIT par consommable utilisé (farine auto-dérivée + sel/levure/huile envoyés dans `consumables_used`).
- **Décimales** : sel en grammes, levure en paquets (0,25 testé), huile en litres (0,33 testé) — `DecimalField(max_digits=10, decimal_places=3)`, aucun arrondi destructeur.
- **Stock de pains incrémenté par la fournée** et **transfert inter-boulangeries en 3 temps** (A demande → B répond positif/négatif → A confirme réception) : workflow exact demandé par remarque.md l.198, multi-lignes, somme du stock groupe inchangée après une validation complète, double confirmation rejetée proprement (400, pas de double mouvement).

### Anomalies confirmées (nouveaux tickets)

| Ticket | Résumé | Gravité |
|---|---|---|
| BUG-038 | Changer `Node.sac_value_fc` puis modifier (même pour un simple commentaire) une fournée déjà déclarée recalcule son `theoretical_yield`/`yield_gap` avec la **nouvelle** valeur — historique faussé. | Majeur |
| BUG-039 | `BreadPrice.category` est un `TextChoices` figé à 4 valeurs (MINI/MOYEN/GRAND/PREMIUM) + `unique=True` : impossible d'ajouter une 5ᵉ catégorie (ex. pain 200 FC) demandée explicitement deux fois par le client. | Majeur |
| BUG-040 | Aucune alerte de surconsommation d'un consommable par rapport à la moyenne par sac — fonctionnalité absente. | Mineur |
| BUG-041 | Une sortie de consommable dépassant le stock disponible n'est ni refusée ni signalée (stock négatif silencieux). | Mineur |
| BUG-042 | `ConsumableCountSerializer` rend `node` obligatoire côté validation alors que le viewset l'assigne lui-même pour un gérant non-HQ → un gérant ne peut pas enregistrer d'inventaire physique sans connaître/fournir l'ID de son propre nœud. | Majeur |
| BUG-043 | Aucune réconciliation production ↔ ventes/retours (ni endpoint backend, ni calcul frontend) : impossible d'obtenir l'écart en pains/FC demandé par CLAUDE.md §5.4. | Majeur |

### Anomalies confirmées mais déjà ticketées par un autre testeur (pas de doublon)

- **BUG-023** (testeur-permissions) : `confirm_reception`/`respond_to_request` n'ont aucun contrôle d'appartenance au nœud — la boulangerie émettrice peut confirmer elle-même sa réception, la destinataire peut répondre à sa propre demande. Tests ajoutés côté `production` : `test_source_bakery_cannot_confirm_its_own_shipment`, `test_destination_bakery_cannot_respond_to_its_own_request`.
- **BUG-037** (testeur-tresorerie) : un transfert `DISPUTED` (écart de quantité) ne bloque pas la création/le versement d'une clôture de caisse. Test ajouté : `test_disputed_transfer_blocks_daily_closure_of_concerned_bakery`.

## Points non couverts dans cette passe (signalés, pas tranchés)

Les lignes de remarque.md suivantes, dans le périmètre de BUG-014, sont des
demandes **d'affichage/UI frontend** (boutons « Voir plus », hauteur de boîte
modale, séparation par boulangerie dans l'affichage, libellés de formulaire,
détail du rapport facturier) : l.14, 16, 18, 20, 90, 118 (partie « prise en
compte dans États Financiers Consolidés », hors module Production),
142-146 (déjà couvert par **BUG-033**, testeur-tresorerie), 158 (Tableau de
Bord, hors module Production), 169-170, 194 (modale « Voir plus »/commentaire
sur fournée côté UI — le champ `notes` existe et est modifiable côté API,
vérifié en passant dans `test_sac_value_change_does_not_corrupt_historical_session_on_unrelated_edit`,
mais l'ergonomie de la boîte modale elle-même n'est pas du ressort d'un test
Django). Je ne les ai pas marquées `[c]` ni ouvert de ticket dédié : elles
relèvent d'une revue frontend/E2E (page ≈ 150 Ko, beaucoup de JSX) plutôt que
de tests backend, et plusieurs recoupent des tickets déjà ouverts par
`testeur-tresorerie` (BUG-033) ou le futur passage de `testeur-e2e`. Je
recommande au coordinateur de les confier à un passage frontend dédié plutôt
que de les laisser sans propriétaire.

## Fichiers créés/modifiés

- `backend/production/tests/__init__.py` (nouveau)
- `backend/production/tests/test_fournees.py` (nouveau)
- `backend/production/tests/test_consumables.py` (nouveau)
- `backend/production/tests/test_transfers.py` (nouveau)
- `backend/production/tests/test_disposal_reconciliation.py` (nouveau)
- `backend/production/tests.py` (supprimé — remplacé par le paquet `tests/`, même convention que `treasury`/`blockchain`)
- `backend/core/testing.py` : non modifié par moi — un autre agent l'a écrit/réécrit en parallèle pendant cette session ; j'ai utilisé sa version (`make_node`, `make_user`, `make_bread_price`, `make_client`, `get_config`) sans y toucher.
- `docs/qa/REGISTRE_BUGS.md` : clôture de BUG-014 (REJETÉ, remplacé), ouverture de BUG-038 à BUG-043 avec fiches détaillées.
- `remarque.md` : marques `[c]` avec notes sur les lignes 1-6, 22, 24, 26, 28, 30, 32, 198.

## Démonstration manuelle (règle `db.sqlite3`, plan §0.1)

Je n'ai pas effectué de démonstration manuelle sur `backend/db.sqlite3` dans
cette itération : tous les scénarios étaient entièrement vérifiables (et
reproductibles de façon fiable) via `python manage.py test production`, qui
couvre à la fois les cas conformes et les 9 anomalies. Aucune donnée
« DEMO »/« TEST » n'a donc été laissée dans la base réelle de développement.
Si le coordinateur souhaite une démonstration visuelle (ex. un transfert K1→K2
visible dans `/admin/`), je peux la fournir sur demande.

## Critère de fin

- `python manage.py test production` : **OK** (24 tests, 9 `expectedFailure`, 0 échec/erreur réel).
- BUG-014 refermé (remplacé par BUG-038..043 + renvois vers BUG-023/BUG-037).
- Aucune modification de code applicatif.
