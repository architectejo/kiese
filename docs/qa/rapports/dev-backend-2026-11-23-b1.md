# Rapport dev-backend (Dev B) - B-1 : taux de commission par boulangerie (2026-11-23)

Ticket : BUG-1103 (CORRIGE backend ; frontend a faire). Source : Q-026 (reponses-clients.md, ferme).

## Ce qui a ete fait
- `core/models.py` : `Node.default_commission_rate` DecimalField(4,2) NULLABLE (vide = `Config.default_commission_rate`) ; helper unique `effective_commission_rate(node)` (0 est un taux valide, distinct de vide).
- `core/migrations/0025_node_default_commission_rate.py` : AddField + migration de donnees defensive (copie le taux de `Config` dans chaque boulangerie ; le noeud SIEGE reste vide ; sans Config rien n'est copie ; inverse sans effet). Aucune migration existante modifiee.
- `core/serializers.py` : champ expose par `NodeSerializer`, `AsciiDigitsMixin '__numeric__'`, bornes 0 a 0,30, vide (null) accepte. Ecriture = `NodeViewSet` existant (`IsDirection` : direction et admin ; gerant/facturier refuses, y compris pour leur propre boulangerie, comme les autres champs du noeud).
- `clients/models.py` : `Client.__init__`/`save()` : un client cree SANS `commission_rate` (REST, import Excel `import_excel`, push sync, creation directe) recoit le taux de sa boulangerie, sinon celui de `Config`. Un objet relu de la base n'est jamais modifie ; un taux explicite prevaut. Fait dans le modele car `clients/views.py` etait reserve (l'import Excel y cree les clients : il est couvert sans y toucher).
- `sync/services.py` : le push d'un client sans `commission_rate` ne force plus 0,25 (laisse `Client.save()` appliquer le defaut de la boulangerie) ; taux fourni = conserve.
- `sales/views.py` : les deux replis `config.default_commission_rate` (inatteignables en pratique, le taux client n'est jamais null) passent par `effective_commission_rate(client.node)`.
- Inchange : types de vente SOLDE/CASH (CM 0), `ClientCommission.commission_rate` fige, `commissions/views.py` (non touche), frontend (non touche).
- Autres lectures de `Config.default_commission_rate` (grep) : `core/admin.py`, `core/signals.py` (journal), `ConfigSerializer`, `sync/views.py` (pull de config vers les noeuds), `seed_from_excel.py` : ce sont la lecture/ecriture de la config globale elle-meme, laissees telles quelles. Voir points d'attention.

## Tests
Nouveau : `backend/core/tests/test_dev_b1_taux_par_boulangerie.py` (19 tests) : helper et repli sur Config, defaut a la creation REST, taux explicite prioritaire, deux boulangeries/deux taux, creation directe et relecture, PATCH du noeud sans effet sur les clients existants, PATCH client apres changement du noeud, commission deja generee figee, gerant K1 refuse sur K1 et K2, facturier refuse, direction/admin autorises sans toucher l'autre boulangerie, bornes (0,31, -0,01, abc, chiffre arabe, 3 decimales refuses ; vide, 0, 0,25, 0,30 acceptes), import Excel, push sync sans taux et avec taux, migration de donnees sur base jetable (copie, SIEGE vide, sans Config, clients existants intacts, retour arriere).

Resultats REELS (log `$TEMP/b1.log`, une seule passe) :
`makemigrations --check --dry-run` : No changes detected.
`manage.py test core.tests.test_dev_b1_taux_par_boulangerie clients.tests.test_clients_v10 clients.tests.test_clients_v13 commissions.tests.test_commissions_v7 core.tests.test_verif_permissions_b4_v4 core.tests.test_verif_permissions_b2_v2 core.tests.test_verif_permissions_b7_v7 sales.tests.test_invoices` : Ran 281 tests in 1037 s, OK.
La suite complete n'a pas ete lancee (hors perimetre demande).

## Points frontend (a faire, Nodes.tsx)
1. Ajouter dans la fiche boulangerie un champ numerique « Taux de commission par defaut » (`default_commission_rate`), visible/modifiable direction et admin uniquement, comme `card_fee_fc`/cotisation sociale.
2. Contrat : `/api/core/nodes/` renvoie `default_commission_rate` en chaine decimale (`"0.25"`) ou `null` ; ecriture : chaine ou nombre, bornes 0 a 0,30 ; `null`/champ vide = reprendre le taux global. Erreur 400 en francais : « Le taux de commission doit etre compris entre 0 et 0,30. »
3. Afficher « vide = taux global (x %) » en aide ; pour un nouveau client, pre-remplir le champ taux du formulaire client avec le taux de la boulangerie choisie (le backend l'applique deja si le champ est omis).
4. Ajouter le champ au type `Node` dans `src/api/` (type nullable). Pas de `any`.

## Points d'attention / risques
- Taux par defaut des boulangeries = copie du 25 % actuel : montant a confirmer avec le client boulangerie par boulangerie.
- Regle REST des taux : 0 a 0,30 (valeurs intermediaires admises) ; le plan parle de 0,25 ou 0,30, la regle code actuelle est plus large, conservee.
- Le defaut s'applique dans `Client.save()` : une affectation explicite de 0,25 apres construction sans taux est indistinguable du defaut et prendra le taux de la boulangerie (cas theorique, aucun appelant connu). `sync_now` (pull cloud) passe toujours un taux explicite : inchange.
- `sync/views.py` pousse toujours le taux global `Config` aux noeuds ; le taux par boulangerie n'est pas encore diffuse dans le pull de config (le noeud local lit le sien via sa propre table `Node` si `core.Node` est synchronise ; sinon, ticket de suite pour `architecte-sync`).
- `clients/views.py` et `commissions/views.py` non modifies, comme demande.
- Ne pas commiter : rien commite (pas de git stash).
