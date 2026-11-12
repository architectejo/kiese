# Rapport testeur-e2e — vague 5 (rejeu des tickets CORRIGÉ), 2026-11-12

Base `db.sqlite3`, serveurs 8000 et 5173 déjà lancés (non redémarrés). Comptes `zz_*` uniquement, autorisation de l'utilisateur pour ce rejeu. Aucun mot de passe consigné. Lecture seule : aucune écriture en base. Code applicatif non modifié.
Tests : `e2e/tests/18-vague5-verification-db.spec.ts` (nouveau), `e2e/tests/16-clients-commissions-vague3-db.spec.ts` (attente BUG-280 mise à jour). Sortie Playwright (`--output`) dans le dossier temporaire personnel de la session. Captures : `docs/qa/captures/vague5-*.png`.

## Résultats (vert / rouge / non joué)

| Ticket | Bureau 1440 | POS 360 | Décision |
|---|---|---|---|
| BUG-242 (garde `/treasury`) | vert | vert | déjà VÉRIFIÉ, reconfirmé |
| BUG-269 (KPI Clients) | vert | vert | déjà VÉRIFIÉ, reconfirmé |
| BUG-270 (Commissions COMPTABLE / DIRECTION) | vert | vert | déjà VÉRIFIÉ, reconfirmé |
| BUG-274 (file livreur, PENDING hors jour) | API vert / écran rouge | API vert / écran rouge | reste CORRIGÉ ; nouveau BUG-283 |
| BUG-276 (message français billetage) | vert | vert | VÉRIFIÉ |
| BUG-277 (validate bloqué si litige) | non joué | non joué | reste CORRIGÉ (écritures réelles nécessaires) |
| BUG-280 (bannière visible après échec ajustement) | vert | vert | VÉRIFIÉ |
| BUG-281 (libellé « période ») | non joué | non joué | reste CORRIGÉ (compte K3 gérant refusé) |
| BUG-282 (vitrine, débordement) | 0 px à 320/360/768/1440 | 0 px à 320/360/768/1440 | VÉRIFIÉ |

## Détails

- **BUG-276** : gérant K4, saisie de 100001 sur la coupure 20 000 puis Valider : « Coupure 20 000 FC : entier entre 0 et 100 000 billets. » dans le formulaire, aucune requête POST de clôture, pas de débordement. (Le test accepte les espaces insécables fines produites par `toLocaleString('fr-FR')`.) La saisie de -3 et 2,5 affiche le même message, mais le test ne distingue pas un message périmé d'un message neuf (le gestionnaire efface l'erreur à chaque soumission). Bordereau et comptage direction non rejoués.
- **BUG-280** : API réelle 403 (jeton COMPTABLE, rôle DIRECTION simulé côté navigateur) ; la fiche se ferme, la bannière « Vous n'avez pas la permission d'effectuer cette action. » est visible, sans `modal-backdrop`. L'ancien test attendait le défaut (fiche restée ouverte) : mis à jour.
- **BUG-282** : mesure `scrollWidth - innerWidth` = 0 aux quatre largeurs dans les deux projets.
- **BUG-274 / BUG-283** : `GET /api/sales/invoices/pending_deliveries/` (facturier K4) renvoie des PENDING datées hors du jour (ex. K4-20260310-0007) : correctif backend confirmé. L'écran (`Sales.tsx` l.192-226) charge `invoice_date = workDate` et n'appelle jamais `pendingDeliveries()` ; ces factures n'apparaissent pas dans la file. Même symptôme côté UI qu'à l'origine de BUG-274. Test passé en `test.fixme` (référence BUG-283). Le franchissement réel de minuit n'a pas été rejoué.
- **BUG-277** : demande un transfert en litige et une clôture du jour dans la base réelle : écritures de données partagées, laissé au test Django du ticket.
- **BUG-281** : visible seulement en rotation (K3). Connexion de `zz_prod_gerant_k3` refusée (« Identifiants invalides ») ; pas d'autre compte gérant K3 ; aucun contournement tenté. Le test se met en `skip` s'il n'y a pas de modale.

## Incidents d'environnement
- Premier lancement : `--output` sous `C:\Users\MUABILU PC` échoue (espace dans le chemin, EPERM) ; dossier dans le scratchpad utilisé à la place.
- Modale « Stock de départ du jour » tardive à 360 px interceptant les clics : le test la reporte désormais avant d'agir.
- Serveur lent par moments (timeout `route.fetch` 10 s sur une exécution de BUG-270 ; repassé vert au rejeu).

## Tickets
- VÉRIFIÉ : BUG-276, BUG-280, BUG-282 (BUG-242, 269, 270 déjà VÉRIFIÉ, reconfirmés).
- Restent CORRIGÉ : BUG-274, BUG-277, BUG-281.
- Nouveau : BUG-283 (frontend, Mineur).

## Note 2026-11-13 : rejeu BUG-283 / BUG-274
- Test « BUG-283 » (`e2e/tests/18-vague5-verification-db.spec.ts`) : vert sur pos (360 px) et bureau, db.sqlite3, compte zz_clients_facturier (K4). La PENDING rétro-datée apparaît dans « File des Livraisons ».
- BUG-283 et BUG-274 passés à VÉRIFIÉ. Tablette et TV non rejouées.
- Lancement : `PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers` est invalide sous Windows (navigateur introuvable) ; variable retirée. `--output` dans le dossier personnel a fonctionné.
