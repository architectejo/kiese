# dev-backend d38 (2026-11-23) : BUG-973 blocage des ventes après l'heure de clôture

## Livré (backend)
- `Node.block_sales_after_closure` (Boolean, défaut False, exposé par `NodeSerializer`), migration `core/0024`. L'heure de clôture réutilise `Node.handover_time` (pas de doublon).
- `backend/treasury/closure_lock.py` : `closure_status(node, now)` et `sales_blocked_for(node, now)`. Bloqué si interrupteur actif ET heure atteinte pour `work_date_for` ET aucune `CashClosure.is_validated` (nœud, jour). SIEGE / sans nœud : jamais bloqué.
- `sales/views.py::_create_once` : 403 + `create_notification` (WARNING). Non bloqués : remboursement BP (`is_debt_repayment`), vente rétroactive, livraison/annulation d'une facture existante.
- `treasury/views.py::ClosureStatusView`, route `/api/treasury/closure-status/`.
- Tests : `treasury/tests/test_dev_d38_blocage_ventes.py`. Non codé : rotation 24 h (Q-017 à Q-021).

## Contrat GET /api/treasury/closure-status/
Authentifié (tout rôle). Nœud de l'utilisateur ; `?node=<code|uuid>` réservé aux profils multi-nœuds (403 sinon, 404 si inconnu).
```
{"closure_hour": "12:00"|null, "blocked": bool, "reason": "...", "closure_date": "AAAA-MM-JJ"|null,
 "validated": bool, "enabled": bool}
```
Création de facture bloquée : HTTP 403 `{"detail": "Ventes bloquées : clôture du jour en attente de validation par la direction."}`.

## Frontend à faire
1. Modale de clôture (gérant) à l'heure de clôture, sur chaque page : sorties non valorisées par catégorie (NV, déclassés, sorties gratuites), réutiliser §3.4 de « Production & Stocks » ; choix de garder/changer d'équipe.
2. Bannière de blocage (interroger `closure-status`, désactiver Facturation / Enregistrer commande, afficher `reason`) ; gérer le 403.
3. Settings/Nodes : libellé « Heure de clôture » (champ `handover_time`) + interrupteur `block_sales_after_closure`.

## Points à clarifier avec le client
Voir BUG-973 : ventes post-validation du même jour (unicité CashClosure par date, lié rotation 24 h), clôture non validée la veille, périmètre rétroactif/remboursements, heure de relève vs clôture distinctes, restes du jour -> stock de départ (opening-confirmation existant, non modifié).

## Risques
Par défaut désactivé : aucun impact existant. Activé, le blocage dépend de la validation `CashClosure.validate` par un profil HQ.
