# Testeur clients/commissions b17 (2026-11-23) : vérification de BUG-998

Fichier de tests : `backend/clients/tests/test_clients_v13.py` (40 tests, données fictives, code applicatif non modifié). Log : `$TEMP/b17.log`.

## Résultat
- **BUG-998 : VÉRIFIÉ** (édition ciblée du registre).
- Revue des 3 tests inversés par le dev : logique conforme à CLAUDE.md 5.1 / remarque.md l.10 (le facturier voit les clients des autres boulangeries). `test_clients_v11` suit `has_more` (max 5 pages : fragile seulement si > 25 000 clients), `test_clients_v12::PerimetrePull` et `test_verif_charge_v4` assertent la présence du client K3/K2 et de celui du poste. Verts. `Migration0010` (base jetable + routeur temporaire) : verte, mêmes vérifications qu'avant.
- 2 nouveaux tickets : **BUG-999** (Majeur), **BUG-1004** (Mineur), `@expectedFailure` (4 tests). Les numéros 1000-1003 étaient pris par un autre testeur.
- Run complet de mes fichiers : 40 tests, 36 OK + 4 échecs attendus.

## Scénarios couverts (v13)
- Pagination : 3 pages avec ex-aequo d'`updated_at` (3+3+2, sans perte ni doublon), ordre stable `(updated_at, id)`, frontière exacte (taille de page, taille+1), rejeu d'une requête, rejeu de toutes les pages côté poste (idempotent, `is_synced`/`updated_at` intacts), client modifié et créé entre deux pages, `client_after_id` sans `since` ignoré, curseur futur sans 400, UUID hostile.
- Boucle : desktop `_pull_only` et `sync_now` bornés à 200 pages (cloud qui répond toujours `has_more`), curseur qui n'avance pas, curseur `after_id` persisté puis effacé en fin de pull, reprise après 503 à la page 2 (et redémarrage), curseur disque corrompu/orphelin, 400 qui oublie le curseur.
- Confidentialité : aucune facture, mouvement de dette, commission, cotisation d'un autre nœud dans la réponse ; colonnes client = liste blanche exacte ; SIEGE sans catalogue ; inactifs d'autres nœuds absents ; paramètre `node` ignoré.
- Lots : édition locale non poussée / mouvement non poussé / client normal dans un même lot, catégorie à risque, dette négative (épargne) + valeurs hostiles, conflit de code (un journal par client), deux lignes de même id.
- Volumétrie : poste neuf 20 000 clients : pull 4 pages en 1,5 à 2,6 s (2,3 Mo/page), création locale 14 à 16 s, pic mémoire Python 12 à 13 Mo. Rejeu `bulk_update` de 5 000 clients : 6,3 à 10,6 s (selon la charge machine), 100 requêtes (constant par lot de 500).

## Questions posées
- **Confidentialité (téléphone et dette courante des clients des autres boulangeries)** : conforme. La REST expose déjà à FACTURIER/LIVREUR toutes les colonnes de `ClientSerializer` (phone, current_debt, notes, cotisation_sociale, commission_rate) pour tous les clients ; le pull n'ajoute aucune colonne (test de comparaison). Réserve à documenter au client : sur le poste, ces colonnes sont dans la base SQLite locale, lisibles par tout compte local (gérant, comptable) et par quiconque a accès au fichier, ce que la REST cloud filtre par rôle. Pas de ticket ; à signaler à la direction (Q client possible).
- **Clients inactifs / supprimés** : un client inactif d'un autre nœud n'est plus envoyé, mais rien ne dit au poste de le désactiver (BUG-999). Un client supprimé (seulement possible sans facture) n'a pas de pierre tombale : copie conservée au poste (limite documentée, test `test_client_supprime_au_cloud_reste_au_poste_limite_documentee`).
- **Client déplacé (bulk_move)** : jamais redescendu (updated_at inchangé) et `node`/`code` non appliqués au pull (BUG-1004).
- **Édition simultanée** : l'édition locale non poussée n'est jamais écrasée, la dette cloud est appliquée, un mouvement de dette non poussé fait ignorer le client : conforme dans un lot mixte.

## Observations (sans ticket)
- Poste ANCIEN qui ignore `has_more` : n'envoie pas `client_after_id`, donc les clients ex-aequo d'`updated_at` après la frontière de page ne sont jamais reçus (test de documentation `..._limite_connue_...`). Réaliste si un `queryset.update()` en masse horodate 5 000+ clients à l'identique. À traiter en déployant les postes avant ou avec le cloud.
- Boucle de pull : pas de détection d'un curseur qui n'avance pas : un cloud défaillant coûte 200 requêtes (2 Mo chacune) par cycle de 30 s. Borné, donc non bloquant ; amélioration possible (sortir si le curseur est identique à celui de la page précédente).
- L'horloge Windows a une granularité d'environ 15 ms : des clients créés en rafale partagent le même `updated_at`, ce qui rend les ex-aequo fréquents en pratique (poste Windows).
- `test_verif_charge_v4::RetenueTroisBoulangeriesVerif::test_imbrication_a_trois_une_seule_retenue` (génération de commissions, retenues dédoublées 20 000/3 000 au lieu de 10 000/1 500) a échoué une fois dans un run groupé de 96 tests et est passé deux fois isolément. Instable à surveiller (hors périmètre BUG-998 ; le sync était modifié en parallèle par un autre agent). Pas de ticket faute de reproduction.

## Tickets ouverts
- BUG-999 : `is_active` non propagé par le pull (désactivation jamais redescendue, client inactif recréé actif sur un poste neuf).
- BUG-1004 : `bulk_move` ne fait pas avancer `updated_at`, et le pull n'applique ni `node` ni `code`.
