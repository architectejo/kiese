# architecte-sync d43 (Dev B) - 2026-11-23 : BUG-989 a 992 (somme du groupe des transferts)

Tickets CORRIGE : 989, 990, 991, 992. Les 4 `@expectedFailure` de `test_verif_production_a14_v14.py` sont supprimes
(assertions inchangees ; import `expectedFailure` retire ; dans `A14Migration0003` ajout d'un `migrate(latest)` avant
la cascade, car la table `sync_transfermirror` doit exister). Lot : a14, a13..a6, sync v5/charge v4/bug004, transferts,
+ `production/tests/test_sync_transfers_d43.py` (4 nouveaux tests) = 390 tests OK ; `makemigrations --check` propre.
Log : `%TEMP%/d43.log`. Ni `treasury/` ni `sales/` touches.

## Contrat final

### Marqueur de miroir (989/990) - migration additive `sync/migrations/0004_transfermirror.py`
- Le cloud ne tient aucun stock de pains pour les postes (ses `BreadStock` ne sont que ceux de ses actions REST) :
  le marqueur dit a un poste ce qu'il a DEJA applique.
- Modele `sync.TransferMirror(node, transfer_id, applied={bp_id: [envoye_deduit, recu_credite]})`, unique (node, transfer).
- Push : champ de tete `mirrors` (hors `records`, hors empreinte) = etat des lignes locales du poste (30 jours / non
  terminaux, max 500) : emettrice -> envoye si statut RESPONDED/DISPUTED/CONFIRMED, receptrice -> recu. Valide (UUID,
  entiers 0..2e9, transfert dont le nœud est partie) puis upsert ; ignore sur un lot rejoue et si absent.
- Pull : `mirrors` = marqueurs du poste pour les transferts descendus (`{}` si aucun ; cle absente = cloud ancien).

### Application locale (`_apply_pulled_transfers`)
- Delta unique, par ligne : `(envoye cloud si statut cloud RESPONDED/DISPUTED/CONFIRMED) - (envoye local si copie deja
  RESPONDED/DISPUTED)` pour l'emettrice ; `recu cloud - recu local` pour la receptrice. Idempotent (la ligne locale est ecrite
  dans la meme transaction).
- 989 : transfert INCONNU et `mirrors` present : base = marqueur (absent = 0). Jamais vu -> credit une fois ; poste reinstalle
  (marqueur = etat applique) -> aucun mouvement. `mirrors` absent (cloud ancien) : ancien comportement (copie sans stock).
- 990 : PENDING -> RESPONDED decide au siege : l'emettrice debite la quantite envoyee (base 0), une seule fois.
- 991 : le pull ne reecrit jamais une copie locale non synchronisee ; une fois la reponse poussee, delta nul.
- Limite connue : le marqueur est rapporte au push SUIVANT l'application ; un poste reinstalle dans cette fenetre d'un cycle
  reapplique le dernier delta (jamais plus que ce delta).

### Push (cloud, `sync/services.py`)
- 991 : sur un `BreadTransfer` pousse par l'EMETTRICE en RESPONDED (cloud PENDING ou RESPONDED, flow REQUEST), ses lignes du
  meme lot peuvent changer `quantity_sent` tant que `quantity_received` est vide et le transfert RESPONDED : la quantite envoyee
  finale est celle de l'emettrice. Toute autre difference reste refusee (BUG-788/920, 974).
- 992 : regle « premier terminal gagne » : un CANCELLED de l'emettrice sur un transfert deja repondu au cloud (ou un
  RESPONDED/DISPUTED/CONFIRMED de l'emettrice sur un transfert deja CANCELLED) est ACQUITTE (ACCEPTED + motif « conflit »,
  le poste ne reste pas non synchronise), trace dans `SyncConflictLog` (`TRANSFER_STATE_CONFLICT`, une ligne non resolue par
  transfert, `occurrences` au rejeu) ; ses lignes du lot sont sans effet.
- Pull : copie locale CANCELLED acquittee alors que le cloud est RESPONDED/DISPUTED/CONFIRMED -> le cloud prevaut (statut, lignes,
  debit de l'emettrice) + notification « Conflit Transfert ». Copie locale RESPONDED synchronisee alors que le cloud est CANCELLED
  -> statut CANCELLED et stock restitue (delta negatif). Somme du groupe nulle dans les deux sens.
- Restrictions de role 874/888/891/921/928/966/974, idempotence et rejeu inchanges.

## A CLARIFIER
Un cloud ancien (sans `mirrors`) avec poste recent reste en comportement d39 ; deployer le cloud d'abord.
